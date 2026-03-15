"""
spell_matcher.py — Spell shape matcher using DTW
=================================================
Compares a recorded wand trail against a spell template using
Dynamic Time Warping on normalised, resampled point sequences.

- Trail is centred + scaled before resampling.
- Savitzky-Golay filter smooths the resampled trail without destroying
  shape extremes (replaces pre-integration EMA for shape comparison).
- 8-rotation search (every 45°) handles any in-plane orientation.
- Each candidate is also tried reversed (direction-agnostic).
- match_all() scores every loaded template and returns a ranked list.
- Per-spell thresholds override the global default when provided.

Score is normalised to [0, 1]: 0 = perfect match, 1 = no match.
"""

import numpy as np
from scipy.spatial.distance import cdist
from scipy.signal import savgol_filter
from spell_shapes import normalise, _resample, RESAMPLE_N
from typing import Optional

DEFAULT_THRESHOLD = 0.25

MIN_TRAIL_PTS = 20

_ANGLES_DEG = [0, 45, 90, 135, 180, 225, 270, 315]

# Per-spell threshold overrides.  Spells with distinct, unambiguous shapes
# can afford a tighter threshold; broad/short shapes need more headroom.
# Tune these using the score distributions in feedback_log.csv.
PER_SPELL_THRESHOLDS: dict[str, float] = {
    # Examples — adjust based on your own feedback_log data:
    # "lumos":       0.20,
    # "nox":         0.20,
    # "expelliarmus": 0.28,
    # "bombarda":    0.30,
}


def _rotate(pts: np.ndarray, deg: float) -> np.ndarray:
    rad = np.radians(deg)
    c, s = np.cos(rad), np.sin(rad)
    return pts @ np.array([[c, -s], [s, c]]).T


def _dtw_distance(a: np.ndarray, b: np.ndarray) -> float:
    """Normalised DTW distance between two (N, 2) arrays."""
    n, m = len(a), len(b)
    D = cdist(a, b, metric="euclidean")
    dtw = np.full((n + 1, m + 1), np.inf)
    dtw[0, 0] = 0.0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = D[i - 1, j - 1]
            dtw[i, j] = cost + min(dtw[i - 1, j], dtw[i, j - 1], dtw[i - 1, j - 1])
    return dtw[n, m] / (n + m)


def _best_score(trail_n: np.ndarray, tmpl_n: np.ndarray) -> float:
    """DTW over 8 rotations × forward+reverse = 16 candidates."""
    best = np.inf
    for deg in _ANGLES_DEG:
        rotated = _rotate(trail_n, deg)
        d = _dtw_distance(rotated, tmpl_n)
        if d < best:
            best = d
        d_rev = _dtw_distance(rotated[::-1], tmpl_n)
        if d_rev < best:
            best = d_rev
        if best == 0.0:
            return 0.0
    return best


def _smooth_trail(pts: np.ndarray) -> np.ndarray:
    """Apply Savitzky-Golay filter to a resampled trail.

    Unlike pre-integration EMA, SG smoothing operates on the final
    resampled shape and preserves extremes (corners, direction reversals)
    while removing high-frequency sensor noise.
    Window=7, poly=2 works well for RESAMPLE_N=64.
    Falls back gracefully if the trail is too short.
    """
    n = len(pts)
    if n < 7:
        return pts
    # Window must be odd and <= n; shrink to fit short trails
    win = min(7, n if n % 2 == 1 else n - 1)
    smoothed = pts.copy()
    smoothed[:, 0] = savgol_filter(pts[:, 0], win, 2)
    smoothed[:, 1] = savgol_filter(pts[:, 1], win, 2)
    return smoothed


def _prepare_trail(trail: np.ndarray) -> np.ndarray:
    """Normalise, resample, smooth, and re-normalise a raw wand trail."""
    trail_n  = normalise(trail.astype(float))
    # Adaptive resample count: don't upsample short gestures too aggressively
    n_pts = min(RESAMPLE_N, max(len(trail) // 2, 20))
    trail_rs = _resample(list(map(tuple, trail_n)), n_pts)
    trail_sm = _smooth_trail(trail_rs)
    return normalise(trail_sm)


class SpellMatcher:
    def __init__(self, threshold: float = DEFAULT_THRESHOLD,
                 per_spell_thresholds: Optional[dict] = None):
        self.threshold  = threshold
        self._per_spell = dict(PER_SPELL_THRESHOLDS)
        if per_spell_thresholds:
            self._per_spell.update(per_spell_thresholds)

    def spell_threshold(self, spell_name: str) -> float:
        """Return the threshold for a specific spell (falls back to global)."""
        return self._per_spell.get(spell_name.lower(), self.threshold)

    def match(self, trail: np.ndarray, template: Optional[np.ndarray],
              spell_name: str = "") -> dict:
        """Compare a raw wand trail against a single spell template."""
        thresh = self.spell_threshold(spell_name) if spell_name else self.threshold
        fail = {"success": False, "score": 1.0, "threshold": thresh}
        if template is None or len(trail) < MIN_TRAIL_PTS:
            return fail

        trail_n2   = _prepare_trail(trail)
        raw_score  = _best_score(trail_n2, template.copy())
        score_norm = round(min(raw_score / 0.8, 1.0), 4)

        return {
            "success":   score_norm <= thresh,
            "score":     score_norm,
            "threshold": thresh,
        }

    def match_all(self, trail: np.ndarray, library) -> list:
        """Score every template in *library* and return results sorted best-first.

        Each entry is a dict with keys:
          spell, score, threshold, success
        The caller should use entry["success"] on the first (best) result to
        decide whether a spell was cast, and can display runner-up entries as
        hints.
        """
        if len(trail) < MIN_TRAIL_PTS:
            return []

        # Pre-process trail once — reused for all templates
        trail_n2 = _prepare_trail(trail)

        results = []
        for name in library.names():
            template = library.get(name)
            if template is None:
                continue
            raw_score  = _best_score(trail_n2, template.copy())
            score_norm = round(min(raw_score / 0.8, 1.0), 4)
            thresh     = self.spell_threshold(name)
            results.append({
                "spell":     name,
                "score":     score_norm,
                "threshold": thresh,
                "success":   score_norm <= thresh,
            })

        results.sort(key=lambda r: r["score"])
        return results
