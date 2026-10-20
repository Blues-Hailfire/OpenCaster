"""
opencaster.casting.session — The casting state machine
=======================================================
Feed it touch-pad masks and IMU batches; it decides when a gesture starts and
ends, grows the trail, assesses the cast, and reports everything through one
callback, on_event(name, payload).  No Bluetooth, no GUI, no timers: time
comes from `clock` (sample time when replaying), and the 8 s timeout is
checked as IMU batches arrive.

Rules:
  - Holding all four pads opens the gesture window; releasing any closes it.
  - Released within MIN_CAST_S → a quick tap, not a cast.
  - Open longer than GESTURE_TIMEOUT_S → closed and assessed.
  - Trails under MIN_TRAIL_PTS points or spanning under MIN_GESTURE_DEG are
    rejected before matching (the matcher normalises size away, so hand
    drift during a grip-and-hold would otherwise match like a real stroke).
  - With a target spell, only it can be accepted; a cast that looks more
    like another spell is rejected, not forced onto the target.
  - With an allowed set (a clash duel's battle spells), casts are ranked
    against those spells only.
  - With label_casts on, each cast must be labelled before the next opens.
  - While calibrating, casts aren't assessed; starting it discards a cast
    still waiting for its label.
  - Pad overrides force pads on (a workaround for a broken sensor).

Events:
    "pads"          (mask: int)          effective pad mask (bit 0..3)
    "window_open"   (target or None)
    "trail"         (ndarray (N, 2))     trail so far, while the window is open
    "tap"           (seconds held)
    "timeout"       ()
    "cast"          (CastResult)
    "blocked"       ()                   window refused: last cast not labelled
    "label_needed"  (record)
    "labelled"      ((label or None, total labelled casts or None, record))
    "calibrating"   ()                   window closed while calibrating
    "calibration"   (state dict)         see calibration.MotionCalibrator.state
"""

import time
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable, Optional

import numpy as np

from .calibration import MotionCalibrator
from .castlog import CastLog, trail_extent
from .matcher import MIN_TRAIL_PTS, SpellMatcher
from .shapes import SpellLibrary, spell_key
from .tracker import GestureTracker

MIN_GESTURE_DEG = 15.0

GATE_OK, GATE_SHORT, GATE_SMALL, GATE_NO_SPELLS = "ok", "too_short", "too_small", "no_spells"


@dataclass(frozen=True)
class CastResult:
    trail: np.ndarray
    gate: str
    ranked: tuple            # Match, best first (empty unless gate ok)
    target: Optional[str]    # spell being practised, or None
    note: str = ""           # overrides message() (e.g. a host rejecting the cast)

    def rejected(self, note: str) -> "CastResult":
        """This result with the best match not accepted, explained by note."""
        ranked = (replace(self.ranked[0], success=False),) + self.ranked[1:] if self.ranked else ()
        return replace(self, ranked=ranked, note=note)

    @property
    def best(self):
        return self.ranked[0] if self.ranked else None

    @property
    def accepted(self) -> bool:
        return bool(self.ranked and self.ranked[0].success)

    @property
    def spell(self) -> Optional[str]:
        return self.ranked[0].spell if self.accepted else None

    @property
    def extent(self) -> float:
        return trail_extent(self.trail)

    def score_of(self, name: str):
        key = spell_key(name)
        return next((m for m in self.ranked if m.key == key), None)

    def message(self) -> str:
        if self.note:
            return self.note
        if self.gate == GATE_SHORT:
            return "gesture too short"
        if self.gate == GATE_SMALL:
            return f"gesture too small ({self.extent:.0f}°)"
        if self.gate == GATE_NO_SPELLS:
            return "no spells loaded"
        if self.accepted:
            return self.spell
        if self.target:
            return f"not {self.target}  (closest: {self.best.spell})"
        return "no match"


def assess(trail: np.ndarray, library: SpellLibrary, matcher: SpellMatcher,
           target: Optional[str] = None, allowed: Optional[frozenset] = None) -> CastResult:
    """Gate and match one finished trail.  `allowed` (spell keys) limits the
    spells it is ranked against."""
    if len(trail) < MIN_TRAIL_PTS:
        return CastResult(trail, GATE_SHORT, (), target)
    if trail_extent(trail) < MIN_GESTURE_DEG:
        return CastResult(trail, GATE_SMALL, (), target)
    templates = library.templates if allowed is None else \
        [t for t in library.templates if t.key in allowed]
    ranked = matcher.rank(trail, templates)
    if not ranked:
        return CastResult(trail, GATE_NO_SPELLS, (), target)
    if target:
        key = spell_key(target)
        ranked = [m if m.key == key or not m.success else replace(m, success=False)
                  for m in ranked]
    return CastResult(trail, GATE_OK, tuple(ranked), target)


class CastSession:
    GESTURE_TIMEOUT_S = 8.0
    MIN_CAST_S        = 0.5

    def __init__(self, library: SpellLibrary, matcher: Optional[SpellMatcher] = None,
                 on_event: Optional[Callable] = None, cast_log: Optional[CastLog] = None,
                 clock: Callable[[], float] = time.monotonic):
        self.library = library
        self.matcher = matcher or SpellMatcher()
        self.on_event = on_event or (lambda name, payload=None: None)
        self.cast_log = cast_log
        self.clock = clock
        self.tracker = GestureTracker()
        self.target: Optional[str] = None
        self.allowed: Optional[frozenset] = None  # spell keys casts are ranked against (None: all)
        self.label_casts = False
        self.pending: Optional[dict] = None       # cast record awaiting a label
        self.wand: Optional[str] = None           # wand address, for cast records
        self.calibrator: Optional[MotionCalibrator] = None
        self.active = False
        self._mask = 0
        self._overrides = 0
        self._opened = 0.0

    def _emit(self, name: str, payload=None):
        self.on_event(name, payload)

    # ── inputs ────────────────────────────────────────────────────────────────

    def feed_buttons(self, mask: int):
        self._mask = mask & 0x0F
        self._apply()

    def feed_imu(self, samples):
        if self.calibrator is not None:
            self.calibrator.feed(samples)
        grew = self.tracker.feed_many(samples)
        if not self.active:
            return
        if grew:
            self._emit("trail", self.tracker.trail())
        if self.clock() - self._opened > self.GESTURE_TIMEOUT_S:
            self._emit("timeout")
            self._close()

    def toggle_override(self, pad: int):
        self._overrides ^= 1 << pad
        self._apply()

    def set_motion(self, motion: Optional[dict]):
        """Rebuild the tracker from a wand profile's motion block."""
        self.tracker = GestureTracker.from_profile(motion)
        self.active = False

    def set_target(self, name: Optional[str]):
        t = self.library.get(name) if name else None
        self.target = t.name if t else None

    def set_label_casts(self, on: bool):
        self.label_casts = on
        if not on and self.pending is not None:
            self.label(None)

    def label(self, label: Optional[str]):
        """Label the pending cast (a spell name or castlog.NOT_A_SPELL);
        None discards it."""
        record, self.pending = self.pending, None
        if record is None:
            return
        total = None
        if label is not None and self.cast_log is not None:
            record["label"] = label
            self.cast_log.append(record)
            total = self.cast_log.count()
        self._emit("labelled", (label, total, record))

    def reset(self):
        """Link lost: drop the open window and pad state without a cast."""
        self.active = False
        self.tracker.end()
        self._mask = 0
        self._emit("pads", self._overrides)

    # calibration ----------------------------------------------------------------

    def start_calibration(self):
        # An unanswered label would refuse every pad hold while calibrating
        # ("blocked"); calibrating instead of answering discards that cast.
        if self.pending is not None:
            self.label(None)
        self.calibrator = MotionCalibrator(lambda s: self._emit("calibration", s))
        self.calibrator.start()

    def end_calibration(self) -> Optional[dict]:
        """Stop calibrating; returns the motion block if it completed."""
        cal, self.calibrator = self.calibrator, None
        return cal.final_result() if cal and cal.done else None

    # ── window ────────────────────────────────────────────────────────────────

    def _apply(self):
        eff = self._mask | self._overrides
        self._emit("pads", eff)
        held = eff == 0x0F
        if held and not self.active:
            if self.pending is not None:
                self._emit("blocked")
            else:
                self._open()
        elif not held and self.active:
            self._close()

    def _open(self):
        self.active = True
        self._opened = self.clock()
        self.tracker.begin()
        self._emit("window_open", self.target)

    def _close(self):
        self.active = False
        trail = self.tracker.end()
        held = self.clock() - self._opened
        if held < self.MIN_CAST_S:
            self._emit("tap", held)
            return
        if self.calibrator is not None:
            self._emit("calibrating")
            return
        result = assess(trail, self.library, self.matcher, self.target, self.allowed)
        self._emit("cast", result)
        if self.label_casts:
            self.pending = self._record(result)
            self._emit("label_needed", self.pending)

    def _record(self, r: CastResult) -> dict:
        best = r.best
        return {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "wand":      self.wand,
            "trail":     [[round(x, 3), round(y, 3)] for x, y in r.trail.tolist()],
            "gate":      r.gate,
            "predicted": best.spell if best else None,
            "accepted":  r.accepted,
            "scores":    [[m.spell, m.score] for m in r.ranked],
            "target":    r.target,
        }
