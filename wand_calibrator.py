"""
wand_calibrator.py — Guided motion calibration for the Magic Caster Wand
=========================================================================
Opens as a modal Toplevel window from the main GUI and measures the three
things motion.GestureTracker needs per wand.  Every step advances on its own
by watching for stillness / motion — no buttons to press mid-step.

  1. Rest     — lay the wand flat and still     → gyro bias + noise
  2. Tip up   — point the tip at the ceiling    → tip axis (sensor frame)
  3. Swipe up — point at the screen, swipe UP    → tip sign check
  4. Swipe right                                 → left/right sign check

Results are stored in wand_profiles.json under the wand's MAC as:
    "motion": {"tip_axis": [x,y,z], "gyro_bias": [x,y,z] (rad/s),
               "gyro_noise_dps": [x,y,z], "params": {"flip_x": bool}, ...}

The old up/down/left/right accel-mean wizard is gone: averaging accel over a
swing mostly measures how the wand was held, not which way it moved.
"""

import time
import tkinter as tk
from tkinter import ttk
from typing import Optional

import numpy as np

from motion import GestureTracker, GyroBias, run_pipeline

# ── Palette (matches wand_gui.py) ─────────────────────────────────────────────
BG       = "#0a0c1a"
BG2      = "#0f1228"
BG3      = "#161a38"
GOLD     = "#c9a84c"
GOLD_DIM = "#7a6328"
GREEN    = "#34d399"
RED      = "#f87171"
BLUE     = "#4a9eff"
TEXT     = "#e8e4d8"
TEXT_DIM = "#6b6880"
BORDER   = "#2a2d4a"
PURPLE   = "#8b5cf6"

STILL_SPAN   = GyroBias.STILL_SPAN   # rad/s peak deviation that counts as still (on a table)
HAND_SPAN    = np.radians(12)        # looser: hand-held "still" has tremor
STILL_WINDOW = 110                   # samples (0.5 s) of stillness before collecting
COLLECT_N    = 330                   # samples (1.5 s) collected once still
MOVE_RATE    = np.radians(60)        # rad/s — a swipe has started
SNAP_DEG     = 25.0                  # snap tip axis to a sensor axis if this close

STEPS = [
    {"id": "rest",  "icon": "━", "color": TEXT_DIM, "title": "Lay the wand flat",
     "instruction": "Put the wand down on a table and don't touch it."},
    {"id": "tipup", "icon": "↑", "color": GREEN, "title": "Point the tip at the ceiling",
     "instruction": "Hold the wand vertical, tip straight up, as still as you can."},
    {"id": "swipe_up", "icon": "↑", "color": BLUE, "title": "Swipe UP",
     "instruction": "Point the wand at the screen, hold still for a moment,\n"
                    "then raise the tip smoothly UPWARD and stop."},
    {"id": "swipe_right", "icon": "→", "color": BLUE, "title": "Swipe RIGHT",
     "instruction": "Point the wand at the screen, hold still for a moment,\n"
                    "then sweep it smoothly to the RIGHT and stop."},
    {"id": "done",  "icon": "✦", "color": GREEN, "title": "Calibration complete",
     "instruction": ""},
]


class WandCalibrator(tk.Toplevel):
    """Modal motion-calibration wizard.  Feed it every IMU sample."""

    def __init__(self, parent: tk.Tk, on_saved=None):
        super().__init__(parent)
        self._on_saved = on_saved
        self.title("✦ Wand Calibration")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self._step_idx = -1
        self._win: list = []        # rolling window for stillness detection
        self._buf: list = []        # samples for the current step
        self._phase = "idle"        # idle | settle | collect | armed | swiping
        self._result: dict = {}

        self._build()
        self._show_intro()

        self.update_idletasks()
        px, py = parent.winfo_x(), parent.winfo_y()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h   = self.winfo_width(), self.winfo_height()
        self.geometry(f"+{px+(pw-w)//2}+{py+(ph-h)//2}")

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build(self):
        tk.Label(self, text="✦  WAND CALIBRATION", bg=BG, fg=GOLD,
                 font=("Georgia", 16, "bold"), pady=12).pack(fill="x")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=16)

        self._icon_lbl = tk.Label(self, text="", bg=BG, fg=TEXT, font=("Segoe UI", 48))
        self._icon_lbl.pack(pady=(10, 0))
        self._title_lbl = tk.Label(self, text="", bg=BG, fg=GOLD,
                                   font=("Georgia", 14, "bold"))
        self._title_lbl.pack()
        self._instr_lbl = tk.Label(self, text="", bg=BG, fg=TEXT,
                                   font=("Georgia", 11), wraplength=400,
                                   justify="center", pady=8)
        self._instr_lbl.pack(padx=30)

        pb_frame = tk.Frame(self, bg=BG, pady=8)
        pb_frame.pack(fill="x", padx=40)
        style = ttk.Style()
        style.configure("Cal.Horizontal.TProgressbar",
                        troughcolor=BG3, background=GREEN,
                        bordercolor=BORDER, lightcolor=GREEN, darkcolor=GREEN)
        self._progress = ttk.Progressbar(pb_frame, style="Cal.Horizontal.TProgressbar",
                                         orient="horizontal", length=320,
                                         mode="determinate", maximum=COLLECT_N)
        self._progress.pack()

        self._status_lbl = tk.Label(self, text="", bg=BG, fg=TEXT_DIM,
                                    font=("Courier New", 9), pady=4, justify="left")
        self._status_lbl.pack()

        btn_row = tk.Frame(self, bg=BG, pady=12)
        btn_row.pack()
        self._next_btn = tk.Button(btn_row, text="Begin  →", bg=GOLD_DIM, fg=BG, bd=0,
                                   padx=16, pady=5, font=("Courier New", 10, "bold"),
                                   activebackground=GOLD, command=self._on_next)
        self._next_btn.pack(side="left", padx=6)
        tk.Button(btn_row, text="Cancel", bg=BG3, fg=TEXT_DIM, bd=0,
                  padx=14, pady=5, font=("Courier New", 9),
                  activebackground=BORDER, command=self._cancel).pack(side="left", padx=6)

    def _show_intro(self):
        self._icon_lbl.configure(text="✦", fg=GOLD)
        self._title_lbl.configure(text="Motion calibration")
        self._instr_lbl.configure(
            text="Four quick steps, about 30 seconds.\n"
                 "Each step advances on its own once the wand is held right.")

    def _on_next(self):
        if self._step_idx >= len(STEPS) - 1:
            self._save()
            self.destroy()
            return
        self._goto_step(self._step_idx + 1)

    def _goto_step(self, idx: int):
        self._step_idx = idx
        step = STEPS[idx]
        self._icon_lbl.configure(text=step["icon"], fg=step["color"])
        self._title_lbl.configure(text=step["title"])
        self._instr_lbl.configure(text=step["instruction"])
        self._progress["value"] = 0
        self._win.clear()
        self._buf.clear()
        if step["id"] == "done":
            self._phase = "idle"
            self._instr_lbl.configure(text=self._summary())
            self._next_btn.configure(state="normal", text="Save  ✓")
        else:
            self._phase = "settle"
            self._next_btn.configure(state="disabled", text="Waiting…")
            self._status_lbl.configure(text="waiting for the wand to be still…", fg=TEXT_DIM)

    # ── Sample intake ─────────────────────────────────────────────────────────

    def feed_sample(self, ax, ay, az, gx, gy, gz):
        """Called by the main GUI for every IMU sample (sensor frame, G / rad/s)."""
        if self._phase == "idle":
            return
        s = (ax, ay, az, gx, gy, gz)
        step = STEPS[self._step_idx]["id"]

        self._win.append(s)
        if len(self._win) > STILL_WINDOW:
            self._win.pop(0)
        span = STILL_SPAN if step == "rest" else HAND_SPAN
        g = np.array(self._win)[:, 3:]
        still = len(self._win) == STILL_WINDOW and np.abs(g - g.mean(0)).max() < span

        if step in ("rest", "tipup"):
            self._feed_static(step, s, still, span)
        else:
            self._feed_swipe(s, still)

    def _feed_static(self, step: str, s: tuple, still: bool, span: float):
        if self._phase == "settle":
            if still:
                self._phase = "collect"
                self._buf = list(self._win)
            return
        # collect
        g = np.array(self._buf[-STILL_WINDOW:])[:, 3:]
        if np.abs(np.array(s[3:]) - g.mean(0)).max() > span * 1.5:
            self._phase = "settle"
            self._buf.clear()
            self._progress["value"] = 0
            self._status_lbl.configure(text="moved — hold still…", fg=RED)
            return
        self._buf.append(s)
        self._progress["value"] = len(self._buf)
        if len(self._buf) >= COLLECT_N:
            self._phase = "idle"
            self._finish_static(step, np.array(self._buf))

    def _finish_static(self, step: str, arr: np.ndarray):
        acc, gyr = arr[:, :3], arr[:, 3:]
        if step == "rest":
            self._result["gyro_bias"]      = gyr.mean(0).tolist()
            self._result["gyro_noise_dps"] = np.degrees(gyr.std(0)).round(3).tolist()
            self._status_lbl.configure(
                text=f"bias  {np.degrees(gyr.mean(0)).round(2)} deg/s\n"
                     f"noise {np.degrees(gyr.std(0)).round(2)} deg/s", fg=GREEN)
        else:
            tip = acc.mean(0)
            tip /= np.linalg.norm(tip)
            k = int(np.argmax(np.abs(tip)))
            off_deg = float(np.degrees(np.arccos(min(1.0, abs(tip[k])))))
            snapped = off_deg <= SNAP_DEG
            if snapped:
                tip = np.zeros(3)
                tip[k] = np.sign(acc.mean(0)[k])
            self._result["tip_axis"] = tip.round(4).tolist()
            self._result["tip_raw_offset_deg"] = round(off_deg, 1)
            name = ("+" if tip[k] > 0 else "-") + "xyz"[k]
            self._status_lbl.configure(
                text=f"tip axis {name}" + (f"  ({off_deg:.0f}° off-axis, snapped)" if snapped
                                          else f"  (not snapped: {off_deg:.0f}° off-axis)"),
                fg=GREEN)
        self.after(900, self._on_next)

    def _feed_swipe(self, s: tuple, still: bool):
        if self._phase == "settle":
            if still:
                self._phase = "armed"
                self._pre = list(self._win)
                self._status_lbl.configure(
                    text=f"ready — {STEPS[self._step_idx]['title'].lower()}", fg=BLUE)
            return
        rate = float(np.linalg.norm(np.array(s[3:]) - np.array(self._result.get("gyro_bias", (0, 0, 0)))))
        if self._phase == "armed":
            if rate > MOVE_RATE:
                self._phase = "swiping"
                self._buf = [s]
            else:
                self._pre = (self._pre + [s])[-STILL_WINDOW:]
            return
        # swiping — stop once still again (or after 2 s)
        self._buf.append(s)
        if (still and len(self._buf) > STILL_WINDOW) or len(self._buf) > 440:
            self._phase = "idle"
            self._finish_swipe()

    def _finish_swipe(self):
        motion = {k: self._result[k] for k in ("tip_axis", "gyro_bias") if k in self._result}
        xs, ys, _ = run_pipeline(self._buf, pre_samples=self._pre, motion=motion)
        dx, dy = float(xs[-1] - xs[0]), float(ys[-1] - ys[0])
        vertical = STEPS[self._step_idx]["id"] == "swipe_up"
        main, cross = (dy, dx) if vertical else (dx, dy)
        if abs(main) < 15 or abs(main) < 1.5 * abs(cross):
            self._goto_step(self._step_idx)
            self._status_lbl.configure(
                text=f"that read as ({dx:+.0f}°, {dy:+.0f}°) — sweep wider and straighter, "
                     f"try again", fg=RED)
            return
        if vertical:
            # Negating the tip inverts vertical only (horizontal is unchanged),
            # so this is safe to settle before the left/right check.
            flipped = dy < 0
            if flipped:
                self._result["tip_axis"] = [-v for v in self._result["tip_axis"]]
            self._result["swipe_up_check"] = [round(dx, 1), round(dy, 1)]
            self._status_lbl.configure(
                text=f"swipe read as {abs(dy):.0f}° "
                     f"{'down → tip was upside-down, fixed' if flipped else 'up ✓'}", fg=GREEN)
            self.after(900, self._on_next)
            return
        flip = dx < 0
        self._result["params"] = {"flip_x": bool(flip)}
        self._result["swipe_check"] = [round(dx, 1), round(dy, 1)]
        self._status_lbl.configure(
            text=f"swipe read as {abs(dx):.0f}° {'left → flipping X' if flip else 'right ✓'}",
            fg=GREEN)
        self.after(900, self._on_next)

    # ── Results ───────────────────────────────────────────────────────────────

    def _summary(self) -> str:
        r = self._result
        tip = r.get("tip_axis", [0, 0, 0])
        bias = np.degrees(r.get("gyro_bias", [0, 0, 0]))
        return (f"Tip axis   {np.round(tip, 2).tolist()}\n"
                f"Gyro bias  {bias.round(2).tolist()} deg/s\n"
                f"Flip X     {r.get('params', {}).get('flip_x', False)}")

    def _save(self):
        self._result["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        if self._on_saved:
            self._on_saved(dict(self._result))

    def _cancel(self):
        self._phase = "idle"
        self.destroy()
