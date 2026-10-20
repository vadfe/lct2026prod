from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.concurrency import run_in_threadpool

from app.schemas.wines import ToastRequest
from app.services.wine_card_service import WineCardService
from app.sommelier.card.catalog import SLUG_PATTERN
from app.sommelier.card.stores_and_history import HISTORICAL_WINES_DB, generate_sommelier_toast_and_advice, get_5_nearest_walking_stores

router = APIRouter(tags=["wines"])

Slug = Annotated[str, Path(max_length=300, pattern=SLUG_PATTERN.pattern)]
OptionalText = Annotated[str | None, Query(max_length=100)]


def _service(request: Request) -> WineCardService:
    service: WineCardService | None = request.app.state.wine_card
    if service is None or not service.available:
        raise HTTPException(status_code=503, detail="wine catalog is not loaded")
    return service


@router.get("/catalog")
async def list_catalog(
    request: Request,
    color: OptionalText = None,
    sugar: OptionalText = None,
    category: OptionalText = None,
    region: OptionalText = None,
    winery: OptionalText = None,
    grape: OptionalText = None,
    q: OptionalText = None,
    dish_query: OptionalText = None,
    min_rating: Annotated[float | None, Query(ge=0, le=5)] = None,
    only_with_history: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """Каталог вин с фильтрами; `dish_query`: steak | fish | dessert | poultry."""
    flt = {
        "color": color, "sugar": sugar, "category": category, "region": region, "winery": winery, "grape": grape,
        "q": q, "dish_query": dish_query, "min_rating": min_rating, "only_with_history": only_with_history,
    }
    return await run_in_threadpool(_service(request).list_catalog, flt, limit, offset)


@router.get("/catalog/facets")
async def catalog_facets(request: Request) -> dict:
    return _service(request).facets()


@router.get("/wine/{slug}")
async def wine_card(slug: Slug, request: Request) -> dict:
    wine = _service(request).get(slug)
    if wine is None:
        raise HTTPException(status_code=404, detail="Wine not found")
    return wine


@router.get("/wine/{slug}/full-sommelier")
async def wine_full_sommelier(slug: Slug, request: Request) -> dict:
    """Полный разбор вина: органолептика, блюда, аналоги, историческая справка."""
    result = await run_in_threadpool(_service(request).full_sommelier, slug)
    if result is None:
        raise HTTPException(status_code=404, detail="Wine not found")
    return result


@router.get("/wine/{slug}/set")
async def wine_set(slug: Slug, request: Request, count: Annotated[int, Query(ge=2, le=7)] = 4) -> dict:
    """Сет из `count` вин, близких по вкусу к выбранному."""
    result = await run_in_threadpool(_service(request).wine_set, slug, count)
    if result is None:
        raise HTTPException(status_code=404, detail="Wine not found")
    return result


@router.get("/wine/{slug}/history")
async def wine_history(slug: Slug) -> object:
    record = HISTORICAL_WINES_DB.get(slug)
    if record is None:
        raise HTTPException(status_code=404, detail="Для этого вина историческая справка не заполнена")
    return record


@router.get("/map/nearby-stores")
async def nearby_stores(
    request: Request,
    lat: Annotated[float, Query(ge=-90, le=90)] = 45.0355,
    lon: Annotated[float, Query(ge=-180, le=180)] = 38.9753,
    wine_slug: Annotated[str | None, Query(max_length=300, pattern=SLUG_PATTERN.pattern)] = None,
) -> dict:
    """5 ближайших магазинов для карты. Магазины, адреса, остатки и цены — демонстрационные шаблоны вокруг точки пользователя,
    а не данные реальной торговой сети."""
    wine = _service(request).get(wine_slug) if wine_slug else None
    stores = get_5_nearest_walking_stores(user_lat=lat, user_lon=lon, wine_slug=wine_slug, base_price=990)
    return {
        "user_location": {"lat": lat, "lon": lon},
        "selected_wine_slug": wine_slug,
        "selected_wine_name": wine.get("name") if wine else None,
        "stores": stores,
    }


@router.get("/wine-set")
async def wine_set_by_query(
    request: Request,
    wine_slug: Annotated[str, Query(max_length=300, pattern=SLUG_PATTERN.pattern)] = "loco-cimbali-blanc-de-neige-shardone-beloe-suhoe-131",
    count: Annotated[int, Query(ge=2, le=7)] = 4,
) -> dict:
    """Сет из `count` вин, близких по вкусу к выбранному (поиск по query-параметру)."""
    result = await run_in_threadpool(_service(request).wine_set, wine_slug, count)
    if result is None:
        raise HTTPException(status_code=404, detail="Wine not found")
    return result


@router.post("/sommelier/toast")
async def sommelier_toast(payload: ToastRequest, request: Request) -> dict:
    """Тост к событию и совет сомелье с привязкой к вину каталога."""
    service = _service(request)
    wine = service.get(payload.wine_slug)
    if wine is None:
        raise HTTPException(status_code=404, detail="Wine not found")
    vec = service.engine.wine_vectors[payload.wine_slug]
    toast = generate_sommelier_toast_and_advice(
        occasion=payload.occasion,
        user_question=payload.question,
        wine_name=wine.get("name") or payload.wine_slug,
        wine_slug=payload.wine_slug,
        acidity=vec.acidity,
        tannins=vec.tannins,
    )
    return {
        "wine": wine,
        "organoleptic": vec,
        "toast": toast,
        "recommended_catalog_wines": service.engine.find_wine_analogs(payload.wine_slug),
    }


@router.post("/sommelier/ask")
async def sommelier_toast_ask(payload: ToastRequest, request: Request) -> dict:
    """Алиас для модального окна тостов фронта VINA (/api/v2/sommelier/ask)."""
    return await sommelier_toast(payload, request)

