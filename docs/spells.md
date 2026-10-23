# Spells

[← OpenCaster](../README.md) · [Documentation](README.md)

Each spell is one SVG in `spells/` containing a single `<path>` in a 200×200
viewBox, drawn in casting order: **the path's start is where the gesture
starts**, because recognition takes direction into account.  The spell's name
is the file name.  Name it after the spellbook entry (e.g.
`Wingardium Leviosa.svg`) so it picks up that spell's effects.

**Reload spells** reloads templates and effects without restarting.

## Adding a spell

- **Draw it:** `python tools/spell_editor.py` lets you draw with the mouse,
  smooth the stroke and save straight to `spells/`.
- **Trace a gesture diagram:** `tools/gesture_png_to_svg.py` traces images
  like eigger's (a stroke running from a start dot to an arrowhead).  Guide
  points in `tools/gesture_waypoints.json` fix the drawing order (dot,
  corners, both sides of each crossing, arrow tip); between them the trace
  follows the drawn stroke's centre line.

  ```bash
  python tools/gesture_png_to_svg.py grid  PNG_DIR out/ --only name     # gridded image to read points from
  python tools/gesture_png_to_svg.py trace PNG_DIR out/ --only name --review out/review.png
  ```

Every extra spell is one more shape a cast can be confused with, so check new
ones with `python -m opencaster.casting evaluate`.

## Tuning recognition

```bash
python -m opencaster.casting evaluate                      # accuracy, confusion table, suggested thresholds
python -m opencaster.casting evaluate --misses             # every labelled cast the matcher got wrong
python -m opencaster.casting evaluate --threshold 0.3 --margin 1.2
```

It re-runs every labelled cast in `casts/casts.jsonl` through the current
matcher and prints a `PER_SPELL_THRESHOLDS` block to paste into
`opencaster/casting/matcher.py`.

Labelled casts are few per spell, so `opencaster.recognition` also tests
against synthetic ones: casts generated from the templates with a hand's
tilt, stretch, wobble and rounded corners, plus near-misses that must be
rejected (half a spell, a spell drawn backwards, two spells blended, random
scribbles).  It fits a threshold per spell and shows the trade-off at several
false-accept weights, on held-out synthetic casts and on your real ones:

```bash
python -m opencaster.recognition synth --per 500 --save synth.npz   # generate, score, fit
python -m opencaster.recognition synth --load synth.npz --fa-weight 2
```

Scoring runs on the GPU through OpenCL when `pyopencl` is installed
(`pip install pyopencl`; any AMD, NVIDIA or Intel GPU driver includes
OpenCL), and on every CPU core otherwise (`--cpu` forces it).  500 per spell
is about 78,000 trails: about 16 s on a Radeon RX 9070 XT and about 18 min
on a 16-core CPU.

## How recognition works

### Gesture tracking (`opencaster/casting/tracker.py`)

The trail is the direction the wand tip points, in degrees, from the gyro:

```
every IMU sample
  ├─ not in a gesture: update gyro bias (rolling still-detector)
  │                    and world-up (low-passed accel)
  └─ in a gesture:
       ω = gyro − bias
       up ← up − (ω × up)·dt        world-up carried through the motion by the gyro
       v  = ω × tip                 tip velocity (wrist roll drops out)
       right += v · unit(tip × up)·dt     (degrees)
       up    += v · up·dt
       tip speed < min_rate → ignored;  point appended every min_step degrees
```

Because "up" is real world-up, the trail keeps its orientation: a Λ stays a Λ
however the wand is held.

### Matching (`opencaster/casting/matcher.py`)

1. **Gates:** trails under 20 points or spanning less than 15° are rejected.
2. **Prepare:** trim 3% of the path from each end, resample to 64 points,
   smooth, and centre/scale by the larger bounding-box side.
3. **Compare:** banded DTW on position **and** stroke direction against every
   template, allowing only ±20° of tilt and no reversal.
4. **Decide:** accept the best spell only if its score is under its threshold
   (default 0.30) **and** the runner-up scores at least 1.25× worse.
