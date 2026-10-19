"""Каталог бутылок (SKU) через интерфейс CatalogProvider (ТЗ п. 3).

Логика подбора работает только с интерфейсом и не знает, откуда пришли бутылки. Источник выбирается одной настройкой
CATALOG_SOURCE=service|demo|retail:
- ServiceCatalogProvider (по умолчанию) — каталог сканера: российские вина базы распознавания (wines_integrated.csv);
- DemoCatalogProvider — data/catalog_demo.csv (вымышленные производители «Демо-…», проверка интерфейса ритейла);
- RetailCatalogProvider объявляет те же методы и пока сообщает «Источник ритейлера не подключён».
Рекомендуются только российские бутылки (is_russian) — фильтр ставит сервис подбора, не провайдер.
Формат выгрузки ритейлера — data/catalog_template.csv (п. 3.3), проверка строк — parse_catalog_row.
"""
from __future__ import annotations

import csv
import os
import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from .reference import DATA_DIR, SWEETNESS, GrapeBook

DEMO_CSV = os.path.join(DATA_DIR, "catalog_demo.csv")
TEMPLATE_CSV = os.path.join(DATA_DIR, "catalog_template.csv")
REQUIRED = ["slug", "name", "producer", "grape", "color", "sweetness", "country", "region", "price_rub", "retailer_sku", "barcode"]
OPTIONAL = ["oak", "volume_l", "store_id", "stock_qty", "is_russian"]
SLUG_RX = re.compile(r"^[a-z0-9][a-z0-9-]{1,200}$")
RETAIL_NOT_CONNECTED = "Источник ритейлера не подключён"


@dataclass
class Bottle:
    slug: str
    name: str
    producer: str
    grape: str                  # как на этикетке
    grape_id: str | None        # сорт справочника; None — позиция не участвует в подборе по блюду (п. 3.4)
    color: str
    sweetness: str
    oak: str | None
    country: str
    region: str
    price_rub: float | None
    volume_l: float | None = None
    retailer_sku: str = ""
    barcode: str = ""
    store_id: str | None = None
    stock_qty: int | None = None
    is_russian: bool = False
    source: str = "demo"
    needs_review: bool = False  # поле выведено обогащением и ещё не проверено человеком
    sparkling: bool = False
    # признаки из описания карточки (шкалы справочника: танины 0–3, кислотность 1–4, тело 1–3); None — в описании нет
    body: float | None = None
    tannins: float | None = None
    acidity: float | None = None
    url: str | None = None
    image_url: str | None = None

    def card(self) -> dict:
        return asdict(self)


@dataclass
class CatalogFilters:
    grape_ids: list[str] | None = None
    color: str | None = None
    sweetness: list[str] | None = None
    price_max: float | None = None
    price_min: float | None = None
    is_russian: bool | None = None
    store_id: str | None = None
    include_unreviewed: bool = False


@dataclass
class CatalogHealth:
    source: str
    ok: bool
    updated_at: str | None
    items: int
    message: str = ""
    details: dict = field(default_factory=dict)


class CatalogProvider(ABC):
    source: str

    @abstractmethod
    def list_wines(self, filters: CatalogFilters) -> list[Bottle]:
        """Бутылки по фильтрам: сорт, цвет, сладость, цена, is_russian, магазин."""

    @abstractmethod
    def get_by_slug(self, slug: str) -> Bottle | None:
        """Одна бутылка; используется после распознавания этикетки."""

    @abstractmethod
    def get_stock(self, slug: str, store_id: str | None) -> dict:
        """Остаток в магазине."""

    @abstractmethod
    def health(self) -> CatalogHealth:
        """Источник, дата обновления, число позиций."""


def ean13_ok(code: str) -> bool:
    if not re.fullmatch(r"\d{13}", code or ""):
        return False
    s = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(code[:12]))
    return (10 - s % 10) % 10 == int(code[12])


def _bool(value: str) -> bool | None:
    v = (value or "").strip().lower()
    return {"да": True, "yes": True, "true": True, "1": True, "нет": False, "no": False, "false": False, "0": False}.get(v)


def parse_catalog_row(row: dict, grapes: GrapeBook, where: str, source: str) -> Bottle:
    """Строка выгрузки -> Bottle с проверкой по требованиям шаблона (п. 3.3). Ошибка — ValueError с указанием строки."""
    missing = [k for k in REQUIRED if not (row.get(k) or "").strip()]
    if missing:
        raise ValueError(f"{where}: не заполнены обязательные поля {', '.join(missing)}")
    slug = row["slug"].strip()
    if not SLUG_RX.match(slug):
        raise ValueError(f"{where}: slug «{slug}» — только латиница в нижнем регистре, цифры и дефис")
    grape = grapes.resolve(row["grape"], include_draft=True)
    if grape is None:
        raise ValueError(f"{where}: сорт «{row['grape']}» не найден среди сортов справочника и их aliases")
    color = row["color"].strip().capitalize()
    if color not in ("Красное", "Белое", "Розовое"):
        raise ValueError(f"{where}: цвет «{row['color']}»")
    sweetness = row["sweetness"].strip().lower()
    if sweetness not in SWEETNESS:
        raise ValueError(f"{where}: сладость «{row['sweetness']}», допустимо: {', '.join(SWEETNESS)}")
    oak = (row.get("oak") or "").strip().lower() or None
    if oak is None and grape.oak_variants in ("да", "нет"):
        oak = grape.oak_variants          # по умолчанию — oak_variants сорта
    if oak not in (None, "да", "нет"):
        raise ValueError(f"{where}: oak «{row['oak']}», допустимо: да / нет")
    country, region = row["country"].strip(), row["region"].strip()
    if country not in grapes.geo:
        raise ValueError(f"{where}: страна «{country}» не из закрытого списка справочника")
    if region not in grapes.geo[country]:
        raise ValueError(f"{where}: регион «{region}» не из закрытого списка для страны {country}")
    try:
        price = float(row["price_rub"])
        volume = float(row["volume_l"]) if (row.get("volume_l") or "").strip() else None
        stock = int(row["stock_qty"]) if (row.get("stock_qty") or "").strip() else None
    except ValueError as exc:
        raise ValueError(f"{where}: число в price_rub/volume_l/stock_qty: {exc}") from exc
    if price <= 0:
        raise ValueError(f"{where}: цена должна быть больше нуля")
    if not ean13_ok(row["barcode"].strip()):
        raise ValueError(f"{where}: штрихкод «{row['barcode']}» не EAN-13")
    is_russian = _bool(row.get("is_russian", ""))
    return Bottle(slug=slug, name=row["name"].strip(), producer=row["producer"].strip(), grape=row["grape"].strip(), grape_id=grape.grape_id,
                  color=color, sweetness=sweetness, oak=oak, country=country, region=region, price_rub=price, volume_l=volume,
                  retailer_sku=row["retailer_sku"].strip(), barcode=row["barcode"].strip(), store_id=(row.get("store_id") or "").strip() or None,
                  stock_qty=stock, is_russian=country == "Россия" if is_russian is None else is_russian, source=source)


def read_catalog_csv(path: str, grapes: GrapeBook, source: str) -> list[Bottle]:
    with open(path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        unknown = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
        if unknown:
            raise ValueError(f"{os.path.basename(path)}: нет колонок {', '.join(unknown)}")
        bottles = [parse_catalog_row(row, grapes, f"{os.path.basename(path)}, строка {i}", source) for i, row in enumerate(reader, start=2)]
    slugs = [b.slug for b in bottles]
    dup = {s for s in slugs if slugs.count(s) > 1}
    if dup:
        raise ValueError(f"{os.path.basename(path)}: slug повторяется: {', '.join(sorted(dup))}")
    return bottles


def apply_filters(bottles: list[Bottle], f: CatalogFilters) -> list[Bottle]:
    out = []
    for b in bottles:
        if b.needs_review and not f.include_unreviewed:
            continue
        if f.grape_ids is not None and b.grape_id not in f.grape_ids:
            continue
        if f.color and b.color != f.color:
            continue
        if f.sweetness and b.sweetness not in f.sweetness:
            continue
        if f.price_max is not None and (b.price_rub is None or b.price_rub > f.price_max):
            continue
        if f.price_min is not None and (b.price_rub is None or b.price_rub < f.price_min):
            continue
        if f.is_russian is not None and b.is_russian != f.is_russian:
            continue
        if f.store_id and b.store_id and b.store_id != f.store_id:
            continue
        out.append(b)
    return out


class DemoCatalogProvider(CatalogProvider):
    """Заглушка: вымышленные бутылки из CSV. Остаток в магазине всегда «есть»."""

    source = "demo"

    def __init__(self, grapes: GrapeBook, path: str = DEMO_CSV):
        self.path = path
        self.bottles = read_catalog_csv(path, grapes, self.source)
        self.by_slug = {b.slug: b for b in self.bottles}
        self.updated_at = datetime.fromtimestamp(os.path.getmtime(path), tz=UTC).isoformat(timespec="seconds")

    def list_wines(self, filters: CatalogFilters) -> list[Bottle]:
        return apply_filters(self.bottles, filters)

    def get_by_slug(self, slug: str) -> Bottle | None:
        return self.by_slug.get(slug)

    def get_stock(self, slug: str, store_id: str | None) -> dict:
        if slug not in self.by_slug:
            return dict(slug=slug, store_id=store_id, in_stock=False, qty=0, source=self.source)
        return dict(slug=slug, store_id=store_id, in_stock=True, qty=self.by_slug[slug].stock_qty, source=self.source)

    def health(self) -> CatalogHealth:
        return CatalogHealth(source=self.source, ok=True, updated_at=self.updated_at, items=len(self.bottles),
                             message="Демо-данные: вымышленные производители, не реальные товары",
                             details=dict(russian=sum(b.is_russian for b in self.bottles)))


def _scale(value, src_lo, src_hi, lo, hi) -> float | None:
    if value is None:
        return None
    return round(lo + (min(max(value, src_lo), src_hi) - src_lo) / (src_hi - src_lo) * (hi - lo), 2)


def bottle_from_card(w: dict, grapes: GrapeBook) -> Bottle:
    """Карточка каталога сканера (app.sommelier.catalog.build) -> Bottle. Сорт — по aliases справочника (включая draft:
    такие позиции видны по slug, но в подбор не идут, пока сорт не подписан). Признаки описания переводятся в шкалы справочника."""
    g = next((x for x in (grapes.resolve(n, include_draft=True) for n in [w.get("grape") or "", *(w.get("grapes") or [])]) if x), None)
    f = w.get("features") or {}
    sweet = {v: k for k, v in SWEETNESS.items()}.get(f.get("sweetness"))
    return Bottle(slug=w["id"], name=w.get("name") or w["id"], producer=w.get("winery") or "", grape=w.get("grape") or "",
                  grape_id=g.grape_id if g else None, color=w.get("category") or "", sweetness=sweet or (g.sweetness_default if g else ""),
                  oak="да" if f.get("oak") else None, country="Россия", region=w.get("region") or "", price_rub=None, is_russian=True,
                  source="service", sparkling=bool(f.get("sparkling")),
                  body=_scale(f.get("body"), 0.5, 4.0, 1.0, 3.0),          # features: тело 0.5–4
                  tannins=_scale(f.get("tannin"), 0.0, 3.5, 0.0, 3.0),     # features: танины 1 / 2 / 3.5
                  acidity=_scale(f.get("acidity"), 1.0, 3.5, 1.0, 3.0),    # features: кислотность 1–3.5 («высокая» = 3)
                  url=w.get("url"), image_url=w.get("image_url"))


class ServiceCatalogProvider(CatalogProvider):
    """Каталог сканера: российские вина базы распознавания этикеток. Цен и остатков в нём нет."""

    source = "service"

    def __init__(self, grapes: GrapeBook, wines: list[dict], updated_at: str | None = None):
        self.bottles = [bottle_from_card(w, grapes) for w in wines]
        self.by_slug = {b.slug: b for b in self.bottles}
        self.updated_at = updated_at

    def list_wines(self, filters: CatalogFilters) -> list[Bottle]:
        return apply_filters(self.bottles, filters)

    def get_by_slug(self, slug: str) -> Bottle | None:
        return self.by_slug.get(slug)

    def get_stock(self, slug: str, store_id: str | None) -> dict:
        return dict(slug=slug, store_id=store_id, in_stock=slug in self.by_slug, qty=None, source=self.source)

    def health(self) -> CatalogHealth:
        return CatalogHealth(source=self.source, ok=bool(self.bottles), updated_at=self.updated_at, items=len(self.bottles),
                             message="Каталог сканера: российские вина базы распознавания, без цен",
                             details=dict(with_grape=sum(b.grape_id is not None for b in self.bottles)))


@dataclass
class RetailConfig:
    kind: str = "csv"          # csv-выгрузка | api
    url: str = ""
    api_key: str = ""
    schedule: str = "0 5 * * *"  # ежедневное обновление (п. 7.1)


class RetailCatalogProvider(CatalogProvider):
    """Источник ритейлера (на перспективу): интерфейс объявлен, загрузка не реализована."""

    source = "retail"

    def __init__(self, config: RetailConfig):
        self.config = config

    def list_wines(self, filters: CatalogFilters) -> list[Bottle]:
        raise NotImplementedError(RETAIL_NOT_CONNECTED)

    def get_by_slug(self, slug: str) -> Bottle | None:
        raise NotImplementedError(RETAIL_NOT_CONNECTED)

    def get_stock(self, slug: str, store_id: str | None) -> dict:
        raise NotImplementedError(RETAIL_NOT_CONNECTED)

    def health(self) -> CatalogHealth:
        return CatalogHealth(source=self.source, ok=False, updated_at=None, items=0, message=RETAIL_NOT_CONNECTED,
                             details=dict(kind=self.config.kind, url_configured=bool(self.config.url), schedule=self.config.schedule))


def make_provider(source: str, grapes: GrapeBook, demo_path: str = DEMO_CSV, retail: RetailConfig | None = None,
                  service_wines: list[dict] | None = None, service_updated_at: str | None = None) -> CatalogProvider:
    if source == "service":
        return ServiceCatalogProvider(grapes, service_wines or [], service_updated_at)
    if source == "demo":
        return DemoCatalogProvider(grapes, demo_path)
    if source == "retail":
        return RetailCatalogProvider(retail or RetailConfig())
    raise ValueError(f"CATALOG_SOURCE={source!r}: допустимо service, demo или retail")
