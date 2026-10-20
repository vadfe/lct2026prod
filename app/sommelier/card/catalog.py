"""Каталог карточек вин для веб-клиента: читается из того же CSV, что и каталог сомелье (см. `Settings.sommelier_csv_path`).

Эти записи питают карточку вина, список «Каталог», фильтры и подбор сета в клиенте `web/vina`. В отличие от
`app.sommelier.catalog` (признаки для диалога сомелье) здесь собираются отображаемые поля: сахар, крепость, ссылка на
фото из датасета. Фото бутылки отдаёт `/api/image/{slug}`; локальные пути датасета в записи не попадают.
"""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SLUG_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,300}$")

_SWEETNESS_BY_SLUG_PART = (
    ("-polusuhoe", "полусухое"),
    ("-suhoe", "сухое"),
    ("-polusladkoe", "полусладкое"),
    ("-sladkoe", "сладкое"),
    ("-desertnoe", "десертное"),
)


def _sweetness_from_slug(slug: str) -> str:
    for part, label in _SWEETNESS_BY_SLUG_PART:
        if part in slug:
            return label
    return ""


def _sugar(slug: str, sweetness: str, title_category: str) -> str:
    """Сахар для отображения и фильтров; порядок проверок повторяет прежнюю логику каталога VINA."""
    if sweetness:
        return sweetness
    low = title_category.lower()
    if "bryut" in slug.lower() or "брют" in low or "brut" in low:
        return "брют"
    if "полусух" in low or "semi-dry" in low:
        return "полусухое"
    if "полуслад" in low or "semi-sweet" in low:
        return "полусладкое"
    if "десерт" in low or "ликерн" in low:
        return "десертное"
    if "сладк" in low:
        return "сладкое"
    if "сух" in low:
        return "сухое"
    return ""


def _alcohol(slug: str, category: str) -> str:
    """Крепость берётся из хвоста slug (`...-14` → 14%, `...-135` → 13.5%); иначе по типу вина.

    Это оценка по slug, а не лабораторное значение: в датасете отдельной колонки крепости нет.
    """
    match = re.search(r"-(\d{2,3})$", slug)
    if match:
        digits = match.group(1)
        return f"{digits[:2]}.{digits[2]}%" if len(digits) == 3 else f"{digits}%"
    if "портвейн" in slug or "мадера" in slug or "ликер" in category.lower():
        return "16.0%"
    return "13.0%"


def load_card_catalog(csv_path: Path) -> list[dict[str, Any]]:
    """CSV датасета -> список карточек вин. Строки без корректного slug пропускаются."""
    wines: list[dict[str, Any]] = []
    seen: set[str] = set()
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            slug = (row.get("Slug") or "").strip()
            if not slug or slug in seen or not SLUG_PATTERN.fullmatch(slug):
                continue
            seen.add(slug)
            name = (row.get("Название вина") or "").strip()
            category = (row.get("Категория") or "").strip()
            sweetness = _sweetness_from_slug(slug)
            remote_url = (row.get("Ссылка на изображение") or "").strip()
            wines.append(
                {
                    "slug": slug,
                    "name": name,
                    "category": category,
                    "color": (row.get("Цвет") or "").strip(),
                    "region": (row.get("Регион") or "").strip(),
                    "grape": (row.get("Сорт винограда") or "").strip(),
                    "description": (row.get("Описание") or "").strip(),
                    "winery": (row.get("Винодельня") or "").strip(),
                    "sweetness": sweetness,
                    "sugar": _sugar(slug, sweetness, f"{name} {category}"),
                    "alcohol": _alcohol(slug, category),
                    "photo_name": (row.get("Название фото") or "").strip(),
                    "remote_image_url": remote_url,
                    "page_url": (row.get("Ссылка на страницу") or "").strip(),
                }
            )
    logger.info("card catalog loaded: %d wines from %s", len(wines), csv_path)
    return wines
