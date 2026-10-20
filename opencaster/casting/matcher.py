"""
opencaster.casting.matcher — DTW spell recogniser
==================================================
Compares a wand trail against every template using Dynamic Time Warping over
position + stroke direction.

1. Prepare: trim TRIM_FRAC of path length from each end (grip settle and
   release wobble), resample to 64 points, Savitzky-Golay smooth, centre and
   scale by the larger bounding-box side (aspect ratio kept).
2. Features: each point carries its position and its unit stroke direction,
   so a sharp corner and a smooth curve don't look alike.
3. Compare: banded DTW against every template under a small tilt search
   (the trail is gravity-referenced, so no big rotations and no reversal:
   Lumos must not match itself drawn backwards).
4. Decide: accept the best spell only if its score is under its threshold
   AND the runner-up scores at least MARGIN_RATIO times worse.

Score = mean per-step DTW cost; lower is better (0 = identical).  All
templates and tilts are scored in one vectorised DTW pass.  Tune thresholds
with `python -m opencaster.casting evaluate`.
"""

from dataclasses import dataclass, replace
from typing import Optional, Sequence

import numpy as np
from scipy.signal import savgol_filter

from .shapes import RESAMPLE_N, resample, spell_key

DEFAULT_THRESHOLD = 0.30
MARGIN_RATIO      = 1.25        # runner-up / best must be at least this
MIN_TRAIL_PTS     = 20
TILT_DEG          = (-20, -10, 0, 10, 20)
DIR_WEIGHT        = 0.5         # stroke-direction term relative to position
BAND_FRAC         = 0.15        # DTW band half-width, fraction of length
TRIM_FRAC         = 0.03

# Per-spell threshold overrides, keyed by spell_key().  The evaluate command
# prints suggested values from your labelled casts.
PER_SPELL_THRESHOLDS: dict = {
}


@dataclass(frozen=True)
class Match:
    spell: str              # template display name
    key: str
    score: float
    threshold: float
    success: bool = False
    margin: float = float("inf")   # runner-up score / this score (best only)


# ── Shape preparation ──────────────────────────────────────────────────────────

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
    if frac <= 0 or len(pts) < 3:
        return pts
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(pts, axis=0).T))])
    keep = (cum >= frac * cum[-1]) & (cum <= (1 - frac) * cum[-1])
    return pts[keep] if keep.sum() >= 2 else pts


def _smooth(pts: np.ndarray) -> np.ndarray:
    if len(pts) < 7:
        return pts
    out = pts.copy()
    out[:, 0] = savgol_filter(pts[:, 0], 7, 2)
    out[:, 1] = savgol_filter(pts[:, 1], 7, 2)
    return out


def _features(pts: np.ndarray) -> np.ndarray:
    """(N, 2) shape → (N, 4) [x, y, w·dx, w·dy] with unit stroke direction."""
    d = np.gradient(pts, axis=0)
    n = np.hypot(d[:, 0], d[:, 1])[:, None]
    d = np.divide(d, n, out=np.zeros_like(d), where=n > 1e-9)
    return np.hstack([pts, DIR_WEIGHT * d])


def prepare(pts, trim: float = 0.0) -> np.ndarray:
    """Raw points (trail in degrees, or a template) → normalised (64, 2)."""
    pts = _trim(np.asarray(pts, dtype=float), trim)
    return _normalise(_smooth(resample(pts, RESAMPLE_N)))


# ── Batched DTW ────────────────────────────────────────────────────────────────

def _dtw_batch(a: np.ndarray, b: np.ndarray, band: int) -> np.ndarray:
    """Banded DTW for every pair: a (R, N, F) × b (T, M, F) → (R, T) mean
    step cost.  Cells on anti-diagonal k = i + j depend only on diagonals
    k-1 and k-2, so each diagonal of all R×T problems is one numpy step."""
    (r, n, f), (t, m, _) = a.shape, b.shape
    cost = np.zeros((r, t, n, m))
    for k in range(f):            # same summation order as a per-pair .sum(-1)
        cost += (a[:, None, :, None, k] - b[None, :, None, :, k]) ** 2
    cost = np.sqrt(cost)
    ii, jj = np.indices((n, m))
    cost[..., np.abs(ii - jj) > band] = np.inf

    d = np.full((r, t, n + 1, m + 1), np.inf)
    d[..., 0, 0] = 0.0
    for k in range(2, n + m + 1):
        i = np.arange(max(1, k - m), min(n, k - 1) + 1)
        j = k - i
        d[..., i, j] = cost[..., i - 1, j - 1] + np.minimum(
            np.minimum(d[..., i - 1, j], d[..., i, j - 1]), d[..., i - 1, j - 1])
    return d[..., n, m] / (n + m)


class SpellMatcher:
    def __init__(self, threshold: float = DEFAULT_THRESHOLD,
                 per_spell_thresholds: Optional[dict] = None,
                 margin_ratio: float = MARGIN_RATIO):
        self.threshold = threshold
        self.margin_ratio = margin_ratio
        self._per_spell = dict(PER_SPELL_THRESHOLDS)
        self._per_spell.update({spell_key(k): v for k, v in (per_spell_thresholds or {}).items()})
        self._cache_pts: tuple = ()          # the template arrays the cache was built from
        self._cache_feat: Optional[np.ndarray] = None

    def threshold_for(self, name: str) -> float:
        return self._per_spell.get(spell_key(name), self.threshold)

    def _template_features(self, templates: Sequence) -> np.ndarray:
        pts = tuple(t.points for t in templates)
        if len(pts) != len(self._cache_pts) or any(a is not b for a, b in zip(pts, self._cache_pts)):
            self._cache_feat = np.stack([_features(prepare(p)) for p in pts])
            self._cache_pts = pts
        return self._cache_feat

    def scores(self, trail, templates: Sequence) -> np.ndarray:
        """Raw best-tilt DTW score of the trail against each template."""
        pts = prepare(trail, TRIM_FRAC)
        tilts = np.stack([_features(_normalise(_rotate(pts, deg))) for deg in TILT_DEG])
        band = max(1, int(BAND_FRAC * RESAMPLE_N))
        return _dtw_batch(tilts, self._template_features(templates), band).min(axis=0)

    def rank(self, trail, templates: Sequence) -> list:
        """Score every template; best first.  Only the best can succeed: under
        its threshold and beating the runner-up by margin_ratio."""
        if len(trail) < MIN_TRAIL_PTS or not templates:
            return []
        raw = self.scores(trail, templates)
        out = sorted((Match(t.name, t.key, round(float(s), 4), self.threshold_for(t.name))
                      for t, s in zip(templates, raw)), key=lambda m: m.score)
        best = out[0]
        margin = (out[1].score / best.score if best.score > 0 else float("inf")) \
            if len(out) > 1 else float("inf")
        out[0] = replace(best, margin=margin,
                         success=best.score <= best.threshold and margin >= self.margin_ratio)
        return out
