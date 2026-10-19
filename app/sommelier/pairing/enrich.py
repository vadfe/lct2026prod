"""Обогащение выгрузки ритейлера (ТЗ п. 3.4): сорт, сладость и выдержка из названия и описания.

Сначала правила (aliases справочника, словарь сладости, упоминания дуба), затем — если правила не справились и подключён
LLMClient — модель; её ответ принимается, только если сорт находится среди aliases справочника. Любое выведенное поле
ставит needs_review=True: такие позиции участвуют в выдаче только после проверки человеком. Позиция без сорта не участвует
в подборе по блюду, но доступна по slug.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from ..features import norm
from .reference import SWEETNESS, GrapeBook

logger = logging.getLogger(__name__)

SWEET_RX = [("полусладкое", r"полусладк"), ("полусухое", r"полусух"), ("сладкое", r"(?<!полу)сладк(ое|ие|ого)\b|десертн"),
            ("сухое", r"(?<!полу)сух(ое|ие|ого)\b|брют")]
OAK_YES = r"дуб|баррик|выдержан\w* в боч|oak|barrique"
OAK_NO = r"без (выдержки в )?дуб|в стали|unoaked"

ENRICH_PROMPT = """Извлеки из названия и описания вина сорт винограда, сладость и выдержку в дубе.
Верни ТОЛЬКО JSON: {"grape": строка|null, "sweetness": "сухое"|"полусухое"|"полусладкое"|"сладкое"|null, "oak": "да"|"нет"|null}.
Нет в тексте — null. Ничего не додумывай."""


@dataclass
class Enrichment:
    grape_id: str | None = None
    sweetness: str | None = None
    oak: str | None = None
    inferred: list[str] = field(default_factory=list)   # какие поля выведены (а не пришли в выгрузке)
    method: dict = field(default_factory=dict)            # поле -> rules|llm

    @property
    def needs_review(self) -> bool:
        return bool(self.inferred)


def by_rules(text: str, grapes: GrapeBook) -> dict:
    t = norm(text)
    g = grapes.resolve(t, include_draft=True)
    sweet = next((label for label, rx in SWEET_RX if re.search(rx, t)), None)
    oak = "нет" if re.search(OAK_NO, t) else "да" if re.search(OAK_YES, t) else None
    return dict(grape_id=g.grape_id if g else None, sweetness=sweet, oak=oak)


def enrich(row: dict, grapes: GrapeBook, llm=None) -> Enrichment:
    """row — строка выгрузки (name, description, grape?, sweetness?, oak?). Заполненные поля не трогаем."""
    out = Enrichment()
    given = grapes.resolve(row.get("grape") or "", include_draft=True)
    out.grape_id = given.grape_id if given else None
    out.sweetness = (row.get("sweetness") or "").strip().lower() or None
    out.oak = (row.get("oak") or "").strip().lower() or None
    text = f"{row.get('name', '')}. {row.get('description', '')}"
    found = by_rules(text, grapes)
    for key in ("grape_id", "sweetness", "oak"):
        if getattr(out, key) is None and found[key] is not None:
            setattr(out, key, found[key])
            out.inferred.append(key)
            out.method[key] = "rules"
    if llm is not None and (out.grape_id is None or out.sweetness is None):
        try:
            data = json.loads(llm.complete(ENRICH_PROMPT, text[:2000], 200, json_mode=True))
        except (ValueError, OSError, KeyError, TypeError) as exc:
            logger.warning("enrichment LLM failed: %s", exc)
            data = {}
        g = grapes.resolve(data.get("grape") or "", include_draft=True) if isinstance(data, dict) else None
        if out.grape_id is None and g is not None:             # только сорт из справочника/aliases
            out.grape_id, out.method["grape_id"] = g.grape_id, "llm"
            out.inferred.append("grape_id")
        if out.sweetness is None and isinstance(data, dict) and data.get("sweetness") in SWEETNESS:
            out.sweetness, out.method["sweetness"] = data["sweetness"], "llm"
            out.inferred.append("sweetness")
        if out.oak is None and isinstance(data, dict) and data.get("oak") in ("да", "нет"):
            out.oak, out.method["oak"] = data["oak"], "llm"
            out.inferred.append("oak")
    return out


def coverage(enrichments: list[Enrichment]) -> float:
    """Доля позиций с сортом — критерий приёмки этапа 7 (≥ 95%)."""
    return sum(e.grape_id is not None for e in enrichments) / len(enrichments) if enrichments else 0.0
