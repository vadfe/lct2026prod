# План: Повышение точности через OCR-pipeline при Уверенности < 80%

## Идея

Когда **DINOv2 + SIFT дают `dino_similarity < 0.80`** — визуального совпадения недостаточно.  
Запускается **второй проход**: OCR-пайплайн читает текст с этикетки,  
извлекает теги (название, винодельня, цвет, регион, сорт, %, год),  
и переранжирует кандидатов по совпадению тегов.

---

## Как работает сейчас (основной пайплайн)

```text
Фото → YOLO-детектор → crop этикетки
     → DINOv2 embedding
     → pgvector ближайшие N кандидатов
     → SIFT переранжирование
     → топ-1 результат + dino_similarity
```

**Проблема:** при плохом освещении, повороте, бликах `dino_similarity` может падать  
ниже 0.80 даже при правильном ответе. SIFT тоже может не найти достаточно точек.

---

## Новый поток при Уверенность < 80%

```text
Фото → dino_similarity < 0.80?
     ├── НЕТ → стандартный результат
     └── ДА  → OCR Confidence Boost Pipeline
                     │
                     ▼
           [Stage1] Препроцессинг + dewarp
                (коррекция перспективы, CLAHE,
                 unsharp mask — уже есть в VINA/pipeline/)
                     │
                     ▼
           [Stage5] OCR с двойным движком
                (RapidOCR PP-OCRv4 + EasyOCR RU+EN)
                + WineVocabularyCorrector
                     │
                     ▼
           Извлечение тегов (TagBundle):
                • title_tokens: слова из текста
                • winery: "АБРАУ-ДЮРСО", "Chateau de Talu"...
                • color: "КРАСНОЕ", "БЕЛОЕ", "РОЗОВОЕ"
                • category: "СУХОЕ", "ПОЛУСУХОЕ", "БРЮТ"...
                • region: "КРЫМ", "КУБАНЬ", "CAHORS"...
                • grape: "КАБЕРНЕ", "МЕРЛО", "СОВИНЬОН"...
                • year: 2021, 2022...
                • alcohol: 13.5%
                     │
                     ▼
           Тег-скоринг кандидатов из pgvector-топа:
                score_tag = сумма по весам:
                  • совпадение winery   → w=3.0
                  • совпадение title    → w=2.5 (fuzzy, порог 0.75)
                  • совпадение color    → w=1.5
                  • совпадение region   → w=1.5
                  • совпадение grape    → w=1.5
                  • совпадение category → w=1.0
                  • совпадение year     → w=0.5
                     │
                     ▼
           Финальный score = (dino_similarity * 0.5) + (tag_score_norm * 0.5)
                     │
                     ▼
           Новый топ-1 + пересчёт Уверенности:
                confidence = min(0.95, final_score)
```

---

## Расчёт итоговой Уверенности

```python
CONFIDENCE_THRESHOLD = 0.80

def compute_confidence(result: SearchResult) -> float:
    """
    Базовая Уверенность из визуального поиска.
    Смешиваем dino_similarity и нормированный sift_score.
    """
    dino = result.dino_similarity          # 0.0 – 1.0
    sift = min(result.sift_score, 1.0)    # нормируем (уже 0..1)
    return round(dino * 0.7 + sift * 0.3, 3)

def apply_ocr_boost(base_conf: float, tag_score: float) -> float:
    """
    Повышаем уверенность за счёт тегов.
    tag_score — сумма весов совпавших тегов, max_possible = 11.5
    """
    tag_norm = min(tag_score / 11.5, 1.0)
    return round(base_conf * 0.5 + tag_norm * 0.5, 3)
```

---

## Компоненты реализации (файлы)

### Backend — `D:\VINA2\lct2026prod`

| Файл | Что меняется |
| ---- | ------------ |
| `app/schemas/search/v1.py` | Добавить поле `confidence: float` в `SearchResult` |
| `app/pipelines/search/v1/pipeline.py` | Вычислять `confidence`, при < 0.80 запускать OCR-boost |
| **[NEW]** `app/pipelines/ocr/stage5_ocr.py` | Перенести `Stage5OCRDecoder` из VINA |
| **[NEW]** `app/pipelines/ocr/wine_lexicon.py` | Перенести `WineVocabularyCorrector` из VINA |
| **[NEW]** `app/pipelines/ocr/tag_scorer.py` | `TagScorer` — извлечение TagBundle + скоринг |
| `app/core/dependencies.py` | Инициализировать OCR-движок как singleton |
| `app/schemas/search/v1.py` | Добавить `ocr_tags: dict \| None = None` для отладки |

### Frontend — `D:\VINA2\lct2026prod\web`

| Файл | Что меняется |
| ---- | ------------ |
| `web/app.js` | Читать `item.confidence` из ответа API |
| `web/index.html` | Индикатор "🔍 Анализируем этикетку..." при низкой уверенности |

---

## Детали алгоритма тег-скоринга (`TagScorer`)

```python
class TagBundle:
    title_tokens: list[str]   # токены слов с этикетки
    winery: str | None        # название винодельни
    color: str | None         # цвет вина
    category: str | None      # тип (сухое, полусухое...)
    region: str | None        # регион
    grape: str | None         # сорт
    year: int | None          # год урожая
    alcohol: float | None     # крепость

def score_candidate(bundle: TagBundle, product: Product) -> float:
    score = 0.0

    # Нечёткое совпадение токенов названия
    if bundle.title_tokens:
        ratio = fuzzy_token_overlap(bundle.title_tokens, product.title)
        if ratio > 0.6:
            score += 2.5 * ratio

    # Строгие теговые поля
    if bundle.winery and fuzzy_match(bundle.winery, product.manufacturer) > 0.75:
        score += 3.0
    if bundle.color and normalize(bundle.color) == normalize(product.color):
        score += 1.5
    if bundle.region and fuzzy_match(bundle.region, product.region) > 0.7:
        score += 1.5
    if bundle.grape and fuzzy_match(bundle.grape, product.grape) > 0.7:
        score += 1.5
    if bundle.category and normalize(bundle.category) == normalize(product.category):
        score += 1.0
    if bundle.year and str(bundle.year) in (product.description or ""):
        score += 0.5

    return score
```

---

## Этапы выполнения

- `[ ]` **Шаг 1 — Backend:** Добавить `confidence: float` в `SearchResult` и вычислять в `pipeline.py`
- `[ ]` **Шаг 2 — Frontend:** Обновить `app.js` для чтения поля `confidence` из API (уже сделано частично)
- `[ ]` **Шаг 3 — OCR-модуль:** Перенести `Stage5OCRDecoder` + `WineVocabularyCorrector` из VINA в lct2026prod
- `[ ]` **Шаг 4 — TagScorer:** Реализовать `TagBundle` + функцию скоринга
- `[ ]` **Шаг 5 — Интеграция:** В `pipeline.py` добавить условие `if base_confidence < 0.80: run_ocr_boost()`
- `[ ]` **Шаг 6 — Тест:** Трудные случаи (боковые снимки, блики, мятые этикетки)
- `[ ]` **Шаг 7 — Тюнинг весов:** Откалибровать веса на тестовом датасете

---

## Почему это работает

| Случай | Что даёт OCR-boost |
| ------ | ------------------ |
| Боковой снимок | DINO слабый, но название/регион на этикетке читаемы |
| Блики | Часть этикетки перекрыта, но текст вокруг сохранён |
| Сходные этикетки (один производитель, разный сорт) | Цвет/сорт из OCR прямо отсекают неправильного кандидата |
| Нестандартные ракурсы | Dewarp выравнивает, OCR потом корректно читает |

---

## Производительность

- `Stage5OCRDecoder` тяжёлый (EasyOCR + RapidOCR) — инициализируется **один раз** при старте.
- OCR-проход добавляет **~300–800 мс** (только при confidence < 0.80, не всегда).
- Рекомендуется: таймаут 2000 мс с graceful fallback к исходному результату.

---

## Ресурсы в VINA (переносятся без изменений)

| Файл | Назначение |
| ---- | ---------- |
| `pipeline/stage5_ocr.py` | OCR engine (RapidOCR + EasyOCR + CLAHE) |
| `pipeline/stage1_preprocessing.py` | Dewarp, perspective correction |
| `pipeline/wine_lexicon_corrector.py` | Словари + fuzzy-коррекция OCR-артефактов |
| `pipeline/catalog.py` | Структура тегов каталога (цвет, сорт, регион) |
