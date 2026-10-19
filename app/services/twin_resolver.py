"""Twin resolver: picks one of near-identical labels of the same producer by the regions where they differ.

Global embeddings (DINOv2, SigLIP 2) cannot separate labels that differ only in a small detail — the blend
tag of «Фантом 30/70 / 50/50 / 70/30», a vintage, an ABV figure: such twins get almost the same score.

1. The twins' reference labels are aligned to the first one (SIFT + RANSAC homography). A twin that does
   not align with enough inliers is not a twin: the stage gives up.
2. The aligned references are compared with each other; pixels where they differ (blurred Lab difference)
   are merged into blobs (strokes of one word or figure become one region); straight line pieces and thin
   elongated blobs (label edges of slightly shifted photos), blobs at the crop border and specks much
   smaller than the main difference are dropped. True twins are one catalog photo with an edited detail: the rest of the label matches almost
   exactly. References that align on few points (`min_reference_inliers`), labels of one series that differ
   in a larger part (`max_difference_fraction`: a grape name, a vintage line), two different photos of one
   label (median difference above `max_background_difference`, many scattered regions), identical references (no region) or regions covering a large part of the label make
   the stage give up — choosing between them by photo noise would be a coin toss.
3. The query label is aligned to the same frame (only now: the checks above need no query) and its
   lightness is normalised to the anchor reference outside the regions (bottle lighting differs from catalog photos).
4. Each region is located in the query by its surrounding context, which is common to all twins (small
   shift and scale search: a bottle label is curved, not flat), and its colour is compared with each twin:
   for a solid region (the blend tag) the median colour of the differing pixels — lightness and hue count
   fully, saturation only a little, since phone cameras change saturation much more than hue; for thin print
   (a red vintage against a grey one) the tint of the ink relative to the paper, which survives the blur of
   small catalog images (see `_ink_tint`). The ink is found in every image separately, so a pixel of
   misalignment does not matter. A region votes with the weight of how much the twins differ in it; a region
   where the references differ less than `min_region_spread` in the measured colour does not vote at all. The twin with the smallest area-weighted colour distance wins when it is
   clearly closer than the second one with the first and with the last reference as the anchor alike;
   otherwise the original order is kept.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Hashable
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class TwinResolution:
    order: list[int] | None  # indices of the input references, best first; None when the stage gave up
    distances: list[float] | None  # colour distance of the query to each reference (input order)
    reason: str


@dataclass(frozen=True)
class _Prepared:
    """Reference-only part of a resolution, reusable for every photo of the same twins."""

    anchor: tuple  # SIFT keypoints and descriptors of the first reference
    labs: list[np.ndarray]  # references aligned to the first one, blurred Lab
    mean_reference: np.ndarray
    valid: np.ndarray  # pixels covered by every aligned reference
    strokes: np.ndarray  # pixels where the references differ
    mask: np.ndarray  # strokes merged into regions
    components: np.ndarray  # region labels of `mask`
    regions: list[tuple]  # (component, x, y, w, h, area, solid core mask or None for thin print)


class TwinResolver:
    def __init__(
        self,
        frame_size: int = 518,
        max_query_side: int = 1036,
        good_inliers: int = 60,
        max_features: int = 4000,
        min_inliers: int = 25,
        diff_threshold: float = 12.0,
        max_background_difference: float = 2.0,
        min_reference_inliers: int = 80,
        max_difference_fraction: float = 0.06,
        max_regions: int = 4,
        merge_size: int = 15,
        min_region_side: int = 16,
        max_region_aspect: float = 6.0,
        tint_scale: float = 40.0,
        min_region_spread: float = 6.0,
        border_fraction: float = 0.04,
        min_region_pixels: int = 20,
        min_region_share: float = 0.2,
        max_region_fraction: float = 0.08,
        context_margin: int = 12,
        shift_fraction: float = 0.05,
        refine_shift: int = 12,
        scales: tuple[float, ...] = (0.85, 0.92, 1.0, 1.08, 1.17, 1.26),
        chroma_weight: float = 0.25,
        max_distance_ratio: float = 0.8,
        cache_size: int = 64,
    ):
        self.frame_size = frame_size
        self.max_query_side = max_query_side
        self.good_inliers = good_inliers
        self.max_features = max_features
        self.min_inliers = min_inliers
        self.diff_threshold = diff_threshold
        self.max_background_difference = max_background_difference
        self.min_reference_inliers = min_reference_inliers
        self.max_difference_fraction = max_difference_fraction
        self.max_regions = max_regions
        self.merge_size = merge_size
        self.min_region_side = min_region_side
        self.max_region_aspect = max_region_aspect
        self.tint_scale = tint_scale
        self.min_region_spread = min_region_spread
        self.border_fraction = border_fraction
        self.min_region_pixels = min_region_pixels
        self.min_region_share = min_region_share
        self.max_region_fraction = max_region_fraction
        self.context_margin = context_margin
        self.shift_fraction = shift_fraction
        self.refine_shift = refine_shift
        self.scales = scales
        self.chroma_weight = chroma_weight
        self.max_distance_ratio = max_distance_ratio
        self.cache_size = cache_size
        self._cache: OrderedDict[tuple, _Prepared | TwinResolution] = OrderedDict()
        self._cache_lock = threading.Lock()

    def resolve(self, query: Image.Image, references: list[Image.Image], key: Hashable | None = None) -> TwinResolution:
        """Resolves twice, with the first and with the last reference as the alignment anchor; the order is changed
        only when both runs pick the same twin (one anchor can align the query slightly off a small detail).

        `key` identifies the references (their media paths): the reference-only work — SIFT, alignment, regions —
        is cached under it, since the same twins come back for every photo of them.
        """
        if len(references) < 2:
            return TwinResolution(None, None, "Меньше двух близнецов")
        query_rgb = np.array(query.convert("RGB"))
        views: dict[int, tuple[np.ndarray, tuple]] = {}
        first = self._resolve_once(query_rgb, views, self._prepared(references, key, reverse=False))
        if first.order is None:
            return first
        reverse = self._resolve_once(query_rgb, views, self._prepared(references, key, reverse=True))
        last = len(references) - 1
        if reverse.order is None or last - reverse.order[0] != first.order[0]:
            return TwinResolution(None, first.distances, "Выбор близнеца зависит от опорного эталона: порядок не меняется")
        return first

    def _prepared(self, references: list[Image.Image], key: Hashable | None, reverse: bool) -> _Prepared | TwinResolution:
        ordered = references[::-1] if reverse else references
        if key is None:
            return self._prepare(ordered)
        cache_key = (key, reverse)
        with self._cache_lock:
            if cache_key in self._cache:
                self._cache.move_to_end(cache_key)
                return self._cache[cache_key]
        prepared = self._prepare(ordered)
        with self._cache_lock:
            self._cache[cache_key] = prepared
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
        return prepared

    def _prepare(self, references: list[Image.Image]) -> _Prepared | TwinResolution:
        """Steps 1–2: references aligned to the first one and the regions where they differ."""
        size = self.frame_size
        sift = cv2.SIFT_create(nfeatures=self.max_features)
        refs = [np.array(image.convert("RGB").resize((size, size), Image.Resampling.LANCZOS)) for image in references]
        anchor = sift.detectAndCompute(cv2.cvtColor(refs[0], cv2.COLOR_RGB2GRAY), None)

        # 1. References into the anchor frame
        aligned = [refs[0]]
        valid = np.full((size, size), 255, np.uint8)
        for index in range(1, len(refs)):
            features = sift.detectAndCompute(cv2.cvtColor(refs[index], cv2.COLOR_RGB2GRAY), None)
            homography, inliers = self._homography(features, anchor)
            if homography is None or inliers < self.min_reference_inliers:
                return TwinResolution(None, None, f"Эталон {index + 1} не совмещается с первым ({inliers} совпадений): не близнецы")
            aligned.append(cv2.warpPerspective(refs[index], homography, (size, size), borderMode=cv2.BORDER_REPLICATE))
            valid &= cv2.warpPerspective(np.full((size, size), 255, np.uint8), homography, (size, size), flags=cv2.INTER_NEAREST)

        valid = cv2.erode(valid, np.ones((9, 9), np.uint8)) > 0

        # 2. Discriminative regions
        labs = [self._lab(image) for image in aligned]
        difference = np.zeros((size, size), np.float32)
        for i in range(len(labs)):
            for j in range(i + 1, len(labs)):
                difference = np.maximum(difference, np.linalg.norm(labs[i] - labs[j], axis=2))
        background = float(np.median(difference[valid]))
        if background > self.max_background_difference:
            return TwinResolution(None, None, f"Эталоны — разные фото (фоновое отличие {background:.1f}), а не близнецы")
        strokes = ((difference > self.diff_threshold) & valid).astype(np.uint8)
        differing = float(strokes[valid].mean())
        if differing > self.max_difference_fraction:
            return TwinResolution(None, None, f"Эталоны различаются на {differing:.0%} этикетки: это разные этикетки одной серии, а не близнецы")
        strokes = cv2.morphologyEx(strokes, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        # Straight line pieces are label edges of slightly shifted photos; drop them before merging, or a merged
        # blob would swallow a real detail next to the edge (the «Фантом» tag sits by the label edge)
        count, components, stats, _ = cv2.connectedComponentsWithStats(strokes)
        for component in range(1, count):
            w, h = int(stats[component, 2]), int(stats[component, 3])
            if max(w, h) >= 15 and max(w, h) >= self.max_region_aspect * min(w, h):
                strokes[components == component] = 0
        mask = cv2.dilate(strokes, np.ones((self.merge_size, self.merge_size), np.uint8))
        solid = cv2.morphologyEx(strokes, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        count, components, stats, _ = cv2.connectedComponentsWithStats(mask)
        border = int(round(self.border_fraction * size))
        candidates = []
        for component in range(1, count):
            x, y, w, h, area = (int(v) for v in stats[component])
            if min(w, h) < self.min_region_side or max(w, h) > self.max_region_aspect * min(w, h):
                continue  # label edges of slightly shifted catalog photos, not a label detail
            if x < border or y < border or x + w > size - border or y + h > size - border:
                continue  # the edge of the crop: bottle and label boundary, not a printed detail
            inside = components == component
            # A solid region survives a 5×5 opening of the differing pixels; thin print does not
            core = (solid > 0) & inside
            pixels = int((strokes[inside] > 0).sum())
            candidates.append((component, x, y, w, h, area, core if core.sum() >= 0.5 * pixels else None, pixels))
        # Specks of resampling noise are dropped next to the real difference
        largest = max((candidate[7] for candidate in candidates), default=0)
        regions = [c[:7] for c in candidates if c[7] >= max(self.min_region_pixels, self.min_region_share * largest)]
        if not regions:
            return TwinResolution(None, None, "Эталоны близнецов не различаются")
        if len(regions) > self.max_regions:
            return TwinResolution(None, None, f"Эталоны различаются в {len(regions)} местах: это разные фото, а не близнецы")
        if sum(region[5] for region in regions) > self.max_region_fraction * size * size:
            return TwinResolution(None, None, "Эталоны различаются на большой части этикетки: это разные фото, а не близнецы")

        return _Prepared(anchor, labs, np.mean(labs, axis=0), valid, strokes, mask, components, regions)

    def _resolve_once(self, query_rgb: np.ndarray, views: dict, prepared: _Prepared | TwinResolution) -> TwinResolution:
        """Steps 3–4 for one anchor."""
        if isinstance(prepared, TwinResolution):
            return prepared
        size = self.frame_size
        labs, valid, strokes, mask, components = prepared.labs, prepared.valid, prepared.strokes, prepared.mask, prepared.components

        # 3. Query into the anchor frame, lightness normalised to the anchor outside the regions
        query_rgb, homography, inliers = self._align_query(query_rgb, views, prepared.anchor)
        if homography is None:
            return TwinResolution(None, None, f"Фото не совмещается с эталоном ({inliers} совпадений)")
        warped_query = cv2.warpPerspective(query_rgb, homography, (size, size), flags=cv2.INTER_AREA, borderMode=cv2.BORDER_REPLICATE)
        query_valid = cv2.warpPerspective(np.full(query_rgb.shape[:2], 255, np.uint8), homography, (size, size), flags=cv2.INTER_NEAREST) > 0
        query_lab = self._normalise(self._lab(warped_query), labs[0], valid & query_valid & (mask == 0))

        # 4. Region colour of the query against each twin
        mean_reference = prepared.mean_reference
        distances = np.zeros(len(labs), np.float64)
        total_weight = 0.0
        for component, x, y, w, h, _area, core in prepared.regions:
            if query_valid[(components == component) & (strokes > 0)].mean() < 0.95:
                continue  # this part of the label is not in the photo
            located = self._locate(query_lab, mean_reference, components == component, x, y, w, h)
            if located is None:
                continue
            found, region_scale, box = located
            left, top, right, bottom = box
            patches = [cv2.resize(lab[top:bottom, left:right], None, fx=region_scale, fy=region_scale) for lab in labs]
            if core is not None:
                pixels = self._scaled(core, box, region_scale)
                colours = [np.median(patch[pixels], axis=0) for patch in patches]
                query_colour = np.median(found[pixels], axis=0)
                region_distances = [self._colour_distance(colour, query_colour) for colour in colours]
                spread = max(self._colour_distance(a, b) for i, a in enumerate(colours) for b in colours[i + 1:])
            else:
                # Only around the differing strokes: unchanged print next to them (black letters by a red
                # vintage) would dominate the ink and hide its tint
                differing = cv2.dilate(((components == component) & (strokes > 0)).astype(np.uint8), np.ones((5, 5), np.uint8))
                pixels = self._scaled(differing, box, region_scale)
                query_tint = self._ink_tint(found[pixels])
                tints = [self._ink_tint(patch[pixels]) for patch in patches]
                if query_tint is None or any(tint is None for tint in tints):
                    continue  # no print found here in some image: no evidence, not «colourless print»
                region_distances = [self.tint_scale * float(np.linalg.norm(tint - query_tint)) for tint in tints]
                spread = max(self.tint_scale * float(np.linalg.norm(a - b)) for i, a in enumerate(tints) for b in tints[i + 1:])
            if spread < self.min_region_spread:
                continue  # the references barely differ here in what is measured: noise, not evidence
            # A region votes with the weight of how much the twins differ in it
            distances += spread * np.asarray(region_distances)
            total_weight += spread
        if total_weight == 0.0:
            return TwinResolution(None, None, "Области различия близнецов не видны на фото или не различают эталоны")
        distances /= total_weight
        order = [int(i) for i in np.argsort(distances, kind="stable")]
        best, second = distances[order[0]], distances[order[1]]
        rounded = [round(float(d), 2) for d in distances]
        if best > self.max_distance_ratio * second:
            return TwinResolution(None, rounded, f"Близнецы не различимы на фото: отличие {best:.1f} против {second:.1f}")
        return TwinResolution(order, rounded, f"Выбран по области различия близнецов: отличие {best:.1f} против {second:.1f}")

    def _align_query(self, query_rgb: np.ndarray, views: dict, anchor) -> tuple[np.ndarray, np.ndarray | None, int]:
        """Homography of the query into the anchor frame, tried at several query sizes.

        A phone photo can be 10× larger than the catalog label: at full size SIFT finds the fine print the
        catalog image does not have, and RANSAC may fit a degenerate homography to wrong matches. The query is
        tried at the catalog scale and larger; implausible homographies are rejected, the most inliers win.
        The query's features per size are kept in `views` for the second anchor.
        """
        best: tuple[np.ndarray, np.ndarray | None, int] = (query_rgb, None, 0)
        longest = max(query_rgb.shape[:2])
        for side in sorted({self.frame_size, 2 * self.frame_size, self.max_query_side}):
            scale = min(1.0, side / longest)
            if side not in views:
                resized = cv2.resize(query_rgb, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1.0 else query_rgb
                sift = cv2.SIFT_create(nfeatures=self.max_features)
                views[side] = (resized, sift.detectAndCompute(cv2.cvtColor(resized, cv2.COLOR_RGB2GRAY), None))
            resized, features = views[side]
            homography, inliers = self._homography(features, anchor)
            if homography is not None and self._plausible(homography, resized.shape[:2]) and inliers > best[2]:
                best = (resized, homography, inliers)
            elif best[1] is None:
                best = (best[0], None, max(best[2], inliers))
            if scale == 1.0 or (best[1] is not None and best[2] >= self.good_inliers):
                break  # the smallest size that aligns well is enough: larger ones cost SIFT time
        return best

    def _plausible(self, homography: np.ndarray, shape: tuple[int, int]) -> bool:
        """The photo's corners must land on a convex quadrilateral of sensible size in the anchor frame."""
        h, w = shape
        corners = cv2.perspectiveTransform(np.float32([[[0, 0]], [[w, 0]], [[w, h]], [[0, h]]]), homography)
        if not np.isfinite(corners).all() or not cv2.isContourConvex(corners.astype(np.float32)):
            return False
        area = cv2.contourArea(corners.astype(np.float32)) / float(self.frame_size**2)
        return 0.1 <= area <= 10.0

    def _locate(self, query_lab, mean_reference, region, x, y, w, h):
        """Finds the region in the query by its context; returns (query window, scale, reference box)."""
        size = self.frame_size
        margin, shift = self.context_margin, max(2, int(round(self.shift_fraction * size)))
        left, top = max(0, x - margin), max(0, y - margin)
        right, bottom = min(size, x + w + margin), min(size, y + h + margin)
        best = None
        for region_scale in self.scales:
            template = cv2.resize(mean_reference[top:bottom, left:right], None, fx=region_scale, fy=region_scale)
            inside = cv2.resize(region[top:bottom, left:right].astype(np.uint8), None, fx=region_scale, fy=region_scale,
                                interpolation=cv2.INTER_NEAREST) > 0
            context = (~inside).astype(np.float32)
            search_left, search_top = max(0, left - shift), max(0, top - shift)
            search = query_lab[search_top:min(size, search_top + template.shape[0] + 2 * shift),
                               search_left:min(size, search_left + template.shape[1] + 2 * shift)]
            if search.shape[0] < template.shape[0] or search.shape[1] < template.shape[1] or context.sum() == 0:
                continue
            # Normalised correlation of lightness: a soft low-contrast catalog template would otherwise match
            # blank paper better than the sharp print it shows
            result = cv2.matchTemplate(np.ascontiguousarray(search[..., 0]), np.ascontiguousarray(template[..., 0]),
                                       cv2.TM_CCOEFF_NORMED, mask=context)
            result[~np.isfinite(result)] = -1.0
            row, column = np.unravel_index(int(np.argmax(result)), result.shape)
            error = -float(result[row, column])
            if best is None or error < best[0]:
                best = (error, search, template, int(row), int(column), region_scale)
        if best is None:
            return None
        _, search, template, row, column, region_scale = best
        # The context fixes the neighbourhood; the whole template, the detail included, snaps onto it (a few
        # pixels matter for thin print)
        refine = self.refine_shift
        top_row, left_column = max(0, row - refine), max(0, column - refine)
        window = search[top_row:min(search.shape[0], row + refine + template.shape[0]),
                        left_column:min(search.shape[1], column + refine + template.shape[1])]
        result = cv2.matchTemplate(np.ascontiguousarray(window[..., 0]), np.ascontiguousarray(template[..., 0]), cv2.TM_CCOEFF_NORMED)
        result[~np.isfinite(result)] = -1.0
        offset_row, offset_column = np.unravel_index(int(np.argmax(result)), result.shape)
        row, column = top_row + int(offset_row), left_column + int(offset_column)
        return search[row:row + template.shape[0], column:column + template.shape[1]], region_scale, (left, top, right, bottom)

    @staticmethod
    def _scaled(region_mask: np.ndarray, box: tuple[int, int, int, int], region_scale: float) -> np.ndarray:
        left, top, right, bottom = box
        return cv2.resize(region_mask[top:bottom, left:right].astype(np.uint8), None, fx=region_scale, fy=region_scale,
                          interpolation=cv2.INTER_NEAREST) > 0

    @staticmethod
    def _ink_tint(values: np.ndarray) -> np.ndarray | None:
        """Colour of thin print relative to the paper: mean (Δa, Δb) of the ink per unit of its lightness contrast.

        Blur of a small catalog image mixes thin strokes with the paper and fades their colour, but it scales the
        chroma and the lightness contrast alike, so their ratio survives: a red vintage stays red, a grey one grey.
        """
        deviation = values - np.median(values, axis=0)
        # Print is darker than paper; the lighter pixels are glare on the bottle and would bias the tint
        contrast = np.maximum(-deviation[:, 0], 0.0)
        ink = contrast >= max(4.0, float(np.percentile(contrast, 75)))
        if ink.sum() < 5:
            return None
        return deviation[ink, 1:].mean(axis=0) / float(contrast[ink].mean())

    def _colour_distance(self, reference: np.ndarray, query: np.ndarray) -> float:
        delta_l = reference[0] - query[0]
        chroma_reference, chroma_query = float(np.hypot(reference[1], reference[2])), float(np.hypot(query[1], query[2]))
        delta_c = chroma_reference - chroma_query
        delta_h_squared = max(0.0, float((reference[1] - query[1]) ** 2 + (reference[2] - query[2]) ** 2) - delta_c**2)
        return float(np.sqrt(delta_l**2 + delta_h_squared + self.chroma_weight * delta_c**2))

    def _homography(self, source, target) -> tuple[np.ndarray | None, int]:
        source_points, source_descriptors = source
        target_points, target_descriptors = target
        if source_descriptors is None or target_descriptors is None or len(source_points) < 4 or len(target_points) < 4:
            return None, 0
        # Brute force, not FLANN: randomised kd-trees give a slightly different homography (and mask) on every call
        matches = cv2.BFMatcher(cv2.NORM_L2).knnMatch(source_descriptors, target_descriptors, k=2)
        good = [pair[0] for pair in matches if len(pair) == 2 and pair[0].distance < 0.75 * pair[1].distance]
        if len(good) < self.min_inliers:
            return None, len(good)
        src = np.float32([source_points[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32([target_points[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        homography, inlier_mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
        inliers = int(inlier_mask.sum()) if inlier_mask is not None else 0
        if homography is None or inliers < self.min_inliers:
            return None, inliers
        return homography, inliers

    @staticmethod
    def _lab(rgb: np.ndarray) -> np.ndarray:
        blurred = cv2.GaussianBlur(rgb, (0, 0), 1.5)
        return cv2.cvtColor(blurred.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)

    @staticmethod
    def _normalise(query: np.ndarray, reference: np.ndarray, region: np.ndarray) -> np.ndarray:
        if region.sum() < 100:
            return query
        result = query.copy()
        q, r = query[..., 0][region], reference[..., 0][region]
        result[..., 0] = (query[..., 0] - q.mean()) * float(r.std() / max(q.std(), 1e-3)) + r.mean()
        return result
