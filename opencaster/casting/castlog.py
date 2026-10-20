"""
opencaster.casting.castlog — Labelled cast storage (JSON lines)
================================================================
Every labelled cast is appended as one JSON line.  The trail is stored raw
(degrees of tip travel, straight from the tracker) so any matcher version
can be re-run against the same data.

Record fields:
    timestamp   ISO time of the cast
    wand        wand MAC address (or null)
    label       spell the user says they cast, or "none" (not a spell)
    trail       [[x, y], ...] in degrees, 3 decimals
    gate        "ok", "too_short", "too_small" or "no_spells"
    predicted   best-matching spell at cast time (or null)
    accepted    whether the matcher accepted that prediction
    scores      [[spell, score], ...] best-first, at cast time
    target      spell being practised, or null for any

Labels are compared with spell_key(), so older lower-case labels match.
"""

import json
from pathlib import Path
from typing import Optional

import numpy as np

from .shapes import spell_key

NOT_A_SPELL = "none"


class CastLog:
    def __init__(self, path):
        self.path = Path(path)

    def append(self, record: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def load(self) -> list:
        if not self.path.exists():
            return []
        with open(self.path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def count(self) -> int:
        if not self.path.exists():
            return 0
        with open(self.path, encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())


def trail_extent(trail) -> float:
    """Larger bounding-box side of a trail, in degrees."""
    t = np.asarray(trail, dtype=float)
    return float(np.ptp(t, axis=0).max()) if len(t) >= 2 else 0.0


class CastSizes:
    """How big casts really are (degrees across), learned from labelled
    casts, so views and practice guides start at a realistic size."""
    DEFAULT_DEG = 45.0

    def __init__(self, records=(), min_deg: float = 15.0):
        self.min_deg = min_deg
        self._sizes: dict = {}
        for r in records:
            self.add(r)

    def add(self, record: dict):
        label = record.get("label")
        if label in (None, NOT_A_SPELL):
            return
        extent = trail_extent(record.get("trail", []))
        if extent >= self.min_deg:          # attempts too small to match don't count
            self._sizes.setdefault(spell_key(label), []).append(extent)

    def typical(self, spell: Optional[str] = None) -> float:
        """Median size of this spell's casts (2+ needed), else of all casts
        (3+ needed), else DEFAULT_DEG."""
        own = self._sizes.get(spell_key(spell), []) if spell else []
        if len(own) >= 2:
            return float(np.median(own))
        every = [e for sizes in self._sizes.values() for e in sizes]
        return float(np.median(every)) if len(every) >= 3 else self.DEFAULT_DEG
