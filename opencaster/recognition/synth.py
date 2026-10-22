"""
opencaster.recognition.synth — Synthetic casts for tuning the matcher
=====================================================================
Real labelled casts are few per spell, so per-spell thresholds fitted to them
are guesses.  This makes thousands of human-like casts from the templates and
thousands of near-misses that must be rejected, scores them all once, and
fits a threshold per spell from the raw scores.

1. Spells: each template perturbed the way a hand and the gyro trail distort
   it — residual tilt, per-axis stretch, rounded corners, a low-frequency
   wobble, a clipped start and end — then laid out as a trail in degrees
   with points every 0.3°, like the tracker's.  NOISE is calibrated so the
   median own-template score matches real casts'.
2. Near-misses: the first part of a spell, a spell drawn backwards, two
   different spells blended, and random scribbles, perturbed the same way.
   A near-miss whose clean shape already scores under IS_SPELL against some
   template is a real drawing of that spell (half of Herbivicus is Protego),
   so it is dropped rather than counted as a negative.
3. Fit: a cast's decision depends only on its best spell's threshold (the
   runner-up margin uses raw scores), so each spell's threshold is chosen
   independently: the one maximising own accepts − fa_weight × other accepts,
   within THRESHOLD_RANGE, preferring the default among equals.  Spells with
   fewer than MIN_FIT accepts keep the default.

Trails are generated in the parent from one seed and only scoring runs in the
process pool (or on the GPU, see gpu.py), so results don't depend on the
number of jobs or the backend beyond float32 rounding.
"""

import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
from scipy.ndimage import gaussian_filter1d

from ..casting.castlog import trail_extent
from ..casting.matcher import DEFAULT_THRESHOLD, MARGIN_RATIO, MIN_TRAIL_PTS, SpellMatcher
from ..casting.session import MIN_GESTURE_DEG
from ..casting.shapes import SpellLibrary, resample

NOISE           = 1.5           # synthetic own-template median ≈ real casts'
SHAPE_N         = 200           # points a template is resampled to before perturbing
POINT_STEP_DEG  = 0.3           # trail point spacing, as the tracker's min_step
SPAN_DEG        = (50, 120)     # gesture size in degrees
NEAR_MISS_MIX   = (("half", 0.4), ("reversed", 0.2), ("blend", 0.2), ("scribble", 0.2))
IS_SPELL        = 0.10          # clean near-miss scoring under this is a real spell drawing
THRESHOLD_RANGE = (0.10, 0.40)
THRESHOLD_STEP  = 0.005
MIN_FIT         = 20            # own accepts needed before a spell's threshold is fitted

SPELL = "spell"
GATED = np.inf                  # score vector of a trail gated as too short / too small


@dataclass
class Synthetic:
    """One scored batch.  scores[i] holds cast i's raw score per template
    (all GATED if the trail was gated); source is the template index it was
    made from (-1 for scribbles)."""
    keys: np.ndarray            # (T,) template keys, in score-column order
    kind: np.ndarray            # (N,) SPELL or a near-miss kind
    source: np.ndarray          # (N,)
    scores: np.ndarray          # (N, T)
    dropped: int = 0            # near-misses dropped as real spell drawings

    def save(self, path: str):
        np.savez_compressed(path, keys=self.keys, kind=self.kind, source=self.source,
                            scores=self.scores, dropped=self.dropped)

    @classmethod
    def load(cls, path: str) -> "Synthetic":
        z = np.load(path, allow_pickle=False)
        return cls(z["keys"], z["kind"], z["source"], z["scores"], int(z["dropped"]))

    def subset(self, mask: np.ndarray) -> "Synthetic":
        return Synthetic(self.keys, self.kind[mask], self.source[mask], self.scores[mask], self.dropped)


# ── Generation ─────────────────────────────────────────────────────────────────

class Generator:
    def __init__(self, seed: int = 7, noise: float = NOISE):
        self.rng = np.random.default_rng(seed)
        self.noise = noise

    def trail(self, shape: np.ndarray) -> np.ndarray:
        """Shape → trail in degrees: starts at the origin, points every 0.3°."""
        p = shape - shape[0]
        p = p * (self.rng.uniform(*SPAN_DEG) / max(float(np.ptp(p, axis=0).max()), 1e-9))
        length = float(np.hypot(*np.diff(p, axis=0).T).sum())
        return resample(p, max(int(length / POINT_STEP_DEG), MIN_TRAIL_PTS + 5))

    def perturb(self, shape: np.ndarray) -> np.ndarray:
        rng, k = self.rng, self.noise
        p = resample(shape, SHAPE_N)
        a = np.radians(rng.normal(0, 7 * k))
        rot = np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])
        stretch = np.diag(np.exp(rng.normal(0, 0.15 * k, 2)))
        p = (p - p.mean(axis=0)) @ (rot @ stretch).T
        p = gaussian_filter1d(p, sigma=rng.uniform(1, 1 + 5 * k), axis=0, mode="nearest")
        t = np.linspace(0, 1, len(p))[:, None]
        amp = 0.04 * k * float(np.ptp(p, axis=0).max())
        for f in rng.uniform(0.5, 4, 3):
            p = p + amp * rng.normal(size=2) * np.sin(2 * np.pi * (f * t + rng.uniform()))
        cum = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(p, axis=0).T))])
        lo, hi = rng.uniform(0, 0.05 * k), 1 - rng.uniform(0, 0.05 * k)
        keep = (cum >= lo * cum[-1]) & (cum <= hi * cum[-1])
        return self.trail(p[keep] if keep.sum() >= 2 else p)

    def near_miss(self, kind: str, shapes: list) -> tuple:
        """(source index, clean shape) for one near-miss of this kind."""
        rng = self.rng
        i = int(rng.integers(len(shapes)))
        a = resample(shapes[i], SHAPE_N)
        if kind == "half":
            return i, a[: int(rng.integers(int(0.35 * SHAPE_N), int(0.7 * SHAPE_N)))]
        if kind == "reversed":
            return i, a[::-1]
        if kind == "blend":
            j = int(rng.integers(len(shapes) - 1))
            b = resample(shapes[j + (j >= i)], SHAPE_N)
            unit = lambda s: (s - s.mean(axis=0)) / max(float(np.ptp(s, axis=0).max()), 1e-9)
            return i, 0.5 * unit(a) + 0.5 * unit(b)
        walk = np.cumsum(rng.normal(size=(SHAPE_N, 2)), axis=0)
        return -1, gaussian_filter1d(walk, 6, axis=0)


# ── Scoring (process pool) ─────────────────────────────────────────────────────

_lib: Optional[SpellLibrary] = None
_matcher: Optional[SpellMatcher] = None


def _init_worker(spells_dir: str):
    global _lib, _matcher
    _lib, _matcher = SpellLibrary(spells_dir), SpellMatcher()


def _score(trail: np.ndarray) -> np.ndarray:
    if len(trail) < MIN_TRAIL_PTS or trail_extent(trail) < MIN_GESTURE_DEG:
        return np.full(len(_lib.templates), GATED, dtype=np.float32)
    return _matcher.scores(trail, _lib.templates).astype(np.float32)


def _prepare(trail: np.ndarray) -> Optional[np.ndarray]:
    if len(trail) < MIN_TRAIL_PTS or trail_extent(trail) < MIN_GESTURE_DEG:
        return None
    from . import gpu
    return gpu.query_features(trail)


def score_trails(trails: list, spells_dir: str, jobs: Optional[int] = None,
                 use_gpu: bool = False, log: Callable = lambda msg: None) -> np.ndarray:
    """(N, T) raw scores, one row per trail (GATED where gated).  On the GPU
    only the trail preparation uses the process pool."""
    jobs = jobs or max(1, (os.cpu_count() or 2) - 1)
    if use_gpu:
        from . import gpu
        if jobs == 1:
            feats = [_prepare(t) for t in trails]
        else:
            with ProcessPoolExecutor(jobs) as pool:
                feats = list(pool.map(_prepare, trails, chunksize=64))
        log(f"prepared {len(trails)} trails")
        templates = SpellLibrary(spells_dir).templates
        out = np.full((len(trails), len(templates)), GATED, dtype=np.float32)
        live = [i for i, f in enumerate(feats) if f is not None]
        if live:
            out[live] = gpu.dtw_scores(np.stack([feats[i] for i in live]), gpu.template_features(templates))
        return out
    if jobs == 1:
        _init_worker(spells_dir)
        return np.stack([_score(t) for t in trails])
    with ProcessPoolExecutor(jobs, initializer=_init_worker, initargs=(spells_dir,)) as pool:
        return np.stack(list(pool.map(_score, trails, chunksize=32)))


def generate(spells_dir: str, per: int, seed: int = 7, noise: float = NOISE,
             jobs: Optional[int] = None, use_gpu: bool = False,
             log: Callable = lambda msg: None) -> Synthetic:
    """`per` casts of every spell plus `per` near-misses per spell, scored."""
    lib = SpellLibrary(spells_dir)
    shapes = [t.points for t in lib.templates]
    gen = Generator(seed, noise)
    kinds, sources, trails, cleans = [], [], [], []
    for _ in range(per):                        # interleaved, so halves split evenly
        for i, shape in enumerate(shapes):
            kinds.append(SPELL); sources.append(i); trails.append(gen.perturb(shape)); cleans.append(None)
    names, weights = zip(*NEAR_MISS_MIX)
    for kind in gen.rng.choice(names, size=per * len(shapes), p=weights):
        i, clean = gen.near_miss(str(kind), shapes)
        kinds.append(str(kind)); sources.append(i); trails.append(gen.perturb(clean))
        cleans.append(gen.trail(clean))
    near = [n for n, c in enumerate(cleans) if c is not None]
    log(f"generated {len(trails)} trails")
    scores = score_trails(trails + [cleans[n] for n in near], spells_dir, jobs, use_gpu, log)
    log("scored")
    scores, clean_scores = scores[:len(trails)], scores[len(trails):]
    keep = np.ones(len(trails), bool)
    keep[np.array(near)[clean_scores.min(axis=1) < IS_SPELL]] = False
    return Synthetic(np.array([t.key for t in lib.templates]), np.array(kinds)[keep],
                     np.array(sources)[keep], scores[keep], int((~keep).sum()))


# ── Decisions and fitting ──────────────────────────────────────────────────────

def ranked(scores: np.ndarray) -> tuple:
    """(best index, best score, runner-up / best margin) per row."""
    order = np.argsort(scores, axis=1)[:, :2]
    rows = np.arange(len(scores))
    s0, s1 = scores[rows, order[:, 0]], scores[rows, order[:, 1]]
    with np.errstate(divide="ignore", invalid="ignore"):
        margin = np.where(s0 > 0, s1 / s0, np.inf)
    return order[:, 0], s0, margin


def decide(scores: np.ndarray, thresholds: np.ndarray, margin_ratio: float = MARGIN_RATIO) -> np.ndarray:
    """Accepted template index per row, or -1 (rejected or gated)."""
    best, s0, margin = ranked(scores)
    ok = np.isfinite(s0) & (s0 <= thresholds[best]) & (margin >= margin_ratio)
    return np.where(ok, best, -1)


def fit_thresholds(data: Synthetic, fa_weight: float = 1.0,
                   margin_ratio: float = MARGIN_RATIO) -> dict:
    """Per-spell thresholds {key: value} for spells with enough own accepts."""
    best, s0, margin = ranked(data.scores)
    live = np.isfinite(s0) & (margin >= margin_ratio)
    grid = np.arange(THRESHOLD_RANGE[0], THRESHOLD_RANGE[1] + 1e-9, THRESHOLD_STEP)
    out = {}
    for j, key in enumerate(data.keys):
        mine = live & (best == j)
        own = mine & (data.kind == SPELL) & (data.source == j)
        gain = (s0[own][None, :] <= grid[:, None]).sum(1) \
            - fa_weight * (s0[mine & ~own][None, :] <= grid[:, None]).sum(1)
        tied = np.flatnonzero(gain == gain.max())        # move off the default only to gain
        g = int(tied[np.argmin(np.abs(grid[tied] - DEFAULT_THRESHOLD))])
        if (s0[own] <= grid[g]).sum() >= MIN_FIT:
            out[str(key)] = round(float(grid[g]), 3)
    return out


def threshold_array(keys: np.ndarray, per_spell: dict, default: float = DEFAULT_THRESHOLD) -> np.ndarray:
    return np.array([per_spell.get(str(k), default) for k in keys])


def summary(data: Synthetic, thresholds: np.ndarray, margin_ratio: float = MARGIN_RATIO) -> dict:
    dec = decide(data.scores, thresholds, margin_ratio)
    spell = data.kind == SPELL
    out = {"spells": int(spell.sum()), "correct": int((dec[spell] == data.source[spell]).sum()),
           "wrong": int(((dec[spell] >= 0) & (dec[spell] != data.source[spell])).sum())}
    for kind, _ in NEAR_MISS_MIX:
        k = data.kind == kind
        out[kind] = (int((dec[k] >= 0).sum()), int(k.sum()))
    return out
