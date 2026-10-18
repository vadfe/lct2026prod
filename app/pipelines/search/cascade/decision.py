"""Answer zones of the cascade: found / probable / not_in_catalog.

similarity — уверенность по первому каскаду (DINOv2) для победителя,
определенного вторым каскадом (SigLIP 2 score fusion);
margin — отрыв по баллам fusion (или DINOv2) между первым и вторым кандидатом.

* not_in_catalog: similarity < 0.55.
* found: similarity >= found_min_similarity (0.83) и margin >= found_min_margin (0.15).
* probable: все промежуточные случаи (близкие соседи, винные близнецы).
"""

from __future__ import annotations

from dataclasses import dataclass

FOUND = "found"
PROBABLE = "probable"
NOT_IN_CATALOG = "not_in_catalog"

MESSAGES = {
    FOUND: "Вино найдено в каталоге",
    PROBABLE: "Похоже на это вино — сверьте название, год и цвет с этикеткой",
    NOT_IN_CATALOG: "Данного вина нет в каталоге",
}


@dataclass(frozen=True)
class RecognitionThresholds:
    found_min_similarity: float = 0.83
    found_min_margin: float = 0.15
    reject_below_similarity: float = 0.55


def classify(similarity: float | None, margin: float | None, thresholds: RecognitionThresholds) -> tuple[str, str]:
    """Returns (status, human-readable reason).

    similarity передается как собственная уверенность победителя из первого каскада (DINOv2).
    """
    if similarity is None:
        return PROBABLE, "Кандидаты не найдены: уверенность не оценивается"
    if similarity < thresholds.reject_below_similarity:
        return NOT_IN_CATALOG, (
            f"Сходство с лучшим вином каталога {similarity:.3f} < {thresholds.reject_below_similarity:.3f}: "
            "ниже порога «нет в каталоге»"
        )
    gap = margin if margin is not None else float("inf")
    if similarity >= thresholds.found_min_similarity and gap >= thresholds.found_min_margin:
        return FOUND, (
            f"Сходство {similarity:.3f} ≥ {thresholds.found_min_similarity:.3f} "
            f"и отрыв от второго кандидата {gap:.3f} ≥ {thresholds.found_min_margin:.3f}"
        )
    if similarity < thresholds.found_min_similarity:
        return PROBABLE, f"Сходство {similarity:.3f} ниже порога уверенного ответа {thresholds.found_min_similarity:.3f}"
    return PROBABLE, f"Близкий второй кандидат: отрыв {gap:.3f} < {thresholds.found_min_margin:.3f}"
