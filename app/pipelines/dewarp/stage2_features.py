"""
Stage 2: Geometric Guides Extraction (Vectorized Mask Guides)
- Extracts exact physical mask corners (P_TL, P_TR, P_BL, P_BR)
- Connects lateral blue boundary lines and top/bottom green boundary curves
- NO text baseline points for guide construction (pure geometric mask guides)
"""

import cv2
import numpy as np
from typing import Optional, Dict, Any, List

from .vectorizer import VectorMask, LabelShape, MaskVectorizer

class Stage2FeatureExtractor:
    def __init__(self):
        self.vectorizer = MaskVectorizer()

    def process(
        self,
        binarized: np.ndarray,
        enhanced_bgr: np.ndarray,
        mask: Optional[np.ndarray] = None,
        vector_mask: Optional[VectorMask] = None
    ) -> dict:
        h, w = enhanced_bgr.shape[:2]
        if mask is None:
            mask = np.ones((h, w), dtype=np.uint8) * 255

        if vector_mask is None:
            vector_mask = self.vectorizer.vectorize(mask)

        P_TL = vector_mask.P_TL
        P_TR = vector_mask.P_TR
        P_BL = vector_mask.P_BL
        P_BR = vector_mask.P_BR
        T_curve = vector_mask.T_curve
        B_curve = vector_mask.B_curve

        L_curve = vector_mask.L_line
        R_curve = vector_mask.R_line

        # Central axis
        p_top_mid = (P_TL + P_TR) / 2.0
        p_bot_mid = (P_BL + P_BR) / 2.0
        m_c = (p_bot_mid[0] - p_top_mid[0]) / max(p_bot_mid[1] - p_top_mid[1], 1.0)
        c_c = p_top_mid[0] - m_c * p_top_mid[1]

        # Render on Image
        vis_img = enhanced_bgr.copy()

        # 1. Central Axis (Red dashed line)
        for s in range(0, int(np.linalg.norm(p_bot_mid - p_top_mid)), 14):
            v_s = s / float(np.linalg.norm(p_bot_mid - p_top_mid))
            pt_a = (1.0 - v_s) * p_top_mid + v_s * p_bot_mid
            cv2.line(vis_img, (int(pt_a[0]), int(pt_a[1])), (int(pt_a[0]), int(pt_a[1] + 7)), (0, 0, 255), 2, cv2.LINE_AA)

        # 2. Side Boundary Lines (Blue - exactly on mask boundary)
        if L_curve is not None and len(L_curve) > 1:
            cv2.polylines(vis_img, [L_curve.astype(np.int32)], False, (255, 140, 0), 4, lineType=cv2.LINE_AA)
        else:
            cv2.line(vis_img, (int(P_TL[0]), int(P_TL[1])), (int(P_BL[0]), int(P_BL[1])), (255, 140, 0), 4, cv2.LINE_AA)

        if R_curve is not None and len(R_curve) > 1:
            cv2.polylines(vis_img, [R_curve.astype(np.int32)], False, (255, 140, 0), 4, lineType=cv2.LINE_AA)
        else:
            cv2.line(vis_img, (int(P_TR[0]), int(P_TR[1])), (int(P_BR[0]), int(P_BR[1])), (255, 140, 0), 4, cv2.LINE_AA)

        # 3. Top and Bottom Boundary Curves (Green)
        cv2.polylines(vis_img, [T_curve.astype(np.int32)], False, (0, 255, 0), 4, lineType=cv2.LINE_AA)
        cv2.polylines(vis_img, [B_curve.astype(np.int32)], False, (0, 255, 0), 4, lineType=cv2.LINE_AA)

        # 4. Top and Bottom Chord lines
        cv2.line(vis_img, (int(P_TL[0] - 25), int(P_TL[1] - 3)), (int(P_TR[0] + 25), int(P_TR[1] + 3)), (0, 255, 0), 1, cv2.LINE_AA)

        # 5. 4 Corner Green Dots strictly on mask boundary
        for pt in [P_TL, P_TR, P_BL, P_BR]:
            cv2.circle(vis_img, (int(pt[0]), int(pt[1])), 9, (255, 255, 255), -1, cv2.LINE_AA)
            cv2.circle(vis_img, (int(pt[0]), int(pt[1])), 7, (0, 255, 0), -1, cv2.LINE_AA)

        return {
            "text_lines": [],
            "line_segments": [],
            "label_boundaries": {
                "P_TL": [float(P_TL[0]), float(P_TL[1])],
                "P_TR": [float(P_TR[0]), float(P_TR[1])],
                "P_BL": [float(P_BL[0]), float(P_BL[1])],
                "P_BR": [float(P_BR[0]), float(P_BR[1])],
                "L_curve": L_curve,
                "R_curve": R_curve,
                "T_curve_xs": [float(x) for x in T_curve[:, 0]],
                "T_curve_ys": [float(y) for y in T_curve[:, 1]],
                "B_curve_xs": [float(x) for x in B_curve[:, 0]],
                "B_curve_ys": [float(y) for y in B_curve[:, 1]],
                "central_axis": {"poly_coeffs": [float(m_c), float(c_c)]}
            },
            "cam_orientation": {
                "tilt_angle_deg": float(np.degrees(np.arctan(m_c))),
                "center_axis_x": float(p_top_mid[0])
            },
            "vis_features": vis_img
        }
