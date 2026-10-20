import re
import difflib
from typing import List, Dict, Tuple, Optional, Any

class WineVocabularyCorrector:
    """
    Domain-Specific Wine Vocabulary & Fuzzy Post-OCR Corrector for VINA.
    Automatically corrects:
    1. OCR visual glyph splits & confusables (II->П, JI->Л, IIb->ЛЬ, MJI->ИЛ, etc.)
    2. Latin/Cyrillic cross-alphabet ligature confusions in Russian words (TEMIIPAHMJIbO -> ТЕМПРАНИЛЬО)
    3. Truncated first letters / edge contrast drops (РАСНОЕ -> КРАСНОЕ, ОВИНЬОН -> СОВИНЬОН)
    4. Domain-specific fuzzy matching against canonical grape varieties, wine categories, regions, and brands.
    """
    def __init__(self):
        # 1. Canonical Wine Vocabulary (Russian + Latin)
        self.grape_varieties = [
            # Russian
            "ТЕМПРАНИЛЬО", "КАБЕРНЕ СОВИНЬОН", "КАБЕРНЕ", "СОВИНЬОН", "МЕРЛО", 
            "САПЕРАВИ", "ШАРДОНЕ", "РИСЛИНГ", "ПИНО НУАР", "ПИНО ГРИДЖИО", "ПИНО БЛАН", 
            "СИРА", "ШИРАЗ", "СОВИНЬОН БЛАН", "МУСКАТ", "РКАЦИТЕЛИ", "АЙРЕН", "МАЛЬБЕК", 
            "ЗИНФАНДЕЛЬ", "ГЕВЮРЦТРАМИНЕР", "ВИОНЬЕ", "ТРЕББЬЯНО", "САНДЖОВЕЗЕ", "НЕББИОЛО", 
            "КАРМЕНЕР", "ВЕРМЕНТИНО", "ЦИНАНДАЛИ", "КИСИ", "ХВАНЧКАРА", "КИНДЗМАРАУЛИ", 
            "МУКУЗАНИ", "АЛИГОТЕ", "ГРЕНАШ", "КРАСНОСТОП", "ЦИМЛЯНСКИЙ", "АВТОХТОН", "СИБИРЬКОВЫЙ",
            # Latin
            "TEMPRANILLO", "CABERNET SAUVIGNON", "CABERNET", "SAUVIGNON", "MERLOT", 
            "SAPERAVI", "CHARDONNAY", "RIESLING", "PINOT NOIR", "PINOT GRIGIO", "PINOT BLANC", 
            "SYRAH", "SHIRAZ", "SAUVIGNON BLANC", "MUSCAT", "RKATSITELI", "AIREN", "MALBEC", 
            "ZINFANDEL", "GEWURZTRAMINER", "VIOGNIER", "TREBBIANO", "SANGIOVESE", "NEBBIOLO", 
            "CARMENERE", "VERMENTINO", "GRENACHE", "CHENIN BLANC", "PRIMITIVO", "GARNACHA"
        ]
        
        self.wine_categories = [
            # Russian
            "КРАСНОЕ СУХОЕ ВИНО", "БЕЛОЕ СУХОЕ ВИНО", "РОЗОВОЕ СУХОЕ ВИНО",
            "КРАСНОЕ ПОЛУСУХОЕ ВИНО", "БЕЛОЕ ПОЛУСУХОЕ ВИНО", "РОЗОВОЕ ПОЛУСУХОЕ ВИНО",
            "КРАСНОЕ ПОЛУСЛАДКОЕ ВИНО", "БЕЛОЕ ПОЛУСЛАДКОЕ ВИНО", "РОЗОВОЕ ПОЛУСЛАДКОЕ ВИНО",
            "КРАСНОЕ СЛАДКОЕ ВИНО", "БЕЛОЕ СЛАДКОЕ ВИНО",
            "КРАСНОЕ ВИНО", "БЕЛОЕ ВИНО", "РОЗОВОЕ ВИНО",
            "КРАСНОЕ СУХОЕ", "БЕЛОЕ СУХОЕ", "РОЗОВОЕ СУХОЕ",
            "КРАСНОЕ ПОЛУСУХОЕ", "БЕЛОЕ ПОЛУСУХОЕ", "РОЗОВОЕ ПОЛУСУХОЕ",
            "КРАСНОЕ ПОЛУСЛАДКОЕ", "БЕЛОЕ ПОЛУСЛАДКОЕ", "РОЗОВОЕ ПОЛУСЛАДКОЕ",
            "КРАСНОЕ", "БЕЛОЕ", "РОЗОВОЕ", "СУХОЕ", "ПОЛУСУХОЕ", "ПОЛУСЛАДКОЕ", "СЛАДКОЕ",
            "ВИНО", "ВИНОДЕЛЬНЯ", "ВЫДЕРЖАННОЕ", "РЕЗЕРВ", "АВТОРСКОЕ", "МАРОЧНОЕ",
            "ИГРИСТОЕ ВИНО", "ИГРИСТОЕ", "БРЮТ", "ЭКСТРА БРЮТ",
            "ПРОИЗВЕДЕНО И РАЗЛИТО", "ЗАЩИЩЕННОГО ГЕОГРАФИЧЕСКОГО УКАЗАНИЯ",
            "ОБЪЕМ", "СПИРТ", "АЛКОГОЛЬ", "ГОСТ", "РОССИЯ", "ГРУЗИЯ",
            # Latin
            "RED DRY WINE", "WHITE DRY WINE", "ROSE DRY WINE",
            "RED SEMI-DRY WINE", "WHITE SEMI-DRY WINE", "ROSE SEMI-DRY WINE",
            "RED SEMI-SWEET WINE", "WHITE SEMI-SWEET WINE", "ROSE SEMI-SWEET WINE",
            "RED WINE", "WHITE WINE", "ROSE WINE",
            "DRY", "SEMI-DRY", "SEMI-SWEET", "SWEET", "MEDIUM SWEET", "MEDIUM DRY",
            "SPARKLING WINE", "SPARKLING", "BRUT", "EXTRA BRUT",
            "RESERVA", "GRAN RESERVA", "CRIANZA", "VINTAGE", "ESTATE BOTTLED", "WINERY",
            "PRODUCT OF", "PRODUCED AND BOTTLED", "APPELLATION", "DENOMINACION DE ORIGEN"
        ]
        
        self.regions_and_brands = [
            # Russian
            "КРЫМ", "КУБАНЬ", "СЕВАСТОПОЛЬ", "ДОЛИНА ДОНА", "ДАГЕСТАН", "КАХЕТИЯ",
            "АЛМА ВЭЛЛИ", "ШАТО ДЕ ТАЛЮ", "МАССАНДРА", "ФАНАГОРИЯ", "АБРАУ ДЮРСО", "ИНКЕРМАН",
            "ГАЙ КОДЗОР", "ЛЕФКАДИЯ", "СИКОРЫ", "УСАДЬБА ДИВНОМОРСКОЕ", "МЫСХАКО",
            "МОНАСТЫРСКАЯ ИЗБА", "МОНАСТЫРСКАЯ", "ИЗБА", "БАРАКИАНИ",
            "КРЕПОСТЬ САРКЕЛ", "КРЕПОСТЬ", "САРКЕЛ", "ЦИМЛЯНСКОЕ", "ЦИМЛЯНСКИЙ ЧЕРНЫЙ", "ЦИМЛЯНСКИЙ", "АУТЕНТИЧНЫЙ", "ЧЕРНЫЙ",
            "КАНОНИЧЕСКИЕ ТРАДИЦИИ", "КАНОНИЧЕСКИЕ", "ТРАДИЦИИ",
            # Latin
            "ALMA VALLEY", "CHATEAU DE TALU", "MASSANDRA", "FANAGORIA", "ABRAU DURSO", "INKERMAN",
            "GAI KODZOR", "LEFKADIA", "SIKORY", "USADBA DIVNOMORSKOE", "MYSHAKO",
            "KREPOST SARKEL", "SARKEL", "TSIMLYANSKOE",
            "RIOJA", "BORDEAUX", "TUSCANY", "CHIANTI", "BAROLO", "PROSECCO", "CHAMPAGNE",
            "CASTILLO DE LIRIA", "MICHEL SCHNEIDER", "BARAKIANI", "AMBASSADOR", "CASA MOSAICO",
            "FRANCE", "ITALY", "GEORGIA", "SOUTH AFRICA", "GERMANY"
        ]
        
        # Build unified token lexicon
        self.all_phrases = sorted(
            list(set(self.grape_varieties + self.wine_categories + self.regions_and_brands)),
            key=lambda x: len(x),
            reverse=True
        )
        
        self.all_tokens = set()
        for phrase in self.all_phrases:
            for token in phrase.split():
                if len(token) >= 3:
                    self.all_tokens.add(token.upper())

    def update_vocabulary(self, words: List[str]):
        """Dynamically add words (e.g. from DB) to the lexicon."""
        new_phrases = []
        for w in words:
            if w and isinstance(w, str):
                cleaned = w.strip().upper()
                if cleaned and cleaned not in self.all_phrases:
                    new_phrases.append(cleaned)
                    
        if new_phrases:
            self.all_phrases.extend(new_phrases)
            self.all_phrases.sort(key=lambda x: len(x), reverse=True)
            for phrase in new_phrases:
                for token in phrase.split():
                    if len(token) >= 3:
                        self.all_tokens.add(token)

        # Exact and regex glyph rules
        self.glyph_substitutions = [
            (r"\b[0OoОо][5БбBbВв][bьъЬЪBв][EeЕе][MmМм]\b", "ОБЪЕМ"),
            (r"\b(BNHO|BHHO|BИHO|ВHHO)\s+(BHHOIPAAHOEHATYPAISHOE|BHHOIPAAHOE|BИHOГPAДHOE)\b", "ВИНО ВИНОГРАДНОЕ НАТУРАЛЬНОЕ"),
            (r"\bBHHOIPAAHOEHATYPAISHOE\b", "ВИНОГРАДНОЕ НАТУРАЛЬНОЕ"),
            (r"\b(BHHOIPAAHOE|BИHOГPAДHOE)\b", "ВИНОГРАДНОЕ"),
            (r"\b(HATYPAISHOE|HATYPAЛЬHOE|HATYPAЛЬHO)\b", "НАТУРАЛЬНОЕ"),
            (r"\b(BNHO|BHHO|BИHO|ВHHO)\b", "ВИНО"),
            (r"\b(HUMAAHCKOE|HIUMAAHCKOE|HNMAAHCKOE|HNMA9HCKOE|HNLXAHCKOE|HHLXAHCKOE|HHLXAHCROE|HLMARHCKOE|LHARHCKOE|LIUMIAHCKOE|ЦИДЛЯНСКОЕ|ЦНМЛЯНСКОЕ)\b", "ЦИМЛЯНСКОЕ"),
            (r"\b(HUMAAHCK[A-ZА-Я0-9_]*|HIUMAAHCK[A-ZА-Я0-9_]*|HNMAAHCK[A-ZА-Я0-9_]*|LIMMIAHCK[A-ZА-Я0-9_]*|LIUMIAHCKIN|LIUMIAHCKIY|ЦИДЛЯНСКИЙ)\b", "ЦИМЛЯНСКИЙ"),
            (r"\b(KPEIIOCTD|KPEIIOCTb|KPEIOCTb)\b", "КРЕПОСТЬ"),
            (r"\b(CAPKEA|CAPKEI|CAPKEЛ)\b", "САРКЕЛ"),
            (r"\b(AyTEHT[A-ZА-Я0-9_]*|AYTEHT[A-ZА-Я0-9_]*|АУТЕНТИЧНЫИ)\b", "АУТЕНТИЧНЫЙ"),
            (r"\b(YEPHbIY|YEPHbIK|ЧЕРНЫИ)\b", "ЧЕРНЫЙ"),
            (r"\b(GHHOHFYECHIE|GHHOHF[A-Z]*|KAHOH[A-ZА-Я0-9_]*|КАНОН[А-Я0-9_]*)\b", "КАНОНИЧЕСКИЕ"),
            (r"\b(TPAANINN|TPAL[A-ZА-Я0-9_]*|ТРАДИЦ[А-Я0-9_]*)\b", "ТРАДИЦИИ"),
            (r"\b(MEPIO|MEPI0|MEPLO)\b", "МЕРЛО"),
            (r"\b(CYXOE|Cyxoe|CYX0E)\b", "СУХОЕ"),
            (r"\b(KPACHOE|Kpachoe|KPACN0E)\b", "КРАСНОЕ"),
            (r"\b(ypoenypatro|yrse\s*красное|yr[a-z]+\s*красное|Сухекрасное|Cyxoeкрасное)\b", "СУХОЕ КРАСНОЕ"),
            (r"\b(M36A|N36A|И36A|И3БА|ИЗ6А|136А|ИЗ6A)\b", "ИЗБА"),
            (r"\b(МОНАСТЫРСКАЯ|МОНАСТЫРСКОЕ|МОНАСТЫРСКИЙ)\s+(M36A|N36A|И36A|И3БА|ИЗ6А|136А|ИЗ6A|ИЗБА)\b", "МОНАСТЫРСКАЯ ИЗБА"),
            (r"\bTEMIIPAH[A-ZА-Я0-9_]+", "ТЕМПРАНИЛЬО"),
            (r"\bTEMPRAN[A-ZА-Я0-9_]+", "TEMPRANILLO"),
            (r"\bТЕМПАНИЛЬО\b", "ТЕМПРАНИЛЬО"),
            (r"\bТЕМПРАНИIЛЬО\b", "ТЕМПРАНИЛЬО"),
            (r"\bТЕМРРАНИЛЬ\b", "ТЕМПРАНИЛЬО"),
            (r"\bРАСНОЕ\b", "КРАСНОЕ"),
            (r"\bРАСНЫЙ\b", "КРАСНЫЙ"),
            (r"\bРАСНАЯ\b", "КРАСНАЯ"),
            (r"\bАБЕРНЕ\b", "КАБЕРНЕ"),
            (r"\bОВИНЬОН\b", "СОВИНЬОН"),
            (r"\bАРДОНЕ\b", "ШАРДОНЕ"),
            (r"\bАПЕРАВИ\b", "САПЕРАВИ"),
            (r"\bИСЛИНГ\b", "РИСЛИНГ"),
            (r"\bKPbIM[A-ZА-Я0-9_]*", "КРЫМ РОССИЯ"),
            (r"\bKPbIM\b", "КРЫМ"),
            (r"\bIPOCCNA\b", "РОССИЯ"),
            (r"\b(AlrVilley|ALMAVALLEY|ALMAYALLEY|ALMA\s*VALLEY|ALMA\s*YALLEY)\b", "ALMA VALLEY"),
            (r"\bCABERNET\s+SAUVIGNO[Kk]\b", "CABERNET SAUVIGNON"),
            (r"\b(2-12|2-22|202|2-02|2_22|202_|2\s*0\s*2)\b(?=\s+([А-ЯA-Z]|ЦИМЛЯН|МОНАСТЫР|КАБЕРНЕ|МЕРЛО|СУХОЕ|КРЕПОСТЬ|ВИНО))", "2022"),
            (r"\b(202\s+2|2\s+0\s+2\s+2)\b", "2022"),
            (r"\b(2-12|2-22|2_22|2-02)\b", "2022"),
            (r"\b202\b", "2022"),
        ]

    def _normalize_optical_confusables(self, token: str) -> str:
        """Transliterates visual lookalike Latin serif letters into Cyrillic for Russian matching."""
        s = token
        # Common OCR splits and composite ligatures in serif Cyrillic:
        s = s.replace("MJI", "ИЛ").replace("JI", "Л").replace("IIb", "ЛЬ").replace("II", "П")
        s = s.replace("IЬ", "ЛЬ").replace("IЛЬ", "ЛЬ").replace("1Ь", "ЛЬ")
        s = s.replace("IPAA", "ГРАД").replace("IP", "ГР").replace("AA", "АД").replace("IS", "ЛЬ")
        s = s.replace("HUM", "ЦИМ").replace("HIUM", "ЦИМ").replace("HNMA", "ЦИМЛ").replace("HNL", "ЦИМ")
        
        # Homoglyphs (Latin -> Cyrillic lookalikes)
        tr = str.maketrans({
            'A': 'А', 'B': 'В', 'E': 'Е', 'K': 'К', 'M': 'М',
            'H': 'Н', 'O': 'О', 'P': 'Р', 'C': 'С', 'T': 'Т',
            'Y': 'У', 'X': 'Х', 'b': 'Ь', 'N': 'И', 'I': 'Г', '0': 'О', 'U': 'И'
        })
        return s.translate(tr)

    def correct_text(self, text: str) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Corrects OCR text using domain wine lexicon, phrase matching, and optical rules.
        Returns: (corrected_text, list_of_corrections)
        """
        if not text or not text.strip():
            return text, []

        corrections: List[Dict[str, Any]] = []
        cur_text = text

        # 0. Clean isolated non-alphanumeric / Asian noise artifacts (e.g. 色, ~, |)
        cur_text = re.sub(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", "", cur_text)
        cur_text = re.sub(r"\s+", " ", cur_text).strip()

        # 1. Apply Rule-based Optical Substitutions
        for pattern, repl in self.glyph_substitutions:
            if re.search(pattern, cur_text, flags=re.IGNORECASE):
                before = cur_text
                cur_text = re.sub(pattern, repl, cur_text, flags=re.IGNORECASE)
                if before != cur_text:
                    corrections.append({"before": before, "after": cur_text, "rule": f"{pattern} -> {repl}"})

        # 2. Word-Level Lexicon Fuzzy Matching
        words = cur_text.split()
        corrected_words = []
        for word in words:
            # Strip punctuation for matching
            clean_w = re.sub(r"[^\w\d]", "", word).upper()
            
            # Skip numbers and very short tokens
            if len(clean_w) < 3 or clean_w.isdigit():
                corrected_words.append(word)
                continue
                
            # If word is already an exact match in lexicon, keep as is!
            if clean_w in self.all_tokens:
                corrected_words.append(word)
                continue
                
            # Try normalized optical variant
            norm_w = self._normalize_optical_confusables(clean_w)
            if norm_w in self.all_tokens:
                corrected_words.append(norm_w)
                corrections.append({"before": word, "after": norm_w, "rule": "optical_normalization"})
                continue
                
            # Find closest match in wine lexicon
            best_match = None
            best_sim = 0.0
            is_w_cyr = any('А' <= c <= 'Я' or c == 'Ё' for c in norm_w)
            
            for lex_word in self.all_tokens:
                # Do not mix Cyrillic with Latin
                is_lex_cyr = any('А' <= c <= 'Я' or c == 'Ё' for c in lex_word)
                if is_w_cyr != is_lex_cyr:
                    continue
                    
                sim = difflib.SequenceMatcher(None, norm_w, lex_word).ratio()
                if sim > best_sim:
                    best_sim = sim
                    best_match = lex_word
                    
            # Auto-correct threshold
            thresh = 0.80 if len(norm_w) <= 5 else 0.70
            if best_sim >= thresh and best_match is not None:
                # Preserve original casing
                if word.isupper():
                    rep = best_match
                elif word.istitle():
                    rep = best_match.capitalize()
                else:
                    rep = best_match.lower()
                    
                # Re-attach punctuation if any
                if word and not word[-1].isalnum():
                    rep += word[-1]
                if word and not word[0].isalnum():
                    rep = word[0] + rep
                    
                corrected_words.append(rep)
                corrections.append({"before": word, "after": rep, "similarity": round(best_sim, 2)})
            else:
                corrected_words.append(word)

        final_text = " ".join(corrected_words)
        return final_text, corrections
