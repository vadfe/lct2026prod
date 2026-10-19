"""Сценарии цифрового сомелье поверх справочников, каталога и LLM-слоя (ТЗ п. 6).

Рекомендуются только российские вина из каталога сервиса — покупатель остаётся в нашем торговом пространстве.

С1/С4 pair_dish — вино к блюду (или к блюду из рецепта): 3 российские бутылки + объяснение.
С2 pair_wine — что к этой бутылке: slug (в том числе от распознавания этикетки) -> карточка + 5 блюд + правило сорта.
С3 similar — похожее, но российское: аналоги сорта + «мост» + российские бутылки.
С5 gift — подарок: повод и бюджет -> 3 российские бутылки с историей.
analog — российский аналог зарубежного вина: LLM описывает свойства вина, алгоритм ищет ближайшие российские бутылки.
В каждом ответе с бутылками — catalog_source (demo -> плашка «Демо-данные») и версии справочников и весов.
"""
from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable

from .. import guardrails
from ..features import norm
from .catalog import Bottle, CatalogFilters, CatalogProvider, bottle_from_card
from .llm_layer import LLMClient, LLMLog, check_explanation, describe_foreign_wine, explain, parse_query, stop_words
from .query import COLOR_RX, ParsedQuery, keyword_profile, parse_rules
from .reference import DATA_DIR, SWEETNESS, DishBook, Grape, GrapeBook
from .scoring import (
    ROLE_LABEL,
    DishProfile,
    ScoredAnalog,
    ScoredBottle,
    bridge_phrase,
    compare_parts,
    dishes_for,
    diverse,
    grape_profile,
    pick_three,
    rank_grapes,
    score_analog,
    score_bottle,
    similar,
)

logger = logging.getLogger(__name__)

FOREIGN_JSON = os.path.join(DATA_DIR, "foreign_styles.json")
CLARIFY = ("Уточните, к какому блюду подбираем вино. Например: «к утке», «шашлык, не сладкое», «подарок» "
           "или «аналог Шабли» — подберу российское вино из каталога.")
CLARIFY_ANALOG = ("Назовите зарубежное вино, регион или сорт, к которому ищем российский аналог: "
                  "например, «аналог Шабли», «замена Бароло», «что-то вроде новозеландского Совиньон Блан».")
LEGAL_NOTE = "Сервис информационный: рассказывает о сочетаниях вина и еды и не продаёт алкоголь. Рекомендуем только российские вина каталога."
ANALOG_RX = r"аналог\w*|похож\w* на|замен\w*|вместо|альтернатив\w*|как (?:у|в) (?:франц|итал|испан|немец|чилий|аргентин|грузин)|вроде"
ANALOG_LABEL = {"best_match": "Ближе всего по профилю", "other_grape": "Другой сорт", "other_price": "Другая цена", "next_best": "Ещё вариант"}
BUDGET_NO_PRICES = "В каталоге нет цен — бюджет не учтён."


class CatalogUnavailable(RuntimeError):
    """Источник каталога не отвечает (например, retail ещё не подключён)."""


def price_text(p: float | None) -> str:
    if not p:
        return "цена не указана"
    return f"{int(p) if float(p).is_integer() else p} ₽"


def first_sentence(text: str) -> str:
    m = re.match(r"(.+?[.!?])(\s|$)", text or "")
    return (m.group(1) if m else text or "").strip()


def load_foreign_styles(path: str = FOREIGN_JSON) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class PairingService:
    def __init__(self, grapes: GrapeBook, dishes: DishBook, provider: CatalogProvider, config: dict, llm: LLMClient | None = None,
                 llm_log: LLMLog | None = None, recognition: Callable[[str], dict | None] | None = None, foreign: dict | None = None):
        self.grapes, self.dishes, self.provider, self.config = grapes, dishes, provider, config
        self.w, self.r, self.s, self.a = config["score"], config["ranking"], config["similar"], config["analog"]
        self.llm = llm
        self.log = llm_log or LLMLog(None)
        self.recognition = recognition
        self.foreign = foreign or load_foreign_styles()

    # ---- общие поля ответа -----------------------------------------------------------------------
    @property
    def catalog_source(self) -> str:
        return self.provider.source

    def versions(self) -> dict:
        h = self.provider.health()
        return dict(grapes=self.grapes.version, dishes=self.dishes.version, weights=self.config["version"],
                    foreign=self.foreign["version"], catalog=f"{h.source}:{h.updated_at or 'n/a'}")

    def _envelope(self, **body) -> dict:
        return dict(**body, catalog_source=self.catalog_source, russian_only=True, versions=self.versions(), note=LEGAL_NOTE)

    def _russian(self, filters: CatalogFilters, budget: float | None = None) -> tuple[list[Bottle], list[str]]:
        """Только российские бутылки каталога. Бюджет применяется, если в каталоге есть цены; иначе — пометка в notes."""
        filters.is_russian = True
        try:
            bottles = self.provider.list_wines(filters)
        except NotImplementedError as exc:
            raise CatalogUnavailable(str(exc)) from exc
        bottles = [b for b in bottles if b.is_russian]
        if budget is None:
            return bottles, []
        if not any(b.price_rub for b in bottles):
            return bottles, [BUDGET_NO_PRICES]
        return [b for b in bottles if b.price_rub is not None and b.price_rub <= budget], []

    def bottle_card(self, b: Bottle, g: Grape | None, sb: ScoredBottle | None = None, explanation: str = "") -> dict:
        card = dict(slug=b.slug, name=b.name, producer=b.producer, region=b.region, country=b.country, price_rub=b.price_rub,
                    volume_l=b.volume_l, is_russian=b.is_russian, russia_mark="Россия" if b.is_russian else None, grape=b.grape,
                    grape_id=b.grape_id, color=b.color, sweetness=b.sweetness, oak=b.oak, sparkling=b.sparkling, source=b.source,
                    needs_review=b.needs_review, url=b.url, image_url=b.image_url, story=g.story if g and b.is_russian else None,
                    explanation=explanation)
        if g is not None:
            card["why"] = dict(rule=g.pairing_text, grape=g.name, tannins=g.tannins, acidity=g.acidity, body=g.body_for(b.oak),
                               factors=sb.factors if sb else [], adjustments=sb.adjustments if sb else [])
        if sb is not None:
            card.update(score=sb.score, grape_score=sb.grape_score, role=sb.role, role_label=ROLE_LABEL.get(sb.role, ""))
        return card

    # ---- разбор запроса ----------------------------------------------------------------------------
    def parse(self, text: str) -> ParsedQuery | None:
        """Правила + (если подключена) LLM. None — LLM дважды вернула невалидный JSON и правила ничего не нашли."""
        q = parse_rules(text, self.grapes, self.dishes)
        if self.llm is None:
            return q
        lq = parse_query(text, self.llm, [d.name for d in self.dishes.dishes], self.log)
        if lq is None:
            return q if (q.dish or q.liked_grape or q.occasion) else None
        q.source = "llm"
        if q.dish is None and lq.dish:
            d = self.dishes.find(lq.dish)
            if d is not None:
                q.dish_text, q.dish = d.name, DishProfile.from_dish(d)
            elif lq.dish_profile is not None:
                p = lq.dish_profile
                q.dish_text = lq.dish
                q.dish = DishProfile(name=lq.dish, body=p.body, fat_protein=p.fat_protein, acid=p.acid, spicy=p.spicy, salty=p.salty,
                                     sweet=p.sweet, cuisine=norm(p.cuisine or ""), source="llm")
        q.budget_max = lq.budget_max or q.budget_max
        q.sweetness = list(lq.sweetness) if lq.sweetness else q.sweetness
        q.color = lq.color or q.color
        if lq.liked_grape and not q.liked_grape:
            g = self.grapes.find_in(lq.liked_grape)
            q.liked_grape = g.grape_id if g else None
        q.occasion = lq.occasion or q.occasion
        return q

    # ---- С1 / С4: вино к блюду ----------------------------------------------------------------------
    def pair_dish(self, query: str, filters: dict | None = None, dish_id: str | None = None, scenario: str = "dish") -> dict:
        filters = filters or {}
        code = guardrails.check(query)
        if code:
            return self._envelope(kind="guardrail", code=code, text=guardrails.MESSAGES[code], wines=[])
        if scenario == "analog" or (dish_id is None and scenario == "dish" and re.search(ANALOG_RX, norm(query))):
            return self.analog(query, filters)
        if dish_id is not None:
            d = self.dishes.by_id.get(dish_id)
            if d is None:
                return self._envelope(kind="clarify", question=f"Блюда «{dish_id}» нет в справочнике.", wines=[])
            q = parse_rules(query, self.grapes, self.dishes)
            q.dish_text, q.dish = d.name, DishProfile.from_dish(d)
        else:
            q = self.parse(query)
            if q is None:
                return self._envelope(kind="clarify", question=CLARIFY, wines=[])
        budget = filters.get("budget_max") or q.budget_max
        if scenario == "gift" or (q.occasion == "gift" and q.dish is None):
            return self.gift(q, budget, filters)
        if q.dish is None:
            q.dish = keyword_profile(query)
            q.dish_text = q.dish.name if q.dish else None
        if q.dish is None:
            if q.liked_grape:
                return self.similar(q.liked_grape, russian=True) | dict(kind="similar", query=q.as_dict())
            return self._envelope(kind="clarify", question=CLARIFY, query=q.as_dict(), wines=[])

        dish = q.dish
        ranked = rank_grapes(self.grapes.grapes, dish, self.w)
        top = [s for s in ranked if s.score >= self.r["min_grape_score"]][: self.r["max_grapes"]]
        color = filters.get("color") or q.color
        sweetness = filters.get("sweetness") or q.sweetness
        if isinstance(sweetness, str):
            sweetness = [sweetness]
        store_id = filters.get("store_id")
        bottles, notes = self._russian(CatalogFilters(grape_ids=[s.grape.grape_id for s in top], color=color, sweetness=sweetness,
                                                      store_id=store_id), budget) if top else ([], [])
        if store_id and filters.get("in_stock", True):
            bottles = [b for b in bottles if self.provider.get_stock(b.slug, store_id).get("in_stock")]
        scored = [score_bottle(b, self.grapes.by_id[b.grape_id], dish, self.w, self.r) for b in bottles]
        picks = pick_three(scored, self.r)
        cards = [self.bottle_card(sb.bottle, sb.grape, sb, self._line(sb)) for sb in picks]
        explanation, how = self._explanation(dish.name, cards, picks)
        return self._envelope(
            kind="pairing", scenario=scenario, query=q.as_dict(), dish_profile=dish.as_dict(),
            grapes=[dict(grape_id=s.grape.grape_id, name=s.grape.name, score=s.score, oak=s.oak, factors=s.factors,
                         passed=s.score >= self.r["min_grape_score"]) for s in ranked[:5]],
            wines=cards, explanation=explanation, notes=notes,
            source=dict(query=q.source, dish_profile=dish.source, explanation=how),
            filters=dict(color=color, sweetness=sweetness, budget_max=budget, store_id=store_id),
            empty_reason=None if cards else self._empty_reason(top))

    def _empty_reason(self, top) -> str:
        if not top:
            return "Ни один сорт справочника не набрал 60 баллов к этому блюду."
        return "Среди российских вин каталога нет бутылок подходящих сортов под эти условия."

    @staticmethod
    def _reasons(sb: ScoredBottle) -> list[str]:
        """Два довода из правила сорта: сначала прямые совпадения (блюдо, кухня, острота), затем совпадение тела и танинов."""
        good = [f["text"] for f in sorted(sb.factors, key=lambda f: -f["points"]) if f["points"] >= 3]
        fit = [f["text"] for f in sb.factors if f["rule"] in ("body", "tannin") and f["points"] >= -6]
        return (good + fit)[:2] or [first_sentence(sb.grape.pairing_text).rstrip(".").lower()]

    def _line(self, sb: ScoredBottle) -> str:
        """1–2 предложения для карточки: правило сорта по факторам скоринга + фраза из story сорта."""
        g = sb.grape
        line = f"{g.name}: {'; '.join(self._reasons(sb))}."
        if g.story:
            line += " " + first_sentence(g.story)
        return line

    @staticmethod
    def _title(c: dict) -> str:
        extra = [x for x in (c["producer"], "" if norm(c["grape"]) in norm(c["name"]) else c["grape"],
                             price_text(c["price_rub"]) if c["price_rub"] else "") if x]
        return f"{c['name']} ({', '.join(extra)})" if extra else c["name"]

    def _template(self, dish_name: str, cards: list[dict], picks: list[ScoredBottle]) -> str:
        if not cards:
            return "Подходящих российских вин в каталоге не нашлось — попробуйте смягчить условия (цвет, сладость)."
        parts = [f"К блюду «{dish_name}»:"]
        story_used = False
        for c, sb in zip(cards, picks, strict=True):
            s = f"{self._title(c)} — {'; '.join(self._reasons(sb))}."
            if c.get("story") and not story_used:
                s += " " + first_sentence(c["story"])
                story_used = True
            parts.append(s)
        text = " ".join(parts)
        if len(text) > 600:   # сначала убираем историю и доводы — названия и цены остаются всегда
            text = " ".join([parts[0]] + [f"{self._title(c)}." for c in cards])
        return text[:600]

    def _explanation(self, dish_name: str, cards: list[dict], picks: list[ScoredBottle]) -> tuple[str, str]:
        template = self._template(dish_name, cards, picks)
        if self.llm is None or not cards:
            return template, "template"
        wines = [dict(name=c["name"], producer=c["producer"], price_rub=c["price_rub"], grape=sb.grape.name, region=c["region"],
                      country=c["country"], is_russian=c["is_russian"], pairing_text=sb.grape.pairing_text, story=sb.grape.story)
                 for c, sb in zip(cards, picks, strict=True)]
        out = explain(dish_name, wines, self.llm, self.log)
        if out is None:
            return template, "template"
        problems = check_explanation(out, wines, self._other_names({c["slug"] for c in cards}), self.quotable(dish_name, picks))
        self.log.write(kind="explain_check", response=out, accepted=not problems, problems=problems)
        if problems:
            logger.info("sommelier pairing LLM explanation rejected: %s", "; ".join(problems[:5]))
            return template, "template"
        return out.strip(), "llm"

    @staticmethod
    def quotable(dish_name: str, picks: list[ScoredBottle]) -> list[str]:
        """Что ответ может брать в «кавычки», кроме бутылок: блюдо и формулировки правил выбранных сортов."""
        return [dish_name, *{r.term for sb in picks for r in sb.grape.pairing_rules}]

    def _other_names(self, passed: set[str]) -> list[str]:
        """Названия и производители остальных бутылок каталога — по ним ловим «чужие» бутылки в ответе LLM."""
        try:
            bottles = self.provider.list_wines(CatalogFilters(include_unreviewed=True))
        except NotImplementedError:
            return []
        aliases = {norm(a) for g in self.grapes.grapes for a in (g.name, *g.aliases)}
        out = set()
        for b in bottles:
            if b.slug in passed:
                continue
            for name in (b.producer, b.name):
                if len(name) >= 5 and norm(name) not in aliases:
                    out.add(name)
        return sorted(out)

    # ---- С5: подарок -------------------------------------------------------------------------------
    def gift(self, q: ParsedQuery, budget: float | None, filters: dict) -> dict:
        active = {g.grape_id for g in self.grapes.active}
        bottles, notes = self._russian(CatalogFilters(grape_ids=sorted(active), color=filters.get("color") or q.color,
                                                      store_id=filters.get("store_id")), budget)
        target = budget or max((b.price_rub or 0 for b in bottles), default=0)
        # автохтоны вперёд (история для подарка), выдержанные вина, ближе к бюджету сверху; без повторов сорта и винодельни
        bottles.sort(key=lambda b: (not self.grapes.by_id[b.grape_id].is_russian_origin, b.oak != "да",
                                    abs(target - (b.price_rub or 0)), b.slug))
        picks, grapes_seen, producers = [], set(), set()
        for b in bottles:
            if b.grape_id in grapes_seen or b.producer in producers:
                continue
            grapes_seen.add(b.grape_id)
            producers.add(b.producer)
            picks.append(b)
            if len(picks) == self.r["top_bottles"]:
                break
        cards = []
        for b in picks:
            g = self.grapes.by_id[b.grape_id]
            card = self.bottle_card(b, g, explanation=first_sentence(g.story))
            card.update(story=g.story, role="gift", role_label=ROLE_LABEL["gift"])
            cards.append(card)
        text = " ".join(f"{self._title(c)}: {c['explanation']}" for c in cards)[:600] or "В каталоге нет российских вин под эти условия."
        assert not stop_words(text), stop_words(text)
        return self._envelope(kind="gift", scenario="gift", query=q.as_dict(), dish_profile=None, wines=cards, explanation=text,
                              notes=notes, source=dict(query=q.source, dish_profile=None, explanation="template"),
                              filters=dict(budget_max=budget))

    # ---- аналог зарубежного вина ----------------------------------------------------------------------
    def _foreign_by_rules(self, text: str) -> dict | None:
        """Без LLM (или если модель не ответила): известное вино/регион из foreign_styles.json или сорт в тексте."""
        t = norm(text)
        style = next((st for st in self.foreign["styles"] if any(re.search(rf"(?<!\w){re.escape(norm(k))}", t) for k in st["keys"])), None)
        grape = self.grapes.find_in(text)
        if style is None and grape is None:
            return None
        if style is not None:
            gids = [g for g in style["grapes"] if g in self.grapes.by_id]
            if style.get("profile"):
                prof = dict(style["profile"])
            else:
                profs = [grape_profile(self.grapes.by_id[g], style.get("oak")) for g in gids]
                prof = {k: round(sum(p[k] for p in profs) / len(profs), 2) for k in ("tannins", "acidity", "body")}
            return dict(name=style["name"], country=style["country"], grape_ids=gids, color=style["color"],
                        sweetness=SWEETNESS.get(style.get("sweetness") or ""), oak=style.get("oak"), source="rules", **prof)
        color = next((c for c, rx in COLOR_RX.items() if re.search(rx, t)), grape.color)
        return dict(name=f"{grape.name} (зарубежный)", country=None, grape_ids=[grape.grape_id], color=color,
                    sweetness=grape.sweetness, oak=None, source="rules", **grape_profile(grape))

    def foreign_profile(self, text: str) -> dict | None:
        if self.llm is not None:
            fw = describe_foreign_wine(text, self.llm, self.log)
            if fw is not None and fw.name.strip():
                gids = [g.grape_id for g in (self.grapes.find_in(x) for x in fw.grapes) if g is not None]
                return dict(name=fw.name, country=fw.country, grape_ids=list(dict.fromkeys(gids)), grapes=fw.grapes, color=fw.color,
                            sweetness=SWEETNESS.get(fw.sweetness or ""), oak=fw.oak, notes=fw.notes, source="llm",
                            tannins=fw.tannins, acidity=fw.acidity, body=fw.body)
        return self._foreign_by_rules(text)

    def analog(self, query: str, filters: dict | None = None) -> dict:
        """Российский аналог зарубежного вина: свойства вина (LLM или справочник стилей) -> ближайшие российские бутылки каталога."""
        filters = filters or {}
        target = self.foreign_profile(query)
        if target is None:
            return self._envelope(kind="clarify", scenario="analog", question=CLARIFY_ANALOG, wines=[])
        active = {g.grape_id for g in self.grapes.active}
        sweetness = filters.get("sweetness")
        bottles, notes = self._russian(CatalogFilters(grape_ids=sorted(active), color=target["color"], sweetness=sweetness,
                                                      store_id=filters.get("store_id")), filters.get("budget_max"))
        bottles = [b for b in bottles if not b.sparkling]   # тихое вино ищем среди тихих
        scored = [score_analog(target, b, self.grapes.by_id[b.grape_id], self.a, self.r["card_weight"]) for b in bottles]
        ranked = sorted((x for x in scored if x.score >= self.a["min_score"]), key=lambda x: (-x.score, x.bottle.slug))
        picks: list[ScoredAnalog] = diverse(ranked, self.a["limit"], self.r["other_price_min_ratio"])
        cards = []
        for x in picks:
            phrase = f"Похоже на «{target['name']}»: {', '.join(compare_parts(target, x.profile))}."
            card = self.bottle_card(x.bottle, x.grape, explanation=phrase)
            card.update(score=x.score, role=x.role, role_label=ANALOG_LABEL.get(x.role, ""),
                        why=dict(card["why"], factors=x.factors, adjustments=[]))
            cards.append(card)
        foreign = {k: target.get(k) for k in ("name", "country", "grapes", "grape_ids", "color", "sweetness", "oak", "notes",
                                              "tannins", "acidity", "body", "source")}
        foreign["sweetness"] = {v: k for k, v in SWEETNESS.items()}.get(target.get("sweetness"))
        if cards:
            text = f"Российские аналоги «{target['name']}»: " + " ".join(f"{self._title(c)} — {c['explanation'].split(': ', 1)[-1]}"
                                                                    for c in cards)
        else:
            text = f"Среди российских вин каталога близких к «{target['name']}» не нашлось."
        return self._envelope(kind="analog", scenario="analog", query=dict(text=query), foreign=foreign, dish_profile=None,
                              wines=cards, explanation=text[:600], notes=notes,
                              source=dict(query="analog", foreign_profile=target["source"], explanation="template"))

    # ---- С2: что к этой бутылке ------------------------------------------------------------------------
    def find_bottle(self, slug: str) -> Bottle | None:
        try:
            b = self.provider.get_by_slug(slug)
        except NotImplementedError:
            b = None
        if b is not None or self.recognition is None:
            return b
        w = self.recognition(slug)       # вино из базы распознавания этикеток (тот же slug, что у /api/cascade/search)
        if not w:
            return None
        b = bottle_from_card(w, self.grapes)
        b.source = "recognition"
        return b

    def pair_wine(self, slug: str) -> dict | None:
        b = self.find_bottle(slug)
        if b is None:
            return None
        g = self.grapes.by_id.get(b.grape_id or "")
        if g is None or not g.active:
            return self._envelope(kind="wine", wine=self.bottle_card(b, None), grape=g.card() if g else None, dishes=[], rule=None,
                                  message="Сорт этой бутылки не сопоставлен с активным сортом справочника — подбор блюд недоступен.")
        oak = b.oak if b.oak in ("да", "нет") else None
        sweet = SWEETNESS.get(b.sweetness or "")
        top = dishes_for(g, self.dishes.dishes, self.w, oak=oak, sweetness=sweet, k=5)
        bridge = similar(g, self.grapes.grapes, self.s, russian=True)[:1] if not g.is_russian_origin else []
        return self._envelope(kind="wine", wine=self.bottle_card(b, g), grape=g.card(), dishes=top, rule=g.pairing_text,
                              story=g.story, bridge=bridge[0]["phrase"] if bridge else None,
                              bridge_grape_id=bridge[0]["grape"].grape_id if bridge else None)

    # ---- С3: похожее, но российское -----------------------------------------------------------------
    def similar(self, grape_ref: str, russian: bool = True) -> dict | None:
        """Аналоги сорта и российские бутылки: сначала автохтоны-аналоги, затем тот же сорт российского производства.
        russian=False расширяет список аналогов на неавтохтонные сорта; бутылки всегда российские."""
        g = self.grapes.by_id.get(grape_ref) or self.grapes.resolve(grape_ref, include_draft=True)
        if g is None:
            return None
        analogs = similar(g, self.grapes.grapes, self.s, russian=russian)[: self.s["limit"]]
        order = [a["grape"] for a in analogs] + ([g] if g.active else [])
        target = dict(grape_profile(g), grape_ids=[g.grape_id], sweetness=g.sweetness, oak=None)
        wines, producers = [], set()
        for ag in order:
            bottles, _ = self._russian(CatalogFilters(grape_ids=[ag.grape_id], color=g.color))
            scored = sorted((score_analog(target, b, ag, self.a, self.r["card_weight"]) for b in bottles if b.producer not in producers),
                            key=lambda x: (-x.score, x.bottle.slug))
            for x in scored[:1]:
                producers.add(x.bottle.producer)
                card = self.bottle_card(x.bottle, ag, explanation=bridge_phrase(g, ag))
                card["story"] = ag.story
                wines.append(card)
            if len(wines) == self.s["limit"]:
                break
        text = " ".join(dict.fromkeys(a["phrase"] for a in analogs)) or f"Российские вина сорта {g.name} из каталога."
        return self._envelope(kind="similar", grape=g.card(), russian=russian, explanation=text,
                              analogs=[dict(grape_id=a["grape"].grape_id, name=a["grape"].name, distance=a["distance"], phrase=a["phrase"],
                                            is_russian_origin=a["grape"].is_russian_origin, story=a["grape"].story) for a in analogs],
                              wines=wines)

    # ---- справочники и здоровье --------------------------------------------------------------------
    def grapes_list(self) -> dict:
        return dict(version=self.grapes.version, grapes=[g.card() for g in self.grapes.grapes])

    def dishes_list(self) -> dict:
        return dict(version=self.dishes.version,
                    dishes=[dict(id=d.id, name=d.name, synonyms=list(d.synonyms), tags=list(d.tags), **d.profile()) for d in self.dishes.dishes])

    def health(self) -> dict:
        h = self.provider.health()
        return dict(status="ok" if h.ok else "degraded", catalog_source=h.source, russian_only=True,
                    catalog=dict(ok=h.ok, updated_at=h.updated_at, items=h.items, message=h.message, details=h.details),
                    llm=getattr(self.llm, "name", None) or "off (templates)",
                    grapes=dict(active=len(self.grapes.active), draft=len(self.grapes.grapes) - len(self.grapes.active)),
                    dishes=len(self.dishes.dishes), versions=self.versions())
