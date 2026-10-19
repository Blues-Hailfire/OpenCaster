"""
opencaster.casting.tracker — Gyro-based gesture tracking
=========================================================
Turns IMU samples into a 2-D trail of where the wand tip points, in degrees.

The tip is a direction on a sphere.  Its angular velocity in body coordinates
is  omega x L  (L = tip axis), so:

    right = (omega x L) . r      r  = unit(L x up)
    up    = (omega x L) . up     up = world-up in body coords

Roll about the wand's own axis gives omega x L = 0 and drops out for free.
World-up comes from the low-passed accelerometer between gestures and is
carried through a gesture by the gyro (up <- up - (omega x up) dt), with a
gentle accel correction only while |a| is close to 1 g.  Because "up" is real
world-up, a Λ stays a Λ however the wand is held.

Sensor facts (measured): 220 Hz, 19 samples per BLE packet sharing one
arrival time (so dt is fixed), gyro bias ~1 deg/s drifting slowly,
still-noise 0.1-0.7 deg/s.  Samples are (ax, ay, az, gx, gy, gz) in g and
rad/s, sensor frame.
"""

from typing import Optional

import numpy as np

SAMPLE_RATE_HZ = 220.0
DT             = 1.0 / SAMPLE_RATE_HZ

# Tip axis in sensor coordinates; the calibrator measures it per wand.
DEFAULT_TIP_AXIS = (0.0, 1.0, 0.0)

DEFAULTS = dict(
    gain_deg   = 1.0,     # trail units per degree of tip travel
    min_rate   = 3.0,     # deg/s - tip speeds below this are treated as stillness
    min_step   = 0.3,     # deg - only append a point once the tip moved this far
    up_tau     = 0.25,    # s - accel low-pass time constant for world-up while idle
    up_correct = 0.005,   # per-sample pull toward accel during a gesture (|a| ≈ 1 g)
    flip_x     = False,   # set by the calibrator's swipe-right check if needed
)

GYRO_CLIP = 32000 * 0.0010908308   # ~1830 deg/s; integration is wrong past this


def _unit(v: np.ndarray) -> Optional[np.ndarray]:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else None


class GyroBias:
    """Rolling still-detector that keeps the gyro bias estimate fresh.

    Watches a 0.5 s window; when every axis stays within STILL_SPAN of its
    window mean, the mean is blended into the bias.
    """
    WINDOW     = 110      # samples (0.5 s)
    STILL_SPAN = 0.06     # rad/s (~3.4 deg/s) peak deviation allowed in window
    BLEND      = 0.2
    MAX_BIAS   = 0.09     # rad/s (~5 deg/s); real bias is ~1 deg/s, more = slow turn

    def __init__(self, bias=(0.0, 0.0, 0.0)):
        self.bias = np.array(bias, dtype=float)
        self._buf = np.zeros((self.WINDOW, 3))
        self._n = 0
        self.updates = 0

    def feed(self, gx: float, gy: float, gz: float):
        self._buf[self._n % self.WINDOW] = (gx, gy, gz)
        self._n += 1
        if self._n < self.WINDOW or self._n % (self.WINDOW // 2):
            return
        m = self._buf.mean(axis=0)
        if np.abs(self._buf - m).max() < self.STILL_SPAN and np.abs(m).max() < self.MAX_BIAS:
            self.bias = self.BLEND * m + (1 - self.BLEND) * self.bias if self.updates else m
            self.updates += 1


class GestureTracker:
    """feed() every sample, always.  Between begin() and end() the trail
    grows; outside a gesture it just tracks world-up and gyro bias."""

    def __init__(self, tip_axis=DEFAULT_TIP_AXIS, gyro_bias=(0.0, 0.0, 0.0), **params):
        self.p = dict(DEFAULTS)
        self.p.update({k: v for k, v in params.items() if k in DEFAULTS})
        self.tip = _unit(np.array(tip_axis, dtype=float))
        self.bias = GyroBias(gyro_bias)
        self._up: Optional[np.ndarray] = None
        self.active = False
        self.trail_x: list = []
        self.trail_y: list = []
        self._x = self._y = 0.0
        self.stats: dict = {}

    @classmethod
    def from_profile(cls, motion: Optional[dict], **params) -> "GestureTracker":
        """Build from a wand profile's "motion" block (or None for defaults)."""
        motion = motion or {}
        merged = dict(motion.get("params", {}))
        merged.update(params)
        return cls(tip_axis=motion.get("tip_axis", DEFAULT_TIP_AXIS),
                   gyro_bias=motion.get("gyro_bias", (0.0, 0.0, 0.0)), **merged)

    # ── gesture window ────────────────────────────────────────────────────────

    def begin(self):
        self.active = True
        self.trail_x, self.trail_y = [0.0], [0.0]
        self._x = self._y = 0.0
        self.stats = {"raw": 0, "moving": 0, "degenerate": 0, "clipped": 0}

    def end(self) -> np.ndarray:
        self.active = False
        return self.trail()

    def trail(self) -> np.ndarray:
        return np.column_stack([self.trail_x, self.trail_y]) if self.trail_x \
            else np.zeros((0, 2))

    def position(self) -> tuple:
        """Where the tip points now, relative to begin(): (right, up) in trail units."""
        return self._x, self._y

    # ── per-sample update ─────────────────────────────────────────────────────

    def feed(self, ax, ay, az, gx, gy, gz):
        a = np.array((ax, ay, az))

        if not self.active:
            self.bias.feed(gx, gy, gz)
            u = _unit(a)
            if u is not None:
                k = DT / (self.p["up_tau"] + DT)
                self._up = u if self._up is None else _unit((1 - k) * self._up + k * u)
            return

        if self._up is None:
            self._up = _unit(a)
            if self._up is None:
                return

        w = np.array((gx, gy, gz)) - self.bias.bias
        up = self._up - np.cross(w, self._up) * DT
        if abs(np.linalg.norm(a) - 1.0) < 0.1:
            up = up + self.p["up_correct"] * (_unit(a) - up)
        self._up = up = _unit(up)

        self.stats["raw"] += 1
        if max(abs(gx), abs(gy), abs(gz)) >= GYRO_CLIP:
            self.stats["clipped"] += 1
        right = _unit(np.cross(self.tip, up))
        if right is None:
            # Tip pointing straight up/down: azimuth undefined this sample.
            self.stats["degenerate"] += 1
            return

        v = np.cross(w, self.tip)                      # tip velocity, rad/s
        if np.degrees(np.linalg.norm(v)) < self.p["min_rate"]:
            return
        self.stats["moving"] += 1

        g = self.p["gain_deg"] * np.degrees(DT)
        self._x += float(v @ right) * g * (-1.0 if self.p["flip_x"] else 1.0)
        self._y += float(v @ up) * g

        lx, ly = self.trail_x[-1], self.trail_y[-1]
        if np.hypot(self._x - lx, self._y - ly) >= self.p["min_step"] * self.p["gain_deg"]:
            self.trail_x.append(self._x)
            self.trail_y.append(self._y)

    def feed_many(self, samples) -> bool:
        """Feed a batch; returns True if the trail grew."""
        n = len(self.trail_x)
        for s in samples:
            self.feed(*s)
        return len(self.trail_x) != n


def run_pipeline(samples: list, pre_samples: Optional[list] = None,
                 motion: Optional[dict] = None, **params) -> tuple:
    """Offline: returns (trail (N, 2), stats).  pre_samples settle world-up
    and gyro bias before the gesture."""
    t = GestureTracker.from_profile(motion, **params)
    if pre_samples:
        t.feed_many(pre_samples)
    t.begin()
    t.feed_many(samples)
    trail = t.end()
    return trail, dict(t.stats, points=len(trail))
