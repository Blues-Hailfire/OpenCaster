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
    imu         raw motion, so the tracker can be re-run (casts from 2026-10 on):
                {"rate_hz", "preroll": samples before the window opened,
                 "fields": ["ax", "ay", "az", "gx", "gy", "gz"],
                 "encoding": "int16" (wand counts; × scale gives g, rad/s) or
                 "float32", "scale": [accel, gyro], "data": base64, little-endian}
    motion      the wand profile's motion block the tracker was built from
    tracker     tracker state when the window opened (GestureTracker.state())

Labels are compared with spell_key(), so older lower-case labels match.
Raw motion is stored as wand counts (about 12 bytes a sample, 220 a second:
roughly 10–30 KB a cast with its 1 s pre-roll); retrack() rebuilds a cast's
trail with the current tracker.
"""

import base64
import json
from pathlib import Path
from typing import Optional

import numpy as np

from .shapes import spell_key
from .tracker import GestureTracker

NOT_A_SPELL = "none"

IMU_FIELDS = ("ax", "ay", "az", "gx", "gy", "gz")
IMU_SCALES = (0.00048828125, 0.0010908308)    # g and rad/s per count (wand.protocol)


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


def encode_imu(samples, preroll: int, rate_hz: float) -> dict:
    """(N, 6) samples (ax..gz in g and rad/s) → the record's "imu" block.
    Wand samples are whole counts × scale and are stored losslessly as int16;
    anything else (fake wands, tests) falls back to float32, marked as such."""
    s = np.asarray(samples, dtype=float).reshape(-1, len(IMU_FIELDS))
    scale = np.repeat(IMU_SCALES, 3)
    counts = np.round(s / scale)
    exact = bool(np.all(np.abs(counts) <= 32767) and np.array_equal(counts * scale, s))
    blob = counts.astype("<i2") if exact else s.astype("<f4")
    return {"rate_hz": rate_hz, "preroll": int(preroll), "fields": list(IMU_FIELDS),
            "encoding": "int16" if exact else "float32", "scale": list(IMU_SCALES),
            "data": base64.b64encode(blob.tobytes()).decode("ascii")}


def decode_imu(record: dict) -> Optional[tuple]:
    """(pre-roll (P, 6), gesture (N, 6)) in g and rad/s, or None without raw motion."""
    imu = record.get("imu")
    if not imu:
        return None
    raw = base64.b64decode(imu["data"])
    if imu["encoding"] == "int16":
        s = np.frombuffer(raw, "<i2").reshape(-1, 6) * np.repeat(imu["scale"], 3)
    else:
        s = np.frombuffer(raw, "<f4").reshape(-1, 6).astype(float)
    return s[:imu["preroll"]], s[imu["preroll"]:]


def retrack(record: dict, from_preroll: bool = False, **params) -> Optional[np.ndarray]:
    """Rebuild a cast's trail from its raw motion with the current tracker.

    By default the tracker starts from the state it had when the window
    opened (exact replay); from_preroll=True instead re-estimates gyro bias
    and world-up from the pre-roll, to test changes to that estimation.
    None for casts recorded without raw motion."""
    imu = decode_imu(record)
    if imu is None or "tracker" not in record:
        return None
    pre, gesture = imu
    t = GestureTracker.from_profile(record.get("motion"), **params)
    if from_preroll:
        t.feed_many(pre)
    else:
        t.restore(record["tracker"])
    t.begin()
    t.feed_many(gesture)
    return t.end()


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
