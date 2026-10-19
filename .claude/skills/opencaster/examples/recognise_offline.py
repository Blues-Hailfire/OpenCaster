"""
Spell recognition on its own: opencaster.casting (numpy + scipy only), no
Bluetooth, no wand needed.

  1. assess(): rank a finished trail (degrees of tip travel, x right, y up)
     against the spell templates – here, each spell's own shape drawn
     sloppily (wobble, tilt, squash), to show how robust matching is.
  2. CastSession: the live state machine – pads open a window, IMU samples
     grow the trail, release gives a "cast" event – driven with synthesised
     samples (or replay a real capture: python -m opencaster.casting replay x.csv).

    python recognise_offline.py                  # every spell, sloppily drawn
    python recognise_offline.py Lumos Incendio   # just these
"""

import math
import sys

import numpy as np
from fake_wands import gesture, repo_root

sys.path.insert(0, str(repo_root()))
from opencaster.casting import CastSession, SpellLibrary, SpellMatcher, assess   # noqa: E402
from opencaster.casting.shapes import resample                                  # noqa: E402
from opencaster.paths import SPELLS_DIR                                         # noqa: E402

DT = 1 / 220


def sloppy(outline, rng, size=40.0, tilt_deg=6.0, squash=0.9, wobble=0.25) -> np.ndarray:
    """A hand-drawn version of a template outline, as a trail in degrees:
    ~150 points (a real trail gets one every 0.3 deg), tilted, squashed and
    wobbly."""
    a = math.radians(rng.uniform(-tilt_deg, tilt_deg))
    rot = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    pts = resample(outline, 150) @ rot.T * (size / 2) * [1.0, rng.uniform(squash, 1.0)]
    drift = np.cumsum(rng.normal(0, wobble, pts.shape), axis=0)
    return pts + drift - np.linspace(0, 1, len(pts))[:, None] * drift[-1]


def session_cast(library, outline):
    """Drive a CastSession like a wand would; returns its CastResult."""
    t, events = [0.0], []
    s = CastSession(library, on_event=lambda name, payload=None: events.append((name, payload)),
                    clock=lambda: t[0])                  # a fake clock: no real waiting

    def feed(samples):
        for i in range(0, len(samples), 19):             # 19 samples per packet, 220 Hz
            s.feed_imu(samples[i:i + 19])
            t[0] += 19 * DT

    still = [(0.0, 0.0, 1.0, 0.0, 0.0, 0.0)] * 57
    feed(still)                                          # world-up settles while idle
    s.feed_buttons(0x0F)                                 # all four pads: window opens
    feed(gesture(outline))
    s.feed_buttons(0x00)                                 # released: the cast is assessed
    return next(payload for name, payload in events if name == "cast")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    library, matcher = SpellLibrary(SPELLS_DIR), SpellMatcher()
    names = sys.argv[1:] or library.names()
    rng = np.random.default_rng(1)
    hits = 0
    for name in names:
        template = library.get(name)
        if template is None:
            sys.exit(f"no template for {name!r}; try one of: {', '.join(library.names())}")
        r = assess(sloppy(template.outline, rng), library, matcher)
        top = "  ".join(f"{m.spell} {m.score:.2f}" for m in r.ranked[:3])
        ok = r.accepted and r.spell == template.name
        hits += ok
        print(f"{'OK  ' if ok else 'MISS'} {name:22s} -> {r.message():22s} [{top}]")
    print(f"\nassess(): {hits}/{len(names)} sloppy drawings recognised")
    r = session_cast(library, library.get(names[0]).outline)
    print(f"CastSession, synthesised IMU for {names[0]}: {r.message()}  ({len(r.trail)} trail points)")


if __name__ == "__main__":
    main()
