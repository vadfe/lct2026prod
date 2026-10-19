"""Tests for the twin resolver: labels that differ only by a small coloured tag."""

from __future__ import annotations

import cv2
import numpy as np
from PIL import Image

from app.services.twin_resolver import TwinResolver

TAGS = {"30/70": (214, 70, 110), "50/50": (110, 20, 40), "70/30": (165, 95, 200)}
BOTTLE = (25, 20, 18)


def label(tag_colour: tuple[int, int, int], seed: int = 7) -> np.ndarray:
    """A printed label: random words, a white side strip and a coloured blend tag on it (as «Фантом»)."""
    rng = np.random.default_rng(seed)
    image = np.full((500, 280, 3), 235, np.uint8)
    for _ in range(120):
        text = "".join(rng.choice(list("ABCDEFGHKMNPRSTWXYZ0123456789"), int(rng.integers(2, 6))))
        position = (int(rng.integers(45, 250)), int(rng.integers(10, 495)))
        font = int(rng.choice([0, 2, 3, 4]))
        cv2.putText(image, text, position, font, float(rng.uniform(0.4, 1.1)), (20, 20, 20), int(rng.integers(1, 3)))
    image[:, :40] = 245
    image[360:396, 6:36] = tag_colour
    return image


def catalog_reference(tag: str) -> Image.Image:
    """Catalog crop as stored in label.webp: a square YOLO box, the label in the middle of the bottle."""
    canvas = np.full((518, 518, 3), BOTTLE, np.uint8)
    canvas[9:509, 119:399] = label(TAGS[tag])
    return Image.fromarray(canvas)


def photo(tag: str, exposure: float = 1.15) -> Image.Image:
    """The label on a shelf: slight perspective, another scale and exposure, bottle around it."""
    image = label(TAGS[tag])
    h, w = image.shape[:2]
    target = np.float32([[90, 40], [395, 55], [390, 600], [85, 585]])
    matrix = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), target)
    warped = cv2.warpPerspective(image, matrix, (480, 640), borderValue=BOTTLE)
    return Image.fromarray(np.clip(warped.astype(np.float32) * exposure, 0, 255).astype(np.uint8))


def test_picks_the_twin_with_the_matching_tag_in_any_order():
    resolver = TwinResolver()
    query = photo("30/70")
    for names in (("50/50", "30/70", "70/30"), ("30/70", "50/50"), ("70/30", "50/50", "30/70")):
        result = resolver.resolve(query, [catalog_reference(name) for name in names])
        assert result.order is not None, result.reason
        assert names[result.order[0]] == "30/70"


def test_identical_references_are_not_resolved():
    result = TwinResolver().resolve(photo("30/70"), [catalog_reference("30/70"), catalog_reference("30/70")])
    assert result.order is None
    assert "не различаются" in result.reason


def test_different_photos_of_one_label_are_not_twins():
    # Same design, but the second catalog photo is warmer and noisier: differences are photo noise, not a detail
    rng = np.random.default_rng(1)
    other = np.asarray(catalog_reference("30/70"), np.float32) * np.array([1.0, 0.9, 0.75]) + rng.normal(0, 8, (518, 518, 3))
    references = [catalog_reference("30/70"), Image.fromarray(np.clip(other, 0, 255).astype(np.uint8))]
    assert TwinResolver().resolve(photo("30/70"), references).order is None


def test_unrelated_photo_is_not_resolved():
    unrelated = Image.fromarray(np.full((600, 400, 3), 128, np.uint8))
    result = TwinResolver().resolve(unrelated, [catalog_reference("30/70"), catalog_reference("50/50")])
    assert result.order is None
    assert "не совмещается" in result.reason


def vintage_label(ink: tuple[int, int, int]) -> np.ndarray:
    """«Поздний сбор»: the same label, the vintage printed in red (красное) or grey (белое) thin italics."""
    image = label(TAGS["50/50"])
    image[200:250, 60:250] = 235
    cv2.putText(image, "2023", (70, 240), cv2.FONT_HERSHEY_SCRIPT_SIMPLEX, 1.4, ink, 2, cv2.LINE_AA)
    return image


def test_thin_print_is_compared_by_ink_tint():
    red, grey = (200, 40, 50), (120, 120, 120)
    references = []
    for ink in (grey, red):
        canvas = np.full((518, 518, 3), BOTTLE, np.uint8)
        # Catalog images are small and soft: the thin red strokes fade, their tint relative to the paper stays
        canvas[9:509, 119:399] = cv2.GaussianBlur(vintage_label(ink), (0, 0), 1.2)
        references.append(Image.fromarray(canvas))
    image = vintage_label(red)
    h, w = image.shape[:2]
    matrix = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), np.float32([[90, 40], [395, 55], [390, 600], [85, 585]]))
    query = Image.fromarray(cv2.warpPerspective(image, matrix, (480, 640), borderValue=BOTTLE))
    for order in ([0, 1], [1, 0]):
        result = TwinResolver().resolve(query, [references[i] for i in order])
        assert result.order is not None, result.reason
        assert order[result.order[0]] == 1
