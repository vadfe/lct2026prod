"""
Stage 3: Transfinite 3D Deformation Grid Construction (Coon's Patch Surface)
- Horizontal guides are a continuous uniform transition from the top mask curve T(u) to the bottom mask curve B(u)
- Bounded strictly by lateral lines connecting the 4 physical mask corners (P_TL, P_TR, P_BL, P_BR)
"""

import cv2
import numpy as np
from typing import Optional, Dict, Any, List

class Stage3CylinderOptimizer:
    def __init__(self, grid_rows: int = 22, grid_cols: int = 28):
        self.grid_rows = grid_rows
        self.grid_cols = grid_cols

    def optimize_cylinder_grid(
        self,
        img_shape: tuple,
        text_lines: list,
        line_segments: list,
        cam_info: dict,
        mask: Optional[np.ndarray] = None,
        label_boundaries: Optional[dict] = None
    ) -> dict:
        h, w = img_shape[:2]

        if label_boundaries and "P_TL" in label_boundaries:
            P_TL = np.array(label_boundaries["P_TL"], dtype=np.float64)
            P_TR = np.array(label_boundaries["P_TR"], dtype=np.float64)
            P_BL = np.array(label_boundaries["P_BL"], dtype=np.float64)
            P_BR = np.array(label_boundaries["P_BR"], dtype=np.float64)

            T_xs = np.array(label_boundaries["T_curve_xs"], dtype=np.float64)
            T_ys = np.array(label_boundaries["T_curve_ys"], dtype=np.float64)
            T_curve = np.column_stack((T_xs, T_ys))

            B_xs = np.array(label_boundaries["B_curve_xs"], dtype=np.float64)
            B_ys = np.array(label_boundaries["B_curve_ys"], dtype=np.float64)
            B_curve = np.column_stack((B_xs, B_ys))

            # Resample curves to grid_cols
            u_vals = np.linspace(0.0, 1.0, self.grid_cols)
            v_vals = np.linspace(0.0, 1.0, self.grid_rows)

            idx_orig = np.linspace(0.0, 1.0, len(T_curve))
            T_resamp = np.column_stack((
                np.interp(u_vals, idx_orig, T_curve[:, 0]),
                np.interp(u_vals, idx_orig, T_curve[:, 1])
            ))
            B_resamp = np.column_stack((
                np.interp(u_vals, idx_orig, B_curve[:, 0]),
                np.interp(u_vals, idx_orig, B_curve[:, 1])
            ))

            if "L_curve" in label_boundaries and label_boundaries["L_curve"] is not None and len(label_boundaries["L_curve"]) > 1:
                L_curve = label_boundaries["L_curve"]
                idx_L = np.linspace(0.0, 1.0, len(L_curve))
                L_resamp = np.column_stack((
                    np.interp(v_vals, idx_L, L_curve[:, 0]),
                    np.interp(v_vals, idx_L, L_curve[:, 1])
                ))
            else:
                L_resamp = (1.0 - v_vals[:, None]) * P_TL + v_vals[:, None] * P_BL

            if "R_curve" in label_boundaries and label_boundaries["R_curve"] is not None and len(label_boundaries["R_curve"]) > 1:
                R_curve = label_boundaries["R_curve"]
                idx_R = np.linspace(0.0, 1.0, len(R_curve))
                R_resamp = np.column_stack((
                    np.interp(v_vals, idx_R, R_curve[:, 0]),
                    np.interp(v_vals, idx_R, R_curve[:, 1])
                ))
            else:
                R_resamp = (1.0 - v_vals[:, None]) * P_TR + v_vals[:, None] * P_BR

            u_src_grid = np.zeros((self.grid_rows, self.grid_cols), dtype=np.float32)
            v_src_grid = np.zeros((self.grid_rows, self.grid_cols), dtype=np.float32)

            for i in range(self.grid_rows):
                v = v_vals[i]
                for j in range(self.grid_cols):
                    u = u_vals[j]
                    corner_blend = (1.0 - u) * (1.0 - v) * P_TL + u * (1.0 - v) * P_TR + (1.0 - u) * v * P_BL + u * v * P_BR
                    pt = (1.0 - v) * T_resamp[j] + v * B_resamp[j] + (1.0 - u) * L_resamp[i] + u * R_resamp[i] - corner_blend
                    u_src_grid[i, j] = np.clip(pt[0], 0, w - 1)
                    v_src_grid[i, j] = np.clip(pt[1], 0, h - 1)

            dst_w = int(max(np.linalg.norm(P_TR - P_TL), np.linalg.norm(P_BR - P_BL)))
            dst_h = int(max(np.linalg.norm(P_BL - P_TL), np.linalg.norm(P_BR - P_TR)))

            grid_y_flat, grid_x_flat = np.meshgrid(
                np.linspace(0, dst_h - 1, self.grid_rows),
                np.linspace(0, dst_w - 1, self.grid_cols),
                indexing='ij'
            )
        else:
            dst_w = w
            dst_h = h
            grid_y_flat, grid_x_flat = np.meshgrid(
                np.linspace(0, h - 1, self.grid_rows),
                np.linspace(0, w - 1, self.grid_cols),
                indexing='ij'
            )
            u_src_grid = grid_x_flat.copy().astype(np.float32)
            v_src_grid = grid_y_flat.copy().astype(np.float32)

        src_ctrl_pts = np.column_stack((u_src_grid.ravel(), v_src_grid.ravel())).astype(np.float32)
        dst_ctrl_pts = np.column_stack((grid_x_flat.ravel(), grid_y_flat.ravel())).astype(np.float32)

        return {
            "opt_params": {
                "center_x": float(cam_info.get("center_axis_x", w / 2.0)),
                "tilt_deg": float(cam_info.get("tilt_angle_deg", 0.0)),
                "converged": True
            },
            "src_ctrl_pts": src_ctrl_pts,
            "dst_ctrl_pts": dst_ctrl_pts,
            "output_width": int(dst_w),
            "output_height": int(dst_h),
            "grid_cols": self.grid_cols,
            "grid_rows": self.grid_rows,
            "u_src_grid": u_src_grid,
            "v_src_grid": v_src_grid
        }

    def draw_grid_overlay(
        self,
        img_bgr: np.ndarray,
        u_grid: np.ndarray,
        v_grid: np.ndarray,
        label_boundaries: Optional[dict] = None
    ) -> np.ndarray:
        vis = img_bgr.copy()
        rows, cols = u_grid.shape

        # Blue Side Boundary Lines (Exact boundary polylines)
        if label_boundaries and "L_curve" in label_boundaries and label_boundaries["L_curve"] is not None:
            cv2.polylines(vis, [label_boundaries["L_curve"].astype(np.int32)], False, (255, 140, 0), 4, cv2.LINE_AA)
            cv2.polylines(vis, [label_boundaries["R_curve"].astype(np.int32)], False, (255, 140, 0), 4, cv2.LINE_AA)
        elif label_boundaries and "P_TL" in label_boundaries:
            P_TL = label_boundaries["P_TL"]
            P_TR = label_boundaries["P_TR"]
            P_BL = label_boundaries["P_BL"]
            P_BR = label_boundaries["P_BR"]
            cv2.line(vis, (int(P_TL[0]), int(P_TL[1])), (int(P_BL[0]), int(P_BL[1])), (255, 140, 0), 4, cv2.LINE_AA)
            cv2.line(vis, (int(P_TR[0]), int(P_TR[1])), (int(P_BR[0]), int(P_BR[1])), (255, 140, 0), 4, cv2.LINE_AA)

        # Horizontal guide curves (Cyan, uniform transition from top to bottom)
        for i in range(rows):
            pts = np.column_stack((u_grid[i, :], v_grid[i, :])).astype(np.int32)
            color = (0, 255, 0) if (i == 0 or i == rows - 1) else (0, 240, 255)
            thick = 3 if (i == 0 or i == rows - 1) else 1
            cv2.polylines(vis, [pts], False, color, thick, lineType=cv2.LINE_AA)

        # Vertical grid lines
        for j in range(cols):
            pts = np.column_stack((u_grid[:, j], v_grid[:, j])).astype(np.int32)
            color = (255, 140, 0) if (j == 0 or j == cols - 1) else (0, 180, 255)
            thick = 3 if (j == 0 or j == cols - 1) else 1
            cv2.polylines(vis, [pts], False, color, thick, lineType=cv2.LINE_AA)

        # 4 Corner Green Dots
        if label_boundaries and "P_TL" in label_boundaries:
            for pt in [label_boundaries["P_TL"], label_boundaries["P_TR"], label_boundaries["P_BL"], label_boundaries["P_BR"]]:
                cv2.circle(vis, (int(pt[0]), int(pt[1])), 9, (255, 255, 255), -1, cv2.LINE_AA)
                cv2.circle(vis, (int(pt[0]), int(pt[1])), 7, (0, 255, 0), -1, cv2.LINE_AA)

        return vis

    def process(
        self,
        img_bgr: np.ndarray,
        text_lines: list,
        line_segments: list,
        cam_info: dict,
        mask: Optional[np.ndarray] = None,
        label_boundaries: Optional[dict] = None
    ) -> dict:
        grid_data = self.optimize_cylinder_grid(
            img_bgr.shape, text_lines, line_segments, cam_info, mask, label_boundaries
        )
        vis_mesh = self.draw_grid_overlay(
            img_bgr, grid_data["u_src_grid"], grid_data["v_src_grid"], label_boundaries
        )
        grid_data["vis_mesh"] = vis_mesh
        return grid_data
