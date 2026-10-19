"""
spell_matcher.py — Spell shape matcher using DTW
=================================================
Compares a recorded wand trail against spell templates using Dynamic Time
Warping over position + stroke direction.

- Trail is resampled by arc length, smoothed, and its head/tail trimmed
  (grip-settle and release wobble).
- Shapes are centred and scaled by their larger bounding-box side, so
  aspect ratio is kept and a mostly-straight stroke isn't blown up.
- Each point carries its position AND its unit stroke direction, so a sharp
  corner and a smooth curve no longer look alike.
- Orientation is known (motion.py's trail is gravity-referenced: +y is up),
  so only a small tilt search is done — no 45° rotations, no reversal.
  Lumos (Λ, left→right) must not match Expelliarmus (┐) or itself backwards.
- DTW is limited to a Sakoe-Chiba band and vectorised along anti-diagonals.
- A cast is only accepted when the best score is under that spell's
  threshold AND clearly beats the runner-up (MARGIN_RATIO).

Score: mean per-step DTW cost, lower is better (0 = identical).
Tune thresholds with eval_matcher.py against labelled casts in casts/.
"""

import numpy as np
from scipy.signal import savgol_filter
from spell_shapes import _resample, RESAMPLE_N
from typing import Optional

DEFAULT_THRESHOLD = 0.30

# Best score must be at most this fraction of the runner-up's score,
# i.e. runner-up / best >= MARGIN_RATIO.  Rejects ambiguous casts.
MARGIN_RATIO = 1.25

MIN_TRAIL_PTS = 20

# Small tilt search only: the trail's "up" is real world-up.
TILT_DEG = (-20, -10, 0, 10, 20)

# Weight of the stroke-direction term relative to position.
DIR_WEIGHT = 0.5

# DTW band half-width as a fraction of the sequence length.
BAND_FRAC = 0.15

# Fraction of path length trimmed from each end of a trail.
TRIM_FRAC = 0.03

# Per-spell threshold overrides.  Spells with distinct, unambiguous shapes
# can afford a tighter threshold; broad/short shapes need more headroom.
# eval_matcher.py prints suggested values from your labelled casts.
PER_SPELL_THRESHOLDS: dict[str, float] = {
}


def _rotate(pts: np.ndarray, deg: float) -> np.ndarray:
    rad = np.radians(deg)
    c, s = np.cos(rad), np.sin(rad)
    return pts @ np.array([[c, -s], [s, c]]).T


def _normalise(pts: np.ndarray) -> np.ndarray:
    """Centre on the centroid; scale so the larger bbox side spans 2."""
    pts = pts - pts.mean(axis=0)
    span = float(np.ptp(pts, axis=0).max())
    return pts * (2.0 / span) if span > 1e-9 else pts


def _trim(pts: np.ndarray, frac: float) -> np.ndarray:
    """Drop the first and last *frac* of path length."""
    if frac <= 0 or len(pts) < 3:
        return pts
    seg = np.hypot(*np.diff(pts, axis=0).T)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    total = cum[-1]
    keep = (cum >= frac * total) & (cum <= (1 - frac) * total)
    return pts[keep] if keep.sum() >= 2 else pts


def _smooth(pts: np.ndarray) -> np.ndarray:
    """Savitzky-Golay on the resampled shape: removes jitter, keeps corners."""
    if len(pts) < 7:
        return pts
    out = pts.copy()
    out[:, 0] = savgol_filter(pts[:, 0], 7, 2)
    out[:, 1] = savgol_filter(pts[:, 1], 7, 2)
    return out


def _features(pts: np.ndarray) -> np.ndarray:
    """(N, 2) normalised points → (N, 4) [x, y, w·dx, w·dy] with unit direction."""
    d = np.gradient(pts, axis=0)
    n = np.hypot(d[:, 0], d[:, 1])[:, None]
    d = np.divide(d, n, out=np.zeros_like(d), where=n > 1e-9)
    return np.hstack([pts, DIR_WEIGHT * d])


def prepare(pts: np.ndarray, trim: float = 0.0) -> np.ndarray:
    """Raw points (trail in degrees, or a template) → normalised (N, 2) shape."""
    pts = np.asarray(pts, dtype=float)
    pts = _trim(pts, trim)
    pts = _resample(list(map(tuple, pts)), RESAMPLE_N)
    return _normalise(_smooth(pts))


def _dtw(a: np.ndarray, b: np.ndarray, band: int) -> float:
    """Banded DTW between two (N, F) feature arrays; returns mean step cost.

    Cells on anti-diagonal k = i + j depend only on diagonals k-1 and k-2,
    so each diagonal is computed in one numpy step.
    """
    n, m = len(a), len(b)
    C = np.sqrt(((a[:, None, :] - b[None, :, :]) ** 2).sum(-1))
    ii, jj = np.indices((n, m))
    C[np.abs(ii - jj) > band] = np.inf

    D = np.full((n + 1, m + 1), np.inf)
    D[0, 0] = 0.0
    for k in range(2, n + m + 1):
        i = np.arange(max(1, k - m), min(n, k - 1) + 1)
        j = k - i
        D[i, j] = C[i - 1, j - 1] + np.minimum(
            np.minimum(D[i - 1, j], D[i, j - 1]), D[i - 1, j - 1])
    return float(D[n, m] / (n + m))


def _best_score(trail_pts: np.ndarray, tmpl_feat: np.ndarray) -> float:
    """DTW over the small tilt search; trail_pts is a prepared (N, 2) shape."""
    band = max(1, int(BAND_FRAC * RESAMPLE_N))
    best = np.inf
    for deg in TILT_DEG:
        feat = _features(_normalise(_rotate(trail_pts, deg)))
        best = min(best, _dtw(feat, tmpl_feat, band))
    return best


class SpellMatcher:
    def __init__(self, threshold: float = DEFAULT_THRESHOLD,
                 per_spell_thresholds: Optional[dict] = None,
                 margin_ratio: float = MARGIN_RATIO):
        self.threshold    = threshold
        self.margin_ratio = margin_ratio
        self._per_spell = dict(PER_SPELL_THRESHOLDS)
        if per_spell_thresholds:
            self._per_spell.update(per_spell_thresholds)
        self._tmpl_cache: dict = {}

    def spell_threshold(self, spell_name: str) -> float:
        """Return the threshold for a specific spell (falls back to global)."""
        return self._per_spell.get(spell_name.lower(), self.threshold)

    def _template_features(self, template: np.ndarray) -> np.ndarray:
        key = template.tobytes()
        if key not in self._tmpl_cache:
            self._tmpl_cache[key] = _features(prepare(template))
        return self._tmpl_cache[key]

    def match(self, trail: np.ndarray, template: Optional[np.ndarray],
              spell_name: str = "") -> dict:
        """Compare a raw wand trail against a single spell template."""
        thresh = self.spell_threshold(spell_name) if spell_name else self.threshold
        fail = {"success": False, "score": 1.0, "threshold": thresh}
        if template is None or len(trail) < MIN_TRAIL_PTS:
            return fail

        score = round(_best_score(prepare(trail, TRIM_FRAC),
                                  self._template_features(template)), 4)
        return {"success": score <= thresh, "score": score, "threshold": thresh}

    def match_all(self, trail: np.ndarray, library) -> list:
        """Score every template in *library* and return results sorted best-first.

        Each entry is a dict with keys:
          spell, score, threshold, success, margin
        Only the first (best) entry can have success=True, and only when it is
        under its threshold and beats the runner-up by margin_ratio.  margin is
        runner-up score / best score (inf when there is no runner-up).
        """
        if len(trail) < MIN_TRAIL_PTS:
            return []

        # Pre-process trail once — reused for all templates
        trail_pts = prepare(trail, TRIM_FRAC)

        results = []
        for name in library.names():
            template = library.get(name)
            if template is None:
                continue
            score = round(_best_score(trail_pts, self._template_features(template)), 4)
            results.append({
                "spell":     name,
                "score":     score,
                "threshold": self.spell_threshold(name),
                "success":   False,
                "margin":    float("inf"),
            })

        results.sort(key=lambda r: r["score"])
        if results:
            best = results[0]
            if len(results) > 1:
                best["margin"] = (results[1]["score"] / best["score"]
                                  if best["score"] > 0 else float("inf"))
            best["success"] = (best["score"] <= best["threshold"]
                               and best["margin"] >= self.margin_ratio)
        return results
