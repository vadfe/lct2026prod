from dataclasses import dataclass, field
import re
from difflib import SequenceMatcher

def fuzzy_match(s1: str, s2: str) -> float:
    if not s1 or not s2: return 0.0
    return SequenceMatcher(None, s1.lower(), s2.lower()).ratio()

def normalize(s: str) -> str:
    if not s: return ""
    return s.strip().lower()

def fuzzy_token_overlap(tokens: list[str], target: str) -> float:
    if not tokens or not target: return 0.0
    target_lower = target.lower()
    matches = 0
    for t in tokens:
        if t.lower() in target_lower:
            matches += 1
    return min(1.0, matches / max(1, len(tokens)))

@dataclass
class TagBundle:
    title_tokens: list[str] = field(default_factory=list)
    winery: str | None = None
    color: str | None = None
    category: str | None = None
    region: str | None = None
    grape: str | None = None
    year: int | None = None
    alcohol: float | None = None

class TagScorer:
    def __init__(self):
        pass

    def extract_bundle(self, ocr_full_text: str) -> TagBundle:
        """Извлекает TagBundle из полного текста OCR."""
        bundle = TagBundle()
        text_lower = ocr_full_text.lower()
        
        bundle.title_tokens = [w for w in ocr_full_text.split() if len(w) > 2]
        
        match = re.search(r'\b(19|20)\d{2}\b', ocr_full_text)
        if match:
            bundle.year = int(match.group())
            
        if "красное" in text_lower or "red" in text_lower: bundle.color = "Красное"
        elif "белое" in text_lower or "white" in text_lower: bundle.color = "Белое"
        elif "розовое" in text_lower or "rose" in text_lower: bundle.color = "Розовое"
        
        if "сухое" in text_lower: bundle.category = "Сухое"
        elif "полусухое" in text_lower: bundle.category = "Полусухое"
        elif "полусладкое" in text_lower: bundle.category = "Полусладкое"
        elif "сладкое" in text_lower: bundle.category = "Сладкое"
        elif "брют" in text_lower or "brut" in text_lower: bundle.category = "Брют"
        
        return bundle

    def score_candidate(self, bundle: TagBundle, product) -> float:
        score = 0.0

        if bundle.title_tokens:
            ratio_title = fuzzy_token_overlap(bundle.title_tokens, product.title or "")
            if ratio_title > 0.6:
                score += 2.5 * ratio_title
                
            # SLUG MATCHING (Latin/translit fallback to guarantee 100% confidence)
            if product.slug:
                slug_target = product.slug.replace('-', ' ').lower()
                ratio_slug = fuzzy_token_overlap(bundle.title_tokens, slug_target)
                if ratio_slug >= 0.4:
                    score += 5.0  # Boost to 100% confidence

        if bundle.winery and product.manufacturer and fuzzy_match(bundle.winery, product.manufacturer) > 0.75:
            score += 3.0
            
        if bundle.color and product.color and normalize(bundle.color) == normalize(product.color):
            score += 1.5
            
        if bundle.region and product.region and fuzzy_match(bundle.region, product.region) > 0.7:
            score += 1.5
            
        if bundle.grape and product.grape and fuzzy_match(bundle.grape, product.grape) > 0.7:
            score += 1.5
            
        if bundle.category and product.category and normalize(bundle.category) == normalize(product.category):
            score += 1.0
            
        if bundle.year and product.description and str(bundle.year) in product.description:
            score += 0.5

        return score
