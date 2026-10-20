"""
Stage 5: Character Recognition & Code Decoding
- High-Fidelity Multi-lingual OCR Engine (RapidOCR PP-OCRv4 + EasyOCR Russian Refinement)
- CLAHE + Lanczos-4 Super-Resolution Text Contrast Enhancement
- Graphical code decoding (Barcodes, QR Codes via OpenCV & pyzbar)
- Extraction of structured text blocks, coordinates, confidence scores
- Visual bounding box annotations
"""

import cv2
import numpy as np
import torch

class Stage5OCRDecoder:
    def __init__(self, languages=['ru', 'en'], use_gpu=True):
        self.use_gpu = use_gpu and torch.cuda.is_available()
        self.languages = languages
        self.rapid_ocr = None
        self.easy_ru = None
        self.easy_en = None
        self._init_engines()
        
        # OpenCV QR & Barcode detectors
        self.qr_detector = cv2.QRCodeDetector()
        try:
            self.barcode_detector = cv2.barcode.BarcodeDetector()
        except Exception:
            self.barcode_detector = None

        # 3. Domain-Specific Wine Lexicon & Post-OCR Corrector
        from .wine_lexicon_corrector import WineVocabularyCorrector
        self.lexicon_corrector = WineVocabularyCorrector()

    def _init_engines(self):
        # 1. Initialize RapidOCR (PP-OCRv4 ONNX) with generous unclip ratio to capture outer digits (e.g. 2022)
        try:
            from rapidocr_onnxruntime import RapidOCR
            self.rapid_ocr = RapidOCR(det_unclip_ratio=1.9, det_db_box_thresh=0.38)
            print("[Stage5] RapidOCR (PP-OCRv4, unclip=1.9) ready.")
        except Exception as e:
            print(f"[Stage5] RapidOCR init error: {e}")
            self.rapid_ocr = None

        # 2. Initialize EasyOCR
        try:
            import easyocr
            self.easy_ru = easyocr.Reader(['ru'], gpu=self.use_gpu)
            self.easy_en = easyocr.Reader(['en'], gpu=self.use_gpu)
            print("[Stage5] EasyOCR (ru & en targeted readers) ready.")
        except Exception as e:
            print(f"[Stage5] EasyOCR init error: {e}")
            self.easy_ru = None
            self.easy_en = None

    def extract_text(self, img_bgr: np.ndarray) -> list[dict]:
        """
        Extracts structured text blocks with coordinates, confidence scores, and content.
        Uses RapidOCR for multilingual base and EasyOCR for targeted Cyrillic enhancement.
        """
        if img_bgr is None or img_bgr.size == 0:
            return []

        h, w = img_bgr.shape[:2]
        
        # 1. Super-Resolution Scaling & CLAHE Contrast Boosting + Unsharp Mask
        scale = 1.5 if max(h, w) < 1200 else 1.0
        if scale > 1.0:
            img_proc = cv2.resize(img_bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LANCZOS4)
        else:
            img_proc = img_bgr.copy()

        # CLAHE Contrast Boost on Luminance
        lab = cv2.cvtColor(img_proc, cv2.COLOR_BGR2LAB)
        l_chan, a_chan, b_chan = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
        l_enh = clahe.apply(l_chan)
        img_enh = cv2.cvtColor(cv2.merge([l_enh, a_chan, b_chan]), cv2.COLOR_LAB2BGR)

        # Unsharp Mask Sharpening for embossed gold/foil digits and serif lettering
        gaussian = cv2.GaussianBlur(img_enh, (0, 0), 2.0)
        img_enh = cv2.addWeighted(img_enh, 1.4, gaussian, -0.4, 0)

        text_blocks = []

        # 2. Primary High-Precision Multilingual Extraction via RapidOCR
        if self.rapid_ocr is not None:
            try:
                rapid_results, _ = self.rapid_ocr(img_enh)
                if rapid_results:
                    for bbox, text, conf in rapid_results:
                        pts = np.array(bbox, dtype=np.float64) / scale
                        x_min, y_min = np.min(pts, axis=0)
                        x_max, y_max = np.max(pts, axis=0)
                        clean_text = text.strip()
                        if clean_text and float(conf) > 0.35:
                            text_blocks.append({
                                "text": clean_text,
                                "confidence": round(float(conf), 3),
                                "bbox": [[int(p[0]), int(p[1])] for p in pts],
                                "rect": {"x": int(x_min), "y": int(y_min), "w": int(x_max - x_min), "h": int(y_max - y_min)}
                            })
            except Exception as e:
                print(f"[Stage5] RapidOCR reading error: {e}")


        # 3. Targeted Cyrillic Augmentation via EasyOCR (Consensus Mode)
        # We always run EasyOCR and merge results if it finds confident Cyrillic that RapidOCR missed or hallucinated as Latin.
        if self.easy_ru is not None:
            try:
                def get_iou(rect1, rect2):
                    x_left = max(rect1["x"], rect2["x"])
                    y_top = max(rect1["y"], rect2["y"])
                    x_right = min(rect1["x"] + rect1["w"], rect2["x"] + rect2["w"])
                    y_bottom = min(rect1["y"] + rect1["h"], rect2["y"] + rect2["h"])
                    if x_right < x_left or y_bottom < y_top:
                        return 0.0
                    intersection_area = (x_right - x_left) * (y_bottom - y_top)
                    rect1_area = rect1["w"] * rect1["h"]
                    rect2_area = rect2["w"] * rect2["h"]
                    iou = intersection_area / float(rect1_area + rect2_area - intersection_area)
                    return iou

                cyrillic_chars = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюяАБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")
                latin_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
                
                easy_ru_results = self.easy_ru.readtext(cv2.cvtColor(img_enh, cv2.COLOR_BGR2RGB))
                
                for bbox, text, conf in easy_ru_results:
                    clean_text = text.strip()
                    if not clean_text or float(conf) < 0.25:
                        continue
                        
                    pts = np.array(bbox, dtype=np.float64) / scale
                    x_min, y_min = np.min(pts, axis=0)
                    x_max, y_max = np.max(pts, axis=0)
                    e_rect = {"x": int(x_min), "y": int(y_min), "w": int(x_max - x_min), "h": int(y_max - y_min)}
                    
                    has_cyr = sum(c in cyrillic_chars for c in clean_text) >= 2
                    
                    # Find if it overlaps with any RapidOCR block
                    matched_idx = -1
                    max_iou = 0
                    for i, r_block in enumerate(text_blocks):
                        iou = get_iou(e_rect, r_block["rect"])
                        if iou > max_iou:
                            max_iou = iou
                            matched_idx = i
                            
                    if max_iou > 0.3:
                        # Overlap exists. Should EasyOCR overwrite RapidOCR?
                        r_text = str(text_blocks[matched_idx].get("text", ""))
                        conf_val = text_blocks[matched_idx].get("confidence", 0.0)
                        r_conf = float(conf_val) if isinstance(conf_val, (int, float, str)) else 0.0
                        
                        r_latin_cnt = sum(c in latin_chars for c in r_text)
                        r_cyr_cnt = sum(c in cyrillic_chars for c in r_text)
                        
                        # If RapidOCR found mostly Latin/gibberish, and EasyOCR found Cyrillic with decent confidence
                        if has_cyr and r_latin_cnt > r_cyr_cnt and float(conf) > 0.35:
                            text_blocks[matched_idx]["text"] = clean_text
                            text_blocks[matched_idx]["confidence"] = round(float(conf), 3)
                            text_blocks[matched_idx]["bbox"] = [[int(p[0]), int(p[1])] for p in pts]
                            text_blocks[matched_idx]["rect"] = e_rect
                        # Or if EasyOCR is just much more confident
                        elif has_cyr and float(conf) > r_conf + 0.2:
                            text_blocks[matched_idx]["text"] = clean_text
                            text_blocks[matched_idx]["confidence"] = round(float(conf), 3)
                            text_blocks[matched_idx]["bbox"] = [[int(p[0]), int(p[1])] for p in pts]
                            text_blocks[matched_idx]["rect"] = e_rect
                    else:
                        # No overlap, it's a new block (e.g. RapidOCR missed it completely)
                        if has_cyr and float(conf) > 0.45:
                            text_blocks.append({
                                "text": clean_text,
                                "confidence": round(float(conf), 3),
                                "bbox": [[int(p[0]), int(p[1])] for p in pts],
                                "rect": e_rect
                            })
                            
            except Exception as e:
                print(f"[Stage5] EasyOCR ru consensus error: {e}")
        # Remove inner boxes to avoid duplicate text (e.g. "Adega de" inside "Adega de Azueira")
        def get_intersection_area(rect1, rect2):
            x_left = max(rect1["x"], rect2["x"])
            y_top = max(rect1["y"], rect2["y"])
            x_right = min(rect1["x"] + rect1["w"], rect2["x"] + rect2["w"])
            y_bottom = min(rect1["y"] + rect1["h"], rect2["y"] + rect2["h"])
            if x_right < x_left or y_bottom < y_top:
                return 0.0
            return (x_right - x_left) * (y_bottom - y_top)

        filtered_blocks = []
        for i, tb1 in enumerate(text_blocks):
            is_outer = False
            rect1 = tb1.get("rect", {})
            a1 = rect1.get("w", 0) * rect1.get("h", 0) if isinstance(rect1, dict) else 0
            if a1 == 0:
                filtered_blocks.append(tb1)
                continue
                
            for j, tb2 in enumerate(text_blocks):
                if i == j: continue
                rect2 = tb2.get("rect", {})
                a2 = rect2.get("w", 0) * rect2.get("h", 0) if isinstance(rect2, dict) else 0
                if a2 == 0: continue
                
                # If tb1 is larger than tb2, check if tb1 encloses tb2
                if a1 > a2:
                    inter_area = get_intersection_area(rect1, rect2)
                    # If tb2 (the smaller box) is >= 40% inside tb1 (the larger box)
                    overlap_ratio = inter_area / float(a2 + 1e-5)
                    print(f"[Stage5] Box '{tb1.get('text')}' (a={a1}) vs '{tb2.get('text')}' (a={a2}) -> Overlap: {overlap_ratio:.2f}", flush=True)
                    if overlap_ratio > 0.4:
                        print(f"[Stage5] Deleting outer box '{tb1.get('text')}' because it encloses '{tb2.get('text')}'", flush=True)
                        is_outer = True
                        break
            if not is_outer:
                filtered_blocks.append(tb1)
        text_blocks = filtered_blocks

        # Flag uninformative stopwords (e.g. "alc", "vol", "%", numbers)
        stop_words = {"алк", "alc", "vol", "ml", "cl", "l", "л", "об", "alk", "alkohol", "alcohol", "мм", "mm", "cm", "см"}
        import string
        for tb in text_blocks:
            clean_t = str(tb.get("text", "")).lower()
            # Remove punctuation
            for p in string.punctuation:
                clean_t = clean_t.replace(p, "")
            
            words = [w for w in clean_t.split() if w]
            
            is_stop = True
            for w in words:
                if w not in stop_words and not w.isdigit():
                    is_stop = False
                    break
            
            tb["is_stopword"] = is_stop

        # Sort top to bottom, then left to right
        def get_sort_key(b):
            rect = b.get("rect", {})
            if isinstance(rect, dict):
                return (rect.get("y", 0), rect.get("x", 0))
            return (0, 0)
            
        text_blocks.sort(key=get_sort_key)
        return text_blocks

    def decode_graphical_codes(self, img_bgr: np.ndarray) -> list[dict]:
        """
        Decodes Barcodes and QR Codes from the rectified flat image.
        """
        codes = []
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)

        # 1. OpenCV QRCodeDetector
        try:
            val, points, _ = self.qr_detector.detectAndDecode(gray)
            if val and points is not None:
                pts = points[0].astype(np.int32).tolist()
                codes.append({
                    "type": "QR_CODE",
                    "data": val,
                    "polygon": pts
                })
        except Exception as e:
            print(f"[Stage5] QR decode notice: {e}")

        # 2. OpenCV Barcode detector
        if self.barcode_detector is not None:
            try:
                ret = self.barcode_detector.detectAndDecode(gray)
                if ret and len(ret) >= 2 and ret[0]:
                    decoded_info = ret[1]
                    for info in decoded_info:
                        if info:
                            codes.append({
                                "type": "BARCODE",
                                "data": str(info),
                                "polygon": []
                            })
            except Exception as e:
                print(f"[Stage5] Barcode decode notice: {e}")

        # 3. Optional pyzbar fallback
        try:
            from pyzbar.pyzbar import decode as zbar_decode
            z_results = zbar_decode(gray)
            for z in z_results:
                data_str = z.data.decode('utf-8', errors='ignore')
                polygon = [[p.x, p.y] for p in z.polygon]
                if not any(c["data"] == data_str for c in codes):
                    codes.append({
                        "type": z.type,
                        "data": data_str,
                        "polygon": polygon
                    })
        except Exception:
            pass

        return codes

    def draw_ocr_annotations(self, img_bgr: np.ndarray, text_blocks: list[dict], codes: list[dict]) -> np.ndarray:
        """
        Draws glowing Apple-style bounding boxes and labels for recognized text and barcodes.
        """
        annotated = img_bgr.copy()
        
        # Draw text blocks
        for tb in text_blocks:
            pts = np.array(tb["bbox"], dtype=np.int32)
            color = (0, 140, 255) if tb.get("is_stopword") else (0, 220, 100) # Orange for stopwords, Green for normal
            
            cv2.polylines(annotated, [pts], isClosed=True, color=color, thickness=2, lineType=cv2.LINE_AA)
            
            # Subtle semi-transparent fill
            overlay = annotated.copy()
            cv2.fillPoly(overlay, [pts], color=color)
            cv2.addWeighted(overlay, 0.15, annotated, 0.85, 0, annotated)

        # Draw graphical codes
        for c in codes:
            pts = np.array(c["polygon"], dtype=np.int32)
            cv2.polylines(annotated, [pts], isClosed=True, color=(0, 240, 255), thickness=3, lineType=cv2.LINE_AA)

        return annotated

    def process(self, dewarped_bgr: np.ndarray) -> dict:
        """Full Stage 5 execution with domain wine dictionary auto-correction"""
        text_blocks = self.extract_text(dewarped_bgr)
        codes = self.decode_graphical_codes(dewarped_bgr)
        
        # Apply Domain Wine Lexicon Auto-Correction to every block
        all_corrections = []
        for tb in text_blocks:
            raw_t = tb["text"]
            corr_t, fixes = self.lexicon_corrector.correct_text(raw_t)
            if corr_t != raw_t:
                tb["raw_ocr_text"] = raw_t
                tb["text"] = corr_t
                tb["confidence"] = max(tb["confidence"], 0.95)  # Boost confidence on lexicon match
                all_corrections.extend(fixes)

        annotated_bgr = self.draw_ocr_annotations(dewarped_bgr, text_blocks, codes)
        full_text = " ".join([b["text"] for b in text_blocks])

        # Global phrase-level pass on full text
        full_text_corr, global_fixes = self.lexicon_corrector.correct_text(full_text)
        if full_text_corr != full_text:
            full_text = full_text_corr
            all_corrections.extend(global_fixes)

        return {
            "text_blocks": text_blocks,
            "codes": codes,
            "full_text": full_text,
            "annotated_bgr": annotated_bgr,
            "num_words": sum(len(b["text"].split()) for b in text_blocks if not b.get("is_stopword")),
            "lexicon_corrections": all_corrections
        }

