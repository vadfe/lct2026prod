"""Подбор «блюдо → сорт → бутылка» по ТЗ «Доработка цифрового сомелье» (docs/SOMMELIER_PAIRING.md).

Справочник сортов — vine_tastes.csv + grapes.json, справочник блюд — dishes.json, веса — pairing_config.json,
бутылки — через CatalogProvider (каталог сканера по умолчанию, демо CSV, выгрузка ритейлера позже).
Рекомендуются только российские вина каталога. LLM только разбирает запрос, описывает зарубежное вино и пишет текст.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime

from .catalog import RetailConfig, make_provider
from .llm_layer import LLMClient, LLMLog
from .reference import DishBook, GrapeBook, load_config
from .service import CatalogUnavailable, PairingService

__all__ = ["CatalogUnavailable", "PairingService", "build_pairing_service", "load_service_wines"]


def load_service_wines(csv_path: str | None = None) -> tuple[list[dict], str | None]:
    """Карточки каталога сканера (wines_integrated.csv) — тот же разбор, что у диалогового сомелье."""
    from ..catalog import DEFAULT_CSV, build

    path = csv_path or DEFAULT_CSV
    updated = datetime.fromtimestamp(os.path.getmtime(path), tz=UTC).isoformat(timespec="seconds")
    return build(csv_path=path, out=None), updated


def build_pairing_service(catalog_source: str = "service", llm: LLMClient | None = None, llm_log_path: str | None = None,
                          recognition=None, retail: RetailConfig | None = None, demo_path: str | None = None,
                          service_wines: list[dict] | None = None, service_updated_at: str | None = None) -> PairingService:
    grapes = GrapeBook()
    kwargs = {"demo_path": demo_path} if demo_path else {}
    if catalog_source == "service" and service_wines is None:
        service_wines, service_updated_at = load_service_wines()
    provider = make_provider(catalog_source, grapes, retail=retail, service_wines=service_wines,
                             service_updated_at=service_updated_at, **kwargs)
    return PairingService(grapes, DishBook(), provider, load_config(), llm=llm, llm_log=LLMLog(llm_log_path), recognition=recognition)
