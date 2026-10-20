"""LLM-слой подбора (ТЗ п. 5): понимает свободный запрос и пишет объяснение, но никогда не выбирает вино.

- LLMClient — интерфейс; провайдер задаётся конфигом (SOMMELIER_LLM_PROVIDER). Без LLM сервис работает на шаблонах.
- parse_query: фраза -> JSON по схеме LLMQuery; невалидный ответ -> повторный запрос -> None (уточняющий вопрос).
- explain: в промпт уходят только бутылки, выбранные алгоритмом, их сорта и pairing_text из таблицы.
- check_explanation: каждое название и цена сверяются с переданным списком, стоп-лист 38-ФЗ, до 600 знаков;
  нарушение -> ответ заменяется шаблоном. Все промпты и ответы пишутся в JSONL-лог для разбора (без данных о личности).
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .. import guardrails
from ..features import norm

logger = logging.getLogger(__name__)

MAX_EXPLANATION = 600


class LLMClient(Protocol):
    name: str

    def complete(self, system: str, user: str, max_tokens: int, json_mode: bool = False) -> str: ...


class GeminiClient:
    """Адаптер к существующему REST-клиенту Gemini (app.sommelier.llm.GeminiLLM)."""

    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout: float):
        from ..llm import GeminiLLM

        self._llm = GeminiLLM(api_key, model, timeout)
        self.model = model

    def complete(self, system: str, user: str, max_tokens: int, json_mode: bool = False) -> str:
        return self._llm._generate(system, user, max_tokens, json_mode=json_mode)


def make_llm_client(provider: str, api_key: str | None, model: str, timeout: float) -> LLMClient | None:
    if provider == "none" or not api_key:
        return None
    if provider == "gemini":
        return GeminiClient(api_key, model, timeout)
    raise ValueError(f"SOMMELIER_LLM_PROVIDER={provider!r}: допустимо gemini или none")


LLM_ERRORS = (urllib.error.URLError, TimeoutError, OSError, KeyError, IndexError, ValueError, TypeError)


class LLMLog:
    """JSONL-журнал промптов и ответов. Без идентификаторов пользователя (152-ФЗ, этап MVP)."""

    def __init__(self, path: str | None):
        self.path = path
        self._lock = threading.Lock()

    def write(self, **record) -> None:
        if not self.path:
            return
        record = {"ts": int(time.time()), **record}
        try:
            with self._lock:
                os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            logger.warning("could not write sommelier LLM log at %s", self.path, exc_info=True)


# ---- 5.1 разбор запроса ---------------------------------------------------------------------------
class LLMDishProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: float = Field(ge=0, le=3)
    fat_protein: float = Field(ge=0, le=3)
    acid: float = Field(ge=0, le=3)
    spicy: float = Field(ge=0, le=3)
    salty: float = Field(ge=0, le=3)
    sweet: float = Field(ge=0, le=3)
    cuisine: str | None = None


Sweetness = Literal["сухое", "полусухое", "полусладкое", "сладкое"]


class LLMQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dish: str | None = Field(None, max_length=200)
    dish_profile: LLMDishProfile | None = None
    budget_max: float | None = Field(None, gt=0, le=1_000_000)
    sweetness: list[Sweetness] | None = None
    color: Literal["Красное", "Белое", "Розовое"] | None = None
    liked_grape: str | None = Field(None, max_length=100)
    occasion: Literal["gift"] | None = None


PARSE_PROMPT = """Ты разбираешь запрос покупателя к цифровому сомелье. Верни ТОЛЬКО JSON по схеме:
{schema}
Правила:
- dish — блюдо так, как его назвал покупатель, в именительном падеже («шашлык»), или null.
- dish_profile — заполняй, только если блюдо не из списка известных: {known}. Оси 0–3: body (насыщенность),
  fat_protein (жир и белок), acid (кислотность), spicy (острота), salty (солёность), sweet (сладость); cuisine — кухня.
- budget_max — число в рублях («до 1500» -> 1500), иначе null.
- sweetness — список допустимых уровней: «не сладкое» -> ["сухое","полусухое"]; не сказано — null.
- color — «Красное»/«Белое»/«Розовое», только если покупатель назвал цвет.
- liked_grape — сорт, который покупатель любит или назвал; occasion — "gift", если вино в подарок.
Ничего не выдумывай: нет в тексте — null."""


def parse_query(text: str, client: LLMClient, known_dishes: list[str], log: LLMLog) -> LLMQuery | None:
    system = PARSE_PROMPT.format(schema=json.dumps(LLMQuery.model_json_schema(), ensure_ascii=False),
                                 known=", ".join(known_dishes))
    user = text
    for attempt in (1, 2):
        try:
            raw = client.complete(system, user, 400, json_mode=True)
        except LLM_ERRORS as exc:
            log.write(kind="parse", attempt=attempt, system=system, user=user, error=str(exc))
            logger.warning("sommelier pairing LLM parse failed: %s", exc)
            return None
        try:
            match = re.search(r"\{.*\}", raw or "", re.S)
            parsed = LLMQuery.model_validate_json(match.group(0) if match else raw)
            log.write(kind="parse", attempt=attempt, system=system, user=user, response=raw, accepted=True)
            return parsed
        except (ValidationError, ValueError) as exc:
            log.write(kind="parse", attempt=attempt, system=system, user=user, response=raw, accepted=False, error=str(exc)[:500])
            user = f"{text}\n\nПредыдущий ответ не прошёл проверку схемы: {str(exc)[:300]}. Верни корректный JSON."
    return None


# ---- свойства зарубежного вина (для поиска российского аналога) ------------------------------------------
class ForeignWine(BaseModel):
    """Описание зарубежного вина моделью. Модель описывает вино, но не выбирает аналог: аналог ищет алгоритм в каталоге."""
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=200)
    country: str | None = Field(None, max_length=60)
    grapes: list[str] = Field(default_factory=list, max_length=6)
    color: Literal["Красное", "Белое", "Розовое"]
    sweetness: Sweetness | None = None
    tannins: float = Field(ge=0, le=3)
    acidity: float = Field(ge=1, le=4)
    body: float = Field(ge=1, le=3)
    oak: Literal["да", "нет"] | None = None
    notes: str | None = Field(None, max_length=300)


FOREIGN_PROMPT = """Ты — сомелье. Покупатель ищет российский аналог зарубежного вина. Опиши свойства этого зарубежного вина
(типичный стиль, если вино названо обобщённо). Верни ТОЛЬКО JSON по схеме:
{schema}
Шкалы как в справочнике сервиса: tannins 0–3 (0 — нет, 1 — низкие, 2 — средние, 3 — высокие), acidity 1–4 (1 — низкая,
2 — средняя, 3 — высокая, 4 — очень высокая), body 1–3 (1 — лёгкое, 2 — среднее, 3 — полное).
grapes — сорта винограда по-русски. Российские вина и бренды не называй. Если в запросе нет зарубежного вина — верни {{"name": ""}}."""


def describe_foreign_wine(text: str, client: LLMClient, log: LLMLog) -> ForeignWine | None:
    system = FOREIGN_PROMPT.format(schema=json.dumps(ForeignWine.model_json_schema(), ensure_ascii=False))
    user = text
    for attempt in (1, 2):
        try:
            raw = client.complete(system, user, 500, json_mode=True)
        except LLM_ERRORS as exc:
            log.write(kind="foreign_wine", attempt=attempt, system=system, user=user, error=str(exc))
            logger.warning("sommelier pairing LLM foreign wine failed: %s", exc)
            return None
        try:
            match = re.search(r"\{.*\}", raw or "", re.S)
            parsed = ForeignWine.model_validate_json(match.group(0) if match else raw)
            log.write(kind="foreign_wine", attempt=attempt, system=system, user=user, response=raw, accepted=True)
            return parsed
        except (ValidationError, ValueError) as exc:
            log.write(kind="foreign_wine", attempt=attempt, system=system, user=user, response=raw, accepted=False, error=str(exc)[:500])
            user = f"{text}\n\nПредыдущий ответ не прошёл проверку схемы: {str(exc)[:300]}. Верни корректный JSON."
    return None


# ---- 5.2 объяснение ---------------------------------------------------------------------------------
EXPLAIN_PROMPT = f"""Ты — цифровой сомелье информационного сервиса. Объясни простым русским языком, почему эти вина подходят к блюду.
Требования:
- Упоминай только бутылки из списка WINES; их названия и цены пиши дословно, как в списке. Других вин, брендов и цен не называй.
- Объяснение строй на правиле сорта (pairing_text: танины, кислотность, тело), 1–2 предложения на бутылку.
- Для российской бутылки (is_russian = true) добавь одну фразу из её story.
- Не давай советов о количестве алкоголя. Не используй призывы к покупке («купите», «скидка», «акция») и оценки «лучшее вино».
- Без markdown, до {MAX_EXPLANATION} знаков на весь ответ."""

STOP_LIST = [r"купи\w*", r"покупай\w*", r"закаж\w*", r"скидк\w*", r"акци\w*", r"распродаж\w*", r"выгодн\w*", r"успей\w*",
             r"лучш\w+ вин\w*", r"самое лучш\w*", r"№\s*1", r"хит продаж", r"спецпредложени\w*", r"по цене \w+ бутыл",
             r"выпей\w*", r"сколько (выпить|пить)", r"бутылк\w+ на (человека|гостя|персону)", r"бокал\w* в день"]

PRICE_RX = re.compile(r"(\d[\d\s ]{0,9}\d|\d)(?:[.,](\d{1,2}))?\s*(?:₽|руб\b|руб\.|рублей|рубля|р\.)")


def stop_words(text: str) -> list[str]:
    t = norm(text)
    found = [rx for rx in STOP_LIST if re.search(rf"(?<!\w){rx}", t)]
    return found + guardrails.check_tone(text)


def check_explanation(text: str, wines: list[dict], other_names: list[str], extra_allowed: list[str] | tuple = ()) -> list[str]:
    """Проблемы ответа (пустой список — ответ принят). wines — переданные бутылки, other_names — остальной каталог,
    extra_allowed — что ещё можно брать в кавычки (блюдо, формулировки правил сорта)."""
    problems = []
    if not text or not text.strip():
        return ["пустой ответ"]
    if len(text) > MAX_EXPLANATION:
        problems.append(f"длиннее {MAX_EXPLANATION} знаков")
    t = norm(text)
    for w in wines:
        if norm(w["name"]) not in t:
            problems.append(f"не названа бутылка «{w['name']}»")
    prices = {round(float(w["price_rub"])) for w in wines if w.get("price_rub")}
    for m in PRICE_RX.finditer(text):
        value = round(float(re.sub(r"\D", "", m.group(1)) + (f".{m.group(2)}" if m.group(2) else "")))
        if value not in prices:
            problems.append(f"цена {m.group(0).strip()} не из выдачи")
    allowed = [norm(x) for w in wines for x in (w["name"], w["producer"], w["grape"], w.get("region", ""), w.get("country", "")) if x]
    quotable = allowed + [norm(x) for x in extra_allowed if x]
    for q in re.findall(r"«([^»]{2,80})»", text):
        nq = norm(q)
        if not any(nq in a or a in nq for a in quotable):
            problems.append(f"неизвестное название «{q}»")
    for name in other_names:
        n = norm(name)
        if n and n in t and not any(n in a for a in allowed):
            problems.append(f"названа бутылка не из выдачи: «{name}»")
    problems += [f"стоп-лист: {rx}" for rx in stop_words(text)]
    return problems


def explain(dish_name: str | None, wines: list[dict], client: LLMClient, log: LLMLog) -> str | None:
    payload = dict(DISH=dish_name, WINES=[dict(name=w["name"], producer=w["producer"], price_rub=w["price_rub"], grape=w["grape"],
                                              region=w["region"], is_russian=w["is_russian"], pairing_text=w["pairing_text"],
                                              story=w["story"] if w["is_russian"] else None) for w in wines])
    user = json.dumps(payload, ensure_ascii=False)
    try:
        out = client.complete(EXPLAIN_PROMPT, user, 600)
    except LLM_ERRORS as exc:
        log.write(kind="explain", system=EXPLAIN_PROMPT, user=user, error=str(exc))
        logger.warning("sommelier pairing LLM explain failed: %s", exc)
        return None
    return out
