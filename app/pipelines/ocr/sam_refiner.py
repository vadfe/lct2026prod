"""
SAM Refiner: Segment Anything Model Integration for VINA
Refines bounding box prompts (from YOLO) into high-fidelity subpixel instance segmentation masks.
Optimized for NVIDIA RTX 3090 / RTX 3060 CUDA with FP16 Autocast and Local ROI Attention.
"""

import os
import logging
from pathlib import Path
from typing import Optional, Tuple, Union
import cv2
import numpy as np
import torch

logger = logging.getLogger("vina.sam_refiner")

MODELS_DIR = Path(r"D:\models")

class SAMRefiner:
    """
    Refines YOLO bounding boxes into smooth, accurate instance segmentation masks
    using Meta's Segment Anything Model (SAM ViT-H or MobileSAM).
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        model_type: str = "vit_h",
        device: Optional[str] = None
    ):
        # Default to cuda:0 (RTX 3090 24GB) for maximum compute throughput
        if device is None:
            self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device if torch.cuda.is_available() else "cpu"

        if model_path is None:
            default_vit_h = MODELS_DIR / "sam_vit_h_4b8939.pth"
            default_mobile = MODELS_DIR / "mobile_sam.pt"
            if default_vit_h.exists():
                model_path = str(default_vit_h)
                model_type = "vit_h"
            elif default_mobile.exists():
                model_path = str(default_mobile)
                model_type = "vit_t"
            else:
                model_path = str(default_vit_h)
                model_type = "vit_h"

        self.model_path = Path(model_path)
        self.model_type = model_type
        self.predictor = None
        self._init_model()

    def _init_model(self):
        try:
            from segment_anything import sam_model_registry, SamPredictor
            logger.info(f"[SAMRefiner] Loading SAM ({self.model_type}) on {self.device} from: {self.model_path}")
            if not self.model_path.exists():
                logger.warning(f"[SAMRefiner] Checkpoint not found at {self.model_path}. SAM refinement disabled.")
                return
            
            sam = sam_model_registry[self.model_type](checkpoint=str(self.model_path))
            sam.to(device=self.device)
            # Use eval mode
            sam.eval()
            self.predictor = SamPredictor(sam)
            logger.info(f"[SAMRefiner] SAM ({self.model_type}) loaded successfully on {self.device}.")
        except Exception as e:
            logger.error(f"[SAMRefiner] Failed to load SAM: {e}. Fallback to YOLO mask.")
            self.predictor = None

    def is_ready(self) -> bool:
        return self.predictor is not None

    def _find_structural_edges(self, roi_bgr: np.ndarray, bx1_local: int, by1_local: int, bx2_local: int, by2_local: int) -> Tuple[Optional[int], Optional[int]]:
        """
        Ищет мощные горизонтальные структурные границы внутри коробки YOLO.
        Возвращает (top_y, bottom_y) относительно roi_bgr.
        """
        gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        
        sobel_y = cv2.Sobel(blurred, cv2.CV_64F, 0, 1, ksize=3)
        abs_sobel_y = np.absolute(sobel_y)
        
        # Обрезаем до внутренних границ YOLO
        box_sobel = abs_sobel_y[by1_local:by2_local, bx1_local:bx2_local]
        if box_sobel.size == 0:
            return None, None
            
        projection = np.sum(box_sobel, axis=1)
        proj_smoothed = np.convolve(projection, np.ones(5)/5.0, mode='same')
        
        import scipy.signal
        prominence_thresh = max(np.max(proj_smoothed) * 0.15, 1000)
        peaks, _ = scipy.signal.find_peaks(proj_smoothed, prominence=prominence_thresh)
        
        top_y = None
        bottom_y = None
        
        if len(peaks) > 0:
            H_box = by2_local - by1_local
            
            # Top peaks (в верхних 25% коробки)
            top_peaks = [p for p in peaks if p < H_box * 0.25]
            if top_peaks:
                best_top = max(top_peaks, key=lambda p: proj_smoothed[p])
                top_y = by1_local + best_top
                
            # Bottom peaks (в нижних 25% коробки)
            bottom_peaks = [p for p in peaks if p > H_box * 0.75]
            if bottom_peaks:
                best_bottom = max(bottom_peaks, key=lambda p: proj_smoothed[p])
                bottom_y = by1_local + best_bottom
                
        return top_y, bottom_y

    def refine_mask(
        self,
        img_bgr: np.ndarray,
        bbox_xyxy: Union[list, np.ndarray, tuple],
        point_prompts: Optional[Tuple[np.ndarray, np.ndarray]] = None
    ) -> Tuple[np.ndarray, float]:
        """
        Generates high-precision binary mask inside the bounding box using GPU FP16 acceleration.
        """
        h, w = img_bgr.shape[:2]
        if self.predictor is None:
            mask = np.zeros((h, w), dtype=np.uint8)
            x1, y1, x2, y2 = [int(v) for v in bbox_xyxy]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            mask[y1:y2, x1:x2] = 255
            return mask, 0.5

        # For large images (e.g. 2560x1180), crop localized ROI around bottle to maximize GPU speed
        bx1, by1, bx2, by2 = [int(v) for v in bbox_xyxy]
        bw, bh = max(1, bx2 - bx1), max(1, by2 - by1)
        
        # Generous padding around the bottle
        pad_x = int(bw * 0.25)
        pad_y = int(bh * 0.25)
        roi_x1 = max(0, bx1 - pad_x)
        roi_y1 = max(0, by1 - pad_y)
        roi_x2 = min(w, bx2 + pad_x)
        roi_y2 = min(h, by2 + pad_y)

        roi_bgr = img_bgr[roi_y1:roi_y2, roi_x1:roi_x2]
        
        # Для маленьких изображений (< 1024px) увеличиваем ROI, чтобы SAM
        # мог различить тонкую кривизну краёв этикетки в тенях.
        roi_h, roi_w = roi_bgr.shape[:2]
        min_dim_for_sam = 1024
        upscale_factor = 1.0
        if max(roi_h, roi_w) < min_dim_for_sam:
            upscale_factor = min_dim_for_sam / max(roi_h, roi_w)
            new_w = int(roi_w * upscale_factor)
            new_h = int(roi_h * upscale_factor)
            roi_bgr_up = cv2.resize(roi_bgr, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
        else:
            roi_bgr_up = roi_bgr
        
        # Локальная нормализация освещенности (CLAHE) для вытягивания краев из глубоких теней.
        # Делаем это строго в L-канале, чтобы не искажать цвета (SAM к этому чувствителен).
        roi_lab = cv2.cvtColor(roi_bgr_up, cv2.COLOR_BGR2LAB)
        l_chan, a_chan, b_chan = cv2.split(roi_lab)
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        l_clahe = clahe.apply(l_chan)
        roi_lab_clahe = cv2.merge((l_clahe, a_chan, b_chan))
        roi_rgb = cv2.cvtColor(roi_lab_clahe, cv2.COLOR_LAB2RGB)

        # Analyze central paper color vs corner anchors (на увеличенных координатах)
        cx_local = int(((bx1 + bx2) / 2.0 - roi_x1) * upscale_factor)
        cy_local = int(((by1 + by2) / 2.0 - roi_y1) * upscale_factor)
        
        roi_lab_orig = cv2.cvtColor(roi_bgr_up, cv2.COLOR_BGR2LAB)
        l_channel = roi_lab_orig[:, :, 0]
        
        c_rad = max(4, int(min(bw, bh) * upscale_factor * 0.08))
        cx_c = int(np.clip(cx_local, 0, roi_rgb.shape[1] - 1))
        cy_c = int(np.clip(cy_local, 0, roi_rgb.shape[0] - 1))
        center_patch = l_channel[max(0, cy_c - c_rad):min(roi_rgb.shape[0], cy_c + c_rad),
                                 max(0, cx_c - c_rad):min(roi_rgb.shape[1], cx_c + c_rad)]
        center_L = float(np.median(center_patch)) if center_patch.size > 0 else 128.0

        # Positive helper points across label body
        bx1_local = int((bx1 - roi_x1) * upscale_factor)
        by1_local = int((by1 - roi_y1) * upscale_factor)
        bx2_local = int((bx2 - roi_x1) * upscale_factor)
        by2_local = int((by2 - roi_y1) * upscale_factor)
        bw_local = max(1, bx2_local - bx1_local)
        bh_local = max(1, by2_local - by1_local)
        
        pts_list = [
            [cx_local, cy_local],
            [bx1_local + int(bw_local * 0.30), cy_local],
            [bx1_local + int(bw_local * 0.70), cy_local],
        ]
        labels_list = [1, 1, 1]
        
        # Structural Edge Detection (исключительно внутри коробки YOLO)
        top_edge_y, bottom_edge_y = self._find_structural_edges(
            roi_bgr_up, bx1_local, by1_local, bx2_local, by2_local
        )
        
        if top_edge_y is not None:
            # Ставим отрицательную точку выше физического края, чтобы отсечь жидкость/горлышко
            neg_y = max(by1_local, top_edge_y - int(bh_local * 0.05))
            pts_list.append([cx_local, neg_y])
            labels_list.append(0)
            logger.info(f"[SAMRefiner] Added NEGATIVE point at TOP {neg_y} (Edge at {top_edge_y})")
            
        if bottom_edge_y is not None:
            # Ставим отрицательную точку ниже физического края
            neg_y = min(by2_local, bottom_edge_y + int(bh_local * 0.05))
            pts_list.append([cx_local, neg_y])
            labels_list.append(0)
            logger.info(f"[SAMRefiner] Added NEGATIVE point at BOTTOM {neg_y} (Edge at {bottom_edge_y})")

        pts_local = np.array(pts_list, dtype=np.float32)
        labels_local = np.array(labels_list, dtype=np.int32)

        with torch.no_grad():
            with torch.amp.autocast('cuda', enabled=("cuda" in str(self.device)), dtype=torch.float16):
                self.predictor.set_image(roi_rgb)

                # Раскрываем bounding box по вертикали на 6%
                expand_y = int(bh_local * 0.06)
                expand_x = int(bw_local * 0.02)
                
                sam_bx1 = max(0, bx1_local - expand_x)
                sam_by1 = max(0, by1_local - expand_y)
                sam_bx2 = min(roi_rgb.shape[1], bx2_local + expand_x)
                sam_by2 = min(roi_rgb.shape[0], by2_local + expand_y)
                
                # Local box in ROI coordinate space
                local_box = np.array([sam_bx1, sam_by1, sam_bx2, sam_by2], dtype=np.float32).reshape(1, 4)
                transformed_boxes = self.predictor.transform.apply_boxes_torch(
                    torch.tensor(local_box, device=self.device),
                    roi_rgb.shape[:2]
                )
                transformed_pts = self.predictor.transform.apply_coords_torch(
                    torch.tensor(pts_local[None, :], device=self.device),
                    roi_rgb.shape[:2]
                )
                labels_tensor = torch.tensor(labels_local[None, :], device=self.device)

                # Predict 3 mask candidates and pick the largest one (most complete coverage)
                masks, scores, _ = self.predictor.predict_torch(
                    point_coords=transformed_pts,
                    point_labels=labels_tensor,
                    boxes=transformed_boxes,
                    multimask_output=True
                )

        # Select the mask with the largest area among those with reasonable score
        masks_np = masks[0].cpu().numpy()  # shape: (3, H, W)
        scores_np = scores[0].cpu().numpy()  # shape: (3,)
        best_idx = 0
        best_area = 0
        
        logger.info(f"[SAMRefiner] SAM predicted 3 masks:")
        for i in range(masks_np.shape[0]):
            area = np.sum(masks_np[i])
            logger.info(f"  Mask {i}: score={scores_np[i]:.4f}, area={area}")
            if scores_np[i] > 0.85:
                if area > best_area:
                    best_area = area
                    best_idx = i
                    
        logger.info(f"[SAMRefiner] Selected Mask {best_idx} with area {best_area}")
        local_mask = (masks_np[best_idx] > 0.5).astype(np.uint8) * 255
        score = float(scores_np[best_idx])

        # Если был upscale, уменьшаем маску обратно до оригинального размера ROI
        if upscale_factor > 1.0:
            local_mask = cv2.resize(local_mask, (roi_w, roi_h), interpolation=cv2.INTER_LINEAR)
            local_mask = (local_mask > 127).astype(np.uint8) * 255

        # Paste back into full image mask
        full_mask = np.zeros((h, w), dtype=np.uint8)
        full_mask[roi_y1:roi_y2, roi_x1:roi_x2] = local_mask

        return full_mask, score
