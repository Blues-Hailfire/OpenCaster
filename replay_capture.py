"""
replay_capture.py — Offline replay of raw IMU captures
=======================================================
Runs saved captures through the gyro pipeline (motion.py, what wand_gui uses)
and the legacy accel pipeline side by side, scores the gyro trail against the
spell library, and writes a comparison PNG.

Captures come from the tuner's "Save Capture" button (captures/<label>_*.csv,
with a "phase" column of pre/gesture).  imu_probe_log.csv also works; it has
no phases, so pass --start/--end seconds to cut a gesture out of it.

Usage:
    python replay_capture.py                       # every file in captures/
    python replay_capture.py captures/circle_*.csv --wand EA:2F:DA:65:F1:08
    python replay_capture.py imu_probe_log.csv --start 2.4 --end 4.2
"""

import argparse
import csv
import glob
import os

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from motion import IMU_ACCEL_SCALE, IMU_GYRO_SCALE, run_pipeline
from spell_matcher import SpellMatcher
from spell_shapes import SpellLibrary
from wand_profiles import WandProfiles
from wand_tuner import run_accel_pipeline

HERE = os.path.dirname(os.path.abspath(__file__))


def load_capture(path: str, start=None, end=None) -> tuple:
    """Return (pre_samples, gesture_samples) as scaled (ax..gz) tuples."""
    pre, gesture = [], []
    with open(path, newline="", encoding="utf-8") as f:
        for i, row in enumerate(csv.DictReader(f)):
            s = (*(int(float(row[k])) * IMU_ACCEL_SCALE for k in ("ax_raw", "ay_raw", "az_raw")),
                 *(int(float(row[k])) * IMU_GYRO_SCALE  for k in ("gx_raw", "gy_raw", "gz_raw")))
            if "phase" in row:
                (pre if row["phase"] == "pre" else gesture).append(s)
            else:
                t = float(row["t"])
                if start is not None and t < start:
                    if t >= start - 1.0:
                        pre.append(s)
                elif end is None or t < end:
                    gesture.append(s)
    return pre, gesture


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--start", type=float)
    ap.add_argument("--end",   type=float)
    ap.add_argument("--wand",  help="MAC address whose motion profile to use")
    ap.add_argument("--out",   default="replay.png")
    args = ap.parse_args()

    files = args.files or sorted(glob.glob(os.path.join(HERE, "captures", "*.csv")))
    if not files:
        print("No captures found — record some with wand_tuner.py → Save Capture.")
        return

    motion  = WandProfiles().load_motion(args.wand) if args.wand else None
    library = SpellLibrary(folder=os.path.join(HERE, "spells"))
    matcher = SpellMatcher()

    fig, axes = plt.subplots(2, len(files), figsize=(3.2 * len(files), 6.4), squeeze=False)
    for col, path in enumerate(files):
        pre, gesture = load_capture(path, args.start, args.end)
        name = os.path.basename(path)
        xs, ys, st = run_pipeline(gesture, pre_samples=pre, motion=motion)
        ox, oy, _  = run_accel_pipeline(gesture, 0.5, 0.01, 1.5, 60.0,
                                        swap_xy=True, flip_y=True)

        results = matcher.match_all(np.column_stack([xs, ys]), library) if len(xs) > 1 else []
        top = ", ".join(f"{r['spell']} {r['score']:.3f}{'✓' if r['success'] else ''}"
                        for r in results[:3]) or "too short"
        clip = f"  ⚠ {st['clipped']} clipped" if st["clipped"] else ""
        print(f"{name}: {len(gesture)} samples, {len(xs)} pts{clip}\n    top-3: {top}")

        for row, (x, y, title) in enumerate([(xs, ys, f"gyro  {name}"),
                                              (ox, oy, "legacy accel")]):
            ax = axes[row][col]
            if len(x) > 1:
                ax.plot(x, y, lw=1.5)
                ax.plot(x[:1], y[:1], "o", color="grey")
                ax.plot(x[-1:], y[-1:], "o", color="goldenrod")
            ax.set_title(title, fontsize=7)
            ax.set_aspect("equal", "datalim")
            ax.tick_params(labelsize=6)
    fig.tight_layout()
    fig.savefig(args.out, dpi=90)
    print(f"\nSaved comparison → {args.out}")


if __name__ == "__main__":
    main()
