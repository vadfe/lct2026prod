from __future__ import annotations

import zlib
from pathlib import Path
from typing import Any

import numpy as np

from app.sommelier.card.catalog import load_card_catalog
from app.sommelier.card.pairing_engine import SommelierPairingEngine
from app.sommelier.card.stores_and_history import HISTORICAL_WINES_DB, get_simple_and_unusual_dishes

_SET_WEIGHTS = np.array([1.3, 1.4, 1.1, 1.6, 0.8], dtype=np.float32)
_SPARKLING_MARKERS = ("игрист", "брют", "шампан", "кава", "просекко", "франчакорта")
# Быстрый фильтр «под блюдо» по вектору вкуса: ключ -> (ось, условие отсева).
_DISH_FILTERS = {
    "steak": "meat", "bbq": "meat", "мясо": "meat",
    "fish": "fish", "рыба": "fish",
    "dessert": "dessert", "десерт": "dessert",
    "poultry": "poultry", "птица": "poultry",
}


def _stable_unit(slug: str, salt: str) -> int:
    """Детерминированное число из slug: `hash()` строк в Python солится на процесс, а цены/рейтинги не должны «плыть» после перезапуска."""
    return zlib.crc32(f"{salt}:{slug}".encode())


def stable_rating(slug: str) -> float:
    """Демо-рейтинг 4.68–4.98: в датасете рейтингов нет, значение производное от slug, а не оценка пользователей."""
    return round(4.68 + (_stable_unit(slug, "rating") % 31) / 100.0, 2)


def stable_price(slug: str) -> int:
    """Демо-цена 750–2190 ₽: в датасете цен нет, значение производное от slug, а не цена магазина."""
    return 750 + (_stable_unit(slug, "price") % 145) * 10


def _dish_rejects(kind: str, vec: Any) -> bool:
    if kind == "meat":
        return vec.tannins < 3.0
    if kind == "fish":
        return vec.tannins > 2.3
    if kind == "dessert":
        return vec.sweetness < 2.8
    if kind == "poultry":
        return vec.acidity < 3.2 or vec.tannins > 3.8
    return False


class WineCardService:
    """Каталог карточек вин + движок органолептики/сочетаний для веб-клиента.

    Данные только читаются: каталог собирается из CSV при старте и не пишется на диск (app/ в проде read-only).
    """

    def __init__(self, csv_path: Path):
        self.wines = load_card_catalog(csv_path) if csv_path.is_file() else []
        items = [{**wine, "image_url": f"/api/image/{wine['slug']}"} for wine in self.wines]
        self.engine = SommelierPairingEngine(catalog_items=items)

    @property
    def available(self) -> bool:
        return bool(self.engine.catalog)

    def get(self, slug: str) -> dict[str, Any] | None:
        return self.engine.catalog.get(slug)

    def has_history(self, slug: str) -> bool:
        return slug in HISTORICAL_WINES_DB

    def facets(self) -> dict[str, list[str]]:
        regions: set[str] = set()
        wineries: set[str] = set()
        grapes: set[str] = set()
        categories: set[str] = set()
        for item in self.engine.catalog.values():
            for value, bucket in ((item.get("region"), regions), (item.get("winery"), wineries), (item.get("category"), categories)):
                if value and str(value).strip():
                    bucket.add(str(value).strip())
            for grape in str(item.get("grape") or "").replace(";", ",").split(","):
                grape = grape.strip()
                if len(grape) > 2:
                    grapes.add(grape)
        return {
            "regions": sorted(regions),
            "wineries": sorted(wineries)[:80],
            "grapes": sorted(grapes)[:80],
            "categories": sorted(categories),
        }

    def _matches(self, slug: str, item: dict[str, Any], flt: dict[str, Any]) -> bool:
        color = flt.get("color")
        if color:
            color_l = color.lower()
            if color_l in ("игристое", "игристые"):
                haystack = f"{item.get('name', '')} {item.get('category', '')} {item.get('sugar', '')}".lower()
                if not any(marker in haystack for marker in _SPARKLING_MARKERS):
                    return False
            elif color_l not in str(item.get("color", "")).lower() and color_l not in str(item.get("category", "")).lower():
                return False
        for key in ("sugar", "category", "region", "winery", "grape"):
            value = flt.get(key)
            if value and value.lower() not in str(item.get(key, "")).lower():
                return False
        if flt.get("only_with_history") and not self.has_history(slug):
            return False
        query = (flt.get("q") or "").lower().strip()
        if query:
            blob = f"{item.get('name', '')} {item.get('grape', '')} {item.get('winery', '')} {item.get('region', '')}".lower()
            if query not in blob:
                return False
        return True

    def list_catalog(self, flt: dict[str, Any], limit: int, offset: int) -> dict[str, Any]:
        dish_kind = _DISH_FILTERS.get((flt.get("dish_query") or "").lower())
        min_rating = flt.get("min_rating")
        matched = []
        for slug, item in self.engine.catalog.items():
            if not self._matches(slug, item, flt):
                continue
            rating = stable_rating(slug)
            if min_rating and rating < min_rating:
                continue
            vec = self.engine.wine_vectors[slug]
            if dish_kind and _dish_rejects(dish_kind, vec):
                continue
            matched.append((slug, item, vec, rating))

        results = []
        for slug, item, vec, rating in matched[offset: offset + limit]:
            quick = get_simple_and_unusual_dishes(vec.acidity, vec.tannins, vec.body, vec.sweetness, slug)
            results.append({
                **item,
                "slug": slug,
                "rating": rating,
                "price": stable_price(slug),
                "has_history": self.has_history(slug),
                "organoleptic": vec.model_dump(),
                "quick_dishes": {
                    "simple": [d.model_dump() for d in quick["simple"]],
                    "unusual": [d.model_dump() for d in quick["unusual"]],
                },
            })
        return {"count": len(matched), "items": results, "limit": limit, "offset": offset, "has_more": offset + limit < len(matched)}

    def full_sommelier(self, slug: str) -> dict[str, Any] | None:
        item = self.get(slug)
        if item is None:
            return None
        vec = self.engine.wine_vectors[slug]
        quick = get_simple_and_unusual_dishes(vec.acidity, vec.tannins, vec.body, vec.sweetness, slug)
        return {
            "wine": item,
            "organoleptic": vec,
            "simple_dishes": quick["simple"],
            "unusual_dishes": quick["unusual"],
            "evidence_pairings": self.engine.recommend_dishes_for_wine(slug, top_k=4),
            "analogs": self.engine.find_wine_analogs(slug),
            "history": HISTORICAL_WINES_DB.get(slug),
        }

    def wine_set(self, slug: str, count: int) -> dict[str, Any] | None:
        """Сет из `count` вин: исходное + ближайшие по взвешенному расстоянию в 5D-пространстве вкуса, того же цвета."""
        base = self.get(slug)
        if base is None:
            return None
        count = max(2, min(7, count))
        target_vec = self.engine.wine_vectors[slug].to_numpy()
        target_color = str(base.get("color", "")).lower()
        scored = []
        for other_slug, item in self.engine.catalog.items():
            if other_slug == slug:
                continue
            other_color = str(item.get("color", "")).lower()
            if target_color and other_color and target_color[:4] != other_color[:4]:
                continue
            diff = target_vec - self.engine.wine_vectors[other_slug].to_numpy()
            scored.append((float(np.sqrt(np.sum(_SET_WEIGHTS * diff**2))), item))
        scored.sort(key=lambda pair: pair[0])
        items = []
        for entry in [base] + [item for _, item in scored[: count - 1]]:
            entry_slug = entry["slug"]
            items.append({
                "slug": entry_slug,
                "title": entry.get("name") or entry_slug,
                "winery": entry.get("winery") or "",
                "meta": ", ".join(part for part in (entry.get("region"), f"{entry.get('color') or 'Вино'}, {str(entry.get('sugar') or '').lower()}".strip(", "), "0.75 л") if part),
                "image_url": f"/api/image/{entry_slug}",
            })
        return {"base_wine": base, "count": len(items), "items": items}
