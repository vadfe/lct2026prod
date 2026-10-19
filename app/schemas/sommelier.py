from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SESSION_ID_PATTERN = r"^[A-Za-z0-9_-]+$"


class SommelierAskRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = Field(None, min_length=1, max_length=64, pattern=SESSION_ID_PATTERN)


class SommelierResetRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=64, pattern=SESSION_ID_PATTERN)


class SommelierPick(BaseModel):
    id: str
    name: str
    score: float
    role: str
    unknown: list[str] = Field(default_factory=list)
    reasons: list[dict[str, Any]] = Field(default_factory=list)
    # display card (explain.pick_card): wine facts, reasons without quotes, one description quote, bottle photo
    winery: str = ""
    category: str = ""
    grape: str = ""
    region: str = ""
    sweetness: str | None = None
    sparkling: bool = False
    url: str | None = None
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    quote: str | None = None
    image_url: str | None = None  # bottle photo from the recognition catalog, when the wine is there


class SommelierAskResponse(BaseModel):
    session_id: str
    kind: str
    text: str
    picks: list[SommelierPick] = Field(default_factory=list)
    types: list[dict[str, Any]] = Field(default_factory=list)
    pool: int | None = None
    total: int | None = None
    context: dict[str, Any] | None = None
    dish_traits: list[str] = Field(default_factory=list)
    note: str | None = None  # neutral footer, shown separately by the scanner


class SommelierWineCard(BaseModel):
    name: str
    winery: str = ""
    category: str = ""  # Красное / Белое / Розовое / Игристое …
    color: str = ""
    region: str = ""
    grape: str = ""
    url: str | None = None  # wine page on the catalog site


class SommelierWineInfoResponse(BaseModel):
    kind: str
    id: str | None = None
    text: str
    card: SommelierWineCard | None = None  # structured wine facts for scanner cards
    profile: dict[str, Any] | None = None  # description blocks, taste scales, aromas, foods (explain.wine_profile)
    pairing: dict[str, Any] | None = None  # with ?dish=: verdict, rule factors, dish traits, better dishes (explain.pairing_profile)
    best_dishes: list[dict[str, Any]] = Field(default_factory=list)  # typical dishes with the highest score for this wine
    note: str | None = None  # neutral footer, shown separately by the scanner


class SommelierAlternative(BaseModel):
    id: str
    name: str
    winery: str
    facts: str
    score: float
    reasons: list[str] = Field(default_factory=list)
    image_url: str | None = None  # label from the recognition catalog, when the wine is there


class SommelierAlternativesResponse(BaseModel):
    kind: str  # "alternatives" | "not_found"
    id: str | None = None
    items: list[SommelierAlternative] = Field(default_factory=list)


# ---- подбор «блюдо → сорт → бутылка» (docs/SOMMELIER_PAIRING.md) ------------------------------------
class PairingFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    color: Literal["Красное", "Белое", "Розовое"] | None = None
    sweetness: list[Literal["сухое", "полусухое", "полусладкое", "сладкое"]] | None = None
    budget_max: float | None = Field(None, gt=0, le=1_000_000)
    store_id: str | None = Field(None, max_length=64, pattern=SESSION_ID_PATTERN)
    in_stock: bool = True


class PairingDishRequest(BaseModel):
    """С1 — вино к блюду, С4 — к блюду из рецепта (dish_id из справочника), С5 — подарок (scenario=gift),
    analog — российский аналог зарубежного вина (определяется и по тексту: «аналог Шабли», «замена Бароло»)."""
    model_config = ConfigDict(extra="forbid")
    query: str = Field("", max_length=500)
    filters: PairingFilters = Field(default_factory=PairingFilters)
    dish_id: str | None = Field(None, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    scenario: Literal["dish", "recipe", "gift", "analog"] = "dish"


class PairingResponse(BaseModel):
    """Ответ с бутылками: catalog_source (demo -> плашка «Демо-данные») и версии справочников и весов — всегда."""
    model_config = ConfigDict(extra="allow")
    kind: str  # pairing | gift | analog | similar | clarify | guardrail | wine
    catalog_source: str
    versions: dict[str, str]
    wines: list[dict[str, Any]] = Field(default_factory=list)
    dish_profile: dict[str, Any] | None = None
    explanation: str | None = None
    source: dict[str, Any] | None = None
    question: str | None = None
    notes: list[str] = Field(default_factory=list)
    russian_only: bool = True
    note: str | None = None
