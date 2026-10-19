"""
opencaster.casting — Spell assessment
======================================
Self-contained: depends only on numpy and scipy.  Knows nothing about
Bluetooth or GUIs; it takes IMU samples (ax, ay, az, gx, gy, gz in g and
rad/s) and touch-pad masks, and produces trails and cast results.

    from opencaster.casting import SpellLibrary, CastSession

    session = CastSession(SpellLibrary("spells"), on_event=print)
    session.feed_buttons(0x0F)         # all pads held: gesture window opens
    session.feed_imu(samples)          # trail grows
    session.feed_buttons(0x00)         # released: "cast" event with a CastResult

Headless:  python -m opencaster.casting --help
"""

from .calibration import MotionCalibrator
from .castlog import NOT_A_SPELL, CastLog, CastSizes
from .matcher import Match, SpellMatcher
from .profiles import WandProfiles
from .session import CastResult, CastSession, assess
from .shapes import SpellLibrary, SpellTemplate, spell_key
from .tracker import GestureTracker

__all__ = ["SpellLibrary", "SpellTemplate", "SpellMatcher", "Match", "CastSession",
           "CastResult", "assess", "GestureTracker", "MotionCalibrator", "CastLog",
           "CastSizes", "WandProfiles", "NOT_A_SPELL", "spell_key"]
