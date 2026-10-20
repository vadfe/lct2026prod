"""
Evaluation Metrics & Quality Gates
- Geometric Fidelity: MS-SSIM, MSE, NRMSE
- Text Legibility: Character Error Rate (CER), Levenshtein Distance, Jaro-Winkler
"""

import cv2
import numpy as np
from skimage.metrics import structural_similarity as ssim
from skimage.metrics import normalized_root_mse

def compute_image_metrics(img_test_bgr: np.ndarray, img_ref_bgr: np.ndarray) -> dict:
    """
    Computes Geometric Fidelity metrics between test (dewarped) image and reference (catalog) template.
    """
    # Resize test image to match reference image shape
    ref_h, ref_w = img_ref_bgr.shape[:2]
    test_resized = cv2.resize(img_test_bgr, (ref_w, ref_h), interpolation=cv2.INTER_LANCZOS4)

    # Convert to grayscale for structural similarity and error
    gray_test = cv2.cvtColor(test_resized, cv2.COLOR_BGR2GRAY)
    gray_ref = cv2.cvtColor(img_ref_bgr, cv2.COLOR_BGR2GRAY)

    # 1. MSE
    mse_val = float(np.mean((gray_test.astype(np.float64) - gray_ref.astype(np.float64)) ** 2))

    # 2. NRMSE
    try:
        nrmse_val = float(normalized_root_mse(gray_ref, gray_test))
    except Exception:
        nrmse_val = float(np.sqrt(mse_val) / (np.max(gray_ref) - np.min(gray_ref) + 1e-6))

    # 3. SSIM (Multi-scale structural similarity approximation)
    try:
        ssim_val, _ = ssim(gray_ref, gray_test, full=True)
        ssim_val = float(ssim_val)
    except Exception:
        ssim_val = 0.0

    return {
        "mse": round(mse_val, 2),
        "nrmse": round(nrmse_val, 4),
        "ssim": round(ssim_val, 4),
        "ssim_percent": round(max(0.0, ssim_val) * 100, 1)
    }

def levenshtein_distance(s1: str, s2: str) -> int:
    """Computes minimum edit distance between two strings."""
    m, n = len(s1), len(s2)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            dp[i][j] = min(
                dp[i - 1][j] + 1,       # deletion
                dp[i][j - 1] + 1,       # insertion
                dp[i - 1][j - 1] + cost # substitution
            )
    return dp[m][n]

def character_error_rate(hypothesis: str, reference: str) -> float:
    """Computes Character Error Rate (CER = Levenshtein / len(reference))."""
    if not reference:
        return 0.0 if not hypothesis else 1.0
    dist = levenshtein_distance(hypothesis, reference)
    return round(float(dist / len(reference)), 4)

def jaro_winkler_similarity(s1: str, s2: str, p: float = 0.1) -> float:
    """Computes Jaro-Winkler string similarity in [0, 1]."""
    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0

    max_dist = max(len1, len2) // 2 - 1
    match1 = [False] * len1
    match2 = [False] * len2
    matches = 0

    for i in range(len1):
        start = max(0, i - max_dist)
        end = min(i + max_dist + 1, len2)
        for j in range(start, end):
            if not match2[j] and s1[i] == s2[j]:
                match1[i] = True
                match2[j] = True
                matches += 1
                break

    if matches == 0:
        return 0.0

    t = 0
    k = 0
    for i in range(len1):
        if match1[i]:
            while not match2[k]:
                k += 1
            if s1[i] != s2[k]:
                t += 1
            k += 1
    t /= 2.0

    jaro = (matches / len1 + matches / len2 + (matches - t) / matches) / 3.0

    # Prefix match up to 4 chars
    prefix = 0
    for i in range(min(4, min(len1, len2))):
        if s1[i] == s2[i]:
            prefix += 1
        else:
            break

    return round(float(jaro + prefix * p * (1.0 - jaro)), 4)
