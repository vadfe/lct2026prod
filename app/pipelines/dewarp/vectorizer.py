"""
Vectorizer Module: Direct Perimeter & Monotone Semi-Ellipsoid Vectorization of Binary Mask
- Step 1: Input mask refined via Solution 3 (Photometric Paper Gate).
- Step 2: Lateral tangent lines (side generators) intersect top and bottom horizontal curves to define 4 exact corner vertices (P_TL, P_TR, P_BL, P_BR).
- Step 3: Connect corner vertices with true semi-ellipses fitted to the source mask profiles using the Monotone Single-Curvature Rule with Edge Priority (no S-curves, no parasitic middle humps).
"""

import cv2
import numpy as np
from dataclasses import dataclass
from typing import Tuple, List, Optional
from enum import Enum

class LabelShape(Enum):
    CYLINDER = "cylinder"
    RECTANGLE = "rectangle"

@dataclass
class VectorMask:
    shape_type: LabelShape
    bbox: Tuple[int, int, int, int]
    P_TL: np.ndarray
    P_TR: np.ndarray
    P_BL: np.ndarray
    P_BR: np.ndarray
    T_curve: np.ndarray
    B_curve: np.ndarray
    L_line: np.ndarray
    R_line: np.ndarray
    polygon: np.ndarray
    left_line: np.ndarray = None
    right_line: np.ndarray = None
    top_curve: np.ndarray = None
    bottom_curve: np.ndarray = None
    text_parabolas: list = None
    raw_T: np.ndarray = None
    raw_B: np.ndarray = None
    raw_L: np.ndarray = None
    raw_R: np.ndarray = None

class MaskVectorizer:
    def __init__(self):
        pass

    def _fit_monotone_semi_ellipse(
        self,
        raw_ys: np.ndarray,
        P_left: np.ndarray,
        P_right: np.ndarray,
        preferred_direction: str = "smile",
        forced_apex_y: Optional[float] = None,
        N_pts: int = 60
    ) -> np.ndarray:
        """
        Fits a canonical semi-ellipse connecting P_left and P_right:
        - Strict monotone single curvature (no double curvature, no central humps).
        - Edge-priority weighting (u <= 0.30 or u >= 0.70).
        """
        N = len(raw_ys)
        u_norm = np.linspace(0.0, 1.0, N)
        y_corner_avg = (P_left[1] + P_right[1]) / 2.0
        
        if forced_apex_y is not None:
            # Directly use the measured apex height relative to corners
            delta_final = forced_apex_y - y_corner_avg
        else:
            # 1. Edge-priority weights: w=4 on corners, w=1 in center
            edge_weights = 1.0 + 3.0 * (2.0 * u_norm - 1.0) ** 2
            tilt_linear = (1.0 - u_norm) * P_left[1] + u_norm * P_right[1]
            raw_delta = raw_ys - tilt_linear
            sin_vals = np.sin(np.pi * u_norm)
            
            # 2. Fit delta using ONLY reliable edge sections (u <= 0.30 or u >= 0.70)
            edge_mask = (u_norm <= 0.30) | (u_norm >= 0.70)
            num = np.sum(edge_weights[edge_mask] * raw_delta[edge_mask] * sin_vals[edge_mask])
            den = np.sum(edge_weights[edge_mask] * (sin_vals[edge_mask] ** 2))
            delta_edge = num / max(den, 1e-6)
            
            if preferred_direction == "smile":
                delta_final = max(delta_edge, 2.0)
            elif preferred_direction == "frown":
                delta_final = min(delta_edge, -2.0)
            else:
                delta_final = delta_edge
                
        # Clamp sagitta to realistic physical bottle bounds (max 15% of label chord width)
        a = max(abs(P_right[0] - P_left[0]) / 2.0, 1.0)
        max_delta = 0.15 * (2.0 * a)
        delta_final = float(np.clip(delta_final, -max_delta, max_delta))
        
        # 3. Construct canonical blended curve (smooth blend between semi-ellipse and circular/parabolic arc)
        theta = np.linspace(0.0, np.pi, N_pts)
        u_norm = theta / np.pi
        x0 = (P_left[0] + P_right[0]) / 2.0
        a = max(abs(P_right[0] - P_left[0]) / 2.0, 1.0)
        
        ell_x = x0 - a * np.cos(theta)
        tilt = (1.0 - u_norm) * P_left[1] + u_norm * P_right[1] - y_corner_avg
        
        # Profile: blend 50% semi-ellipse sin(theta) and 50% parabolic arc 4*u*(1-u)
        profile_ellipse = np.sin(theta)
        profile_arc = 4.0 * u_norm * (1.0 - u_norm)
        profile_blended = 0.5 * profile_ellipse + 0.5 * profile_arc
        
        ell_y = y_corner_avg + delta_final * profile_blended + tilt
        ell_y[0] = P_left[1]
        ell_y[-1] = P_right[1]
        
        return np.column_stack((ell_x, ell_y))

    def _smooth_horizontal_guide(
        self,
        raw_curve: np.ndarray,
        P_left: np.ndarray,
        P_right: np.ndarray,
        N_pts: int = 60
    ) -> np.ndarray:
        """
        Сглаживает верхнюю или нижнюю горизонтальную направляющую, устраняя
        высокочастотную рябь и ступенчатость пикселей маски, сохраняя глобальную физическую дугу цилиндра.
        Использует ортогональный гармонический базис (Fourier Sine Series) с
        жестким закреплением граничных угловых точек P_left и P_right.
        """
        N = len(raw_curve)
        u = np.linspace(0.0, 1.0, N)
        
        # 1. Линейная хорда между углами
        chord_x = (1.0 - u) * P_left[0] + u * P_right[0]
        chord_y = (1.0 - u) * P_left[1] + u * P_right[1]
        
        # 2. Отклонения от хорды
        delta_x = raw_curve[:, 0] - chord_x
        delta_y = raw_curve[:, 1] - chord_y
        
        # 3. Ортогональный гармонический базис Фурье (sin(k*pi*u)), равный строго 0 на границах u=0 и u=1
        S1 = np.sin(np.pi * u)
        S2 = np.sin(2.0 * np.pi * u)
        S3 = np.sin(3.0 * np.pi * u)
        A = np.column_stack((S1, S2, S3))
        
        c_y, _, _, _ = np.linalg.lstsq(A, delta_y, rcond=None)
        c_x, _, _, _ = np.linalg.lstsq(A, delta_x, rcond=None)
        
        y_smooth = chord_y + A @ c_y
        x_smooth = chord_x + A @ c_x
        
        # Жесткое закрепление угловых точек (0 пикселей отклонения)
        y_smooth[0], y_smooth[-1] = P_left[1], P_right[1]
        x_smooth[0], x_smooth[-1] = P_left[0], P_right[0]
        
        return np.column_stack((x_smooth, y_smooth))

    def _fit_straight_lateral_guide(
        self,
        raw_segment: np.ndarray,
        P_top: np.ndarray,
        P_bot: np.ndarray,
        max_dev_px: float = 6.0,
        N_pts: int = 60
    ) -> np.ndarray:
        """
        Строго интерполирует боковую направляющую до идеальной прямой линии
        между точками P_top и P_bot.
        """
        v_vals = np.linspace(0.0, 1.0, N_pts)
        x_gen = (1.0 - v_vals) * P_top[0] + v_vals * P_bot[0]
        y_gen = (1.0 - v_vals) * P_top[1] + v_vals * P_bot[1]
        return np.column_stack((x_gen, y_gen))

    def _get_lowest_point(self, contour: np.ndarray) -> np.ndarray:
        """Returns the (x, y) of the lowest pixel in the contour (max Y)."""
        pts = contour.reshape(-1, 2)
        max_y_idx = np.argmax(pts[:, 1])
        return pts[max_y_idx]

    def _extract_text_parabolas(self, ocr_data: dict, img_w: int, img_h: int, T_curve=None, B_curve=None, image: Optional[np.ndarray]=None) -> list[np.ndarray]:
        parabolas = []
        if not ocr_data or "text_blocks" not in ocr_data or image is None:
            return parabolas
            
        blocks = ocr_data.get("text_blocks", [])
        
        for b in blocks:
            poly = b.get("bbox", [])
            if len(poly) != 4:
                continue
                
            pts = np.array(poly, np.int32)
            x_coords = pts[:, 0]
            y_coords = pts[:, 1]
            w = np.max(x_coords) - np.min(x_coords)
            
            # Process lines spanning > 25% width
            if w < img_w * 0.25:
                continue
                
            margin = 5
            x_min, x_max = max(0, int(np.min(x_coords)) - margin), min(image.shape[1], int(np.max(x_coords)) + margin)
            y_min, y_max = max(0, int(np.min(y_coords)) - margin), min(image.shape[0], int(np.max(y_coords)) + margin)
            
            crop = image[y_min:y_max, x_min:x_max]
            if crop.size == 0:
                continue
                
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
            gray = clahe.apply(gray)
            _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            
            contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            valid_contours = []
            crop_h = y_max - y_min
            crop_area = crop_h * (x_max - x_min)
            
            for c in contours:
                cx, cy, cw, ch = cv2.boundingRect(c)
                if cv2.contourArea(c) > crop_area * 0.002 and ch > crop_h * 0.15:
                    valid_contours.append(c)
                    
            valid_contours.sort(key=lambda c: cv2.boundingRect(c)[0])
            
            if len(valid_contours) < 3:
                continue
                
            pts_all = []
            for c in valid_contours:
                lowest_pt = self._get_lowest_point(c)
                gx = lowest_pt[0] + x_min
                gy = lowest_pt[1] + y_min
                pts_all.append([gx, gy])
                
            pts_all = np.array(pts_all, dtype=np.float64)
            # Сортируем точки по X слева направо
            pts_all = pts_all[np.argsort(pts_all[:, 0])]
            
            # Фильтр скачков (по правилу: дельта не должна превышать 1.1 * соседнюю дельту)
            # Добавляем 2.0 пикселя для компенсации дискретизации
            if len(pts_all) >= 3:
                valid_mask = np.ones(len(pts_all), dtype=bool)
                for i in range(1, len(pts_all) - 1):
                    dy_left = abs(pts_all[i, 1] - pts_all[i-1, 1])
                    dy_right = abs(pts_all[i+1, 1] - pts_all[i, 1])
                    # Если точка сильно выбивается относительно обоих соседей
                    if dy_left > 1.1 * dy_right + 2.0 and dy_right > 1.1 * dy_left + 2.0:
                        valid_mask[i] = False
                    # Или если она просто прыгает вверх/вниз относительно локального медианного шага
                    med_dy = np.median(np.abs(np.diff(pts_all[:, 1])))
                    if dy_left > 1.1 * med_dy + 2.0 or dy_right > 1.1 * med_dy + 2.0:
                        valid_mask[i] = False
                
                # Проверка краев
                if len(pts_all) >= 2:
                    if abs(pts_all[1, 1] - pts_all[0, 1]) > 1.1 * np.median(np.abs(np.diff(pts_all[:, 1]))) + 2.0:
                        valid_mask[0] = False
                    if abs(pts_all[-1, 1] - pts_all[-2, 1]) > 1.1 * np.median(np.abs(np.diff(pts_all[:, 1]))) + 2.0:
                        valid_mask[-1] = False
                        
                pts_all = pts_all[valid_mask]

            n_pts = len(pts_all)
            if n_pts < 5:
                continue
            best_inliers = []
            best_poly = None
            max_inlier_count = 0
            
            # Перебираем случайные тройки (до 50 итераций)
            num_iters = min(50, n_pts * (n_pts - 1) * (n_pts - 2) // 6)
            
            for _ in range(num_iters):
                idx3 = np.random.choice(n_pts, 3, replace=False)
                sample = pts_all[idx3]
                
                # Защита от коллинеарности по X
                if abs(sample[0,0] - sample[1,0]) < 2 or abs(sample[1,0] - sample[2,0]) < 2 or abs(sample[0,0] - sample[2,0]) < 2:
                    continue
                    
                try:
                    p = np.polyfit(sample[:, 0], sample[:, 1], 2)
                    # Оцениваем все точки
                    preds = np.polyval(p, pts_all[:, 0])
                    errors = np.abs(preds - pts_all[:, 1])
                    inliers = pts_all[errors < 4.0] # 4 пикселя допуск
                    
                    if len(inliers) > max_inlier_count:
                        max_inlier_count = len(inliers)
                        best_inliers = inliers
                        best_poly = p
                except np.linalg.LinAlgError:
                    continue
                    
            if max_inlier_count >= 5 and best_poly is not None:
                # Финальный фит по равномерно распределенным инлайнерам
                try:
                    best_inliers = best_inliers[np.argsort(best_inliers[:, 0])]
                    min_x = best_inliers[0, 0]
                    max_x = best_inliers[-1, 0]
                    
                    num_anchors = min(10, len(best_inliers))
                    if num_anchors >= 3:
                        target_xs = np.linspace(min_x, max_x, num_anchors)
                        anchor_indices = []
                        for tx in target_xs:
                            idx = np.argmin(np.abs(best_inliers[:, 0] - tx))
                            if idx not in anchor_indices:
                                anchor_indices.append(idx)
                                
                        # Гарантируем наличие первой и последней буквы
                        if 0 not in anchor_indices:
                            anchor_indices.insert(0, 0)
                        if (len(best_inliers) - 1) not in anchor_indices:
                            anchor_indices.append(len(best_inliers) - 1)
                            
                        anchor_indices = sorted(list(set(anchor_indices)))
                        anchor_pts = best_inliers[anchor_indices]
                    else:
                        anchor_pts = best_inliers
                        
                    final_poly = np.polyfit(anchor_pts[:, 0], anchor_pts[:, 1], 2)
                    if abs(final_poly[0]) < 0.005:
                        parabolas.append((w, final_poly, anchor_pts))
                except Exception as e:
                    print(f"[Vectorizer] RANSAC final fit failed: {e}")
                
        parabolas.sort(key=lambda x: x[0], reverse=True)
        return [(p[1], p[2]) for p in parabolas[:4]]

    def vectorize(self, mask: np.ndarray, image: Optional[np.ndarray] = None, ocr_data: dict = None) -> VectorMask:
        if len(mask.shape) == 3:
            if mask.shape[2] == 3:
                mask = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)
            else:
                mask = mask[:, :, 0]

        h, w = mask.shape[:2]
        
        # 1. Retain largest component
        binary = np.uint8(mask > 127)
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        if num_labels > 2:
            largest_label = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
            clean_mask = np.zeros((h, w), dtype=np.uint8)
            clean_mask[labels == largest_label] = 255
            mask = clean_mask

        # Morphological closing
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask_closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        y_indices, x_indices = np.where(mask_closed > 127)
        if len(y_indices) == 0:
            P_TL = np.array([0.0, 0.0])
            P_TR = np.array([w - 1.0, 0.0])
            P_BL = np.array([0.0, h - 1.0])
            P_BR = np.array([w - 1.0, h - 1.0])
            return VectorMask(
                shape_type=LabelShape.RECTANGLE,
                bbox=(0, 0, w, h),
                P_TL=P_TL, P_TR=P_TR, P_BL=P_BL, P_BR=P_BR,
                T_curve=np.array([P_TL, P_TR]),
                B_curve=np.array([P_BL, P_BR]),
                L_line=np.array([P_TL, P_BL]),
                R_line=np.array([P_TR, P_BR]),
                polygon=np.array([P_TL, P_TR, P_BR, P_BL], dtype=np.int32),
                left_line=np.array([0.0, 0.0]),
                right_line=np.array([0.0, float(w - 1)]),
                top_curve=np.array([P_TL, P_TR]),
                bottom_curve=np.array([P_BL, P_BR])
            )

        x_min, x_max = int(np.min(x_indices)), int(np.max(x_indices))
        y_min, y_max = int(np.min(y_indices)), int(np.max(y_indices))
        H_mask = y_max - y_min

        # 2. Extract row-by-row left and right points along the mask
        valid_ys = np.unique(y_indices)
        left_pts = []
        right_pts = []
        for y in valid_ys:
            col_xs = np.where(mask_closed[y, :] > 127)[0]
            if len(col_xs) > 0:
                left_pts.append((float(col_xs[0]), float(y)))
                right_pts.append((float(col_xs[-1]), float(y)))

        left_pts = np.array(left_pts)
        right_pts = np.array(right_pts)

        # 4. Fit Lateral Tangent Lines (Касательные образующие цилиндра x = m*y + c)
        # Use middle region of mask height (25% to 75%) for stable regression
        mid_mask_L = (left_pts[:, 1] >= y_min + 0.25 * H_mask) & (left_pts[:, 1] <= y_min + 0.75 * H_mask)
        mid_mask_R = (right_pts[:, 1] >= y_min + 0.25 * H_mask) & (right_pts[:, 1] <= y_min + 0.75 * H_mask)

        def fit_lateral_ransac(xs, ys, tol=2.0):
            if len(ys) < 8: return None
            best_p = None
            max_inliers = 0
            n = len(ys)
            for _ in range(50):
                idx = np.random.choice(n, 2, replace=False)
                y1, y2 = ys[idx[0]], ys[idx[1]]
                x1, x2 = xs[idx[0]], xs[idx[1]]
                if abs(y1 - y2) < 1e-3: continue
                m = (x2 - x1) / (y2 - y1)
                c = x1 - m * y1
                preds = m * ys + c
                errs = np.abs(preds - xs)
                inliers = errs <= tol
                num_inliers = np.sum(inliers)
                if num_inliers > max_inliers:
                    max_inliers = num_inliers
                    best_p = np.array([m, c])
            if best_p is not None and max_inliers >= 4:
                preds = best_p[0] * ys + best_p[1]
                inliers = np.abs(preds - xs) <= tol
                return np.polyfit(ys[inliers], xs[inliers], deg=1)
            return None

        poly_L = fit_lateral_ransac(left_pts[mid_mask_L, 0], left_pts[mid_mask_L, 1], tol=2.0)
        if poly_L is None:
            poly_L = np.polyfit(left_pts[mid_mask_L, 1], left_pts[mid_mask_L, 0], deg=1) if np.count_nonzero(mid_mask_L) >= 8 else np.array([0.0, float(x_min)])

        poly_R = fit_lateral_ransac(right_pts[mid_mask_R, 0], right_pts[mid_mask_R, 1], tol=2.0)
        if poly_R is None:
            poly_R = np.polyfit(right_pts[mid_mask_R, 1], right_pts[mid_mask_R, 0], deg=1) if np.count_nonzero(mid_mask_R) >= 8 else np.array([0.0, float(x_max)])

        # 5. Extract continuous external contour
        contours, _ = cv2.findContours(mask_closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not contours:
            P_TL = np.array([float(x_min), float(y_min)])
            P_TR = np.array([float(x_max), float(y_min)])
            P_BL = np.array([float(x_min), float(y_max)])
            P_BR = np.array([float(x_max), float(y_max)])
            return VectorMask(
                shape_type=LabelShape.CYLINDER,
                bbox=(x_min, y_min, x_max - x_min, y_max - y_min),
                P_TL=P_TL, P_TR=P_TR, P_BL=P_BL, P_BR=P_BR,
                T_curve=np.array([P_TL, P_TR]),
                B_curve=np.array([P_BL, P_BR]),
                L_line=np.array([P_TL, P_BL]),
                R_line=np.array([P_TR, P_BR]),
                polygon=np.array([P_TL, P_TR, P_BR, P_BL], dtype=np.int32)
            )

        cnt = max(contours, key=cv2.contourArea)
        pts_cnt = cnt.squeeze(1)
        N_cnt = len(pts_cnt)

        # 6. RANSAC Robust Lateral Guides (VINA 3.0)
        x_mid = (x_min + x_max) / 2.0
        
        def _extract_longest_vertical_segment(contour: np.ndarray, is_left: bool, max_angle_deg: float = 15.0) -> tuple:
            # 1. Делим контур на отрезки по изломам (epsilon = 2.0 пикселя)
            epsilon = 2.0
            approx = cv2.approxPolyDP(contour, epsilon, closed=True).reshape(-1, 2)
            
            best_line = None
            best_len = 0
            max_m = np.tan(np.radians(max_angle_deg))
            
            # 2. Идем по всем полученным отрезкам
            for i in range(len(approx)):
                p1 = approx[i]
                p2 = approx[(i + 1) % len(approx)]
                
                mid_x = (p1[0] + p2[0]) / 2.0
                if is_left and mid_x > x_mid:
                    continue
                if not is_left and mid_x <= x_mid:
                    continue
                    
                dx = p2[0] - p1[0]
                dy = p2[1] - p1[1]
                length = np.hypot(dx, dy)
                
                if length < 10.0 or abs(dy) < 1e-3:
                    continue
                    
                m = dx / dy
                # Проверяем отклонение от вертикали
                if abs(m) <= max_m:
                    y_min_seg, y_max_seg = min(p1[1], p2[1]), max(p1[1], p2[1])
                    side_pts = contour[contour[:, 0] <= x_mid] if is_left else contour[contour[:, 0] > x_mid]
                    if len(side_pts) == 0:
                        continue
                        
                    # Извлекаем все точки маски на этом Y-отрезке
                    seg_pts = side_pts[(side_pts[:, 1] >= y_min_seg) & (side_pts[:, 1] <= y_max_seg)]
                    
                    if len(seg_pts) < 10:
                        continue
                        
                    # 3. Точки привязки равномерно распределяются вдоль отрезка
                    seg_pts = seg_pts[np.argsort(seg_pts[:, 1])]
                    indices = np.linspace(0, len(seg_pts) - 1, 10, dtype=int)
                    anchor_pts = seg_pts[indices]
                    
                    # 4. Фитим линию строго по этим 10 равномерным точкам
                    vx, vy, cx, cy = cv2.fitLine(anchor_pts, cv2.DIST_L2, 0, 0.01, 0.01)
                    vx, vy, cx, cy = float(vx[0]), float(vy[0]), float(cx[0]), float(cy[0])
                    
                    # 5. Проверяем максимальное отдаление не более 2 пикселей
                    m_fit = vx / (vy + 1e-6)
                    preds_x = m_fit * (anchor_pts[:, 1] - cy) + cx
                    errors = np.abs(anchor_pts[:, 0] - preds_x)
                    
                    if np.max(errors) <= 2.0:
                        # Из всех валидных вертикальных направляющих оставляем самую длинную
                        if length > best_len:
                            best_len = length
                            best_line = (vx, vy, cx, cy)
                            
            if best_line is None:
                # Fallback: самая крайняя точка
                pts = contour[contour[:, 0] <= x_mid] if is_left else contour[contour[:, 0] > x_mid]
                if len(pts) == 0:
                    pts = contour
                extreme_idx = np.argmin(pts[:, 0]) if is_left else np.argmax(pts[:, 0])
                return (0.0, 1.0, pts[extreme_idx, 0], pts[extreme_idx, 1])
                
            return best_line

        line_L = _extract_longest_vertical_segment(pts_cnt, is_left=True, max_angle_deg=15.0)
        line_R = _extract_longest_vertical_segment(pts_cnt, is_left=False, max_angle_deg=15.0)
        
        # Расширяем направляющие цилиндра для извлечения точек контура
        vx_L, vy_L, cx_L, cy_L = line_L
        norm_L = np.hypot(vx_L, vy_L)
        dist_L = np.abs(vy_L * (pts_cnt[:, 0] - cx_L) - vx_L * (pts_cnt[:, 1] - cy_L)) / (norm_L + 1e-6)
        
        vx_R, vy_R, cx_R, cy_R = line_R
        norm_R = np.hypot(vx_R, vy_R)
        dist_R = np.abs(vy_R * (pts_cnt[:, 0] - cx_R) - vx_R * (pts_cnt[:, 1] - cy_R)) / (norm_R + 1e-6)
        
        # Точки контура, лежащие на боковых образующих (допуск 4 пикселя)
        inliers_L = np.where(dist_L <= 4.0)[0]
        inliers_R = np.where(dist_R <= 4.0)[0]
        
        if len(inliers_L) == 0: inliers_L = np.where(dist_L <= 15.0)[0]
        if len(inliers_R) == 0: inliers_R = np.where(dist_R <= 15.0)[0]
        
        # Истинные индексы углов контура маски (самые верхние и нижние точки на боковых гранях)
        pts_L = pts_cnt[inliers_L]
        i_tl = inliers_L[np.argmin(pts_L[:, 1])]
        i_bl = inliers_L[np.argmax(pts_L[:, 1])]
        
        pts_R = pts_cnt[inliers_R]
        i_tr = inliers_R[np.argmin(pts_R[:, 1])]
        i_br = inliers_R[np.argmax(pts_R[:, 1])]

        def get_cnt_segment(s_idx, e_idx):
            if (e_idx - s_idx) % N_cnt < (s_idx - e_idx) % N_cnt:
                return pts_cnt[[(s_idx + i) % N_cnt for i in range((e_idx - s_idx) % N_cnt + 1)]]
            else:
                return pts_cnt[[(s_idx - i) % N_cnt for i in range((s_idx - e_idx) % N_cnt + 1)]]

        # Извлекаем верхние и нижние точки маски
        raw_T = get_cnt_segment(i_tr, i_tl) if np.mean(get_cnt_segment(i_tr, i_tl)[:, 1]) < np.mean(get_cnt_segment(i_tl, i_tr)[:, 1]) else get_cnt_segment(i_tl, i_tr)
        raw_B = get_cnt_segment(i_bl, i_br) if np.mean(get_cnt_segment(i_bl, i_br)[:, 1]) > np.mean(get_cnt_segment(i_br, i_bl)[:, 1]) else get_cnt_segment(i_br, i_bl)
        
        if raw_B[0, 0] > raw_B[-1, 0]:
            raw_B = raw_B[::-1]

        N_pts = 60

        # 6.6. Построение параболы (дуги) через детерминированную фильтрацию ломаной
        def _get_horizontal_parabola_poly(raw_pts: np.ndarray, tol: float = 4.0):
            N = len(raw_pts)
            if N < 3:
                p = np.polyfit(raw_pts[:, 0], raw_pts[:, 1], 1)
                return np.array([0.0, p[0], p[1]]), raw_pts

            # 1. Аппроксимируем контур ломаной линией
            epsilon = 3.0
            approx = cv2.approxPolyDP(raw_pts, epsilon, closed=False).reshape(-1, 2)
            
            if len(approx) < 2:
                final_poly = np.polyfit(raw_pts[:, 0], raw_pts[:, 1], 2)
                return final_poly, raw_pts
                
            # 2. Фильтр 1: Исключаем диагональные линии по углу
            valid_segments = []
            for i in range(len(approx) - 1):
                p1 = approx[i]
                p2 = approx[i+1]
                dx = p2[0] - p1[0]
                dy = p2[1] - p1[1]
                
                # Если угол больше ~40 градусов (наклон > 0.8), это диагональный срез (брак)
                if abs(dx) < 1e-3 or abs(dy/dx) > 0.8:
                    valid_segments.append(False)
                else:
                    valid_segments.append(True)
                    
            # 3. Группируем смежные горизонтальные отрезки
            groups = []
            current_group = []
            for i, is_valid in enumerate(valid_segments):
                if is_valid:
                    current_group.append(i)
                else:
                    if current_group:
                        groups.append(current_group)
                        current_group = []
            if current_group:
                groups.append(current_group)
                
            if not groups:
                # Fallback, если все отбраковалось
                final_poly = np.polyfit(raw_pts[:, 0], raw_pts[:, 1], 2)
                return final_poly, raw_pts
                
            # 4. Фильтр 2: Выбираем самую длинную непрерывную цепь горизонтальных направляющих (отбрасываем короткие)
            best_group = None
            max_span = -1
            
            for g in groups:
                p_start = approx[g[0]]
                p_end = approx[g[-1] + 1]
                span = abs(p_end[0] - p_start[0])
                if span > max_span:
                    max_span = span
                    best_group = g
                    
            # 5. Извлекаем точки оригинального контура, соответствующие этому лучшему (самому длинному) участку
            start_pt = approx[best_group[0]]
            end_pt = approx[best_group[-1] + 1]
            
            dists_start = np.sum((raw_pts - start_pt)**2, axis=1)
            dists_end = np.sum((raw_pts - end_pt)**2, axis=1)
            idx_start = int(np.argmin(dists_start))
            idx_end = int(np.argmin(dists_end))
            
            if idx_start > idx_end:
                idx_start, idx_end = idx_end, idx_start
                
            best_inliers = raw_pts[idx_start:idx_end+1]
            
            # Строгое требование: направляющие должны быть образованы не менее чем по 5 точкам
            if len(best_inliers) >= 5:
                # Строим симметричную параболу (которая математически эквивалентна круговой дуге)
                # Это жестко фиксирует вершину параболы по центру бутылки (x_mid) и гарантирует, 
                # что левая часть дуги будет идеальным зеркальным отражением правой части, 
                # и она никогда не "взлетит" вверх.
                x_sym = (best_inliers[:, 0] - x_mid)**2
                p_1d = np.polyfit(x_sym, best_inliers[:, 1], 1)
                a = p_1d[0]
                c = p_1d[1]
                b = -2 * a * x_mid
                c_orig = a * x_mid**2 + c
                final_poly = np.array([a, b, c_orig])
                return final_poly, best_inliers
            else:
                final_poly = np.polyfit(raw_pts[:, 0], raw_pts[:, 1], 2)
                return final_poly, raw_pts


        def intersect_line_parabola(line, poly, ref_x):
            vx, vy, cx, cy = line
            a, b, c = poly
            A_line = vy
            B_line = -vx
            C_line = vx * cy - vy * cx
            
            c2 = B_line * a
            c1 = A_line + B_line * b
            c0 = B_line * c + C_line
            
            if abs(c2) < 1e-9:
                if abs(c1) < 1e-9:
                    return np.array([ref_x, np.polyval(poly, ref_x)])
                x_int = -c0 / c1
                return np.array([x_int, np.polyval(poly, x_int)])
                
            disc = c1**2 - 4 * c2 * c0
            if disc < 0:
                return np.array([ref_x, np.polyval(poly, ref_x)])
                
            x1 = (-c1 + np.sqrt(disc)) / (2 * c2)
            x2 = (-c1 - np.sqrt(disc)) / (2 * c2)
            
            x_int = x1 if abs(x1 - ref_x) < abs(x2 - ref_x) else x2
            y_int = np.polyval(poly, x_int)
            return np.array([x_int, y_int])

        # 1. Извлекаем независимые полиномы для верха и низа чисто по контуру маски
        poly_T, raw_T = _get_horizontal_parabola_poly(raw_T, tol=4.0)
        poly_B, raw_B = _get_horizontal_parabola_poly(raw_B, tol=4.0)

        # 2. Находим точные точки пересечения базовых парабол с боковыми направляющими
        P_TL = intersect_line_parabola(line_L, poly_T, pts_cnt[i_tl, 0])
        P_TR = intersect_line_parabola(line_R, poly_T, pts_cnt[i_tr, 0])
        P_BL = intersect_line_parabola(line_L, poly_B, pts_cnt[i_bl, 0])
        P_BR = intersect_line_parabola(line_R, poly_B, pts_cnt[i_br, 0])

        # Мы больше не сдвигаем параболы к y_min/y_max. 
        # Искусственный сдвиг приводил к отрыву зеленых дуг от фактического контура на краях.

        # 3. Формируем дуги T_curve и B_curve строго между вычисленными углами пересечения
        x_base_T = np.linspace(P_TL[0], P_TR[0], N_pts)
        T_curve = np.column_stack((x_base_T, np.polyval(poly_T, x_base_T)))

        x_base_B = np.linspace(P_BL[0], P_BR[0], N_pts)
        B_curve = np.column_stack((x_base_B, np.polyval(poly_B, x_base_B)))

        # 7. Извлечение боковых сегментов контура
        seg_l1 = get_cnt_segment(i_tl, i_bl)
        seg_l2 = get_cnt_segment(i_bl, i_tl)
        raw_L = seg_l1 if np.mean(seg_l1[:, 0]) < np.mean(seg_l2[:, 0]) else seg_l2

        seg_r1 = get_cnt_segment(i_tr, i_br)
        seg_r2 = get_cnt_segment(i_br, i_tr)
        raw_R = seg_r1 if np.mean(seg_r1[:, 0]) > np.mean(seg_r2[:, 0]) else seg_r2

        # 8. Проверка ровности образующих при углах ~180° и фильтрация резких порогов
        L_curve = self._fit_straight_lateral_guide(raw_L, P_TL, P_BL, N_pts=N_pts)
        R_curve = self._fit_straight_lateral_guide(raw_R, P_TR, P_BR, N_pts=N_pts)

        polygon = np.concatenate([T_curve, R_curve[1:-1], B_curve[::-1], L_curve[::-1][1:-1]])
        text_parabolas = self._extract_text_parabolas(ocr_data, w, h, T_curve=T_curve, B_curve=B_curve, image=image)

        return VectorMask(
            shape_type=LabelShape.CYLINDER,
            bbox=(int(x_min), int(y_min), int(x_max - x_min), int(y_max - y_min)),
            P_TL=P_TL, P_TR=P_TR, P_BL=P_BL, P_BR=P_BR,
            T_curve=T_curve,
            B_curve=B_curve,
            L_line=L_curve,
            R_line=R_curve,
            polygon=polygon,
            left_line=poly_L,
            right_line=poly_R,
            top_curve=T_curve,
            bottom_curve=B_curve,
            text_parabolas=text_parabolas,
            raw_T=raw_T,
            raw_B=raw_B,
            raw_L=raw_L,
            raw_R=raw_R
        )

    def extract_vector_mask(self, mask: np.ndarray, image: Optional[np.ndarray] = None, ocr_data: dict = None) -> VectorMask:
        return self.vectorize(mask, image=image, ocr_data=ocr_data)

Vectorizer = MaskVectorizer
