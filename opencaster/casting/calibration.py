"""
opencaster.casting.calibration — Guided motion calibration (UI-free logic)
===========================================================================
Measures what the tracker needs per wand.  Every step advances on its own by
watching for stillness / motion; feed it every IMU sample and render
`state` however you like (the GUI shows a dialog, a CLI could print it).

  1. Rest         lay the wand flat and still      → gyro bias + noise
  2. Swipe up     point at the screen, swipe UP    → confirms tracking reads up
  3. Swipe right                                   → confirms it reads right

The tip axis and left/right sign are the same on every Magic Caster wand,
so nothing here changes them: a swipe that reads the wrong way is the
user's mistake and is asked for again.  (Measuring the tip from a "point it
at the ceiling" pose saved a sideways tip whenever the wand was held level.)

`result` is the profile "motion" block:
    {"tip_axis": [x,y,z], "gyro_bias": [x,y,z] (rad/s), "gyro_noise_dps": [...],
     "params": {"flip_x": bool}, "swipe_up_check": [dx, dy], ...}
"""

import time
from collections import deque
from typing import Callable, Optional

import numpy as np

from .tracker import DEFAULT_TIP_AXIS, GyroBias, run_pipeline

STILL_SPAN   = GyroBias.STILL_SPAN   # rad/s peak deviation that counts as still (on a table)
HAND_SPAN    = np.radians(12)        # looser: hand-held "still" has tremor
STILL_WINDOW = 110                   # samples (0.5 s) of stillness before collecting
COLLECT_N    = 330                   # samples (1.5 s) collected once still
MOVE_RATE    = np.radians(60)        # rad/s - a swipe has started
SWIPE_MAX_N  = 440                   # samples (2 s) - a swipe can't take longer
PAUSE_N      = 198                   # samples (0.9 s) showing a result before moving on

STEPS = (
    {"id": "rest", "icon": "━", "title": "Lay the wand flat",
     "instruction": "Put the wand down on a table and don't touch it."},
    {"id": "swipe_up", "icon": "↑", "title": "Swipe UP",
     "instruction": "Point the wand at the screen, hold still for a moment,\n"
                    "then raise the tip smoothly UPWARD and stop."},
    {"id": "swipe_right", "icon": "→", "title": "Swipe RIGHT",
     "instruction": "Point the wand at the screen, hold still for a moment,\n"
                    "then sweep it smoothly to the RIGHT and stop."},
)


class MotionCalibrator:
    def __init__(self, on_update: Optional[Callable[[dict], None]] = None):
        self.on_update = on_update or (lambda state: None)
        self.step = -1
        self.phase = "intro"     # intro | settle | collect | armed | swiping | pause | done
        self.status, self.status_kind = "", "info"
        # Fixed for the hardware; saved anyway so a recalibration replaces a
        # bad block from an older calibrator.
        self.result: dict = {"tip_axis": list(DEFAULT_TIP_AXIS), "params": {"flip_x": False}}
        self._win: deque = deque(maxlen=STILL_WINDOW)
        self._buf: list = []
        self._pre: list = []
        self._pause = 0

    # ── control ───────────────────────────────────────────────────────────────

    def start(self):
        self._goto(0)
        self._publish()

    @property
    def done(self) -> bool:
        return self.phase == "done"

    @property
    def state(self) -> dict:
        if self.phase == "intro":
            info = {"id": "intro", "icon": "✦", "title": "Motion calibration",
                    "instruction": "Three quick steps, about 20 seconds.\n"
                                   "Each step advances on its own once the wand is held right."}
        elif self.done:
            info = {"id": "done", "icon": "✦", "title": "Calibration complete",
                    "instruction": self.summary()}
        else:
            info = STEPS[self.step]
        collecting = self.phase == "collect"
        return dict(info, step=self.step, steps=len(STEPS), phase=self.phase,
                    progress=min(1.0, len(self._buf) / COLLECT_N) if collecting
                    else (1.0 if self.phase == "pause" else 0.0),
                    status=self.status, status_kind=self.status_kind, done=self.done)

    def final_result(self) -> dict:
        return dict(self.result, timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"))

    def summary(self) -> str:
        r = self.result
        bias = np.degrees(r.get("gyro_bias", [0, 0, 0]))
        up = r.get("swipe_up_check", [0, 0])[1]
        right = r.get("swipe_check", [0, 0])[0]
        return (f"Gyro bias  {bias.round(2).tolist()} deg/s\n"
                f"Swipes     {up:.0f}° up, {right:.0f}° right")

    # ── sample intake ─────────────────────────────────────────────────────────

    def feed(self, samples):
        """Feed one IMU batch; publishes the state once if anything changed."""
        if self.phase in ("intro", "done"):
            return
        before = (self.step, self.phase, len(self._buf) * (self.phase == "collect"), self.status)
        for s in samples:
            self._feed_one(tuple(s))
            if self.phase in ("intro", "done"):
                break
        if before != (self.step, self.phase, len(self._buf) * (self.phase == "collect"),
                      self.status):
            self._publish()

    def _feed_one(self, s: tuple):
        if self.phase == "pause":
            self._pause -= 1
            if self._pause <= 0:
                self._goto(self.step + 1)
            return
        step = STEPS[self.step]["id"]
        self._win.append(s)
        span = STILL_SPAN if step == "rest" else HAND_SPAN
        still = False
        if len(self._win) == STILL_WINDOW:
            g = np.array(self._win)[:, 3:]
            still = np.abs(g - g.mean(0)).max() < span
        if step == "rest":
            self._feed_rest(s, still, span)
        else:
            self._feed_swipe(s, still)

    def _feed_rest(self, s: tuple, still: bool, span: float):
        if self.phase == "settle":
            if still:
                self.phase = "collect"
                self._buf = list(self._win)
            return
        g = np.array(self._buf[-STILL_WINDOW:])[:, 3:]
        if np.abs(np.array(s[3:]) - g.mean(0)).max() > span * 1.5:
            self.phase = "settle"
            self._buf = []
            self._set_status("moved - hold still...", "error")
            return
        self._buf.append(s)
        if len(self._buf) >= COLLECT_N:
            self._finish_rest(np.array(self._buf))

    def _finish_rest(self, arr: np.ndarray):
        gyr = arr[:, 3:]
        self.result["gyro_bias"] = gyr.mean(0).tolist()
        self.result["gyro_noise_dps"] = np.degrees(gyr.std(0)).round(3).tolist()
        self._set_status(f"bias  {np.degrees(gyr.mean(0)).round(2)} deg/s\n"
                         f"noise {np.degrees(gyr.std(0)).round(2)} deg/s", "ok")
        self._pause_then_next()

    def _feed_swipe(self, s: tuple, still: bool):
        if self.phase == "settle":
            if still:
                self.phase = "armed"
                self._pre = list(self._win)
                self._set_status(f"ready - {STEPS[self.step]['title'].lower()}", "ready")
            return
        bias = np.array(self.result.get("gyro_bias", (0, 0, 0)))
        rate = float(np.linalg.norm(np.array(s[3:]) - bias))
        if self.phase == "armed":
            if rate > MOVE_RATE:
                self.phase = "swiping"
                self._buf = [s]
            else:
                self._pre = (self._pre + [s])[-STILL_WINDOW:]
            return
        self._buf.append(s)                    # swiping: stop once still again
        if (still and len(self._buf) > STILL_WINDOW) or len(self._buf) > SWIPE_MAX_N:
            self._finish_swipe()

    def _finish_swipe(self):
        motion = {k: self.result[k] for k in ("tip_axis", "gyro_bias") if k in self.result}
        trail, _ = run_pipeline(self._buf, pre_samples=self._pre, motion=motion)
        dx, dy = float(trail[-1, 0] - trail[0, 0]), float(trail[-1, 1] - trail[0, 1])
        vertical = STEPS[self.step]["id"] == "swipe_up"
        main, cross = (dy, dx) if vertical else (dx, dy)
        if abs(main) < 15 or abs(main) < 1.5 * abs(cross):
            self._goto(self.step)
            self._set_status(f"that read as ({dx:+.0f}°, {dy:+.0f}°) - sweep wider and "
                             f"straighter, try again", "error")
            return
        if main < 0:
            # The wand's axes are fixed, so the wrong way round is a mistaken
            # swipe – "fixing" the profile for it would mirror every cast.
            self._goto(self.step)
            self._set_status(f"that read as {abs(main):.0f}° " + ("down - swipe UP" if vertical
                             else "left - swipe RIGHT") + ", try again", "error")
            return
        self.result["swipe_up_check" if vertical else "swipe_check"] = [round(dx, 1), round(dy, 1)]
        self._set_status(f"swipe read as {main:.0f}° " + ("up ✓" if vertical else "right ✓"), "ok")
        self._pause_then_next()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _goto(self, idx: int):
        self._win.clear()
        self._buf = []
        if idx >= len(STEPS):
            self.phase = "done"
            self._set_status("", "info")
            return
        self.step = idx
        self.phase = "settle"
        self._set_status("waiting for the wand to be still...", "info")

    def _pause_then_next(self):
        self.phase = "pause"
        self._pause = PAUSE_N

    def _set_status(self, text: str, kind: str):
        self.status, self.status_kind = text, kind

    def _publish(self):
        self.on_update(self.state)
