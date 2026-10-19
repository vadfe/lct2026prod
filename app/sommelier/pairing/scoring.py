"""Детерминированный подбор «блюдо → сорт → бутылка» (ТЗ п. 4). LLM здесь не участвует.

1. score_grape — оценка сорта 0–100: соответствие профилей вина и блюда + прямое совпадение с правилом сорта (п. 4.2).
2. score_bottle / pick_three — российские бутылки каталога по оценке сорта ± поправки стиля (п. 4.3).
3. similar — «мост» от знакомого сорта к российскому по евклидову расстоянию профилей (п. 4.4).
4. dishes_for — обратный сценарий: блюда справочника к бутылке (п. 4.5).
5. score_analog — российский аналог зарубежного вина по его свойствам (тело, танины, кислотность, сладость, сорт, дуб).
Каждая оценка раскладывается на факторы (rule, points, text) — их показывает кнопка «Почему это сочетание?».
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .catalog import Bottle
from .reference import SWEETNESS, Dish, Grape

TANNIN_WORD = {0.0: "без танинов", 1.0: "низкие", 1.5: "мягкие", 2.0: "средние", 2.5: "заметные", 3.0: "высокие"}


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass
class DishProfile:
    """Профиль блюда на осях 0–3 (п. 4.1). source: dictionary — из справочника, llm/keywords — оценка, а не справочник."""
    name: str
    body: float
    fat_protein: float
    acid: float
    spicy: float
    salty: float
    sweet: float
    cuisine: str = ""
    tags: tuple[str, ...] = ()
    dish_id: str | None = None
    source: str = "dictionary"

    @classmethod
    def from_dish(cls, d: Dish) -> DishProfile:
        return cls(name=d.name, dish_id=d.id, tags=d.tags, **d.profile())

    def as_dict(self) -> dict:
        return dict(name=self.name, dish_id=self.dish_id, body=self.body, fat_protein=self.fat_protein, acid=self.acid,
                    spicy=self.spicy, salty=self.salty, sweet=self.sweet, cuisine=self.cuisine, tags=list(self.tags),
                    source=self.source, estimated=self.source != "dictionary")


@dataclass
class GrapeScore:
    grape: Grape
    score: float
    oak: str | None
    factors: list[dict] = field(default_factory=list)


def grape_profile(g: Grape, oak: str | None = None) -> dict:
    return dict(tannins=g.tannins, acidity=g.acidity, body=g.body_for(oak))


def score_grape(g: Grape, dish: DishProfile, w: dict, oak: str | None = None, sweetness: int | None = None,
                profile: dict | None = None) -> GrapeScore:
    """Оценка сорта к блюду. oak/сладость/profile (танины, кислотность, тело) — стиль конкретной бутылки, если задан.
    Без oak у сорта «оба» берётся лучший стиль."""
    if oak is None and len(g.oak_options()) > 1:
        return max((score_grape(g, dish, w, o, sweetness, profile) for o in g.oak_options()), key=lambda s: s.score)
    oak = oak if oak is not None else g.oak_options()[0]
    sweet = g.sweetness if sweetness is None else sweetness
    p = profile or grape_profile(g, oak)
    body, tannins, acidity = p["body"], p["tannins"], p["acidity"]
    factors: list[dict] = []

    def add(rule, points, text):
        if abs(points) >= 0.05 or rule in ("body", "tannin"):  # совпадение тела и танинов — тоже довод
            factors.append(dict(rule=rule, points=round(points, 1), text=text))

    d = abs(body - dish.body)
    add("body", -w["body_per_unit"] * d,
        "тело вина в тон насыщенности блюда" if d <= 0.5 else
        f"вино {'заметно ' if d >= 1.5 else ''}{'плотнее' if body > dish.body else 'легче'} блюда")
    d = abs(tannins - dish.fat_protein)
    add("tannin", -w["tannin_per_unit"] * d,
        "танины в меру жира и белка блюда" if d <= 0.5 else
        ("танинов больше, чем нужно этому блюду" if tannins > dish.fat_protein else "танинов мало для жира и белка блюда"))
    short = max(0.0, dish.acid - acidity)
    add("acid", -w["acid_shortfall_per_unit"] * short, "кислотность вина ниже кислотности блюда — вино покажется плоским")
    add("spicy_tannin", -w["spicy_tannin"] * dish.spicy * tannins / 3, "танины усиливают остроту")
    heat = max(dish.spicy, dish.salty) / 3
    relief = 0.5 * _clip((acidity - 2) / 2) + 0.5 * _clip(sweet / 2)
    add("spicy_salty", w["spicy_salty_bonus_max"] * heat * relief,
        "кислотность и сладость вина гасят остроту и солёность")
    if dish.sweet >= w["sweet_dish_min"] and sweet < dish.sweet:
        add("sweet_dish", -w["sweet_dish_penalty"], "вино суше десерта — рядом со сладким покажется кислым и горьким")
    excess = sweet - dish.sweet - 1
    if excess > 0:
        add("sweet_wine", -w["sweet_wine_dry_dish_per_unit"] * excess, "сладкое вино спорит с несладким блюдом")
    rules = [r for r in g.pairing_rules if (r.oak is None or r.oak == oak) and set(r.tags) & set(dish.tags)]
    if rules:
        best = max(rules, key=lambda r: r.weight)
        add("rule_dish", w["rule_dish_bonus"] * best.weight, f"«{best.term}» прямо названо в правиле сорта")
    if dish.cuisine and dish.cuisine in g.cuisines:
        add("cuisine", w["cuisine_bonus"], f"кухня блюда ({dish.cuisine}) названа в правиле сорта")
    score = _clip(w["base"] + sum(f["points"] for f in factors), 0, 100)
    return GrapeScore(grape=g, score=round(score, 1), oak=oak, factors=factors)


def rank_grapes(grapes: list[Grape], dish: DishProfile, w: dict) -> list[GrapeScore]:
    return sorted((score_grape(g, dish, w) for g in grapes if g.active), key=lambda s: (-s.score, s.grape.grape_id))


# ---- бутылки ------------------------------------------------------------------------------------
@dataclass
class ScoredBottle:
    bottle: Bottle
    grape: Grape
    grape_score: float
    score: float
    factors: list[dict]
    adjustments: list[dict]
    role: str = ""


def bottle_profile(b: Bottle, g: Grape, oak: str | None, card_weight: float) -> tuple[dict, list[str]]:
    """Профиль бутылки = профиль сорта (в её стиле по дубу) + поправки стиля: розовое/оранжевое/белое из красного сорта,
    игристое, затем признаки из описания карточки (тело, танины, кислотность) с весом card_weight."""
    p, notes = grape_profile(g, oak), []
    if b.color == "Розовое" and g.color == "Красное":
        p.update(tannins=min(p["tannins"], 0.5), body=min(p["body"], 1.5), acidity=max(p["acidity"], 2.5))
        notes.append("розовое: почти без танинов и легче красного")
    elif b.color == "Белое" and g.color == "Красное":
        p.update(tannins=0.0, body=min(p["body"], 2.0))
        notes.append("белое из красного сорта: без танинов")
    elif b.color == "Оранжевое":
        p.update(tannins=max(p["tannins"], 1.0))
        notes.append("оранжевое: лёгкие танины от мацерации")
    if b.sparkling:
        p.update(body=max(1.0, p["body"] - 0.5), acidity=max(p["acidity"], 3.0))
        notes.append("игристое: свежее и легче")
    seen = []
    for key, word in (("body", "тело"), ("tannins", "танины"), ("acidity", "кислотность")):
        value = getattr(b, key)
        if value is not None:
            p[key] = round((1 - card_weight) * p[key] + card_weight * value, 2)
            seen.append(word)
    if seen:
        notes.append("по описанию вина уточнены " + ", ".join(seen))
    return p, notes


def score_bottle(b: Bottle, g: Grape, dish: DishProfile, w: dict, r: dict) -> ScoredBottle:
    """Оценка бутылки = оценка сорта в её стиле (дуб, сладость, цвет, игристость, описание) ± отход от сладости правила сорта."""
    oak = b.oak if b.oak in ("да", "нет") else None
    sweet = SWEETNESS.get(b.sweetness or "", g.sweetness)
    base = score_grape(g, dish, w)
    best = None
    for o in ([oak] if oak else g.oak_options()):
        p, notes = bottle_profile(b, g, o, r["card_weight"])
        gs = score_grape(g, dish, w, oak=o, sweetness=sweet, profile=p)
        if best is None or gs.score > best[0].score:
            best = (gs, notes)
    gs, notes = best
    adjustments = []
    if gs.score != base.score:
        style = ["с дубом" if gs.oak == "да" else "без дуба", b.sweetness or g.sweetness_default, *notes]
        adjustments.append(dict(rule="style", points=round(gs.score - base.score, 1), text="стиль бутылки: " + "; ".join(style)))
    steps = abs(sweet - g.sweetness)
    if steps and not (dish.sweet >= w["sweet_dish_min"] and sweet > g.sweetness):
        adjustments.append(dict(rule="sweetness", points=-r["sweetness_deviation_per_step"] * steps,
                                text=f"сладость отличается от правила сорта ({g.sweetness_default})"))
    score = _clip(gs.score + sum(a["points"] for a in adjustments if a["rule"] == "sweetness"), 0, 100)
    return ScoredBottle(bottle=b, grape=g, grape_score=base.score, score=round(score, 1), factors=gs.factors, adjustments=adjustments)


ROLE_LABEL = {"best_match": "Лучшее сочетание", "other_grape": "Другой сорт", "other_price": "Вариант в другой цене",
              "next_best": "Ещё вариант", "gift": "Для подарка", "analog": "Российский аналог"}


def pick_three(scored: list[ScoredBottle], r: dict) -> list[ScoredBottle]:
    """Три российские бутылки без повторов: лучшее сочетание, лучшая бутылка другого сорта, вариант в другой цене
    (если цены известны) или ещё один сорт / винодельня."""
    ranked = sorted((s for s in scored if s.score >= r["min_grape_score"]), key=lambda s: (-s.score, s.bottle.price_rub or 0, s.bottle.slug))
    return diverse(ranked, r["top_bottles"], r["other_price_min_ratio"])


def diverse(ranked: list, k: int, price_ratio: float) -> list:
    """Разнообразная выдача из отсортированного списка (ScoredBottle / ScoredAnalog) с ролями. Одна винодельня — один раз,
    пока есть из чего выбирать."""
    if not ranked:
        return []
    ranked[0].role = "best_match"
    out = [ranked[0]]

    def free(x, new_grape):
        return x not in out and all(o.bottle.producer != x.bottle.producer for o in out) and \
            (not new_grape or all(o.grape.grape_id != x.grape.grape_id for o in out))

    def other_price(x):
        p, prices = x.bottle.price_rub, [o.bottle.price_rub for o in out if o.bottle.price_rub]
        return bool(p and prices) and all(abs(p - q) / max(p, q) >= price_ratio for q in prices)

    while len(out) < k:
        candidates = [("other_price", lambda x: len(out) == 2 and free(x, False) and other_price(x)),
                      ("other_grape", lambda x: free(x, True)), ("next_best", lambda x: free(x, False)),
                      ("next_best", lambda x: x not in out)]
        pick = None
        for role, ok in candidates:
            pick = next((x for x in ranked if ok(x)), None)
            if pick is not None:
                pick.role = role
                break
        if pick is None:
            break
        out.append(pick)
    return out


# ---- «мост» и сравнение профилей (п. 4.4) -------------------------------------------------------------
def distance(a: Grape, b: Grape, color_weight: float) -> float:
    color = 0.0 if a.color == b.color else color_weight
    return math.sqrt((a.tannins - b.tannins) ** 2 + (a.acidity - b.acidity) ** 2 + (a.body - b.body) ** 2 + color ** 2)


def compare_parts(src: dict, dst: dict, signature: str = "") -> list[str]:
    """Чем профиль dst похож на src и чем отличается: «та же плотность и танины», «свежее», «больше пряности»."""
    parts = []
    same_body, same_tannins = abs(src["body"] - dst["body"]) <= 0.5, abs(src["tannins"] - dst["tannins"]) <= 0.5
    if same_body and same_tannins:
        parts.append("та же плотность и танины")
    elif same_body:
        parts.append("та же плотность")
    elif same_tannins:
        parts.append("те же танины")
    if not same_body:
        parts.append("плотнее" if dst["body"] > src["body"] else "легче")
    if not same_tannins:
        parts.append("танины жёстче" if dst["tannins"] > src["tannins"] else "танины мягче")
    if abs(src["acidity"] - dst["acidity"]) > 0.5:
        parts.append("свежее" if dst["acidity"] > src["acidity"] else "мягче по кислотности")
    if signature:
        parts.append(signature)
    return parts or ["похожий профиль"]


def bridge_phrase(src: Grape, dst: Grape) -> str:
    """«Любите Каберне Совиньон? Попробуйте Красностоп Золотовский: та же плотность и танины, больше пряности»."""
    if src.grape_id == dst.grape_id:
        return f"Любите {src.name}? Попробуйте российский {dst.name}: тот же сорт, местный характер."
    return f"Любите {src.name}? Попробуйте {dst.name}: {', '.join(compare_parts(grape_profile(src), grape_profile(dst), dst.signature))}."


def similar(src: Grape, grapes: list[Grape], s: dict, russian: bool = True) -> list[dict]:
    """Ближайшие сорта по танинам, кислотности, телу и цвету (не дальше max_distance); russian=True — только автохтоны."""
    pool = [g for g in grapes if g.active and g.grape_id != src.grape_id and (g.is_russian_origin or not russian)
            and distance(src, g, s["color_weight"]) <= s["max_distance"]]
    ranked = sorted(pool, key=lambda g: (distance(src, g, s["color_weight"]), g.grape_id))
    return [dict(grape=g, distance=round(distance(src, g, s["color_weight"]), 2), phrase=bridge_phrase(src, g)) for g in ranked]


# ---- российский аналог зарубежного вина ----------------------------------------------------------------
@dataclass
class ScoredAnalog:
    bottle: Bottle
    grape: Grape
    score: float
    factors: list[dict]
    profile: dict
    role: str = ""


def score_analog(target: dict, b: Bottle, g: Grape, a: dict, card_weight: float) -> ScoredAnalog:
    """Близость российской бутылки к свойствам зарубежного вина: расстояние профилей, сладость, сорт, дуб."""
    oak = b.oak if b.oak in ("да", "нет") else (target.get("oak") if target.get("oak") in g.oak_options() else None)
    p, notes = bottle_profile(b, g, oak, card_weight)
    d = math.sqrt(sum((p[k] - target[k]) ** 2 for k in ("tannins", "acidity", "body")))
    factors = [dict(rule="profile", points=round(-a["per_unit"] * d, 1), text="профиль: " + ", ".join(compare_parts(target, p)))]
    if target.get("sweetness") is not None:
        steps = abs(SWEETNESS.get(b.sweetness or "", g.sweetness) - target["sweetness"])
        if steps:
            factors.append(dict(rule="sweetness", points=-a["sweet_per_step"] * steps, text="сладость отличается"))
    if g.grape_id in target.get("grape_ids", []):
        factors.append(dict(rule="same_grape", points=a["same_grape_bonus"], text=f"тот же сорт — {g.name}"))
    if target.get("oak") == "да" and b.oak == "да":
        factors.append(dict(rule="oak", points=a["oak_bonus"], text="тоже с выдержкой в дубе"))
    if notes:
        factors.append(dict(rule="style", points=0.0, text="; ".join(notes)))
    score = _clip(100 + sum(f["points"] for f in factors), 0, 100)
    return ScoredAnalog(bottle=b, grape=g, score=round(score, 1), factors=factors, profile=p)


# ---- обратный сценарий (п. 4.5) -----------------------------------------------------------------
def dishes_for(g: Grape, dishes: list[Dish], w: dict, oak: str | None = None, sweetness: int | None = None, k: int = 5) -> list[dict]:
    scored = []
    for d in dishes:
        gs = score_grape(g, DishProfile.from_dish(d), w, oak=oak, sweetness=sweetness)
        scored.append(dict(dish_id=d.id, name=d.name, cuisine=d.cuisine, score=gs.score,
                           why=[f["text"] for f in gs.factors if f["points"] > 0][:2]))
    return sorted(scored, key=lambda x: (-x["score"], x["dish_id"]))[:k]
