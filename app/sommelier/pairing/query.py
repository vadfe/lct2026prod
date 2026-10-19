"""Разбор запроса без LLM (шаблонный режим, ТЗ п. 5.4): блюдо по справочнику, бюджет, сладость, цвет, любимый сорт, повод."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..features import norm
from .reference import DishBook, GrapeBook
from .scoring import DishProfile

COLOR_RX = {"Красное": r"\bкрасн\w*", "Белое": r"\bбел(ое|ого|ому|ым|ые|ых|ая|ой|ую)\b", "Розовое": r"\bрозов\w*"}
BUDGET_RX = r"(?:до|не дороже|дешевле|в пределах|бюджет\w*|максимум|за)\s*(\d[\d\s]{1,8})\s*(?:₽|р\b|руб\w*|т\.?р|тыс\w*)?"
GIFT_RX = r"подар\w*|презент\w*|на день рождени\w*|юбиле\w*"


@dataclass
class ParsedQuery:
    text: str
    dish_text: str | None = None
    dish: DishProfile | None = None
    budget_max: float | None = None
    sweetness: list[str] | None = None
    color: str | None = None
    liked_grape: str | None = None
    occasion: str | None = None
    source: str = "rules"
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return dict(text=self.text, dish=self.dish_text, budget_max=self.budget_max, sweetness=self.sweetness, color=self.color,
                    liked_grape=self.liked_grape, occasion=self.occasion, source=self.source)


def parse_budget(t: str) -> float | None:
    m = re.search(BUDGET_RX, t)
    if not m:
        return None
    value = float(re.sub(r"\s", "", m.group(1)))
    if re.search(r"т\.?р|тыс", m.group(0)):
        value *= 1000
    return value if value >= 100 else None


def parse_sweetness(t: str) -> list[str] | None:
    if re.search(r"не\s+сладк|несладк", t):
        return ["сухое", "полусухое"]
    if re.search(r"полусладк", t):
        return ["полусладкое"]
    if re.search(r"полусух", t):
        return ["полусухое"]
    if re.search(r"\bсух(ое|ого|ие|ое вино)\b", t):
        return ["сухое"]
    if re.search(r"\bсладк(ое|ого|ие|енькое)\b", t):
        return ["полусладкое", "сладкое"]
    return None


def parse_rules(text: str, grapes: GrapeBook, dishes: DishBook) -> ParsedQuery:
    t = norm(text)
    q = ParsedQuery(text=text)
    d = dishes.find(text)
    if d is not None:
        q.dish_text, q.dish = d.name, DishProfile.from_dish(d)
    q.budget_max = parse_budget(t)
    q.sweetness = parse_sweetness(t)
    q.color = next((c for c, rx in COLOR_RX.items() if re.search(rx, t)), None)
    g = grapes.find_in(text)
    q.liked_grape = g.grape_id if g else None
    q.occasion = "gift" if re.search(GIFT_RX, t) else None
    return q


def keyword_profile(text: str) -> DishProfile | None:
    """Блюда нет в справочнике и LLM недоступна: оценка по ключевым словам существующего разбора (dishes.parse_dish),
    перевод шкалы 0–4 -> 0–3. Помечается source=keywords — это оценка, а не справочник."""
    from ..dishes import parse_dish

    p = parse_dish(text)
    if not p or not p.get("matched_main"):
        return None
    a = p["axes"]
    k = 0.75
    name = p["matched_main"][0].split(" (")[0]
    return DishProfile(name=name, body=round(min(3, a["intensity"] * k), 1), fat_protein=round(min(3, a["fat"] * k), 1),
                       acid=round(min(3, a["acid"] * k), 1), spicy=round(min(3, a["heat"] * k), 1), salty=round(min(3, a["salt"] * k), 1),
                       sweet=round(min(3, a["sweet"]), 1), cuisine=norm((p.get("cuisine_style") or [""])[0]), source="keywords")
