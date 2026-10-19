from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.concurrency import run_in_threadpool

from app.schemas.sommelier import PairingDishRequest, PairingResponse
from app.sommelier.pairing import CatalogUnavailable, PairingService

# Подбор «блюдо → сорт → бутылка» (ТЗ «Доработка цифрового сомелье», п. 6.2). Методы ТЗ /v1/... живут под /api/sommelier/...
# без версии в пути: в проекте версионируются только search-пайплайны (AGENTS.md); версии справочников и весов — в каждом ответе.
router = APIRouter(prefix="/sommelier", tags=["sommelier-pairing"])

SLUG = Annotated[str, Path(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$")]


def _service(request: Request) -> PairingService:
    service: PairingService | None = getattr(request.app.state, "sommelier_pairing", None)
    if service is None:
        raise HTTPException(status_code=503, detail="sommelier pairing is not loaded")
    return service


async def _call(fn, *args, **kwargs):
    try:
        return await run_in_threadpool(fn, *args, **kwargs)
    except CatalogUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/pairing/dish", response_model=PairingResponse)
async def pairing_dish(payload: PairingDishRequest, request: Request) -> dict[str, Any]:
    """С1, С4, С5: {query, filters} -> {dish_profile, wines[], explanation, source}. До трёх бутылок: лучшая российская,
    лучшее сочетание, другой сорт, другая цена или винодельня — только российские вина каталога.
    Без блюда в справочнике и без LLM — уточняющий вопрос (kind=clarify)."""
    service = _service(request)
    return await _call(service.pair_dish, payload.query, payload.filters.model_dump(exclude_none=True), payload.dish_id, payload.scenario)


@router.post("/analog", response_model=PairingResponse)
async def analog(payload: PairingDishRequest, request: Request) -> dict[str, Any]:
    """Российский аналог зарубежного вина: {query: «аналог Шабли»} -> свойства вина (LLM или справочник стилей)
    и до трёх ближайших российских бутылок каталога. Вино выбирает алгоритм, не модель."""
    service = _service(request)
    return await _call(service.analog, payload.query, payload.filters.model_dump(exclude_none=True))


@router.get("/pairing/wine/{slug}", response_model=PairingResponse)
async def pairing_wine(slug: SLUG, request: Request) -> dict[str, Any]:
    """С2: slug бутылки (из каталога или от распознавания этикетки) -> карточка, 5 блюд и правило сорта."""
    result = await _call(_service(request).pair_wine, slug)
    if result is None:
        raise HTTPException(status_code=404, detail="wine not found")
    return result


@router.get("/similar/{grape_id}", response_model=PairingResponse)
async def similar_grapes(
    grape_id: Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")],
    request: Request,
    russian: bool = Query(True),
) -> dict[str, Any]:
    """С3: аналоги сорта с фразой-«мостом» и российские бутылки; russian=true — только автохтонные сорта-аналоги."""
    result = await _call(_service(request).similar, grape_id, russian)
    if result is None:
        raise HTTPException(status_code=404, detail="grape not found")
    return result


@router.get("/grapes")
async def grapes(request: Request) -> dict[str, Any]:
    """Справочник сортов (включая draft — они видны, но не участвуют в выдаче)."""
    return _service(request).grapes_list()


@router.get("/dishes")
async def dishes(request: Request) -> dict[str, Any]:
    """Справочник блюд с осями профиля и синонимами."""
    return _service(request).dishes_list()


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """Состояние подбора и источник каталога (demo / retail)."""
    return await run_in_threadpool(_service(request).health)
