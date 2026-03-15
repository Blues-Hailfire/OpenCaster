"""
wand_calibrator.py — Guided IMU axis calibration for the Magic Caster Wand
===========================================================================
Opens as a modal Toplevel window from the main GUI.
Walks the user through a 5-step axis calibration sequence:

  1. Flat  — place wand on flat surface (3s countdown, no cast needed)
  2. Up    — perform a cast gesture moving the wand UPWARD
  3. Down  — perform a cast gesture moving the wand DOWNWARD
  4. Left  — perform a cast gesture moving the wand LEFT
  5. Right — perform a cast gesture moving the wand RIGHT

Each directional step is triggered automatically when the user
performs a cast gesture (gesture window open → close).
IMU samples are collected during the gesture window.
Results are saved to calibration.json next to the script.
"""

import json
import os
import time
import tkinter as tk
from tkinter import ttk
from typing import Optional
import numpy as np

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

CALIBRATION_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "calibration.json")

# ── Calibration steps ─────────────────────────────────────────────────────────
# collect=False → auto-countdown, no cast needed
# collect=True  → triggered by user's cast gesture

STEPS = [
    {
        "id":          "flat",
        "title":       "Place wand flat",
        "instruction": "Place the wand on a flat, level surface and keep it still.\nCalibration will begin automatically.",
        "icon":        "━",
        "color":       TEXT_DIM,
        "collect":     False,
        "wait_secs":   3,
    },
    {
        "id":          "up",
        "title":       "Cast  ↑  UP",
        "instruction": "Pick up the wand and perform a cast gesture\nmoving the wand firmly UPWARD.",
        "icon":        "↑",
        "color":       GREEN,
        "collect":     True,
    },
    {
        "id":          "centre_1",
        "title":       "Return to centre",
        "instruction": "Hold the wand still in a neutral position.",
        "icon":        "•",
        "color":       TEXT_DIM,
        "collect":     False,
        "wait_secs":   2,
    },
    {
        "id":          "down",
        "title":       "Cast  ↓  DOWN",
        "instruction": "Perform a cast gesture moving the wand firmly DOWNWARD.",
        "icon":        "↓",
        "color":       BLUE,
        "collect":     True,
    },
    {
        "id":          "centre_2",
        "title":       "Return to centre",
        "instruction": "Hold the wand still in a neutral position.",
        "icon":        "•",
        "color":       TEXT_DIM,
        "collect":     False,
        "wait_secs":   2,
    },
    {
        "id":          "left",
        "title":       "Cast  ←  LEFT",
        "instruction": "Perform a cast gesture moving the wand firmly to the LEFT.",
        "icon":        "←",
        "color":       GOLD,
        "collect":     True,
    },
    {
        "id":          "centre_3",
        "title":       "Return to centre",
        "instruction": "Hold the wand still in a neutral position.",
        "icon":        "•",
        "color":       TEXT_DIM,
        "collect":     False,
        "wait_secs":   2,
    },
    {
        "id":          "right",
        "title":       "Cast  →  RIGHT",
        "instruction": "Perform a cast gesture moving the wand firmly to the RIGHT.",
        "icon":        "→",
        "color":       PURPLE,
        "collect":     True,
    },
    {
        "id":          "done",
        "title":       "Calibration complete",
        "instruction": "All axes captured. Results saved to calibration.json.",
        "icon":        "✦",
        "color":       GREEN,
        "collect":     False,
        "wait_secs":   0,
    },
]


class WandCalibrator(tk.Toplevel):
    """Modal calibration wizard — cast-triggered collection."""

    def __init__(self, parent: tk.Tk, on_saved=None):
        """
        on_saved: optional callback(calibration_dict) called after save.
        """
        super().__init__(parent)
        self._on_saved = on_saved
        self.title("✦ Wand Calibration")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        self._step_idx      = 0
        self._collecting    = False   # True while gesture window is open
        self._waiting_cast  = False   # True when we're waiting for user to cast
        self._samples: dict[str, list] = {}
        self._current_buf: list = []
        self._countdown_job = None
        self._auto_job      = None

        self._build()
        self._goto_step(0)

        # Centre over parent
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

        # Step dots (one per collect step)
        step_row = tk.Frame(self, bg=BG, pady=6)
        step_row.pack(fill="x", padx=20)
        self._step_dots = []
        for s in [s for s in STEPS if s["collect"]]:
            dot = tk.Label(step_row, text="⬤", bg=BG, fg=BG3,
                           font=("Segoe UI", 10))
            dot.pack(side="left", padx=4)
            self._step_dots.append((dot, s["id"]))

        self._icon_lbl = tk.Label(self, text="", bg=BG, fg=TEXT,
                                   font=("Segoe UI", 48))
        self._icon_lbl.pack(pady=(10, 0))

        self._title_lbl = tk.Label(self, text="", bg=BG, fg=GOLD,
                                    font=("Georgia", 14, "bold"))
        self._title_lbl.pack()

        self._instr_lbl = tk.Label(self, text="", bg=BG, fg=TEXT,
                                    font=("Georgia", 11), wraplength=380,
                                    justify="center", pady=8)
        self._instr_lbl.pack(padx=30)

        pb_frame = tk.Frame(self, bg=BG, pady=8)
        pb_frame.pack(fill="x", padx=40)
        style = ttk.Style()
        style.configure("Cal.Horizontal.TProgressbar",
                        troughcolor=BG3, background=GREEN,
                        bordercolor=BORDER, lightcolor=GREEN, darkcolor=GREEN)
        self._progress = ttk.Progressbar(
            pb_frame, style="Cal.Horizontal.TProgressbar",
            orient="horizontal", length=320, mode="determinate")
        self._progress.pack()
        self._progress_lbl = tk.Label(pb_frame, text="", bg=BG, fg=TEXT_DIM,
                                       font=("Courier New", 8))
        self._progress_lbl.pack(pady=(2, 0))

        self._status_lbl = tk.Label(self, text="", bg=BG, fg=TEXT_DIM,
                                     font=("Courier New", 9), pady=4)
        self._status_lbl.pack()

        btn_row = tk.Frame(self, bg=BG, pady=12)
        btn_row.pack()
        self._next_btn = tk.Button(
            btn_row, text="Begin  →", bg=GOLD_DIM, fg=BG, bd=0,
            padx=16, pady=5, font=("Courier New", 10, "bold"),
            activebackground=GOLD, command=self._on_begin)
        self._next_btn.pack(side="left", padx=6)
        tk.Button(btn_row, text="Cancel", bg=BG3, fg=TEXT_DIM, bd=0,
                  padx=14, pady=5, font=("Courier New", 9),
                  activebackground=BORDER, command=self._cancel).pack(side="left", padx=6)
        tk.Button(btn_row, text="Clear Calibration", bg=BG3, fg=RED, bd=0,
                  padx=14, pady=5, font=("Courier New", 9),
                  activebackground=BORDER,
                  command=self._clear_calibration).pack(side="left", padx=6)

    # ── Step navigation ────────────────────────────────────────────────────────

    def _goto_step(self, idx: int):
        if self._countdown_job:
            self.after_cancel(self._countdown_job)
            self._countdown_job = None
        if self._auto_job:
            self.after_cancel(self._auto_job)
            self._auto_job = None

        self._step_idx     = idx
        self._collecting   = False
        self._waiting_cast = False
        self._current_buf.clear()
        self._progress["value"] = 0
        self._progress_lbl.configure(text="")

        if idx >= len(STEPS):
            return

        step = STEPS[idx]
        self._icon_lbl.configure(text=step["icon"], fg=step["color"])
        self._title_lbl.configure(text=step["title"], fg=step["color"])
        self._instr_lbl.configure(text=step["instruction"])
        self._status_lbl.configure(text="")

        # Update progress dots
        done_ids = [s["id"] for s in STEPS[:idx] if s["collect"]]
        for dot, sid in self._step_dots:
            if sid in done_ids:
                dot.configure(fg=GREEN)
            elif sid == step["id"] and step["collect"]:
                dot.configure(fg=step["color"])
            else:
                dot.configure(fg=BG3)

        if step["id"] == "done":
            self._save_calibration()
            self._next_btn.configure(text="Close", state="normal",
                                      command=self._finish,
                                      bg=GREEN, fg=BG)
            self._status_lbl.configure(text="✦  Calibration saved!", fg=GREEN)
            return

        if step["collect"]:
            # Waiting for user to cast — disable button, show pulse instruction
            self._next_btn.configure(state="disabled", text="Waiting for cast…")
            self._waiting_cast = True
            self._status_lbl.configure(
                text="⟳  Perform the cast gesture now", fg=step["color"])
        elif step.get("wait_secs", 0) > 0:
            self._next_btn.configure(state="disabled", text="Please wait…")
            self._run_countdown(step["wait_secs"])
        else:
            # Should not normally happen, but handle gracefully
            self._auto_job = self.after(300, self._advance_step)

    def _on_begin(self):
        """Only used for the very first step (flat surface countdown)."""
        self._advance_step()

    def _run_countdown(self, secs: int):
        if secs <= 0:
            self._status_lbl.configure(text="")
            self._auto_job = self.after(200, self._advance_step)
            return
        self._status_lbl.configure(
            text=f"Auto-advancing in {secs}s…", fg=TEXT_DIM)
        self._countdown_job = self.after(1000, self._run_countdown, secs - 1)

    def _advance_step(self):
        self._goto_step(self._step_idx + 1)

    # ── Cast-triggered collection ──────────────────────────────────────────────

    def feed_gesture_open(self):
        """Called by main GUI when gesture window opens (100b)."""
        if not self._waiting_cast:
            return
        step = STEPS[self._step_idx]
        self._collecting   = True
        self._waiting_cast = False
        self._current_buf.clear()
        self._progress["maximum"] = 0   # indeterminate while collecting
        self._progress.configure(mode="indeterminate")
        self._progress.start(50)
        self._status_lbl.configure(
            text="● Recording gesture…", fg=step["color"])

    def feed_gesture_close(self):
        """Called by main GUI when gesture window closes (1000/100f)."""
        if not self._collecting:
            return
        step = STEPS[self._step_idx]
        self._collecting = False
        self._progress.stop()
        self._progress.configure(mode="determinate")
        n = len(self._current_buf)

        if n < 5:
            # Too few samples — gesture was too short, ask again
            self._waiting_cast = True
            self._status_lbl.configure(
                text=f"Too short ({n} samples) — try again", fg=RED)
            self._progress["value"] = 0
            self._progress_lbl.configure(text="")
            return

        self._samples[step["id"]] = list(self._current_buf)
        self._progress["maximum"] = n
        self._progress["value"]   = n
        self._progress_lbl.configure(text=f"{n} samples captured")
        self._status_lbl.configure(
            text=f"✓  {step['title']} captured", fg=GREEN)

        # Auto-advance to next step after a brief pause
        self._auto_job = self.after(800, self._advance_step)

    def feed_sample(self, ax: int, ay: int, az: int):
        """Called by main GUI for every IMU sample."""
        if self._collecting:
            self._current_buf.append((ax, ay, az))

    # ── Save / finish / cancel ─────────────────────────────────────────────────

    def _finish(self):
        self.destroy()

    def _cancel(self):
        for job in (self._countdown_job, self._auto_job):
            if job:
                self.after_cancel(job)
        self.destroy()

    def _clear_calibration(self):
        """Delete calibration.json and reset the wizard to the start."""
        if os.path.isfile(CALIBRATION_FILE):
            os.remove(CALIBRATION_FILE)
        self._samples.clear()
        self._status_lbl.configure(text="Calibration cleared.", fg=RED)
        self._goto_step(0)

    def _save_calibration(self):
        import numpy as np
        result = {"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), "axes": {}}

        for step_id, samples in self._samples.items():
            arr = np.array(samples, dtype=float)
            result["axes"][step_id] = {
                "mean_ax": float(arr[:, 0].mean()),
                "mean_ay": float(arr[:, 1].mean()),
                "mean_az": float(arr[:, 2].mean()),
                "std_ax":  float(arr[:, 0].std()),
                "std_ay":  float(arr[:, 1].std()),
                "std_az":  float(arr[:, 2].std()),
                "n":       len(samples),
            }

        axis_names = ["ax", "ay", "az"]
        axes = result["axes"]

        # ── Axis identification ───────────────────────────────────────────────
        if "up" in axes and "down" in axes:
            up_m   = np.array([axes["up"][f"mean_{a}"]   for a in axis_names])
            down_m = np.array([axes["down"][f"mean_{a}"] for a in axis_names])
            result["vertical_axis"] = axis_names[int(np.argmax(np.abs(up_m - down_m)))]

        if "left" in axes and "right" in axes:
            left_m  = np.array([axes["left"][f"mean_{a}"]  for a in axis_names])
            right_m = np.array([axes["right"][f"mean_{a}"] for a in axis_names])
            result["horizontal_axis"] = axis_names[int(np.argmax(np.abs(left_m - right_m)))]

        with open(CALIBRATION_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)

        print(f"  [calibration] Saved → {CALIBRATION_FILE}")
        for k in ("vertical_axis", "horizontal_axis"):
            if k in result:
                print(f"  [calibration] {k}: {result[k]}")

        if self._on_saved:
            self._on_saved(result)


def load_calibration() -> Optional[dict]:
    if os.path.isfile(CALIBRATION_FILE):
        with open(CALIBRATION_FILE, encoding="utf-8") as f:
            return json.load(f)
    return None
