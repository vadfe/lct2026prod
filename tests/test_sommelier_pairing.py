"""Подбор «блюдо → сорт → бутылка» (ТЗ «Доработка цифрового сомелье»): справочники, скоринг, каталог, LLM-слой, API."""
import json
import re
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.sommelier.pairing_router import router as pairing_router
from app.sommelier.pairing import CatalogUnavailable, build_pairing_service
from app.sommelier.pairing.catalog import (
    DEMO_CSV,
    OPTIONAL,
    REQUIRED,
    RETAIL_NOT_CONNECTED,
    TEMPLATE_CSV,
    Bottle,
    CatalogFilters,
    RetailCatalogProvider,
    RetailConfig,
    make_provider,
    parse_catalog_row,
)
from app.sommelier.pairing.enrich import enrich
from app.sommelier.pairing.llm_layer import LLMLog, check_explanation, parse_query, stop_words
from app.sommelier.pairing.reference import (
    GRAPES_JSON,
    DishBook,
    GrapeBook,
    ReferenceDataError,
    load_config,
    load_reference,
    parse_grapes_csv,
)
from app.sommelier.pairing.scoring import DishProfile, ScoredBottle, pick_three, rank_grapes, score_grape, similar

GB, DB, CFG = GrapeBook(), DishBook(), load_config()
W, R = CFG["score"], CFG["ranking"]
SVC = build_pairing_service("demo")          # демо-каталог: 12 российских + 9 зарубежных бутылок с ценами
SCAN = build_pairing_service("service")      # каталог сканера: российские вина базы распознавания, без цен


def all_russian(r):
    return all(w["is_russian"] and w["country"] == "Россия" for w in r.get("wines", []))


def dish(dish_id):
    return DishProfile.from_dish(DB.by_id[dish_id])


# ---- 2. справочник сортов ------------------------------------------------------------------------
def test_all_nine_table_grapes_load_with_numeric_scales():
    rows = parse_grapes_csv()
    assert len(rows) == 9
    assert sum(r["color"] == "Красное" for r in rows) == 5 and sum(r["color"] == "Белое" for r in rows) == 4
    by = {g.grape_id: g for g in GB.grapes}
    assert (by["cabernet_sauvignon"].tannins, by["cabernet_sauvignon"].acidity, by["cabernet_sauvignon"].body) == (3, 2, 3)
    assert (by["merlot"].tannins, by["merlot"].body) == (1.5, 2.5)          # «Низкие/Средние», «Среднее/Полное»
    assert (by["riesling"].acidity, by["riesling"].body) == (4, 1.5)        # «Очень высокая», «Легкое/Среднее»
    assert (by["muscat_white"].acidity, by["muscat_white"].type) == (1.5, "Белое/Десертное")
    assert by["krasnostop_zolotovsky"].tannins == 2.5 and by["krasnostop_zolotovsky"].is_russian_origin
    # правило из таблицы для LLM — без изменений
    assert by["saperavi"].pairing_text.startswith("Мощная структура требует насыщенных вкусов")


def test_unknown_scale_value_is_load_error_with_row(tmp_path):
    src = open(parse_grapes_csv.__defaults__[0], encoding="utf-8-sig").read().replace("Высокие,Средняя,Полное", "Огромные,Средняя,Полное", 1)
    bad = tmp_path / "vine_tastes.csv"
    bad.write_text(src, encoding="utf-8-sig")
    with pytest.raises(ReferenceDataError, match=r"строка 2.*Танины.*Огромные"):
        parse_grapes_csv(str(bad))


def test_grape_fields_and_aliases():
    for g in GB.grapes:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", g.grape_id)
        assert g.sweetness_default in ("сухое", "полусухое", "полусладкое", "сладкое") and g.oak_variants in ("да", "нет", "оба")
        assert g.pairing_rules and len(g.story) <= 300 and g.pairing_text
    assert GB.resolve("Krasnostop").grape_id == "krasnostop_zolotovsky"
    assert GB.resolve("Каберне-Совиньон").grape_id == "cabernet_sauvignon"
    assert GB.resolve("Рислинг Рейнский").grape_id == "riesling"
    assert GB.find_in("люблю каберне").grape_id == "cabernet_sauvignon"


def test_chardonnay_rule_is_conditional_on_oak():
    ch = GB.by_id["chardonnay"]
    assert {r.oak for r in ch.pairing_rules} == {"да", "нет"}
    oaked = score_grape(ch, dish("fish_cream"), W, oak="да")
    unoaked = score_grape(ch, dish("fish_cream"), W, oak="нет")
    assert any(f["rule"] == "rule_dish" for f in oaked.factors) and not any(f["rule"] == "rule_dish" for f in unoaked.factors)
    assert any(f["rule"] == "rule_dish" for f in score_grape(ch, dish("oysters"), W, oak="нет").factors)
    assert score_grape(ch, dish("fish_cream"), W).oak == "да"   # без указания стиля берётся лучший


def test_russian_extension_is_draft_and_excluded_until_signed():
    ru = [g for g in GB.grapes if g.source == "grapes.json"]
    assert len(ru) >= 6 and all(g.is_russian_origin for g in ru)
    names = {g.name for g in ru}
    assert {"Цимлянский чёрный", "Сибирьковый", "Кокур белый", "Пухляковский", "Голубок"} <= names
    assert all(g.status == "draft" and g.signed_by is None for g in ru)
    draft = {g.grape_id for g in ru}
    for d in DB.dishes:
        assert not {s.grape.grape_id for s in rank_grapes(GB.grapes, DishProfile.from_dish(d), W)} & draft
    assert not {a["grape"].grape_id for a in similar(GB.by_id["cabernet_sauvignon"], GB.grapes, CFG["similar"])} & draft


def test_reference_files_are_versioned():
    meta = json.load(open(GRAPES_JSON, encoding="utf-8"))
    assert meta["version"] and DB.version and CFG["version"]


# ---- 4.1 справочник блюд ------------------------------------------------------------------------
def test_dish_dictionary_size_axes_and_synonyms():
    assert len(DB.dishes) >= 60
    for q in ("шашлык", "шашлычок", "мясо на мангале", "что взять к шашлыку"):
        assert DB.find(q).id == "shashlik", q
    assert DB.find("к утке").id == "duck"
    assert DB.find("под устриц").id == "oysters"
    assert DB.find("квантовая физика") is None


# ---- 4.2 скоринг --------------------------------------------------------------------------------
def test_scoring_rules_and_weights_from_config():
    cab, sb = GB.by_id["cabernet_sauvignon"], GB.by_id["sauvignon_blanc"]
    steak = score_grape(cab, dish("steak"), W)
    assert steak.score == 100 and any(f["rule"] == "rule_dish" and f["points"] == W["rule_dish_bonus"] for f in steak.factors)
    cake = score_grape(cab, dish("cake"), W)
    assert any(f["rule"] == "sweet_dish" and f["points"] == -W["sweet_dish_penalty"] for f in cake.factors)
    curry = score_grape(cab, dish("thai_curry"), W)
    assert any(f["rule"] == "spicy_tannin" and f["points"] == -18.0 for f in curry.factors)   # 6 × острота 3 × танины 3 / 3
    body = next(f for f in score_grape(sb, dish("steak"), W).factors if f["rule"] == "body")
    assert body["points"] == -W["body_per_unit"] * 2
    softer = dict(W, body_per_unit=0)
    assert score_grape(sb, dish("steak"), softer).score > score_grape(sb, dish("steak"), W).score
    assert all(0 <= s.score <= 100 for d in DB.dishes for s in rank_grapes(GB.grapes, DishProfile.from_dish(d), W))


# ---- 8.1 эталонный набор ------------------------------------------------------------------------
def test_reference_metrics():
    ref = load_reference()
    pairs = ref["pairs"]
    assert len(pairs) >= 60 and all(1 <= len(p["good"]) <= 3 and 1 <= len(p["bad"]) <= 2 for p in pairs)
    hit = bad = slots = with_grape = answered = 0
    for p in pairs:
        ranked = rank_grapes(GB.grapes, dish(p["dish"]), W)
        top = [s.grape.grape_id for s in ranked if s.score >= R["min_grape_score"]][:3]
        hit += bool(set(top) & set(p["good"]))
        bad += len(set(top) & set(p["bad"]))
        slots += len(top)
        r = SCAN.pair_dish(DB.by_id[p["dish"]].name)
        assert all_russian(r)
        if top:
            with_grape += 1
            answered += bool(r["wines"])
    assert hit / len(pairs) >= 0.85
    assert bad / slots <= 0.05
    assert answered / with_grape >= 0.90     # есть подходящий сорт -> есть российская бутылка в каталоге


# ---- 4.3 ранжирование: только российские вина каталога -------------------------------------------------
def _sb(slug, score, producer, grape="merlot", price=None):
    g = GB.by_id[grape]
    b = Bottle(slug=slug, name=slug, producer=producer, grape=g.name, grape_id=grape, color=g.color, sweetness="сухое", oak="нет",
               country="Россия", region="Крым", price_rub=price, is_russian=True)
    return ScoredBottle(bottle=b, grape=g, grape_score=score, score=score, factors=[], adjustments=[])


def test_pick_three_diverse_grapes_producers_and_price():
    scored = [_sb("a", 95, "W1", price=1000), _sb("b", 94, "W1", price=1000), _sb("c", 90, "W2", "pinot_noir", 1100),
              _sb("d", 85, "W3", price=2500), _sb("e", 80, "W4", "saperavi", 1050)]
    out = pick_three(scored, R)
    assert [s.bottle.slug for s in out] == ["a", "c", "d"]
    assert [s.role for s in out] == ["best_match", "other_grape", "other_price"]
    scored = [_sb("a", 95, "W1"), _sb("b", 94, "W2"), _sb("c", 90, "W3", "saperavi"), _sb("x", 50, "W4", "pinot_noir")]
    out = pick_three(scored, R)                       # без цен: другой сорт, затем другая винодельня; ниже 60 — не берём
    assert [s.bottle.slug for s in out] == ["a", "c", "b"] and out[2].role == "next_best"


def test_only_russian_wines_in_every_scenario():
    """Покупатель остаётся в нашем торговом пространстве: зарубежных бутылок нет ни в одном сценарии."""
    for svc in (SVC, SCAN):
        for q in ("стейк", "устрицы", "тирамису", "к утке", "подарок", "люблю каберне", "аналог Шабли", "замена Бароло"):
            r = svc.pair_dish(q)
            assert r["russian_only"] is True and r["wines"] and all_russian(r), (svc.catalog_source, q)
        assert all_russian(svc.similar("cabernet_sauvignon", russian=False))
    foreign = {b.slug for b in SVC.provider.list_wines(CatalogFilters()) if not b.is_russian}
    assert len(foreign) == 9
    for d in DB.dishes:
        assert not {w["slug"] for w in SVC.pair_dish(d.name)["wines"]} & foreign, d.name


def test_three_bottles_without_repeats_with_budget():
    r = SVC.pair_dish("что взять к шашлыку, до 1500, не сладкое")
    assert r["kind"] == "pairing" and r["dish_profile"]["dish_id"] == "shashlik" and not r["notes"]
    slugs = [w["slug"] for w in r["wines"]]
    assert len(slugs) == len(set(slugs)) >= 2
    assert all(w["price_rub"] <= 1500 and w["sweetness"] in ("сухое", "полусухое") for w in r["wines"])
    assert all(w["russia_mark"] == "Россия" and w["score"] >= R["min_grape_score"] for w in r["wines"])
    for w in r["wines"]:   # карточка: название, производитель, регион, цена, отметка «Россия», объяснение, правило сорта
        assert w["name"] and w["producer"].startswith("Демо-") and w["region"] and w["explanation"] and w["why"]["rule"]


def test_scanner_catalog_without_prices_ignores_budget_with_note():
    h = SCAN.health()
    assert h["catalog_source"] == "service" and h["catalog"]["items"] > 2000 and h["russian_only"]
    r = SCAN.pair_dish("шашлык до 1500")
    assert r["notes"] == ["В каталоге нет цен — бюджет не учтён."] and len(r["wines"]) == 3
    assert len({w["producer"] for w in r["wines"]}) == 3
    assert all(w["url"] and w["price_rub"] is None for w in r["wines"])
    assert "₽" not in r["explanation"]


def test_rose_and_sparkling_style_adjust_bottle_profile():
    from app.sommelier.pairing.scoring import bottle_profile
    pinot = GB.by_id["pinot_noir"]
    rose = Bottle(slug="r", name="r", producer="p", grape="Пино Нуар", grape_id="pinot_noir", color="Розовое", sweetness="сухое",
                  oak=None, country="Россия", region="Крым", price_rub=None, is_russian=True, sparkling=True)
    p, notes = bottle_profile(rose, pinot, None, R["card_weight"])
    assert p["tannins"] <= 0.5 and p["acidity"] >= 3 and len(notes) == 2


def test_filters_color_and_store():
    r = SVC.pair_dish("устрицы", {"color": "Белое", "store_id": "demo-store-1"})
    assert r["wines"] and all(w["color"] == "Белое" for w in r["wines"])


# ---- аналог зарубежного вина ---------------------------------------------------------------------
def test_analog_by_rules_without_llm():
    r = SCAN.pair_dish("аналог Шабли")
    assert r["kind"] == "analog" and r["foreign"]["name"] == "Шабли" and r["source"]["foreign_profile"] == "rules"
    assert len(r["wines"]) == 3 and all_russian(r) and all(w["color"] == "Белое" and not w["sparkling"] for w in r["wines"])
    assert all(w["explanation"].startswith("Похоже на «Шабли»") for w in r["wines"])
    r = SCAN.analog("замена Бароло")
    assert r["wines"][0]["grape_id"] in ("saperavi", "cabernet_sauvignon", "krasnostop_zolotovsky") and all_russian(r)
    assert SCAN.pair_dish("аналог чего-нибудь")["kind"] == "clarify"


def test_analog_uses_llm_for_properties_but_algorithm_picks_wine():
    described = dict(name="Barolo DOCG", country="Италия", grapes=["Неббиоло"], color="Красное", sweetness="сухое",
                     tannins=3, acidity=3.5, body=3, oak="да", notes="Château Fake как пример")
    calls = []

    def fn(system, user):
        calls.append(system)
        return json.dumps(described, ensure_ascii=False)

    svc = build_pairing_service("demo", llm=FakeLLM(fn))
    r = svc.pair_dish("найди аналог бароло")
    assert r["kind"] == "analog" and r["source"]["foreign_profile"] == "llm" and r["foreign"]["name"] == "Barolo DOCG"
    assert r["wines"] and all_russian(r) and all(w["slug"].startswith("demo-") for w in r["wines"])
    assert {w["slug"] for w in r["wines"]} <= {b.slug for b in svc.provider.list_wines(CatalogFilters()) if b.is_russian}
    assert len(calls) == 1 and "российский аналог" in calls[0].lower()


def test_analog_llm_invalid_falls_back_to_rules():
    svc = build_pairing_service("demo", llm=FakeLLM('{"name": "X", "color": "Синее"}'))
    r = svc.analog("аналог шабли")
    assert r["source"]["foreign_profile"] == "rules" and r["wines"] and all_russian(r)


# ---- 4.4 / 4.5 «мост» и обратный сценарий ------------------------------------------------------------
def test_similar_cabernet_bridges_to_krasnostop():
    r = SCAN.similar("cabernet_sauvignon", russian=True)
    assert r["analogs"][0]["grape_id"] == "krasnostop_zolotovsky"
    assert r["analogs"][0]["phrase"] == ("Любите Каберне Совиньон? Попробуйте Красностоп Золотовский: "
                                         "та же плотность и танины, больше пряности.")
    assert len(r["wines"]) >= 2 and all_russian(r) and r["catalog_source"] == "service"
    assert r["wines"][0]["grape_id"] == "krasnostop_zolotovsky"
    assert SVC.similar("no_such_grape") is None


def test_pair_wine_returns_five_dishes_and_rule():
    r = SVC.pair_wine("demo-kubanskaya-dolina-kaberne")
    assert r["kind"] == "wine" and len(r["dishes"]) == 5
    assert r["rule"] == GB.by_id["cabernet_sauvignon"].pairing_text
    assert r["dishes"] == sorted(r["dishes"], key=lambda d: -d["score"]) and r["dishes"][0]["dish_id"] == "steak"
    assert r["bridge"].startswith("Любите Каберне Совиньон?")
    assert SVC.pair_wine("no-such-slug") is None


def test_pair_wine_from_label_recognition_slug():
    wines = {"fanagoriya-kaberne": dict(id="fanagoriya-kaberne", name="Каберне", winery="Фанагория", grape="Каберне Совиньон",
                                        category="Красное", region="Кубань", features=dict(sweetness=0, oak=False))}
    svc = build_pairing_service("demo", recognition=wines.get)
    r = svc.pair_wine("fanagoriya-kaberne")
    assert r["wine"]["source"] == "recognition" and r["wine"]["grape_id"] == "cabernet_sauvignon" and len(r["dishes"]) == 5
    slug = next(b.slug for b in SCAN.provider.list_wines(CatalogFilters(grape_ids=["saperavi"])))
    r = SCAN.pair_wine(slug)                       # каталог сканера: slug распознанной этикетки
    assert r["wine"]["source"] == "service" and len(r["dishes"]) == 5 and r["rule"].startswith("Мощная структура")


# ---- 3. каталог ---------------------------------------------------------------------------------
def test_demo_catalog_is_fictional():
    h = SVC.provider.health()
    assert (h.source, h.items, h.details["russian"]) == ("demo", 21, 12)
    bottles = SVC.provider.list_wines(CatalogFilters())
    assert all(b.producer.startswith("Демо-") and b.source == "demo" for b in bottles)
    assert SVC.provider.get_stock(bottles[0].slug, "any-store")["in_stock"] is True


def test_retail_provider_switch_and_clear_error():
    p = make_provider("retail", GB, retail=RetailConfig(kind="api", url="https://example.invalid"))
    assert isinstance(p, RetailCatalogProvider)
    for call in (lambda: p.list_wines(CatalogFilters()), lambda: p.get_by_slug("x"), lambda: p.get_stock("x", None)):
        with pytest.raises(NotImplementedError, match=RETAIL_NOT_CONNECTED):
            call()
    svc = build_pairing_service("retail")
    assert svc.health()["catalog_source"] == "retail" and svc.health()["status"] == "degraded"
    with pytest.raises(CatalogUnavailable, match=RETAIL_NOT_CONNECTED):
        svc.pair_dish("стейк")
    with pytest.raises(ValueError):
        make_provider("excel", GB)


def test_template_csv_and_row_validation():
    header = open(TEMPLATE_CSV, encoding="utf-8-sig").readline().strip().split(",")
    assert set(REQUIRED) | set(OPTIONAL) == set(header)
    row = dict(zip(header, open(TEMPLATE_CSV, encoding="utf-8-sig").read().splitlines()[1].split(","), strict=True))
    b = parse_catalog_row(row, GB, "template", "retail")
    assert b.is_russian and b.grape_id == "krasnostop_zolotovsky"   # is_russian вычислен из country
    for field, value, msg in (("barcode", "4601234567890", "EAN-13"), ("grape", "Неизвестный сорт", "aliases"),
                              ("region", "Луна", "регион"), ("sweetness", "брют", "сладость")):
        with pytest.raises(ValueError, match=msg):
            parse_catalog_row(dict(row, **{field: value}), GB, "строка 2", "retail")
    assert open(DEMO_CSV, encoding="utf-8-sig").readline().strip().split(",")[:len(header)] == header


# ---- 3.4 обогащение -----------------------------------------------------------------------------
class FakeLLM:
    name = "fake"

    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def complete(self, system, user, max_tokens, json_mode=False):
        self.calls.append((system, user))
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply(system, user) if callable(self.reply) else self.reply


def test_enrichment_rules_and_review_flag():
    e = enrich(dict(name="Красностоп Золотовский сухое, выдержанное в дубе"), GB)
    assert (e.grape_id, e.sweetness, e.oak, e.needs_review) == ("krasnostop_zolotovsky", "сухое", "да", True)
    e = enrich(dict(name="Вино красное", grape="Мерло", sweetness="сухое", oak="нет"), GB)
    assert not e.needs_review
    e = enrich(dict(name="Красное вино N7"), GB, FakeLLM('{"grape": "Пино Неизвестный", "sweetness": "сухое", "oak": null}'))
    assert e.grape_id is None and e.sweetness == "сухое" and e.method["sweetness"] == "llm"   # сорт вне aliases не принят


def test_unreviewed_and_grapeless_bottles():
    b = SVC.provider.get_by_slug("demo-yuzhny-bereg-merlo")
    b.needs_review = True
    try:
        assert b.slug not in {w["slug"] for w in SVC.pair_dish("пицца")["wines"]}
        assert SVC.pair_wine(b.slug)["wine"]["needs_review"] is True       # по slug доступна
    finally:
        b.needs_review = False


# ---- 5. LLM-слой --------------------------------------------------------------------------------
def test_llm_query_parse_validated_and_retried(tmp_path):
    log = LLMLog(str(tmp_path / "log.jsonl"))
    good = '{"dish": "шашлык", "budget_max": 1500, "sweetness": ["сухое", "полусухое"], "color": null, "liked_grape": null}'
    q = parse_query("что взять к шашлыку, до 1500, не сладкое", FakeLLM(good), ["Шашлык"], log)
    assert q.dish == "шашлык" and q.budget_max == 1500
    replies = iter(['{"dish": "шашлык", "budget": "дёшево"}', good])
    llm = FakeLLM(lambda s, u: next(replies))
    assert parse_query("к шашлыку", llm, [], log).dish == "шашлык" and len(llm.calls) == 2   # повтор после ошибки схемы
    assert parse_query("к шашлыку", FakeLLM("не JSON"), [], log) is None
    lines = [json.loads(x) for x in (tmp_path / "log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert lines and all(x["kind"] == "parse" and "user" in x for x in lines)


def test_llm_parse_failure_asks_clarifying_question():
    svc = build_pairing_service("demo", llm=FakeLLM("мусор"))
    assert svc.pair_dish("хочу что-нибудь вкусное")["kind"] == "clarify"
    assert svc.pair_dish("к утке")["kind"] == "pairing"         # справочник находит блюдо и без LLM


def test_llm_unknown_dish_profile_marked_as_estimate():
    reply = json.dumps(dict(dish="севиче из гребешка с маракуйей", dish_profile=dict(body=2, fat_protein=1, acid=0.5, spicy=0,
                                                                                   salty=1.5, sweet=0, cuisine="латиноамериканская")))
    svc = build_pairing_service("demo", llm=FakeLLM(lambda s, u: reply if "JSON по схеме" in s else "x"))
    r = svc.pair_dish("севиче из гребешка с маракуйей")
    assert SVC.pair_dish("севиче из гребешка с маракуйей")["dish_profile"]["source"] == "keywords"   # без LLM — оценка по словам
    assert r["dish_profile"]["source"] == "llm" and r["dish_profile"]["estimated"] is True


def _explain_with(reply):
    def fn(system, user):
        if "JSON по схеме" in system:
            return '{"dish": "стейк"}'
        return reply(json.loads(user)) if callable(reply) else reply
    svc = build_pairing_service("demo", llm=FakeLLM(fn))
    return svc.pair_dish("стейк")


def test_llm_explanation_accepted_when_it_matches_algorithm():
    def ok(payload):
        return " ".join(f"{w['name']} за {int(w['price_rub'])} ₽: танины держат жир стейка." for w in payload["WINES"])
    r = _explain_with(ok)
    assert r["source"]["explanation"] == "llm" and all(w["name"] in r["explanation"] for w in r["wines"])


@pytest.mark.parametrize("reply", [
    lambda p: " ".join(w["name"] for w in p["WINES"]) + " и ещё «Шато Выдумка» 2015 года.",          # выдуманная бутылка
    lambda p: " ".join(f"{w['name']} за 99 ₽" for w in p["WINES"]),                                     # чужая цена
    lambda p: " ".join(w["name"] for w in p["WINES"]) + ". Купите сейчас, скидка!",                    # призыв к покупке
    lambda p: p["WINES"][0]["name"],                                                                  # не все бутылки
    lambda p: " ".join(w["name"] for w in p["WINES"]) + " Bourgogne Pinot Noir тоже подойдёт.",       # бутылка каталога вне выдачи
    lambda p: " ".join(w["name"] for w in p["WINES"]) + "." + " Очень вкусно." * 80,                   # длиннее 600 знаков
    OSError("network down"),
])
def test_llm_explanation_rejected_falls_back_to_template(reply):
    r = _explain_with(reply) if not isinstance(reply, Exception) else build_pairing_service(
        "demo", llm=FakeLLM(lambda s, u: '{"dish": "стейк"}' if "JSON по схеме" in s else (_ for _ in ()).throw(reply))).pair_dish("стейк")
    assert r["source"]["explanation"] == "template"
    assert r["explanation"] == SVC.pair_dish("стейк")["explanation"]


def test_zero_invented_bottles_on_200_queries():
    """Этап 4 приёмки: 0 выдуманных бутылок на 200 запросах — модель «галлюцинирует» в каждом втором ответе."""
    counter = iter(range(10_000))

    def llm(system, user):
        if "JSON по схеме" in system:
            return '{"dish": null}'
        payload, n = json.loads(user), next(counter)
        names = " ".join(f"{w['name']} ({int(w['price_rub'])} ₽)." for w in payload["WINES"])
        return names + (" Ещё советую «Château Fantôme» за 5000 ₽." if n % 2 else "")

    svc = build_pairing_service("demo", llm=FakeLLM(llm))
    dishes = [d.name for d in DB.dishes]
    catalog = {b.slug: b for b in svc.provider.list_wines(CatalogFilters(include_unreviewed=True))}
    queries = [f"{dishes[i % len(dishes)]}{', до 1500' if i % 3 == 0 else ''}{', белое' if i % 7 == 0 else ''}" for i in range(200)]
    for q in queries:
        r = svc.pair_dish(q)
        if r["kind"] != "pairing" or not r["wines"]:
            continue
        assert all(w["slug"] in catalog for w in r["wines"])
        wines = [dict(name=w["name"], producer=w["producer"], grape=w["grape"], price_rub=w["price_rub"], region=w["region"],
                      country=w["country"]) for w in r["wines"]]
        picks = [type("P", (), {"grape": GB.by_id[w["grape_id"]]})() for w in r["wines"]]
        problems = check_explanation(r["explanation"], wines, svc._other_names({w["slug"] for w in r["wines"]}),
                                     svc.quotable(r["dish_profile"]["name"], picks))
        assert not problems, (q, problems, r["explanation"])
        assert "Fantôme" not in r["explanation"]


def test_templates_pass_stop_list_and_length():
    for d in DB.dishes:
        r = SVC.pair_dish(d.name)
        assert len(r["explanation"]) <= 600 and not stop_words(r["explanation"]), (d.name, r["explanation"])
    assert stop_words("Купите со скидкой — лучшее вино года")


def test_guardrails_and_clarify():
    assert SVC.pair_dish("мне 16 лет, что взять к шашлыку")["kind"] == "guardrail"
    assert SVC.pair_dish("")["kind"] == "clarify"


def test_gift_scenario_with_stories():
    r = SVC.pair_dish("подарок до 2000")
    assert r["kind"] == "gift" and len(r["wines"]) == 3 and all_russian(r)
    assert all(w["price_rub"] <= 2000 and w["story"] for w in r["wines"])
    assert len({w["grape_id"] for w in r["wines"]}) == 3
    r = SCAN.pair_dish("подарок")
    assert len(r["wines"]) == 3 and all_russian(r) and GB.by_id[r["wines"][0]["grape_id"]].is_russian_origin


def test_liked_grape_without_dish_gives_russian_analogs():
    r = SVC.pair_dish("люблю каберне")
    assert r["kind"] == "similar" and r["analogs"][0]["grape_id"] == "krasnostop_zolotovsky"


# ---- 7.1 время ответа без LLM ----------------------------------------------------------------------
def test_latency_without_llm_p95_under_300ms():
    times = []
    for d in DB.dishes * 3:
        t = time.perf_counter()
        SCAN.pair_dish(d.name, {"budget_max": 2000})
        times.append(time.perf_counter() - t)
    assert sorted(times)[int(len(times) * 0.95)] < 0.3


# ---- 6.2 API ------------------------------------------------------------------------------------
@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(pairing_router, prefix="/api")
    app.state.sommelier_pairing = SVC
    return TestClient(app)


def test_api_methods(client):
    r = client.post("/api/sommelier/pairing/dish", json={"query": "к утке", "filters": {"budget_max": 3000}})
    body = r.json()
    assert r.status_code == 200 and body["kind"] == "pairing" and body["catalog_source"] == "demo"
    assert {"grapes", "dishes", "weights", "catalog"} <= set(body["versions"]) and body["wines"] and body["dish_profile"] and body["source"]
    r = client.post("/api/sommelier/pairing/dish", json={"dish_id": "plov", "scenario": "recipe"})
    assert r.status_code == 200 and r.json()["dish_profile"]["dish_id"] == "plov"
    r = client.get("/api/sommelier/pairing/wine/demo-kubanskaya-dolina-kaberne")
    assert r.status_code == 200 and len(r.json()["dishes"]) == 5 and r.json()["catalog_source"] == "demo"
    r = client.get("/api/sommelier/similar/cabernet_sauvignon?russian=true")
    assert r.status_code == 200 and r.json()["analogs"]
    assert len(client.get("/api/sommelier/grapes").json()["grapes"]) == 16
    assert len(client.get("/api/sommelier/dishes").json()["dishes"]) >= 60
    assert client.get("/api/sommelier/health").json()["catalog_source"] == "demo"
    r = client.post("/api/sommelier/analog", json={"query": "аналог Шабли"})
    assert r.status_code == 200 and r.json()["kind"] == "analog" and r.json()["russian_only"] is True
    assert all(w["is_russian"] for w in r.json()["wines"])


def test_api_errors(client):
    assert client.get("/api/sommelier/pairing/wine/no-such-wine").status_code == 404
    assert client.get("/api/sommelier/pairing/wine/bad%20slug").status_code == 422
    assert client.get("/api/sommelier/similar/nope").status_code == 404
    assert client.post("/api/sommelier/pairing/dish", json={"query": "стейк", "filters": {"color": "Синее"}}).status_code == 422
    app = FastAPI()
    app.include_router(pairing_router, prefix="/api")
    app.state.sommelier_pairing = build_pairing_service("retail")
    r = TestClient(app).post("/api/sommelier/pairing/dish", json={"query": "стейк"})
    assert r.status_code == 503 and r.json()["detail"] == RETAIL_NOT_CONNECTED
    app.state.sommelier_pairing = None
    assert TestClient(app).get("/api/sommelier/health").status_code == 503
