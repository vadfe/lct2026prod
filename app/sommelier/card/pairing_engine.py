# -*- coding: utf-8 -*-
"""
VINA Sommelier Pairing & Analog Engine
Модуль доказательной гастропары (Вино ⇄ Блюдо) и поиска вкусовых аналогов.
"""

from __future__ import annotations
import math
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
from pydantic import BaseModel, Field


# =====================================================================
# 1. МОДЕЛИ ДАННЫХ (Pydantic Schemas для FastAPI и внутренней логики)
# =====================================================================

class WineOrganolepticVector(BaseModel):
    """5-мерный органолептический профиль вина (шкала от 1.0 до 5.0)."""
    acidity: float = Field(3.0, ge=1.0, le=5.0, description="Кислотность (1 - плоская, 5 - звенящая)")
    tannins: float = Field(1.0, ge=1.0, le=5.0, description="Танинность/терпкость (1 - нет, 5 - мощная)")
    body: float = Field(3.0, ge=1.0, le=5.0, description="Тело/плотность вина (1 - легкое, 5 - густое/полнотелое)")
    sweetness: float = Field(1.5, ge=1.0, le=5.0, description="Сладость (1 - брют/сухое, 5 - десертное/ликерное)")
    oak_intensity: float = Field(2.0, ge=1.0, le=5.0, description="Ароматическая мощь и выдержка в дубе")

    def to_numpy(self) -> np.ndarray:
        return np.array([
            self.acidity,
            self.tannins,
            self.body,
            self.sweetness,
            self.oak_intensity
        ], dtype=np.float32)


class DishProfile(BaseModel):
    """Карточка блюда с его физико-химическим вектором и триггерами аппетита."""
    dish_id: str
    title: str
    subtitle: str = Field(..., description="Аппетитное описание подачи, вызывающее слюноотделение")
    category: str = Field(..., description="Категория: Мясо, Птица, Рыба, Морепродукты, Паста, Сыры, Десерт")
    sensory_tags: List[str] = Field(default_factory=list, description="Короткие чипсы текстур и ароматов для UI")
    image_url: str = Field("", description="Путь к фото блюда в static/images/dishes/")
    flux_prompt: str = Field("", description="Промт для генерации эталонного макро-фото в FLUX")

    # Вектор характеристик блюда (от 1.0 до 5.0)
    fat: float = Field(3.0, ge=1.0, le=5.0, description="Жирность (сливочность, мраморность, масло)")
    protein: float = Field(3.0, ge=1.0, le=5.0, description="Насыщенность животным белком")
    acidity: float = Field(2.0, ge=1.0, le=5.0, description="Кислотность блюда/соуса (томаты, цитрус, ягоды)")
    spiciness: float = Field(1.5, ge=1.0, le=5.0, description="Острота и пряность (чили, перец, специи)")
    weight: float = Field(3.0, ge=1.0, le=5.0, description="Плотность/тяжесть блюда и соуса")
    sweetness: float = Field(1.5, ge=1.0, le=5.0, description="Сладость блюда/глазури")
    is_oily_fish: bool = Field(False, description="Флаг жирной рыбы/морепродуктов для проверки конфликта с танинами")


class EvidenceCard(BaseModel):
    """Доказательная карточка: обучает пользователя почему сочетание работает."""
    rule_id: str
    badge_title: str = Field(..., description="Короткий заголовок правила для плашки в UI")
    icon: str = Field("🧪", description="Эмодзи-иконка правила")
    wine_metric_label: str = Field(..., description="Например: Кислотность вина 4.5/5")
    dish_metric_label: str = Field(..., description="Например: Жирность блюда 4.5/5")
    scientific_explanation: str = Field(..., description="Понятное объяснение химии вкуса на языке рецепторов")
    impact_score: float = Field(..., description="Вклад правила в итоговую синергию (+/- баллы)")


class DishPairingRecommendation(BaseModel):
    """Результат подбора блюда к конкретному вину."""
    dish: DishProfile
    synergy_score: float = Field(..., description="Итоговый индекс совместимости (0..100%)")
    match_level: str = Field(..., description="Идеальная синергия / Отличная пара / Хороший выбор")
    sommelier_verdict: str = Field(..., description="Короткий эмоциональный вердикт сомелье")
    evidence_base: List[EvidenceCard] = Field(default_factory=list, description="Доказательная база")


class WinePairingRecommendation(BaseModel):
    """Результат обратного подбора: вино из каталога к выбранному блюду."""
    nomination: str = Field(..., description="Номинация: Классическая гармония / Смелый эксперимент / Лучшая цена")
    nomination_icon: str
    wine_slug: str
    wine_name: str
    wine_color: str
    wine_sugar: str
    price_rub: Optional[float] = None
    rating: Optional[float] = None
    image_url: Optional[str] = None
    organoleptic: WineOrganolepticVector
    synergy_score: float
    sommelier_pitch: str = Field(..., description="Почему именно это вино заставит блюдо заиграть")
    evidence_base: List[EvidenceCard]


class WineAnalogCard(BaseModel):
    """Карточка вина-аналога."""
    analog_type: str = Field(..., description="style_twin | smart_value | upgrade")
    badge_label: str = Field(..., description="🎯 Близнец по вкусу | 💎 Выгодная альтернатива | 👑 На ступень выше")
    wine_slug: str
    wine_name: str
    price_rub: Optional[float] = None
    rating: Optional[float] = None
    similarity_percent: float = Field(..., description="Процент совпадения вкусового профиля (0..100%)")
    organoleptic: WineOrganolepticVector
    comparison_note: str = Field(..., description="Объяснение сомелье: чем похоже и в чем отличие")


class DishBuilderInput(BaseModel):
    """Входные параметры конструктора ужина (3 шага от пользователя)."""
    base_ingredient: str = Field(..., description="steak | duck | poultry | white_fish | salmon | seafood | pasta | cheese | dessert")
    cooking_method: str = Field("grill", description="grill | roasted | raw_steam | creamy_stew | fried")
    sauce: str = Field("none", description="creamy | tomato_citrus | berry_wine | spicy_asian | herb_butter | none")


# =====================================================================
# 2. ЭКСПЕРТНАЯ БАЗА СОРТОВ ВИНОГРАДА И КАТАЛОГА БЛЮД
# =====================================================================

# Базовые органолептические профили сортов (включая российские автохтоны):
# Формат: (acidity, tannins, body, sweetness_base, oak_intensity)
GRAPE_PROFILES: Dict[str, Tuple[float, float, float, float, float]] = {
    # Красные сорта и автохтоны России
    "саперави": (4.2, 4.6, 4.7, 1.5, 4.0),
    "красностоп": (4.0, 4.7, 4.8, 1.5, 4.3),
    "каберне совиньон": (3.8, 4.5, 4.5, 1.4, 4.2),
    "каберне фран": (4.0, 3.8, 3.8, 1.5, 3.5),
    "мерло": (3.3, 3.4, 3.9, 1.7, 3.5),
    "шираз": (3.5, 4.2, 4.6, 1.7, 4.1),
    "сира": (3.6, 4.2, 4.5, 1.6, 4.0),
    "пино нуар": (4.3, 2.3, 2.6, 1.6, 2.8),
    "цимлянский черный": (3.7, 3.6, 3.9, 1.7, 3.2),
    "голубок": (3.8, 3.5, 3.8, 1.6, 3.3),
    "бастардо": (3.2, 3.3, 4.0, 2.2, 3.2),
    "мальбек": (3.5, 4.1, 4.4, 1.7, 3.9),
    "санджовезе": (4.4, 4.0, 3.7, 1.4, 3.4),
    "марселан": (3.6, 4.0, 4.2, 1.6, 3.7),

    # Белые сорта и автохтоны России
    "рислинг": (4.8, 1.0, 2.7, 1.8, 1.5),
    "совиньон блан": (4.7, 1.0, 2.5, 1.5, 1.4),
    "шардоне": (3.6, 1.2, 3.8, 1.7, 3.4),
    "сибирьковый": (4.3, 1.0, 2.6, 1.5, 1.5),
    "кокур": (4.1, 1.1, 2.9, 1.6, 1.8),
    "алиготе": (4.4, 1.0, 2.4, 1.4, 1.4),
    "пино гриджо": (4.1, 1.0, 2.5, 1.6, 1.3),
    "пино блан": (3.8, 1.0, 2.8, 1.6, 1.6),
    "ркацители": (4.2, 1.8, 3.3, 1.5, 2.2),
    "гевюрцтраминер": (3.1, 1.2, 3.6, 2.4, 2.0),
    "мускат": (3.2, 1.0, 3.1, 2.8, 1.6),
    "вионье": (3.2, 1.2, 3.9, 1.8, 2.8),
}


DEFAULT_DISHES_DB: List[DishProfile] = [
    DishProfile(
        dish_id="ribeye_steak_herb_butter",
        title="Стейк Рибай Prime на углях с тающим маслом",
        subtitle="Сочная мраморная говядина прожарки Medium Rare с хрустящей корочкой, на которой медленно тает сливочное масло с чесноком и свежим тимьяном.",
        category="Мясо",
        sensory_tags=["🔥 Дым и угли", "🥩 Сочная мраморность", "🧈 Тающее травяное масло"],
        image_url="/static/images/dishes/ribeye_steak.webp",
        flux_prompt="Macro food photography of pan-seared ribeye steak medium rare, melting garlic herb butter on top, charred crust, glistening meat juices, dark slate plate, blurred red wine glass in background, warm dramatic lighting, 85mm f/1.8",
        fat=4.6, protein=4.8, acidity=1.8, spiciness=2.0, weight=4.8, sweetness=1.2, is_oily_fish=False
    ),
    DishProfile(
        dish_id="duck_breast_cherry_glaze",
        title="Утиная грудка Магре с вишнево-винным демигласом",
        subtitle="Утиное филе с золотистой хрустящей кожей, нежной розовой серединой и густым глянцевым соусом из темной вишни, портвейна и черного перца.",
        category="Птица",
        sensory_tags=["🍒 Кисло-сладкая вишня", "🦆 Хрустящая корочка", "🍷 Глянцевый демиглас"],
        image_url="/static/images/dishes/duck_cherry.webp",
        flux_prompt="Macro food photography of sliced duck breast magret with crispy golden skin, pink center, glossy dark cherry red wine reduction sauce drizzled over, dark moody restaurant table, 85mm lens",
        fat=4.0, protein=4.0, acidity=3.6, spiciness=2.2, weight=3.9, sweetness=2.4, is_oily_fish=False
    ),
    DishProfile(
        dish_id="scallops_citrus_beurre_blanc",
        title="Морские гребешки в цитрусовом соусе Бёр-Блан",
        subtitle="Обжаренные до карамельной корочки сахалинские гребешки в воздушной эмульсии из охлажденного сливочного масла, белого вина и сока лайма.",
        category="Морепродукты",
        sensory_tags=["🍋 Звонкий лайм", "🐚 Нежная текстура", "🧈 Сливочная эмульсия"],
        image_url="/static/images/dishes/scallops_citrus.webp",
        flux_prompt="Macro food photography of pan-seared golden sea scallops in creamy citrus beurre blanc sauce with microgreens and lime zest, dark ceramic plate, chilled white wine glass, ultra appetizing",
        fat=3.5, protein=3.2, acidity=4.3, spiciness=1.2, weight=2.6, sweetness=1.8, is_oily_fish=True
    ),
    DishProfile(
        dish_id="pasta_carbonara_guanciale",
        title="Паста Карбонара с хрустящим гуанчале и Пекорино",
        subtitle="Горячие спагетти, окутанные шелковистым соусом из фермерских желтков и выдержанного сыра Пекорино с золотистыми шкварками вяленых щечек и свежемолотым перцем.",
        category="Паста",
        sensory_tags=["🧀 Сливочный желток и сыр", "🥓 Хрустящий гуанчале", "🌶 Черный перец"],
        image_url="/static/images/dishes/carbonara.webp",
        flux_prompt="Macro food photography of authentic Roman pasta carbonara twirled on a fork, glossy egg yolk pecorino emulsion, crispy guanciale cubes, cracked black pepper, steam rising, dark moody lighting",
        fat=4.5, protein=3.4, acidity=1.8, spiciness=2.3, weight=3.8, sweetness=1.3, is_oily_fish=False
    ),
    DishProfile(
        dish_id="baked_camembert_honey_nuts",
        title="Запеченный Камамбер с сотовым медом и пеканом",
        subtitle="Головка фермерского сыра из печи с тягучей сливочной сердцевиной, веточкой запеченного розмарина, тягучим горным медом и карамелизированным орехом пекан.",
        category="Сыры",
        sensory_tags=["🧀 Тягучая сливочность", "🍯 Горный мед", "🌰 Хрустящий пекан"],
        image_url="/static/images/dishes/baked_camembert.webp",
        flux_prompt="Macro food photography of oven baked camembert cheese cut open with oozing melted cheese center, drizzled with golden honey, roasted pecans and rosemary sprig, rustic dark wood",
        fat=4.7, protein=3.3, acidity=2.1, spiciness=1.3, weight=3.6, sweetness=2.8, is_oily_fish=False
    ),
    DishProfile(
        dish_id="tom_yum_king_prawns",
        title="Пряный лангустин гриль в соусе манго-чили и лемонграсс",
        subtitle="Обжаренные на открытом огне хвосты лангустинов с пикантной глазурью из спелого манго, перца чили, имбиря и сока каффир-лайма.",
        category="Морепродукты",
        sensory_tags=["🌶 Огненный чили", "🥭 Спелое манго", "🌿 Свежий лемонграсс"],
        image_url="/static/images/dishes/spicy_prawns.webp",
        flux_prompt="Macro food photography of grilled king prawns glazed with glossy mango chili sauce, fresh cilantro, lime wedges and red chili slices, glistening texture, dark slate background",
        fat=2.4, protein=3.5, acidity=3.8, spiciness=4.6, weight=2.7, sweetness=3.1, is_oily_fish=True
    ),
    DishProfile(
        dish_id="braised_lamb_saperavi_herbs",
        title="Томленая лопатка ягненка с кавказскими травами и гранатом",
        subtitle="Мясо ягненка 6-часового томления, распадающееся на волокна от прикосновения вилки, с густым мясным соком, кинзой, чесноком и рубиновыми зернами граната.",
        category="Мясо",
        sensory_tags=["🍖 Тающие волокна", "🌿 Пряные травы и чеснок", "💎 Рубиновый гранат"],
        image_url="/static/images/dishes/braised_lamb.webp",
        flux_prompt="Macro food photography of slow-braised lamb shoulder falling off the bone, glossy dark jus reduction, ruby pomegranate seeds and fresh herbs, warm moody lighting, 85mm lens",
        fat=4.4, protein=4.6, acidity=2.8, spiciness=3.2, weight=4.6, sweetness=1.8, is_oily_fish=False
    ),
    DishProfile(
        dish_id="salmon_tartare_avocado",
        title="Тартар из дикого лосося со спелым авокадо и понзу",
        subtitle="Охлажденные кубики нежного лосося с кремовым муссом из авокадо, кунжутным маслом, каперсами и цитрусово-соевой заправкой понзу.",
        category="Рыба",
        sensory_tags=["🐟 Нежный лосось", "🥑 Кремовое авокадо", "🍊 Цитрусовый понзу"],
        image_url="/static/images/dishes/salmon_tartare.webp",
        flux_prompt="Macro food photography of fresh salmon tartare stacked on creamy avocado mousse, glossy citrus ponzu dressing, sesame seeds, micro herbs, fine dining dark plate, chilled rose wine glass",
        fat=3.8, protein=3.6, acidity=3.7, spiciness=1.8, weight=2.5, sweetness=1.6, is_oily_fish=True
    ),
]


# =====================================================================
# 3. ЯДРО СОМЕЛЬЕ: ДОКАЗАТЕЛЬНАЯ БАЗА И АЛГОРИТМЫ ПОДБОРА
# =====================================================================

class SommelierPairingEngine:
    """
    Главный движок гастрономических сочетаний и поиска аналогов VINA.
    """

    def __init__(
        self,
        catalog_items: Optional[List[Dict[str, Any]]] = None,
        dishes_db: Optional[List[DishProfile]] = None,
    ):
        """
        :param catalog_items: Список словарей вин из каталога VINA (например, из catalog.json)
        :param dishes_db: Список карточек блюд (по умолчанию DEFAULT_DISHES_DB)
        """
        self.dishes: Dict[str, DishProfile] = {
            d.dish_id: d for d in (dishes_db or DEFAULT_DISHES_DB)
        }
        self.catalog: Dict[str, Dict[str, Any]] = {}
        self.wine_vectors: Dict[str, WineOrganolepticVector] = {}

        if catalog_items:
            self.load_catalog(catalog_items)

    # -----------------------------------------------------------------
    # ИНИЦИАЛИЗАЦИЯ КАТАЛОГА И АВТО-ВЫЧИСЛЕНИЕ ВЕКТОРА ОРГАНОЛЕПТИКИ
    # -----------------------------------------------------------------

    def load_catalog(self, catalog_items: List[Dict[str, Any]]) -> None:
        """Загружает каталог вин и строит 5D-векторы вкуса для каждого вина."""
        for item in catalog_items:
            slug = item.get("slug") or item.get("id")
            if not slug:
                continue
            self.catalog[str(slug)] = item
            self.wine_vectors[str(slug)] = self.infer_wine_vector(item)

    @staticmethod
    def infer_wine_vector(wine_data: Dict[str, Any]) -> WineOrganolepticVector:
        """
        Извлекает или реконструирует 5D-вектор органолептики вина из метаданных каталога.
        Если в JSON уже есть явные числа (acidity, tannins...), использует их.
        Иначе вычисляет по сорту винограда, цвету, сахару и выдержке.
        """
        # 1. Проверяем, есть ли готовые поля в карточке
        if all(k in wine_data for k in ("acidity", "tannins", "body", "sweetness")):
            return WineOrganolepticVector(
                acidity=float(wine_data["acidity"]),
                tannins=float(wine_data["tannins"]),
                body=float(wine_data["body"]),
                sweetness=float(wine_data["sweetness"]),
                oak_intensity=float(wine_data.get("oak_intensity", 2.5)),
            )

        text_blob = " ".join([
            str(wine_data.get("name", "")),
            str(wine_data.get("grape", "")),
            str(wine_data.get("grapes", "")),
            str(wine_data.get("description", "")),
            str(wine_data.get("slug", "")),
        ]).lower()

        color = str(wine_data.get("color", "")).lower()
        sugar = str(wine_data.get("sugar", "")).lower()

        # Базовые значения по цвету
        if "красн" in color or "krasnoe" in text_blob:
            acidity, tannins, body, sweetness, oak = 3.6, 3.8, 3.9, 1.5, 3.4
        elif "розов" in color or "rose" in text_blob or "rozovoe" in text_blob:
            acidity, tannins, body, sweetness, oak = 4.2, 1.4, 2.5, 1.7, 1.5
        else:  # Белое / Игристое
            acidity, tannins, body, sweetness, oak = 4.2, 1.1, 2.7, 1.6, 1.7

        # Уточнение по сорту винограда (если найден в купаже, усредняем)
        matched_grapes = [
            vec for grape_name, vec in GRAPE_PROFILES.items()
            if grape_name in text_blob
        ]
        if matched_grapes:
            arr = np.mean(matched_grapes, axis=0)
            acidity, tannins, body, sweetness, oak = [float(x) for x in arr]

        # Коррекция по типу сахара
        if any(w in sugar or w in text_blob for w in ("экстра брют", "extra brut", "брют натюр")):
            sweetness = 1.0
            acidity = min(5.0, acidity + 0.4)
        elif "брют" in sugar or "brut" in text_blob:
            sweetness = 1.3
            acidity = min(5.0, acidity + 0.3)
        elif "сухое" in sugar or "suhoe" in text_blob:
            sweetness = 1.5
        elif "полусухое" in sugar or "polusuhoe" in text_blob:
            sweetness = 2.5
        elif "полусладкое" in sugar or "polusladkoe" in text_blob:
            sweetness = 3.6
        elif "сладкое" in sugar or "десертн" in sugar or "ликерн" in sugar:
            sweetness = 4.7
            body = min(5.0, body + 0.5)

        # Коррекция на выдержку в дубе (Резерв / Выдержанное / Коллекционное)
        if any(w in text_blob for w in ("резерв", "reserve", "reserva", "выдержан", "дуб", "barrique")):
            oak = min(5.0, oak + 1.0)
            body = min(5.0, body + 0.4)
            tannins = min(5.0, tannins + 0.3) if tannins > 2.0 else tannins

        return WineOrganolepticVector(
            acidity=round(float(np.clip(acidity, 1.0, 5.0)), 1),
            tannins=round(float(np.clip(tannins, 1.0, 5.0)), 1),
            body=round(float(np.clip(body, 1.0, 5.0)), 1),
            sweetness=round(float(np.clip(sweetness, 1.0, 5.0)), 1),
            oak_intensity=round(float(np.clip(oak, 1.0, 5.0)), 1),
        )

    # -----------------------------------------------------------------
    # 4. МАТЕМАТИЧЕСКОЕ ЯДРО «ДОКАЗАТЕЛЬНОЙ БАЗЫ» (Synergy & Evidence)
    # -----------------------------------------------------------------

    def calculate_synergy(
        self,
        wine_vec: WineOrganolepticVector,
        dish: DishProfile,
    ) -> Tuple[float, List[EvidenceCard], str]:
        """
        Вычисляет процент синергии (0..100%) между вином и блюдом
        и формирует список обучающих карточек Доказательной базы.
        """
        base_score = 84.0
        evidence: List[EvidenceCard] = []

        # ПРАВИЛО 1: «Кислотный скальпель» (Кислотность вина vs Жирность блюда)
        if dish.fat >= 3.5:
            if wine_vec.acidity >= dish.fat - 0.5:
                bonus = 6.5
                base_score += bonus
                evidence.append(EvidenceCard(
                    rule_id="acid_cuts_fat",
                    badge_title="Кислотность режет жир",
                    icon="⚡",
                    wine_metric_label=f"Кислотность вина: {wine_vec.acidity}/5",
                    dish_metric_label=f"Жирность блюда: {dish.fat}/5",
                    scientific_explanation=(
                        "Высокая кислотность вина вызывает естественное слюноотделение и работает как "
                        "гастрономический скальпель: она расщепляет липидную пленку на языке после каждого "
                        "кусочка и полностью обновляет ваши рецепторы."
                    ),
                    impact_score=bonus
                ))
            else:
                penalty = -12.0 * (dish.fat - wine_vec.acidity)
                base_score += penalty
                evidence.append(EvidenceCard(
                    rule_id="low_acid_vs_fat",
                    badge_title="Нехватка кислотности против жира",
                    icon="⚠️",
                    wine_metric_label=f"Кислотность вина: {wine_vec.acidity}/5",
                    dish_metric_label=f"Жирность блюда: {dish.fat}/5",
                    scientific_explanation=(
                        "Насыщенный жир блюда обволакивает рецепторы, а мягкой кислотности этого вина "
                        "недостаточно, чтобы освежить нёбо — сочетание может показаться тяжеловесным."
                    ),
                    impact_score=round(penalty, 1)
                ))

        # ПРАВИЛО 2: Баланс кислотности соуса и вина
        if dish.acidity >= 3.2:
            if wine_vec.acidity >= dish.acidity:
                bonus = 4.5
                base_score += bonus
                evidence.append(EvidenceCard(
                    rule_id="acid_harmony",
                    badge_title="Гармония с кислым соусом",
                    icon="🍋",
                    wine_metric_label=f"Кислотность вина: {wine_vec.acidity}/5",
                    dish_metric_label=f"Кислотность соуса: {dish.acidity}/5",
                    scientific_explanation=(
                        "Главный закон сомелье: вино всегда должно быть кислотнее соуса. Здесь яркая "
                        "кислотность вина легко выдерживает натиск цитрусовых/ягодных нот блюда и раскрывает фруктовый букет."
                    ),
                    impact_score=bonus
                ))
            else:
                penalty = -14.0 * (dish.acidity - wine_vec.acidity)
                base_score += penalty

        # ПРАВИЛО 3: «Танинный магнит» (Танины вина vs Белок мяса)
        if dish.protein >= 3.8 and not dish.is_oily_fish:
            tannin_diff = abs(wine_vec.tannins - dish.protein)
            if wine_vec.tannins >= 3.5 and tannin_diff <= 1.2:
                bonus = 8.0
                base_score += bonus
                evidence.append(EvidenceCard(
                    rule_id="tannin_protein_lock",
                    badge_title="Танины + Мясной белок",
                    icon="🥩",
                    wine_metric_label=f"Танинность вина: {wine_vec.tannins}/5",
                    dish_metric_label=f"Белок и сочность мяса: {dish.protein}/5",
                    scientific_explanation=(
                        "Молекулы танинов мгновенно связываются с белками и пептидами сочного мяса, а не "
                        "с белками вашей слюны. В результате терпкость вина исчезает, уступая место бархатистым ягодным тонам."
                    ),
                    impact_score=bonus
                ))
            elif wine_vec.tannins < 2.2 and dish.weight >= 4.2:
                base_score -= 10.0

        # ПРАВИЛО 4: Конфликт танинов и рыбьего жира
        if dish.is_oily_fish:
            if wine_vec.tannins >= 2.8:
                penalty = -28.0
                base_score += penalty
                evidence.append(EvidenceCard(
                    rule_id="tannin_fish_conflict",
                    badge_title="Конфликт танинов и морепродуктов",
                    icon="🚫",
                    wine_metric_label=f"Танинность вина: {wine_vec.tannins}/5",
                    dish_metric_label="Омега-3 и йод морепродуктов",
                    scientific_explanation=(
                        "Высокие танины красного вина вступают в химическую реакцию с ненасыщенными жирными "
                        "кислотами рыбы, вызывая во рту неприятное металлическое послевкусие."
                    ),
                    impact_score=penalty
                ))
            else:
                bonus = 5.5
                base_score += bonus
                evidence.append(EvidenceCard(
                    rule_id="delicate_seafood_match",
                    badge_title="Чистота морского вкуса",
                    icon="🐚",
                    wine_metric_label=f"Деликатные танины: {wine_vec.tannins}/5",
                    dish_metric_label="Нежный белок морепродуктов",
                    scientific_explanation=(
                        "Отсутствие грубых танинов позволяет сохранить тонкую минеральность и сладковатую "
                        "текстуру морепродуктов без малейшей горечи в послевкусии."
                    ),
                    impact_score=bonus
                ))

        # ПРАВИЛО 5: «Огнетушитель» (Сладость/Фруктовость vs Острота и пряность)
        if dish.spiciness >= 3.5:
            if wine_vec.sweetness >= 2.2 and wine_vec.tannins <= 2.2:
                bonus = 7.5
                base_score += bonus
                evidence.append(EvidenceCard(
                    rule_id="sweet_cools_spice",
                    badge_title="Укрощение огня специй",
                    icon="🌶️",
                    wine_metric_label=f"Сладость/Фруктовость: {wine_vec.sweetness}/5",
                    dish_metric_label=f"Пикантность чили: {dish.spiciness}/5",
                    scientific_explanation=(
                        "Остаточный сахар и сочная фруктовость вина работают как прохладный компресс для "
                        "рецепторов, нейтрализуя жжение капсаицина и подчеркивая экзотические специи."
                    ),
                    impact_score=bonus
                ))
            elif wine_vec.tannins >= 3.5:
                base_score -= 15.0

        # ПРАВИЛО 6: «Равный вес» (Тело вина vs Плотность блюда)
        weight_diff = abs(wine_vec.body - dish.weight)
        if weight_diff <= 0.8:
            bonus = 5.0
            base_score += bonus
            evidence.append(EvidenceCard(
                rule_id="equal_body_weight",
                badge_title="Баланс плотности и тела",
                icon="⚖️",
                wine_metric_label=f"Тело вина: {wine_vec.body}/5",
                dish_metric_label=f"Плотность блюда: {dish.weight}/5",
                scientific_explanation=(
                    "Вес вина и насыщенность блюда находятся в идеальном равновесии: вино не подавляет "
                    "текстуру продукта, а блюдо не делает вино водянистым."
                ),
                impact_score=bonus
            ))
        else:
            base_score -= (weight_diff - 0.8) * 7.5

        final_score = round(float(np.clip(base_score, 15.0, 99.0)), 1)

        if final_score >= 92.0:
            match_level = "🔥 Идеальная синергия"
            verdict = "Безупречный союз: вино и блюдо раскрывают скрытые грани друг друга."
        elif final_score >= 82.0:
            match_level = "✨ Отличная гастропара"
            verdict = "Гармоничное сочетание с ярким балансом кислотности и текстур."
        elif final_score >= 70.0:
            match_level = "👍 Хороший выбор"
            verdict = "Приятная повседневная пара без вкусовых конфликтов."
        else:
            match_level = "⚠️ Рискованное сочетание"
            verdict = "Характеристики вина и блюда спорят между собой — лучше выбрать другой профиль."

        return final_score, evidence, f"{match_level}: {verdict}"

    # -----------------------------------------------------------------
    # 5. СЦЕНАРИЙ 1: ПОДБОР БЛЮД К ВЫБРАННОМУ ВИНУ (Вино -> Блюда)
    # -----------------------------------------------------------------

    def recommend_dishes_for_wine(
        self,
        wine_slug: str,
        top_k: int = 4,
    ) -> List[DishPairingRecommendation]:
        """Возвращает топ самых аппетитных блюд к выбранному вину с доказательной базой."""
        if wine_slug not in self.wine_vectors:
            raise KeyError(f"Вино со slug '{wine_slug}' не найдено в каталоге.")

        wine_vec = self.wine_vectors[wine_slug]
        results: List[DishPairingRecommendation] = []

        for dish in self.dishes.values():
            score, evidence, verdict = self.calculate_synergy(wine_vec, dish)
            results.append(DishPairingRecommendation(
                dish=dish,
                synergy_score=score,
                match_level=verdict.split(":")[0],
                sommelier_verdict=verdict.split(":", 1)[1].strip(),
                evidence_base=evidence,
            ))

        results.sort(key=lambda r: r.synergy_score, reverse=True)
        return results[:top_k]

    # -----------------------------------------------------------------
    # 6. СЦЕНАРИЙ 2: ПОДБОР ВИН К БЛЮДУ / КОНСТРУКТОРУ УЖИНА (Блюдо -> Вина)
    # -----------------------------------------------------------------

    @staticmethod
    def build_custom_dish_profile(builder: DishBuilderInput) -> DishProfile:
        """
        Собирает динамический физико-химический вектор блюда из 3 шагов пользователя:
        Основной продукт + Способ приготовления + Соус.
        """
        base_map = {
            "steak": ("Мраморный стейк из говядины", 4.2, 4.8, 1.5, 1.5, 4.4, 1.2, False),
            "duck": ("Утиная грудка / Дичь", 4.0, 4.1, 2.0, 1.8, 3.8, 1.6, False),
            "poultry": ("Фермерский цыпленок / Индейка", 2.6, 3.5, 1.8, 1.5, 2.8, 1.4, False),
            "white_fish": ("Белая морская рыба (сибас, дорадо, палтус)", 2.3, 3.3, 2.2, 1.2, 2.2, 1.3, True),
            "salmon": ("Стейк из дикого лосося / Форели", 3.9, 3.7, 2.0, 1.4, 3.1, 1.4, True),
            "seafood": ("Креветки, гребешки и мидии", 2.2, 3.2, 2.5, 1.5, 2.1, 1.8, True),
            "pasta": ("Итальянская паста / Ризотто", 3.5, 2.8, 2.2, 1.6, 3.4, 1.5, False),
            "cheese": ("Фермерское сырное плато", 4.5, 3.5, 2.0, 1.5, 3.5, 2.0, False),
            "dessert": ("Ягодно-фруктовый десерт", 3.2, 1.5, 3.0, 1.0, 3.0, 4.5, False),
        }
        title, fat, protein, acid, spice, weight, sweet, is_fish = base_map.get(
            builder.base_ingredient, base_map["steak"]
        )

        # Модификаторы способа приготовления
        method_labels = {
            "grill": ("на открытом огне с дымком", +0.3, +0.2, 0.0, +0.3, +0.5),
            "roasted": ("запеченное до золотистой корочки", +0.2, 0.0, 0.0, +0.1, +0.3),
            "raw_steam": ("деликатного приготовления (тартар / на пару)", -0.4, 0.0, +0.4, 0.0, -0.5),
            "creamy_stew": ("томленое до нежности", +0.5, 0.0, 0.0, +0.1, +0.4),
            "fried": ("с хрустящей корочкой", +0.6, 0.0, 0.0, +0.2, +0.3),
        }
        m_label, d_fat, d_prot, d_acid, d_spice, d_weight = method_labels.get(
            builder.cooking_method, method_labels["grill"]
        )

        # Модификаторы соуса (соус — главный дирижер винной пары!)
        sauce_labels = {
            "creamy": ("в бархатном сливочно-сырном соусе", +0.9, +0.1, -0.2, 0.0, +0.6, +0.2),
            "tomato_citrus": ("с ярким томатно-цитрусовым акцентом", -0.1, 0.0, +1.5, +0.2, +0.1, +0.2),
            "berry_wine": ("под густым ягодно-винным демигласом", +0.1, 0.0, +1.0, +0.3, +0.5, +0.7),
            "spicy_asian": ("в пикантной азиатской глазури с чили и имбирем", 0.0, 0.0, +0.7, +2.4, +0.2, +1.1),
            "herb_butter": ("с ароматным чесночно-травяным маслом", +0.7, 0.0, +0.2, +0.2, +0.3, 0.0),
            "none": ("в собственном соку", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        }
        s_label, s_fat, s_prot, s_acid, s_spice, s_weight, s_sweet = sauce_labels.get(
            builder.sauce, sauce_labels["none"]
        )

        return DishProfile(
            dish_id=f"custom_{builder.base_ingredient}_{builder.cooking_method}_{builder.sauce}",
            title=f"{title} {m_label} {s_label}".strip(),
            subtitle="Индивидуальная гастропара, собранная в конструкторе сомелье.",
            category="Конструктор ужина",
            sensory_tags=[f"🔥 {m_label.capitalize()}", f"🥣 {s_label.capitalize()}"],
            fat=round(float(np.clip(fat + d_fat + s_fat, 1.0, 5.0)), 1),
            protein=round(float(np.clip(protein + d_prot + s_prot, 1.0, 5.0)), 1),
            acidity=round(float(np.clip(acid + d_acid + s_acid, 1.0, 5.0)), 1),
            spiciness=round(float(np.clip(spice + d_spice + s_spice, 1.0, 5.0)), 1),
            weight=round(float(np.clip(weight + d_weight + s_weight, 1.0, 5.0)), 1),
            sweetness=round(float(np.clip(sweet + s_sweet, 1.0, 5.0)), 1),
            is_oily_fish=is_fish,
        )

    def recommend_wines_for_dish(
        self,
        dish: DishProfile,
    ) -> List[WinePairingRecommendation]:
        """
        Подбирает Топ-3 вина из каталога к блюду в 3 номинациях:
        1) 👑 Классическая гармония
        2) ✨ Смелый гастро-эксперимент
        3) 💎 Лучшая цена / качество
        """
        candidates = []
        for slug, item in self.catalog.items():
            w_vec = self.wine_vectors[slug]
            score, evidence, _ = self.calculate_synergy(w_vec, dish)
            price = float(item.get("price") or item.get("price_rub") or 950.0)
            rating = float(item.get("rating") or 4.2)

            candidates.append({
                "slug": slug,
                "item": item,
                "vec": w_vec,
                "score": score,
                "evidence": evidence,
                "price": price,
                "rating": rating,
            })

        if not candidates:
            return []

        candidates.sort(key=lambda x: (x["score"], x["rating"]), reverse=True)

        selected: List[WinePairingRecommendation] = []
        used_slugs = set()

        # 1. Номинация «Классическая гармония» (максимальный Synergy Score)
        best = candidates[0]
        used_slugs.add(best["slug"])
        selected.append(self._pack_wine_recommendation(
            best,
            nomination="Классическая гармония",
            icon="👑",
            pitch=(
                f"Эталонное попадание ({best['score']}%): баланс кислотности ({best['vec'].acidity}/5) "
                f"и тела ({best['vec'].body}/5) идеально ложится на текстуру блюда «{dish.title}»."
            )
        ))

        # 2. Номинация «Лучшая цена / качество» (среди вин с синергией >= 80%)
        high_synergy_pool = [
            c for c in candidates
            if c["slug"] not in used_slugs and c["score"] >= max(78.0, best["score"] - 8.0)
        ]
        if high_synergy_pool:
            best_value = min(high_synergy_pool, key=lambda c: c["price"] / max(c["rating"], 3.8))
            used_slugs.add(best_value["slug"])
            selected.append(self._pack_wine_recommendation(
                best_value,
                nomination="Умный выбор (Цена / Качество)",
                icon="💎",
                pitch=(
                    f"Дает {best_value['score']}% гастрономической синергии по максимально "
                    f"привлекательной цене ({int(best_value['price'])} ₽)."
                )
            ))

        # 3. Номинация «Смелый гастро-эксперимент» (другой сорт или контрастный стиль с высоким баллом)
        experiment_pool = [c for c in candidates if c["slug"] not in used_slugs]
        if experiment_pool:
            exp = experiment_pool[0]
            selected.append(self._pack_wine_recommendation(
                exp,
                nomination="Гастро-открытие сомелье",
                icon="✨",
                pitch=(
                    f"Нетривиальная пара ({exp['score']}%), которая раскроет блюдо с новой стороны "
                    f"за счет игры ароматики и свежей структуры."
                )
            ))

        return selected

    def _pack_wine_recommendation(
        self,
        cand: Dict[str, Any],
        nomination: str,
        icon: str,
        pitch: str,
    ) -> WinePairingRecommendation:
        item = cand["item"]
        return WinePairingRecommendation(
            nomination=nomination,
            nomination_icon=icon,
            wine_slug=cand["slug"],
            wine_name=str(item.get("name", cand["slug"])),
            wine_color=str(item.get("color", "Не указан")),
            wine_sugar=str(item.get("sugar", "Сухое")),
            price_rub=cand["price"],
            rating=cand["rating"],
            image_url=item.get("image_url") or item.get("image"),
            organoleptic=cand["vec"],
            synergy_score=cand["score"],
            sommelier_pitch=pitch,
            evidence_base=cand["evidence"],
        )

    # -----------------------------------------------------------------
    # 7. СЦЕНАРИЙ 3: ПОИСК АНАЛОГОВ ВИНА (Analog Finder в каталоге)
    # -----------------------------------------------------------------

    def find_wine_analogs(self, wine_slug: str) -> List[WineAnalogCard]:
        """
        Находит 3 лучших аналога вина в каталоге по близости 5D-вектора вкуса:
        1) 🎯 Близнец по стилю (максимальное совпадение кислотности, танинов, тела и сахара)
        2) 💎 Выгодная альтернатива (близкий профиль, но дешевле)
        3) 👑 На ступень выше (тот же профиль, но выше рейтинг/выдержка)
        """
        if wine_slug not in self.catalog:
            raise KeyError(f"Вино '{wine_slug}' не найдено в каталоге.")

        target_item = self.catalog[wine_slug]
        target_vec = self.wine_vectors[wine_slug].to_numpy()
        target_color = str(target_item.get("color", "")).lower()
        target_price = float(target_item.get("price") or target_item.get("price_rub") or 1000.0)
        target_rating = float(target_item.get("rating") or 4.2)

        # Веса важности осей при поиске аналога: [acidity, tannins, body, sweetness, oak]
        weights = np.array([1.3, 1.4, 1.1, 1.6, 0.8], dtype=np.float32)

        scored_pool = []
        for slug, item in self.catalog.items():
            if slug == wine_slug:
                continue

            # Фильтруем по тому же цвету вина (красное к красному, белое к белому)
            cand_color = str(item.get("color", "")).lower()
            if target_color and cand_color and (target_color[:4] != cand_color[:4]):
                continue

            cand_vec_obj = self.wine_vectors[slug]
            cand_vec = cand_vec_obj.to_numpy()

            # Взвешенное евклидово расстояние -> переводим в % сходства (0..100%)
            weighted_dist = float(np.sqrt(np.sum(weights * ((target_vec - cand_vec) ** 2))))
            similarity = round(float(np.clip(100.0 * math.exp(-0.28 * weighted_dist), 10.0, 99.4)), 1)

            cand_price = float(item.get("price") or item.get("price_rub") or target_price)
            cand_rating = float(item.get("rating") or 4.2)

            scored_pool.append({
                "slug": slug,
                "item": item,
                "vec": cand_vec_obj,
                "similarity": similarity,
                "price": cand_price,
                "rating": cand_rating,
            })

        scored_pool.sort(key=lambda x: x["similarity"], reverse=True)
        if not scored_pool:
            return []

        analogs: List[WineAnalogCard] = []
        used = set()

        # 1. Близнец по стилю
        twin = scored_pool[0]
        used.add(twin["slug"])
        analogs.append(self._build_analog_card(
            target_vec_obj=self.wine_vectors[wine_slug],
            target_price=target_price,
            cand=twin,
            analog_type="style_twin",
            badge_label="🎯 Близнец по вкусу",
        ))

        # 2. Выгодная альтернатива (сходство >= 82% и цена ниже)
        cheaper_candidates = [
            c for c in scored_pool
            if c["slug"] not in used and c["similarity"] >= 82.0 and c["price"] < target_price * 0.92
        ]
        if cheaper_candidates:
            smart_val = cheaper_candidates[0]
            used.add(smart_val["slug"])
            analogs.append(self._build_analog_card(
                target_vec_obj=self.wine_vectors[wine_slug],
                target_price=target_price,
                cand=smart_val,
                analog_type="smart_value",
                badge_label="💎 Выгоднее по цене",
            ))

        # 3. Премиум-апгрейд (сходство >= 80% и выше рейтинг или выдержка в дубе)
        upgrade_candidates = [
            c for c in scored_pool
            if c["slug"] not in used
            and c["similarity"] >= 80.0
            and (c["rating"] > target_rating or c["vec"].oak_intensity > self.wine_vectors[wine_slug].oak_intensity)
        ]
        if upgrade_candidates:
            upg = upgrade_candidates[0]
            used.add(upg["slug"])
            analogs.append(self._build_analog_card(
                target_vec_obj=self.wine_vectors[wine_slug],
                target_price=target_price,
                cand=upg,
                analog_type="upgrade",
                badge_label="👑 На ступень выше",
            ))

        # Добиваем до 3 карточек, если какой-то спец-номинации не нашлось
        for c in scored_pool:
            if len(analogs) >= 3:
                break
            if c["slug"] not in used:
                used.add(c["slug"])
                analogs.append(self._build_analog_card(
                    target_vec_obj=self.wine_vectors[wine_slug],
                    target_price=target_price,
                    cand=c,
                    analog_type="style_twin",
                    badge_label="🔄 Похожий профиль",
                ))

        return analogs

    @staticmethod
    def _build_analog_card(
        target_vec_obj: WineOrganolepticVector,
        target_price: float,
        cand: Dict[str, Any],
        analog_type: str,
        badge_label: str,
    ) -> WineAnalogCard:
        c_vec: WineOrganolepticVector = cand["vec"]
        diffs = []

        if abs(c_vec.acidity - target_vec_obj.acidity) <= 0.3:
            diffs.append(f"идентичная кислотность ({c_vec.acidity}/5)")
        elif c_vec.acidity > target_vec_obj.acidity:
            diffs.append(f"чуть более свежая и звонкая кислотность ({c_vec.acidity}/5)")
        else:
            diffs.append(f"более мягкая кислотность ({c_vec.acidity}/5)")

        if c_vec.tannins >= 2.0 or target_vec_obj.tannins >= 2.0:
            if abs(c_vec.tannins - target_vec_obj.tannins) <= 0.3:
                diffs.append("такая же структура танинов")
            elif c_vec.tannins < target_vec_obj.tannins:
                diffs.append("более шелковистые и округлые танины")
            else:
                diffs.append("более плотный танинный каркас")

        price_diff = int(target_price - cand["price"])
        if price_diff > 80:
            diffs.append(f"экономия {price_diff} ₽ на бутылке")

        note = "Совпадение профиля " + f"{cand['similarity']}%: " + ", ".join(diffs) + "."

        return WineAnalogCard(
            analog_type=analog_type,
            badge_label=badge_label,
            wine_slug=cand["slug"],
            wine_name=str(cand["item"].get("name", cand["slug"])),
            price_rub=cand["price"],
            rating=cand["rating"],
            similarity_percent=cand["similarity"],
            organoleptic=c_vec,
            comparison_note=note,
        )