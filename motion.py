"""
motion.py — Shared gyro-based gesture tracking for OpenCaster
==============================================================
One pipeline used by wand_gui.py, wand_tuner.py and replay_capture.py so
live drawing, tuner replay and offline analysis can never drift apart.

Why gyro, not accel
-------------------
The old pipeline summed per-sample accel deltas, which telescopes to
accel[n] - accel[0]: it plotted tilt-of-gravity plus linear jerk, not
movement.  It also cannot see a left/right swing of a level wand at all,
because yaw does not change the gravity vector.  Probe data (imu_probe_log.csv)
showed |a| swinging 0.2-5 g during casts, swamping the tilt signal.

The wand tip is a direction on a sphere.  Its angular velocity in body
coordinates is  omega x L  (L = tip axis), so:

    right = (omega x L) . r      r  = unit(L x up)
    up    = (omega x L) . up     up = world-up in body coords

Roll about the wand's own axis gives omega x L = 0 and is ignored for free.
World-up is taken from the low-passed accelerometer before the gesture and
propagated with the gyro during it (up <- up - (omega x up) dt), with a gentle
accel correction only while |a| is close to 1 g.

Sensor facts (measured from imu_probe_log.csv):
    220 Hz, 19 samples per BLE packet (all samples in a packet share one
    timestamp, so dt is fixed rather than wall-clock).
    accel 2048 counts/g (+/-16 g), gyro 0.0625 deg/s per count (+/-2000 deg/s).
    Gyro bias ~1 deg/s, still-noise std ~0.1-0.7 deg/s per axis.
"""

import struct
from typing import Optional

import numpy as np

IMU_ACCEL_SCALE = 0.00048828125   # raw int16 → G
IMU_GYRO_SCALE  = 0.0010908308    # raw int16 → rad/s

SAMPLE_RATE_HZ = 220.0
DT             = 1.0 / SAMPLE_RATE_HZ

# Tip axis in sensor coordinates.  Probe data points at +y (centripetal
# accel during swings and the near-saturating roll rate both sit on y),
# but the calibrator's "tip up" step measures it per wand.
DEFAULT_TIP_AXIS = (0.0, 1.0, 0.0)

DEFAULTS = dict(
    gain_deg  = 1.0,    # trail units per degree of tip travel
    min_rate  = 3.0,    # deg/s — tip speeds below this are treated as stillness
    min_step  = 0.3,    # deg — decimate: only append when tip moved this far
    up_tau    = 0.25,   # s — accel low-pass time constant for world-up while idle
    up_correct = 0.005, # per-sample pull toward accel during a gesture (when |a|≈1 g)
    flip_x    = False,  # set by the calibrator's swipe-right check if needed
)

GYRO_CLIP = 32000 * IMU_GYRO_SCALE   # ~1830 deg/s; integration is wrong past this


def decode_imu_packet(data: bytes) -> list:
    """Decode an 0x2C IMU packet → list of (ax, ay, az, gx, gy, gz).

    Sensor frame, scaled to G and rad/s.  Wire order per sample is
    gyroX gyroY gyroZ accelX accelY accelZ (int16 LE).
    """
    if not data or data[0] != 0x2C or len(data) < 4:
        return []
    count = data[3]
    if len(data) < 4 + count * 12 or (len(data) - 4) % 12 != 0:
        return []
    out, off = [], 4
    for _ in range(count):
        gx, gy, gz, ax, ay, az = struct.unpack_from('<hhhhhh', data, off)
        off += 12
        out.append((
            ax * IMU_ACCEL_SCALE, ay * IMU_ACCEL_SCALE, az * IMU_ACCEL_SCALE,
            gx * IMU_GYRO_SCALE,  gy * IMU_GYRO_SCALE,  gz * IMU_GYRO_SCALE,
        ))
    return out


def _unit(v: np.ndarray) -> Optional[np.ndarray]:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else None


class GyroBias:
    """Rolling still-detector that keeps the gyro bias estimate fresh.

    Watches a 0.5 s window; when every axis stays within STILL_SPAN of its
    window mean, the mean is blended into the bias.  Bias drifts with
    temperature, so this runs continuously between gestures.
    """
    WINDOW     = 110      # samples (0.5 s)
    STILL_SPAN = 0.06     # rad/s (~3.4 deg/s) peak deviation allowed in window
    BLEND      = 0.2
    MAX_BIAS   = 0.09     # rad/s (~5 deg/s); real bias is ~1 deg/s, more = slow turn

    def __init__(self, bias=(0.0, 0.0, 0.0)):
        self.bias = np.array(bias, dtype=float)
        self._buf = np.zeros((self.WINDOW, 3))
        self._n   = 0
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
    """Turns IMU samples into a 2-D trail of tip direction (degrees).

    feed() every sample, always.  Between begin() and end() the trail grows;
    outside a gesture it just tracks world-up and gyro bias.
    """

    def __init__(self, tip_axis=DEFAULT_TIP_AXIS, gyro_bias=(0.0, 0.0, 0.0), **params):
        self.p = dict(DEFAULTS)
        self.p.update({k: v for k, v in params.items() if k in DEFAULTS})
        self.tip  = _unit(np.array(tip_axis, dtype=float))
        self.bias = GyroBias(gyro_bias)
        self._up: Optional[np.ndarray] = None
        self.active = False
        self.trail_x: list = []
        self.trail_y: list = []
        self._x = self._y = 0.0
        self.stats = {}

    # ── gesture window ────────────────────────────────────────────────────────

    def begin(self):
        self.active = True
        self.trail_x, self.trail_y = [0.0], [0.0]
        self._x = self._y = 0.0
        self.stats = {"raw": 0, "moving": 0, "degenerate": 0, "clipped": 0}

    def end(self) -> tuple:
        self.active = False
        return self.trail_x, self.trail_y

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
            # Tip pointing straight up/down: azimuth is undefined this sample.
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

    def feed_many(self, samples):
        for s in samples:
            self.feed(*s)

    # ── profile helpers ───────────────────────────────────────────────────────

    @classmethod
    def from_profile(cls, motion: Optional[dict], **params) -> "GestureTracker":
        """Build from a wand_profiles.json "motion" block (or None for defaults)."""
        motion = motion or {}
        merged = dict(motion.get("params", {}))
        merged.update(params)
        return cls(tip_axis=motion.get("tip_axis", DEFAULT_TIP_AXIS),
                   gyro_bias=motion.get("gyro_bias", (0.0, 0.0, 0.0)),
                   **merged)


def run_pipeline(raw_samples: list, pre_samples: Optional[list] = None,
                 motion: Optional[dict] = None, **params) -> tuple:
    """Offline replay: returns (trail_x, trail_y, stats).

    pre_samples (optional) are fed before the gesture to settle world-up and
    gyro bias; otherwise world-up comes from the first gesture sample.
    """
    t = GestureTracker.from_profile(motion, **params)
    if pre_samples:
        t.feed_many(pre_samples)
    t.begin()
    t.feed_many(raw_samples)
    xs, ys = t.end()
    return xs, ys, dict(t.stats, points=len(xs))
