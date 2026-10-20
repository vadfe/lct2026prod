from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_images, get_session
from app.db.repositories.products import ProductRepository
from app.services.images import ImageService
from app.sommelier.card.catalog import SLUG_PATTERN

logger = logging.getLogger(__name__)
router = APIRouter(tags=["wines"])

Slug = Annotated[str, Path(max_length=300, pattern=SLUG_PATTERN.pattern)]
CACHE_HEADERS = {"Cache-Control": "public, max-age=86400"}


@router.get("/image/{slug}")
async def wine_image(
    slug: Slug,
    request: Request,
    session: AsyncSession = Depends(get_session),
    images: ImageService = Depends(get_images),
):
    """Фото бутылки: файл из хранилища media (источник загрузки в products), иначе ссылка на изображение из датасета.

    Адрес редиректа берётся только из каталога (колонка «Ссылка на изображение»), не из запроса.
    """
    try:
        product = await ProductRepository(session).get_by_slug(slug)
    except (SQLAlchemyError, OSError):
        logger.warning("wine image: database unavailable for %s", slug, exc_info=True)
        product = None
    if product is not None and product.source_image_path:
        try:
            return FileResponse(images.resolve(product.source_image_path), headers=CACHE_HEADERS)
        except FileNotFoundError:
            logger.warning("wine image: media file missing for %s", slug)

    service = request.app.state.wine_card
    card = service.get(slug) if service is not None else None
    remote_url = str(card.get("remote_image_url") or "") if card else ""
    if remote_url.startswith("https://"):
        return RedirectResponse(remote_url, status_code=307, headers=CACHE_HEADERS)
    raise HTTPException(status_code=404, detail="Image not found")
