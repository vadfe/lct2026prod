"""Справочники подбора «блюдо → сорт → бутылка»: сорта (vine_tastes.csv + grapes.json), блюда, веса скоринга.

Таблица сортов читается как есть (UTF-8 с BOM, «/» в составных значениях) и переводится в числовые шкалы (ТЗ п. 2.1).
Неизвестное значение — ошибка загрузки с номером строки. Дополнительные поля сорта (grape_id, aliases, сладость, дуб,
структурированные правила, история) и российские сорта-черновики лежат в grapes.json (п. 2.2–2.4).
"""
from __future__ import annotations

import csv
import difflib
import json
import os
import re
from dataclasses import dataclass, field

from ..features import norm

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(HERE, "data")
GRAPES_CSV = os.path.join(DATA_DIR, "vine_tastes.csv")
GRAPES_JSON = os.path.join(DATA_DIR, "grapes.json")
DISHES_JSON = os.path.join(DATA_DIR, "dishes.json")
CONFIG_JSON = os.path.join(DATA_DIR, "pairing_config.json")
REFERENCE_JSON = os.path.join(DATA_DIR, "pairing_reference.json")

# ---- числовые шкалы (ТЗ п. 2.1) -----------------------------------------------------------------
TANNINS = {"нет (0)": 0.0, "нет": 0.0, "низкие": 1.0, "низкие/средние": 1.5, "средние": 2.0, "средние/высокие": 2.5, "высокие": 3.0}
ACIDITY = {"низкая": 1.0, "низкая/средняя": 1.5, "средняя": 2.0, "высокая": 3.0, "очень высокая": 4.0}
BODY = {"легкое": 1.0, "легкое/среднее": 1.5, "среднее": 2.0, "среднее/полное": 2.5, "полное": 3.0}
SWEETNESS = {"сухое": 0, "полусухое": 1, "полусладкое": 2, "сладкое": 3}
SWEETNESS_LABEL = {v: k for k, v in SWEETNESS.items()}
OAK_VARIANTS = {"да", "нет", "оба"}
COLORS = {"Красное", "Белое", "Розовое"}
CSV_COLUMNS = ["Сорт винограда", "Тип", "Танины", "Кислотность", "Тело (по крепости)", "Правило сочетания (для LLM)"]


class ReferenceDataError(ValueError):
    """Ошибка загрузки справочника; в тексте — файл, строка и поле."""


def _key(value: str) -> str:
    # «Низкие-Средние», «Низкие / Средние», «Лёгкое» -> «низкие/средние», «легкое»
    return re.sub(r"\s*[/-]\s*", "/", norm(value).strip())


def scale(table: dict, value: str, where: str) -> float:
    k = _key(value)
    if k not in table:
        raise ReferenceDataError(f"{where}: неизвестное значение «{value}», допустимо: {', '.join(table)}")
    return table[k]


def color_of(type_value: str) -> str:
    # «Белое/Десертное» -> Белое: цвет — первая часть, «десертное» описывает сладость (sweetness_default)
    head = type_value.split("/")[0].strip().capitalize()
    return head


@dataclass(frozen=True)
class PairingRule:
    term: str                 # формулировка из таблицы («жареное мясо»)
    tags: tuple[str, ...]     # теги блюд справочника, которые она покрывает
    weight: float = 1.0
    oak: str | None = None    # условие «при oak = да/нет» (Шардоне)


@dataclass
class Grape:
    grape_id: str
    name: str
    type: str
    color: str
    tannins: float
    acidity: float
    body: float
    pairing_text: str
    aliases: list[str]
    sweetness_default: str
    oak_variants: str
    is_russian_origin: bool
    pairing_rules: list[PairingRule]
    cuisines: list[str] = field(default_factory=list)
    story: str = ""
    signature: str = ""
    status: str = "active"
    signed_by: str | None = None
    oak_body: dict[str, float] = field(default_factory=dict)  # тело с дубом / без (oak_profile)
    source: str = "vine_tastes.csv"

    @property
    def sweetness(self) -> int:
        return SWEETNESS[self.sweetness_default]

    @property
    def active(self) -> bool:
        return self.status == "active"

    def oak_options(self) -> list[str | None]:
        """Стили по дубу, которые различает скоринг: «оба» -> да и нет, иначе одно значение."""
        return ["да", "нет"] if self.oak_variants == "оба" else [self.oak_variants]

    def body_for(self, oak: str | None) -> float:
        return self.oak_body.get(oak or "", self.body)

    def card(self) -> dict:
        return dict(grape_id=self.grape_id, name=self.name, type=self.type, color=self.color, tannins=self.tannins,
                    acidity=self.acidity, body=self.body, sweetness_default=self.sweetness_default, oak_variants=self.oak_variants,
                    is_russian_origin=self.is_russian_origin, aliases=self.aliases, pairing_text=self.pairing_text,
                    pairing_rules=[dict(term=r.term, tags=list(r.tags), weight=r.weight, oak=r.oak) for r in self.pairing_rules],
                    cuisines=self.cuisines, story=self.story, status=self.status, signed_by=self.signed_by, source=self.source)


def _extras(item: dict, where: str) -> dict:
    for k in ("grape_id", "aliases", "sweetness_default", "oak_variants", "is_russian_origin", "pairing_rules", "status"):
        if k not in item:
            raise ReferenceDataError(f"{where}: нет поля {k}")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", item["grape_id"]):
        raise ReferenceDataError(f"{where}: grape_id должен быть латиницей: {item['grape_id']!r}")
    if item["sweetness_default"] not in SWEETNESS:
        raise ReferenceDataError(f"{where}: sweetness_default «{item['sweetness_default']}», допустимо: {', '.join(SWEETNESS)}")
    if item["oak_variants"] not in OAK_VARIANTS:
        raise ReferenceDataError(f"{where}: oak_variants «{item['oak_variants']}», допустимо: да / нет / оба")
    if item["status"] not in ("active", "draft"):
        raise ReferenceDataError(f"{where}: status должен быть active или draft")
    if len(item.get("story", "")) > 300:
        raise ReferenceDataError(f"{where}: story длиннее 300 знаков")
    rules = []
    for r in item["pairing_rules"]:
        oak = (r.get("when") or {}).get("oak")
        if oak is not None and oak not in ("да", "нет"):
            raise ReferenceDataError(f"{where}: условие правила oak={oak!r}")
        rules.append(PairingRule(term=r["term"], tags=tuple(r["tags"]), weight=float(r.get("weight", 1.0)), oak=oak))
    oak_body = {k: scale(BODY, v["body"], f"{where}: oak_profile.{k}") for k, v in (item.get("oak_profile") or {}).items()}
    return dict(grape_id=item["grape_id"], aliases=list(item["aliases"]), sweetness_default=item["sweetness_default"],
                oak_variants=item["oak_variants"], is_russian_origin=bool(item["is_russian_origin"]), pairing_rules=rules,
                cuisines=[norm(c) for c in item.get("cuisines", [])], story=item.get("story", ""), signature=item.get("signature", ""),
                status=item["status"], signed_by=item.get("signed_by"), oak_body=oak_body)


def parse_grapes_csv(path: str = GRAPES_CSV) -> list[dict]:
    """vine_tastes.csv -> записи с числовыми шкалами. Ошибка формата — ReferenceDataError с номером строки."""
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in CSV_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ReferenceDataError(f"{os.path.basename(path)}: нет колонок {', '.join(missing)}")
        rows = []
        for line, row in enumerate(reader, start=2):  # строка 1 — заголовок
            where = f"{os.path.basename(path)}, строка {line}"
            name = (row["Сорт винограда"] or "").strip()
            if not name:
                raise ReferenceDataError(f"{where}: пустое название сорта")
            color = color_of(row["Тип"] or "")
            if color not in COLORS:
                raise ReferenceDataError(f"{where}: неизвестный тип «{row['Тип']}»")
            rows.append(dict(name=name, type=row["Тип"].strip(), color=color,
                             tannins=scale(TANNINS, row["Танины"], f"{where}, «Танины»"),
                             acidity=scale(ACIDITY, row["Кислотность"], f"{where}, «Кислотность»"),
                             body=scale(BODY, row["Тело (по крепости)"], f"{where}, «Тело»"),
                             pairing_text=(row["Правило сочетания (для LLM)"] or "").strip()))
    return rows


class GrapeBook:
    """Справочник сортов: таблица + расширение. Draft-сорта видны в справочнике, но не участвуют в выдаче."""

    def __init__(self, csv_path: str = GRAPES_CSV, json_path: str = GRAPES_JSON):
        with open(json_path, encoding="utf-8") as fh:
            meta = json.load(fh)
        self.version = meta["version"]
        self.geo: dict[str, list[str]] = meta.get("geo", {})
        extras = {item["csv_name"]: item for item in meta["grapes"]}
        self.grapes: list[Grape] = []
        for row in parse_grapes_csv(csv_path):
            item = extras.get(row["name"])
            if item is None:
                raise ReferenceDataError(f"grapes.json: нет дополнительных полей для сорта «{row['name']}» из таблицы")
            self.grapes.append(Grape(**row, **_extras(item, f"grapes.json, {row['name']}")))
        for item in meta.get("russian_extension", []):
            where = f"grapes.json, {item.get('name')}"
            color = color_of(item["type"])
            if color not in COLORS:
                raise ReferenceDataError(f"{where}: неизвестный тип «{item['type']}»")
            self.grapes.append(Grape(name=item["name"], type=item["type"], color=color,
                                     tannins=scale(TANNINS, item["tannins"], f"{where}, «Танины»"),
                                     acidity=scale(ACIDITY, item["acidity"], f"{where}, «Кислотность»"),
                                     body=scale(BODY, item["body"], f"{where}, «Тело»"),
                                     pairing_text=item["pairing_text"], source="grapes.json", **_extras(item, where)))
        ids = [g.grape_id for g in self.grapes]
        if len(ids) != len(set(ids)):
            raise ReferenceDataError("grapes.json: grape_id повторяется")
        self.by_id = {g.grape_id: g for g in self.grapes}
        # алиас -> сорт; длинные алиасы проверяются первыми («Рислинг Рейнский» раньше «Рислинг»)
        self._aliases: list[tuple[str, Grape]] = sorted(
            ((norm(a), g) for g in self.grapes for a in [g.name, *g.aliases]), key=lambda kv: -len(kv[0]))

    @property
    def active(self) -> list[Grape]:
        return [g for g in self.grapes if g.active]

    def resolve(self, text: str | None, include_draft: bool = False) -> Grape | None:
        """Написание с этикетки/из запроса («Krasnostop», «Каберне-Совиньон») -> сорт справочника."""
        t = norm(text or "").strip()
        if not t:
            return None
        pool = [(a, g) for a, g in self._aliases if include_draft or g.active]
        for alias, g in pool:
            if t == alias:
                return g
        for alias, g in pool:
            if re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", t):
                return g
        return None

    def find_in(self, text: str) -> Grape | None:
        """Сорт, названный в свободной фразе («люблю каберне» -> Каберне Совиньон), с допуском на падеж."""
        g = self.resolve(text)
        if g:
            return g
        words = re.findall(r"[\w-]+", norm(text))
        for alias, grape in self._aliases:
            if not grape.active or len(alias) < 5:
                continue
            first = alias.split()[0]
            if any(w.startswith(first[:-1]) and len(w) >= len(first) - 1 for w in words):
                return grape
        return None


@dataclass(frozen=True)
class Dish:
    id: str
    name: str
    cuisine: str
    synonyms: tuple[str, ...]
    body: float
    fat_protein: float
    acid: float
    spicy: float
    salty: float
    sweet: float
    tags: tuple[str, ...]

    def profile(self) -> dict:
        return dict(body=self.body, fat_protein=self.fat_protein, acid=self.acid, spicy=self.spicy, salty=self.salty,
                    sweet=self.sweet, cuisine=self.cuisine)


AXES = ("body", "fat_protein", "acid", "spicy", "salty", "sweet")


def _stem(word: str) -> str:
    """Основа для нечёткого сравнения: без падежного окончания («пельменям» -> «пельмен», «шашлыку» -> «шашлык»)."""
    return re.sub(r"(ами|ями|ого|его|ому|ему|ах|ях|ам|ям|ой|ей|ом|ем|ую|юю|[аяоеэыиуюйь])+$", "", word)


class DishBook:
    def __init__(self, path: str = DISHES_JSON):
        with open(path, encoding="utf-8") as fh:
            meta = json.load(fh)
        self.version = meta["version"]
        self.dishes: list[Dish] = []
        for i, d in enumerate(meta["dishes"], start=1):
            where = f"dishes.json, блюдо {i} ({d.get('id')})"
            for axis in AXES:
                v = d.get(axis)
                if not isinstance(v, int | float) or not 0 <= v <= 3:
                    raise ReferenceDataError(f"{where}: ось {axis} должна быть числом 0–3, получено {v!r}")
            self.dishes.append(Dish(id=d["id"], name=d["name"], cuisine=norm(d["cuisine"]), synonyms=tuple(d["synonyms"]),
                                    tags=tuple(d.get("tags", [])), **{a: float(d[a]) for a in AXES}))
        self.by_id = {d.id: d for d in self.dishes}
        if len(self.by_id) != len(self.dishes):
            raise ReferenceDataError("dishes.json: id блюда повторяется")
        self._names: list[tuple[str, Dish]] = sorted(
            ((norm(s), d) for d in self.dishes for s in (d.name, *d.synonyms)), key=lambda kv: -len(kv[0]))
        # Основы однословных названий для нечёткого сравнения отдельных слов («к шашлылу» -> «шашлык»)
        self._stems: dict[str, Dish] = {}
        for name, d in self._names:
            stem = _stem(name)
            if " " not in name and len(stem) >= 4:
                self._stems.setdefault(stem, d)

    def find(self, text: str | None) -> Dish | None:
        """Блюдо в свободной фразе. Сначала словосочетания (точно, затем по основам всех слов в любом падеже и порядке),
        потом одиночные слова (точно, затем по основе), затем нечёткое сравнение. Словосочетание идёт раньше одиночного
        слова: «к красной рыбе» — это «красная рыба» (лосось), а не любая «рыба»."""
        t = " " + re.sub(r"[^\w\s-]", " ", norm(text or "")) + " "
        if not t.strip():
            return None
        words = t.split()
        exact = [(name, d) for name, d in self._names if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", t)]
        for name, d in exact:
            if " " in name:
                return d
        for name, d in self._names:   # «к красной рыбе», «рыба красная»: все значимые слова словосочетания по основе
            if " " not in name:
                continue
            stems = [_stem(w) for w in name.split()]
            stems = [st for st in stems if len(st) >= 3]
            if len(stems) >= 2 and all(any(w.startswith(st) for w in words) for st in stems):
                return d
        if exact:
            return exact[0][1]
        for name, d in self._names:   # «к шашлыку», «под устриц»: основа синонима из одного слова
            stem = re.sub(r"[аяоеэыиуюйь]+$", "", name)
            if " " in name or len(stem) < 3:
                continue
            if any(w.startswith(stem) and len(w) <= len(name) + 3 for w in words):
                return d
        close = difflib.get_close_matches(t.strip(), [n for n, _ in self._names], n=1, cutoff=0.82)
        if close:
            return next(d for n, d in self._names if n == close[0])
        # Опечатка в одном слове: основа слова против основ названий («шашлылу» -> «шашлык», «стейкк» -> «стейк»)
        for word in sorted(words, key=len, reverse=True):
            stem = _stem(word)
            if len(stem) < 4:
                continue
            # Начало слова опечатка обычно не трогает: так «красное» не станет «карасём», а «физика» — «финиками»
            close = difflib.get_close_matches(stem, [s for s in self._stems if s[:3] == stem[:3]], n=1, cutoff=0.8)
            if close:
                return self._stems[close[0]]
        return None


def load_config(path: str = CONFIG_JSON) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_reference(path: str = REFERENCE_JSON) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
