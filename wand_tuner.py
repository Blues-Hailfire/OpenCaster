"""
wand_tuner.py — IMU Drawing Parameter Tuner for OpenCaster
===========================================================
Connect to the wand and tune drawing parameters in real-time.
Replay the last captured gesture with any new settings instantly —
no need to re-cast the spell each time you change a value.

Usage: python wand_tuner.py
"""

import asyncio, csv, json, os, queue, struct, threading, time
from collections import deque
import tkinter as tk
from tkinter import ttk, filedialog
from typing import Optional

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from bleak import BleakClient, BleakScanner

from motion import (decode_imu_packet, GestureTracker, DEFAULTS as MOTION_DEFAULTS,
                    run_pipeline as run_gyro_pipeline, IMU_ACCEL_SCALE, IMU_GYRO_SCALE)

# ── BLE UUIDs and IMU scale factors ───────────────────────────────────────────
WRITE_UUID      = "57420002-587e-48a0-974c-544d6163c577"
NOTIFY_UUID     = "57420003-587e-48a0-974c-544d6163c577"
# ── Palette ───────────────────────────────────────────────────────────────────
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

# ── Parameter presets ─────────────────────────────────────────────────────────
# "Gyro" is what wand_gui.py runs (motion.GestureTracker).  The accel presets
# are the legacy delta-accel pipeline, kept only for side-by-side comparison:
# it telescopes to accel[n]-accel[0] and cannot see yaw.
PRESETS = {
    "Default":   dict(alpha=0.50, dead_zone=0.010, hysteresis=1.5, accel_scale=60.0,
                      use_gyro=False, swap_xy=True,  flip_x=False, flip_y=True),
    "Smooth":    dict(alpha=0.20, dead_zone=0.015, hysteresis=2.0, accel_scale=50.0,
                      use_gyro=False, swap_xy=True,  flip_x=False, flip_y=True),
    "Sensitive": dict(alpha=0.70, dead_zone=0.005, hysteresis=1.2, accel_scale=80.0,
                      use_gyro=False, swap_xy=True,  flip_x=False, flip_y=True),
    "Gyro":      dict(use_gyro=True, min_rate=MOTION_DEFAULTS["min_rate"],
                      min_step=MOTION_DEFAULTS["min_step"]),
    "No Remap":  dict(alpha=0.50, dead_zone=0.010, hysteresis=1.5, accel_scale=60.0,
                      use_gyro=False, swap_xy=False, flip_x=False, flip_y=False),
}


TIP_AXES = {"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0),
            "-y": (0, -1, 0), "+z": (0, 0, 1), "-z": (0, 0, -1)}


# ── Legacy accel pipeline (pure function — used for both live and replay) ─────

def run_accel_pipeline(raw_samples: list, alpha: float, dead_zone: float,
                 hysteresis: float, accel_scale: float,
                 use_gyro=False, swap_xy=False, flip_x=False, flip_y=False):
    """Process raw IMU samples through the full drawing pipeline.

    raw_samples : list of (ax, ay, az, gx, gy, gz) scaled floats
    Returns (trail_x, trail_y, stats_dict)
    """
    trail_x: list[float] = []
    trail_y: list[float] = []
    prev_x = prev_y = None
    ema_x  = ema_y  = None
    dz_active = False
    pos_x = pos_y = 0.0
    total = filtered = 0

    for ax, ay, az, gx, gy, gz in raw_samples:
        src_x = gx if use_gyro else ax
        src_y = gy if use_gyro else ay

        if swap_xy:
            src_x, src_y = src_y, src_x
        if flip_x:
            src_x = -src_x
        if flip_y:
            src_y = -src_y

        if prev_x is None:
            prev_x, prev_y = src_x, src_y
            continue

        dx = src_x - prev_x
        dy = src_y - prev_y
        prev_x, prev_y = src_x, src_y
        total += 1

        if ema_x is None:
            ema_x, ema_y = dx, dy
        else:
            ema_x = alpha * dx + (1 - alpha) * ema_x
            ema_y = alpha * dy + (1 - alpha) * ema_y

        mag       = max(abs(ema_x), abs(ema_y))
        re_entry  = dead_zone * hysteresis

        if dz_active:
            if mag < dead_zone:
                dz_active = False
        else:
            if mag >= re_entry:
                dz_active = True

        if not dz_active:
            filtered += 1
            continue

        pos_x += ema_x * accel_scale
        pos_y += ema_y * accel_scale
        trail_x.append(pos_x)
        trail_y.append(pos_y)

    pass_pct = 100 * (total - filtered) / max(total, 1)
    stats = {
        "raw":      total,
        "filtered": filtered,
        "points":   len(trail_x),
        "pass_pct": pass_pct,
    }
    return trail_x, trail_y, stats


# ── BLE Worker ────────────────────────────────────────────────────────────────

class BLEWorker:
    SCAN_TIMEOUT = 6.0

    def __init__(self, q: queue.Queue):
        self.q = q
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._client: Optional[BleakClient] = None
        self._stop = False
        self._target_name:    Optional[str] = None
        self._target_address: Optional[str] = None
        self._connect_event:  Optional[asyncio.Event] = None

    def start(self):
        threading.Thread(target=lambda: asyncio.run(self._main()), daemon=True).start()

    def stop(self):
        self._stop = True
        if self.loop and self._connect_event:
            self.loop.call_soon_threadsafe(self._connect_event.set)

    async def _main(self):
        self.loop = asyncio.get_running_loop()
        self._connect_event = asyncio.Event()
        while not self._stop:
            await self._connect_event.wait()
            self._connect_event.clear()
            if self._stop:
                break
            await self._session()

    def scan_for_wands(self, cb):
        def _worker():
            async def _scan():
                devs = await BleakScanner.discover(timeout=self.SCAN_TIMEOUT)
                return [(d.name, d.address) for d in devs
                        if d.name and d.name.startswith("MCW")]
            lp = asyncio.new_event_loop()
            try:
                res = lp.run_until_complete(_scan())
            except Exception:
                res = []
            finally:
                lp.close()
            cb(res)
        threading.Thread(target=_worker, daemon=True).start()

    def connect_to(self, name: str, address: str):
        self._target_name    = name
        self._target_address = address
        if self.loop and self._connect_event:
            self.loop.call_soon_threadsafe(self._connect_event.set)

    async def _session(self):
        self.q.put({"type": "status", "text": f"Connecting to {self._target_name}…"})
        retry = 2.0
        while not self._stop:
            if self._connect_event.is_set():
                self._connect_event.clear()
                return
            try:
                async with BleakClient(self._target_address, timeout=20.0) as client:
                    self._client = client
                    self.q.put({"type": "connected", "name": self._target_name})
                    retry = 2.0

                    # Inline pong handler so the wand doesn't disconnect us
                    async def _pong():
                        try:
                            await client.write_gatt_char(
                                WRITE_UUID, bytes([0x01]), response=False)
                        except Exception:
                            pass

                    def _on_notify(_, data):
                        data = bytes(data)
                        if data and data[0] == 0x01:
                            asyncio.run_coroutine_threadsafe(_pong(), self.loop)
                        else:
                            self.q.put({"type": "ble", "data": data})

                    await client.start_notify(NOTIFY_UUID, _on_notify)
                    await asyncio.sleep(0.3)

                    # Start IMU streaming
                    await client.write_gatt_char(WRITE_UUID, bytes([0x31]), response=False)
                    await asyncio.sleep(0.1)
                    await client.write_gatt_char(
                        WRITE_UUID, bytes([0x30, 0x00, 0x80]), response=False)

                    while not self._stop and client.is_connected:
                        if self._connect_event.is_set():
                            break
                        await asyncio.sleep(0.5)

                    try:
                        await client.write_gatt_char(
                            WRITE_UUID, bytes([0x31]), response=False)
                    except Exception:
                        pass
                    await client.stop_notify(NOTIFY_UUID)

                self._client = None
                self.q.put({"type": "disconnected"})
                if self._connect_event.is_set():
                    return
                if not self._stop:
                    self.q.put({"type": "status", "text": "Disconnected — reconnecting…"})
                    await asyncio.sleep(2.0)

            except Exception as e:
                self._client = None
                self.q.put({"type": "disconnected"})
                self.q.put({"type": "status", "text": f"Error: {e}"})
                if self._connect_event.is_set():
                    return
                if not self._stop:
                    await asyncio.sleep(retry)
                    retry = min(retry * 1.5, 15.0)


# ── Main GUI ─────────────────────────────────────────────────────────────────

class WandTuner:
    GESTURE_TIMEOUT_S = 10.0

    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("✦ OpenCaster — IMU Tuner")
        root.configure(bg=BG)
        root.geometry("1340x840")
        root.minsize(1100, 720)

        self.q:   queue.Queue = queue.Queue()
        self.ble: BLEWorker   = BLEWorker(self.q)

        # Connection state
        self._found_wands: dict  = {}
        self._scanning           = False
        self._wand_var           = tk.StringVar(value="")
        self.status_var          = tk.StringVar(value="Scan for wands, then connect")
        self.battery_var         = tk.StringVar(value="—")

        # Gesture state
        self.gesture_active      = False
        self._gesture_timer      = None
        self._button_states:dict = {}

        # Raw sample buffer for replay (pre-remap, scaled floats)
        self._live_raw: list     = []   # fills during active gesture
        self._last_raw: list     = []   # frozen after gesture closes
        # 1 s of samples before each gesture: settles world-up + gyro bias in
        # gyro mode and is saved alongside captures for offline replay.
        self._pre_raw: deque     = deque(maxlen=220)
        self._live_pre: list     = []
        self._last_pre: list     = []
        self._tracker: Optional[GestureTracker] = None
        self._live_gyro = False

        # Live accumulator state (reset each gesture open)
        self._prev_x = self._prev_y = None
        self._ema_x  = self._ema_y  = None
        self._dz_active = False
        self._pos_x = self._pos_y = 0.0
        self._live_trail_x: list = []
        self._live_trail_y: list = []

        self._build_ui()
        self.ble.start()
        root.after(50, self._poll)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Parameter accessor ─────────────────────────────────────────────────────

    def _params(self) -> dict:
        return dict(
            alpha       = self._alpha_var.get(),
            dead_zone   = self._dz_var.get(),
            hysteresis  = self._hys_var.get(),
            accel_scale = self._scale_var.get(),
            use_gyro    = bool(self._use_gyro.get()),
            swap_xy     = bool(self._swap_xy.get()),
            flip_x      = bool(self._flip_x.get()),
            flip_y      = bool(self._flip_y.get()),
            min_rate    = self._minrate_var.get(),
            min_step    = self._minstep_var.get(),
            tip_axis    = TIP_AXES[self._tip_var.get()],
            gyro_flip_x = bool(self._gyro_flip_x.get()),
        )

    def _gyro_kwargs(self, p: dict) -> dict:
        return dict(motion={"tip_axis": p["tip_axis"]}, min_rate=p["min_rate"],
                    min_step=p["min_step"], flip_x=p["gyro_flip_x"])

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(self.root, bg=BG, pady=8)
        hdr.pack(fill="x", padx=16, pady=(10, 0))
        tk.Label(hdr, text="✦  WAND TUNER", bg=BG, fg=GOLD,
                 font=("Georgia", 20, "bold")).pack(side="left")
        tk.Label(hdr, text="IMU Drawing Config Explorer", bg=BG, fg=TEXT_DIM,
                 font=("Georgia", 10, "italic")).pack(side="left", padx=(10, 0), pady=(5, 0))

        right = tk.Frame(hdr, bg=BG)
        right.pack(side="right")
        tk.Label(right, text="🔋", bg=BG, fg=TEXT_DIM,
                 font=("Segoe UI", 11)).pack(side="left")
        tk.Label(right, textvariable=self.battery_var, bg=BG, fg=GREEN,
                 font=("Courier New", 11, "bold")).pack(side="left", padx=(2, 12))
        self._conn_dot = tk.Label(right, text="⬤", bg=BG, fg=RED,
                                   font=("Segoe UI", 14))
        self._conn_dot.pack(side="left")
        tk.Label(right, textvariable=self.status_var, bg=BG, fg=TEXT_DIM,
                 font=("Courier New", 9)).pack(side="left", padx=(6, 12))

        self._scan_btn = tk.Button(
            right, text="Scan", bg=BG3, fg=TEXT_DIM, bd=0, padx=10, pady=3,
            font=("Courier New", 9), activebackground=BORDER, command=self._do_scan)
        self._scan_btn.pack(side="left", padx=(0, 4))

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Wand.TCombobox",
                        fieldbackground=BG3, background=BG3, foreground=TEXT,
                        selectbackground=BG3, selectforeground=TEXT,
                        arrowcolor=GOLD_DIM, bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER)
        style.map("Wand.TCombobox",
                  fieldbackground=[("readonly", BG3)],
                  selectbackground=[("readonly", BG3)])
        self._wand_combo = ttk.Combobox(
            right, textvariable=self._wand_var,
            style="Wand.TCombobox", state="readonly",
            width=18, font=("Courier New", 9))
        self._wand_combo["values"] = ["— no wands found —"]
        self._wand_combo.pack(side="left", padx=(0, 4))
        tk.Button(right, text="Connect", bg=GOLD_DIM, fg=BG, bd=0, padx=10, pady=3,
                  font=("Courier New", 9, "bold"), activebackground=GOLD,
                  command=self._do_connect).pack(side="left")

        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x", padx=16, pady=6)

        # ── Body ──────────────────────────────────────────────────────────────
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        body.columnconfigure(0, weight=0, minsize=250)
        body.columnconfigure(1, weight=1, minsize=460)
        body.columnconfigure(2, weight=0, minsize=250)
        body.rowconfigure(0, weight=1)

        self._build_param_panel(body)
        self._build_plot_panel(body)
        self._build_diag_panel(body)

    def _panel(self, parent, col, title):
        outer = tk.Frame(parent, bg=BORDER, padx=1, pady=1)
        outer.grid(row=0, column=col, sticky="nsew",
                   padx=(0 if col == 0 else 6, 0 if col == 2 else 6))
        inner = tk.Frame(outer, bg=BG2)
        inner.pack(fill="both", expand=True)
        tk.Label(inner, text=title, bg=BG2, fg=GOLD_DIM,
                 font=("Georgia", 9, "bold"), pady=6).pack(fill="x", padx=10)
        tk.Frame(inner, bg=BORDER, height=1).pack(fill="x")
        return inner

    # ── Parameter panel ───────────────────────────────────────────────────────

    def _build_param_panel(self, body):
        panel = self._panel(body, 0, "PARAMETERS")

        self._alpha_var = tk.DoubleVar(value=0.5)
        self._dz_var    = tk.DoubleVar(value=0.010)
        self._hys_var   = tk.DoubleVar(value=1.5)
        self._scale_var = tk.DoubleVar(value=60.0)

        sliders = [
            ("EMA Alpha",    self._alpha_var, 0.01, 1.0,  0.01, ".2f",
             "Smoothing: 0=frozen  1=raw delta"),
            ("Dead Zone",    self._dz_var,    0.001, 0.15, 0.001, ".4f",
             "Min delta to register movement"),
            ("Hysteresis",   self._hys_var,   1.0,  5.0,  0.1,  ".1f",
             "Exit DZ at DZ × this  (>1 = sticky)"),
            ("Accel Scale",  self._scale_var, 5.0,  500.0, 1.0, ".0f",
             "Pixels per G/sample (sensitivity)"),
        ]

        for lbl, var, lo, hi, res, fmt, tip in sliders:
            header = tk.Frame(panel, bg=BG2)
            header.pack(fill="x", padx=10, pady=(10, 0))
            tk.Label(header, text=lbl, bg=BG2, fg=GOLD,
                     font=("Courier New", 8, "bold"), anchor="w").pack(side="left")
            entry = tk.Entry(header, textvariable=var, width=8, bg=BG3, fg=TEXT,
                             insertbackground=TEXT, bd=0, relief="flat",
                             font=("Courier New", 9))
            entry.pack(side="right")

            slider = tk.Scale(
                panel, variable=var, from_=lo, to=hi, resolution=res,
                orient="horizontal", bg=BG2, fg=TEXT_DIM,
                troughcolor=BG3, highlightthickness=0, bd=0,
                activebackground=GOLD, sliderrelief="flat",
                showvalue=False, length=210)
            slider.pack(fill="x", padx=10)

            # Trigger replay on slider release or entry commit
            slider.bind("<ButtonRelease-1>", lambda e: self._on_param_change())
            entry.bind("<Return>",           lambda e: self._on_param_change())
            entry.bind("<FocusOut>",         lambda e: self._on_param_change())

            tk.Label(panel, text=tip, bg=BG2, fg=TEXT_DIM,
                     font=("Courier New", 7), anchor="w").pack(anchor="w", padx=14)

        tk.Frame(panel, bg=BORDER, height=1).pack(fill="x", padx=10, pady=10)

        # ── Axis source ───────────────────────────────────────────────────────
        tk.Label(panel, text="AXIS SOURCE", bg=BG2, fg=GOLD_DIM,
                 font=("Georgia", 8, "bold")).pack(anchor="w", padx=12)
        self._use_gyro = tk.IntVar(value=0)
        src = tk.Frame(panel, bg=BG2)
        src.pack(anchor="w", padx=16, pady=4)
        for text, val in [("Accel (legacy)", 0), ("Gyro", 1)]:
            tk.Radiobutton(src, text=text, variable=self._use_gyro, value=val,
                           bg=BG2, fg=TEXT, activebackground=BG2, selectcolor=BG3,
                           font=("Courier New", 8),
                           command=self._on_param_change).pack(side="left", padx=(0, 12))

        # ── Gyro (motion.py) parameters ───────────────────────────────────────
        tk.Label(panel, text="GYRO  (used by wand_gui)", bg=BG2, fg=GOLD_DIM,
                 font=("Georgia", 8, "bold")).pack(anchor="w", padx=12, pady=(6, 0))
        self._minrate_var = tk.DoubleVar(value=MOTION_DEFAULTS["min_rate"])
        self._minstep_var = tk.DoubleVar(value=MOTION_DEFAULTS["min_step"])
        for lbl, var, lo, hi, res in [("Min rate °/s", self._minrate_var, 0.0, 30.0, 0.5),
                                      ("Min step °",   self._minstep_var, 0.0, 3.0, 0.05)]:
            row = tk.Frame(panel, bg=BG2)
            row.pack(fill="x", padx=10)
            tk.Label(row, text=lbl, bg=BG2, fg=GOLD, width=12, anchor="w",
                     font=("Courier New", 8, "bold")).pack(side="left")
            sl = tk.Scale(row, variable=var, from_=lo, to=hi, resolution=res,
                          orient="horizontal", bg=BG2, fg=TEXT_DIM, troughcolor=BG3,
                          highlightthickness=0, bd=0, sliderrelief="flat",
                          font=("Courier New", 7), length=130)
            sl.pack(side="left", fill="x", expand=True)
            sl.bind("<ButtonRelease-1>", lambda e: self._on_param_change())
        row = tk.Frame(panel, bg=BG2)
        row.pack(fill="x", padx=10, pady=(2, 0))
        tk.Label(row, text="Tip axis", bg=BG2, fg=GOLD, width=12, anchor="w",
                 font=("Courier New", 8, "bold")).pack(side="left")
        self._tip_var = tk.StringVar(value="+y")
        tip_box = ttk.Combobox(row, textvariable=self._tip_var, values=list(TIP_AXES),
                               state="readonly", width=4, font=("Courier New", 8))
        tip_box.pack(side="left")
        tip_box.bind("<<ComboboxSelected>>", lambda e: self._on_param_change())
        self._gyro_flip_x = tk.IntVar(value=0)
        tk.Checkbutton(row, text="Flip X", variable=self._gyro_flip_x, bg=BG2, fg=TEXT,
                       activebackground=BG2, selectcolor=BG3, font=("Courier New", 8),
                       command=self._on_param_change).pack(side="left", padx=(10, 0))

        tk.Frame(panel, bg=BORDER, height=1).pack(fill="x", padx=10, pady=8)

        # ── Axis remapping ────────────────────────────────────────────────────
        tk.Label(panel, text="AXIS REMAPPING", bg=BG2, fg=GOLD_DIM,
                 font=("Georgia", 8, "bold")).pack(anchor="w", padx=12)
        tk.Label(panel, text="Default = swap+flipY (90° PCB rotation)",
                 bg=BG2, fg=TEXT_DIM, font=("Courier New", 7)).pack(anchor="w", padx=14)

        self._swap_xy = tk.IntVar(value=1)
        self._flip_x  = tk.IntVar(value=0)
        self._flip_y  = tk.IntVar(value=1)
        for text, var in [("Swap X / Y", self._swap_xy),
                          ("Flip X",     self._flip_x),
                          ("Flip Y",     self._flip_y)]:
            tk.Checkbutton(panel, text=text, variable=var, bg=BG2, fg=TEXT,
                           activebackground=BG2, selectcolor=BG3,
                           font=("Courier New", 8),
                           command=self._on_param_change).pack(anchor="w", padx=16)

        tk.Frame(panel, bg=BORDER, height=1).pack(fill="x", padx=10, pady=8)

        # ── Presets ───────────────────────────────────────────────────────────
        tk.Label(panel, text="PRESETS", bg=BG2, fg=GOLD_DIM,
                 font=("Georgia", 8, "bold")).pack(anchor="w", padx=12, pady=(0, 4))
        pf = tk.Frame(panel, bg=BG2)
        pf.pack(fill="x", padx=10, pady=(0, 6))
        names = list(PRESETS.keys())
        for i, name in enumerate(names):
            tk.Button(pf, text=name, bg=BG3, fg=TEXT_DIM, bd=0,
                      padx=6, pady=3, font=("Courier New", 8),
                      activebackground=BORDER,
                      command=lambda n=name: self._apply_preset(n)).grid(
                row=i // 2, column=i % 2, padx=3, pady=2, sticky="ew")
        pf.columnconfigure(0, weight=1)
        pf.columnconfigure(1, weight=1)

    # ── Plot panel ────────────────────────────────────────────────────────────

    def _build_plot_panel(self, body):
        panel = self._panel(body, 1, "GESTURE TRAIL")

        self._gesture_label = tk.Label(
            panel, text="waiting for gesture…", bg=BG2, fg=TEXT_DIM,
            font=("Georgia", 10, "italic"))
        self._gesture_label.pack(pady=(4, 0))

        fig = plt.Figure(figsize=(7, 6.5), dpi=100)
        fig.patch.set_facecolor(BG2)
        self.ax = fig.add_subplot(111)
        self._style_ax()

        self.canvas = FigureCanvasTkAgg(fig, master=panel)
        self.canvas.get_tk_widget().configure(bg=BG2, highlightthickness=0)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=4, pady=4)
        self.fig = fig

        btn_row = tk.Frame(panel, bg=BG2)
        btn_row.pack(pady=(0, 6))
        tk.Button(btn_row, text="Clear", bg=BG3, fg=TEXT_DIM, bd=0, padx=10, pady=3,
                  font=("Courier New", 8), activebackground=BORDER,
                  command=self._clear_trail).pack(side="left", padx=4)
        self._manual_btn = tk.Button(
            btn_row, text="● Start Gesture", bg=BG3, fg=GREEN, bd=0, padx=10, pady=3,
            font=("Courier New", 8, "bold"), activebackground=BORDER,
            command=self._toggle_manual_gesture)
        self._manual_btn.pack(side="left", padx=4)
        tk.Button(btn_row, text="↺ Replay Last", bg=BG3, fg=BLUE, bd=0, padx=10, pady=3,
                  font=("Courier New", 8), activebackground=BORDER,
                  command=self._replay).pack(side="left", padx=4)

    # ── Diagnostics panel ─────────────────────────────────────────────────────

    def _build_diag_panel(self, body):
        panel = self._panel(body, 2, "DIAGNOSTICS")

        tk.Label(panel, text="LAST IMU SAMPLE", bg=BG2, fg=GOLD_DIM,
                 font=("Georgia", 7, "bold")).pack(anchor="w", padx=14, pady=(10, 2))
        self._imu_label = tk.Label(panel, text="—", bg=BG2, fg=BLUE,
                                    font=("Courier New", 8), justify="left")
        self._imu_label.pack(anchor="w", padx=14)

        tk.Frame(panel, bg=BORDER, height=1).pack(fill="x", padx=10, pady=8)

        tk.Label(panel, text="TRAIL STATS", bg=BG2, fg=GOLD_DIM,
                 font=("Georgia", 7, "bold")).pack(anchor="w", padx=14)
        self._stats_label = tk.Label(panel, text="—", bg=BG2, fg=TEXT_DIM,
                                      font=("Courier New", 8), justify="left")
        self._stats_label.pack(anchor="w", padx=14, pady=(2, 0))

        tk.Frame(panel, bg=BORDER, height=1).pack(fill="x", padx=10, pady=8)

        tk.Label(panel, text="GESTURE", bg=BG2, fg=GOLD_DIM,
                 font=("Georgia", 7, "bold")).pack(anchor="w", padx=14)
        self._gest_status = tk.Label(panel, text="inactive", bg=BG2,
                                      fg=TEXT_DIM, font=("Courier New", 8))
        self._gest_status.pack(anchor="w", padx=14, pady=(2, 0))
        self._raw_count_label = tk.Label(panel, text="Saved: 0 raw samples",
                                          bg=BG2, fg=TEXT_DIM, font=("Courier New", 8))
        self._raw_count_label.pack(anchor="w", padx=14, pady=(2, 0))

        cap = tk.Frame(panel, bg=BG2)
        cap.pack(fill="x", padx=10, pady=(6, 0))
        self._cap_label = tk.StringVar(value="circle")
        tk.Entry(cap, textvariable=self._cap_label, width=12, bg=BG3, fg=TEXT,
                 insertbackground=TEXT, bd=0, font=("Courier New", 9)).pack(side="left")
        tk.Button(cap, text="Save Capture", bg=BG3, fg=GREEN, bd=0, padx=8, pady=2,
                  font=("Courier New", 8), activebackground=BORDER,
                  command=self._save_capture).pack(side="left", padx=(6, 0))
        tk.Label(panel, text="label = what you drew → captures/", bg=BG2, fg=TEXT_DIM,
                 font=("Courier New", 7)).pack(anchor="w", padx=14)

        tk.Frame(panel, bg=BORDER, height=1).pack(fill="x", padx=10, pady=8)

        tk.Label(panel, text="CONFIG OUTPUT", bg=BG2, fg=GOLD_DIM,
                 font=("Georgia", 7, "bold")).pack(anchor="w", padx=14, pady=(0, 4))
        tk.Label(panel, text="Paste into WandGUI class:", bg=BG2, fg=TEXT_DIM,
                 font=("Courier New", 7)).pack(anchor="w", padx=14)
        self._config_text = tk.Text(
            panel, bg=BG3, fg=GREEN, bd=0, relief="flat",
            font=("Courier New", 7), height=10, wrap="none", state="disabled")
        self._config_text.pack(fill="x", padx=10, pady=(2, 4))

        btn_f = tk.Frame(panel, bg=BG2)
        btn_f.pack(fill="x", padx=10, pady=(0, 6))
        tk.Button(btn_f, text="Copy Config", bg=BG3, fg=GOLD, bd=0,
                  padx=8, pady=3, font=("Courier New", 8), activebackground=BORDER,
                  command=self._copy_config).pack(side="left", padx=(0, 4))
        tk.Button(btn_f, text="Save JSON", bg=BG3, fg=GOLD, bd=0,
                  padx=8, pady=3, font=("Courier New", 8), activebackground=BORDER,
                  command=self._save_config).pack(side="left")

        self._update_config_output()

    def _style_ax(self):
        self.ax.set_facecolor(BG3)
        self.ax.tick_params(colors=TEXT_DIM, labelsize=6)
        for spine in self.ax.spines.values():
            spine.set_color(BORDER)
        self.ax.set_xlabel("X", labelpad=4, fontsize=7, color=TEXT_DIM)
        self.ax.set_ylabel("Y", labelpad=4, fontsize=7, color=TEXT_DIM)

    # ── Wand selector ─────────────────────────────────────────────────────────

    def _do_scan(self):
        if self._scanning:
            return
        self._scanning = True
        self._scan_btn.configure(text="Scanning…", state="disabled", fg=GOLD_DIM)
        self._wand_combo["values"] = ["Scanning…"]
        self._wand_var.set("Scanning…")
        self.ble.scan_for_wands(lambda r: self.root.after(0, self._on_scan_done, r))

    def _on_scan_done(self, results: list):
        self._scanning = False
        self._scan_btn.configure(text="Scan", state="normal", fg=TEXT_DIM)
        for name, addr in results:
            self._found_wands[addr] = name
        if not self._found_wands:
            self._wand_combo["values"] = ["— no wands found —"]
            self._wand_var.set("— no wands found —")
            return
        labels = [f"{name}  ({addr})" for addr, name in sorted(self._found_wands.items())]
        self._wand_combo["values"] = labels
        self._wand_var.set(labels[0])

    def _do_connect(self):
        label = self._wand_var.get()
        for addr, name in self._found_wands.items():
            if addr in label:
                self.ble.connect_to(name, addr)
                return
        self.status_var.set("Select a wand from the dropdown first")

    # ── Event polling ─────────────────────────────────────────────────────────

    def _poll(self):
        try:
            while True:
                self._handle_msg(self.q.get_nowait())
        except queue.Empty:
            pass
        self.root.after(50, self._poll)

    def _handle_msg(self, msg: dict):
        t = msg["type"]
        if t == "connected":
            self.status_var.set(msg["name"])
            self._conn_dot.configure(fg=GREEN)
        elif t == "disconnected":
            self.status_var.set("Disconnected")
            self._conn_dot.configure(fg=RED)
            self.gesture_active = False
            self._gest_status.configure(text="inactive", fg=TEXT_DIM)
        elif t == "battery":
            self.battery_var.set(f"{msg['pct']}%")
        elif t == "status":
            self.status_var.set(msg["text"])
        elif t == "ble":
            self._handle_ble(msg["data"])

    def _handle_ble(self, data: bytes):
        if not data:
            return
        op = data[0]
        if op == 0x2C:
            samples = decode_imu_packet(data)
            if samples:
                self._handle_imu_samples(samples)
        elif op == 0x10:
            mask = data[1] if len(data) >= 2 else 0
            states = {f"button_{i+1}": bool(mask & (1 << i)) for i in range(4)}
            self._button_states = states
            self._evaluate_buttons(states)

    def _evaluate_buttons(self, states: dict):
        gripped = states.get("button_1", False)
        if gripped and not self.gesture_active:
            self._open_gesture()
        elif not gripped and self.gesture_active:
            self._close_gesture()

    # ── IMU sample handler ────────────────────────────────────────────────────

    def _handle_imu_samples(self, samples: list):
        ax, ay, az, gx, gy, gz = samples[0]
        self._imu_label.configure(
            text=f"ax={ax:+.4f}G   ay={ay:+.4f}G\n"
                 f"az={az:+.4f}G\n"
                 f"w=({np.degrees(gx):+5.0f} {np.degrees(gy):+5.0f} "
                 f"{np.degrees(gz):+5.0f}) °/s")

        if not self.gesture_active:
            self._pre_raw.extend(samples)
            return

        p = self._params()
        self._live_raw.extend(samples)
        self._raw_count_label.configure(
            text=f"Recording: {len(self._live_raw)} raw samples")

        if self._live_gyro:
            self._tracker.feed_many(samples)
            self._live_trail_x = self._tracker.trail_x
            self._live_trail_y = self._tracker.trail_y
            self._redraw(self._live_trail_x, self._live_trail_y, "live (gyro)")
            return

        # Push each sample through the stateful live pipeline
        for ax, ay, az, gx, gy, gz in samples:
            src_x, src_y = ax, ay

            if p["swap_xy"]: src_x, src_y = src_y, src_x
            if p["flip_x"]:  src_x = -src_x
            if p["flip_y"]:  src_y = -src_y

            if self._prev_x is None:
                self._prev_x, self._prev_y = src_x, src_y
                continue

            dx = src_x - self._prev_x
            dy = src_y - self._prev_y
            self._prev_x, self._prev_y = src_x, src_y

            if self._ema_x is None:
                self._ema_x, self._ema_y = dx, dy
            else:
                a = p["alpha"]
                self._ema_x = a * dx + (1 - a) * self._ema_x
                self._ema_y = a * dy + (1 - a) * self._ema_y

            mag = max(abs(self._ema_x), abs(self._ema_y))
            re  = p["dead_zone"] * p["hysteresis"]
            if self._dz_active:
                if mag < p["dead_zone"]: self._dz_active = False
            else:
                if mag >= re: self._dz_active = True

            if not self._dz_active:
                continue

            self._pos_x += self._ema_x * p["accel_scale"]
            self._pos_y += self._ema_y * p["accel_scale"]
            self._live_trail_x.append(self._pos_x)
            self._live_trail_y.append(self._pos_y)

        self._redraw(self._live_trail_x, self._live_trail_y, "live")

    # ── Gesture window ────────────────────────────────────────────────────────

    def _open_gesture(self):
        self.gesture_active = True
        self._live_raw.clear()
        self._live_pre = list(self._pre_raw)
        p = self._params()
        self._live_gyro = p["use_gyro"]          # mode locked until gesture closes
        if p["use_gyro"]:
            kw = self._gyro_kwargs(p)
            self._tracker = GestureTracker.from_profile(kw.pop("motion"), **kw)
            self._tracker.feed_many(self._live_pre)
            self._tracker.begin()
        self._live_trail_x.clear()
        self._live_trail_y.clear()
        self._prev_x = self._prev_y = None
        self._ema_x  = self._ema_y  = None
        self._dz_active = False
        self._pos_x = self._pos_y = 0.0
        self._gesture_label.configure(text="● recording…", fg=GOLD)
        self._gest_status.configure(text="recording", fg=GREEN)
        self._manual_btn.configure(text="■ Stop Gesture", fg=RED)
        if self._gesture_timer:
            self.root.after_cancel(self._gesture_timer)
        self._gesture_timer = self.root.after(
            int(self.GESTURE_TIMEOUT_S * 1000), self._gesture_timeout)

    def _close_gesture(self):
        self.gesture_active = False
        if self._gesture_timer:
            self.root.after_cancel(self._gesture_timer)
            self._gesture_timer = None
        self._gest_status.configure(text="inactive", fg=TEXT_DIM)
        self._manual_btn.configure(text="● Start Gesture", fg=GREEN)

        if self._live_raw:
            self._last_raw = list(self._live_raw)
            self._last_pre = list(self._live_pre)

        pts = len(self._live_trail_x)
        if pts < 5:
            self._gesture_label.configure(
                text=f"too short ({pts} pts — try slower/wider motion)", fg=RED)
            self._raw_count_label.configure(
                text=f"Saved: {len(self._last_raw)} raw samples")
            return

        self._raw_count_label.configure(
            text=f"Saved: {len(self._last_raw)} raw samples  (↺ Replay to re-process)")
        self._gesture_label.configure(
            text=f"captured — {pts} trail points", fg=GREEN)
        self._redraw(self._live_trail_x, self._live_trail_y, "recorded")
        self._update_stats(self._live_trail_x, self._live_trail_y)

    def _gesture_timeout(self):
        if self.gesture_active:
            self._gesture_label.configure(text="timeout — closing", fg=RED)
            self._close_gesture()

    def _toggle_manual_gesture(self):
        if self.gesture_active:
            self._close_gesture()
        else:
            self._open_gesture()

    # ── Trail rendering ───────────────────────────────────────────────────────

    def _redraw(self, xs, ys, label=""):
        self.ax.cla()
        self._style_ax()

        if len(xs) < 2:
            self.canvas.draw_idle()
            return

        xa = np.array(xs, dtype=float)
        ya = np.array(ys, dtype=float)
        n  = len(xa)
        cm = plt.get_cmap("cool")

        for i in range(n - 1):
            t = i / max(n - 2, 1)
            self.ax.plot(xa[i:i+2], ya[i:i+2], color=cm(t),
                         linewidth=2.0, alpha=0.9, solid_capstyle="round")

        self.ax.scatter([xa[0]],  [ya[0]],  color=TEXT_DIM, s=25, zorder=5)
        self.ax.scatter([xa[-1]], [ya[-1]], color=GOLD,     s=45, zorder=6)

        pad  = max(abs(xa).max(), abs(ya).max()) * 0.15 or 50
        xc   = (xa.max() + xa.min()) / 2
        yc   = (ya.max() + ya.min()) / 2
        half = max(xa.max() - xa.min(), ya.max() - ya.min()) / 2 + pad
        self.ax.set_xlim(xc - half, xc + half)
        self.ax.set_ylim(yc - half, yc + half)

        if label:
            self.ax.set_title(label, color=PURPLE, fontsize=9, pad=4, fontfamily="serif")

        self.canvas.draw_idle()

    def _update_stats(self, xs, ys, stats: Optional[dict] = None):
        if not xs:
            self._stats_label.configure(text="—")
            return
        xa, ya = np.array(xs), np.array(ys)
        lines = [
            f"Points : {len(xs)}",
            f"X range: {xa.min():.1f}  →  {xa.max():.1f}",
            f"Y range: {ya.min():.1f}  →  {ya.max():.1f}",
            f"W × H  : {xa.max()-xa.min():.1f} × {ya.max()-ya.min():.1f}",
        ]
        if stats:
            lines += [
                f"Raw    : {stats['raw']} samples",
                f"Filtered: {stats['filtered']}",
                f"Pass   : {stats['pass_pct']:.0f}%",
            ]
        self._stats_label.configure(text="\n".join(lines))

    # ── Param change / replay ─────────────────────────────────────────────────

    def _on_param_change(self):
        self._update_config_output()
        if self._last_raw and not self.gesture_active:
            self._replay(silent=True)

    def _replay(self, silent=False):
        if not self._last_raw:
            if not silent:
                self._gesture_label.configure(
                    text="no gesture saved yet — perform one first", fg=RED)
            return
        p = self._params()
        if p["use_gyro"]:
            xs, ys, st = run_gyro_pipeline(self._last_raw, pre_samples=self._last_pre,
                                           **self._gyro_kwargs(p))
            stats = {"raw": st["raw"], "filtered": st["raw"] - st["moving"],
                     "pass_pct": 100 * st["moving"] / max(st["raw"], 1)}
        else:
            accel_p = {k: p[k] for k in ("alpha", "dead_zone", "hysteresis", "accel_scale",
                                         "swap_xy", "flip_x", "flip_y")}
            xs, ys, st = run_accel_pipeline(self._last_raw, **accel_p)
            stats = st
        if len(xs) > 1:
            self._redraw(xs, ys, f"replay  {len(xs)} pts  pass {stats['pass_pct']:.0f}%")
            self._update_stats(xs, ys, stats)
            self._gesture_label.configure(
                text=f"replay: {len(xs)} pts  ({stats['pass_pct']:.0f}% passed DZ)",
                fg=BLUE)
            if st.get("clipped"):
                self._gesture_label.configure(
                    text=f"⚠ {st['clipped']} samples hit gyro full-scale — swing slower",
                    fg=RED)
        else:
            self._redraw([], [], "")
            self._gesture_label.configure(
                text="replay: empty trail — all samples filtered by dead zone", fg=RED)
            self._update_stats([], [])

    # ── Presets ───────────────────────────────────────────────────────────────

    def _apply_preset(self, name: str):
        p = PRESETS.get(name, {})
        self._alpha_var.set(p.get("alpha", 0.5))
        self._dz_var.set(p.get("dead_zone", 0.010))
        self._hys_var.set(p.get("hysteresis", 1.5))
        self._scale_var.set(p.get("accel_scale", 60.0))
        self._use_gyro.set(1 if p.get("use_gyro", False) else 0)
        self._swap_xy.set(1 if p.get("swap_xy", True)  else 0)
        self._flip_x.set( 1 if p.get("flip_x",  False) else 0)
        self._flip_y.set( 1 if p.get("flip_y",  True)  else 0)
        self._minrate_var.set(p.get("min_rate", MOTION_DEFAULTS["min_rate"]))
        self._minstep_var.set(p.get("min_step", MOTION_DEFAULTS["min_step"]))
        self._on_param_change()

    # ── Trail clear ───────────────────────────────────────────────────────────

    def _clear_trail(self):
        self._live_trail_x.clear()
        self._live_trail_y.clear()
        self._gesture_label.configure(text="trail cleared", fg=TEXT_DIM)
        self.ax.cla()
        self._style_ax()
        self.canvas.draw_idle()

    # ── Config output ─────────────────────────────────────────────────────────

    def _update_config_output(self):
        p = self._params()
        if p["use_gyro"]:
            tip = next(k for k, v in TIP_AXES.items() if v == p["tip_axis"])
            text = (
                f"# ── motion.DEFAULTS (or profile params) ──\n"
                f"min_rate = {p['min_rate']:.1f}   # deg/s\n"
                f"min_step = {p['min_step']:.2f}  # deg\n"
                f"flip_x   = {p['gyro_flip_x']}\n"
                f"# tip axis {tip} — set per wand by\n"
                f"# the GUI's Calibrate wizard\n"
            )
            self._config_text.configure(state="normal")
            self._config_text.delete("1.0", "end")
            self._config_text.insert("1.0", text)
            self._config_text.configure(state="disabled")
            return
        axis_note = ""
        if p["swap_xy"] or p["flip_x"] or p["flip_y"]:
            axis_note = (
                f"\n# Axis remap applied in decode_imu_packet:\n"
                f"# swap_xy={p['swap_xy']}  flip_x={p['flip_x']}  flip_y={p['flip_y']}\n"
                f"# Source: {'gyro' if p['use_gyro'] else 'accel'}\n"
            )
        text = (
            f"# ── Paste into WandGUI class ──────────────\n"
            f"IMU_ALPHA            = {p['alpha']:.2f}\n"
            f"IMU_DEAD_ZONE        = {p['dead_zone']:.4f}\n"
            f"DEAD_ZONE_HYSTERESIS = {p['hysteresis']:.1f}\n"
            f"ACCEL_SCALE          = {p['accel_scale']:.1f}\n"
            f"{axis_note}"
        )
        self._config_text.configure(state="normal")
        self._config_text.delete("1.0", "end")
        self._config_text.insert("1.0", text)
        self._config_text.configure(state="disabled")

    def _copy_config(self):
        p = self._params()
        text = (
            f"IMU_ALPHA            = {p['alpha']:.2f}\n"
            f"IMU_DEAD_ZONE        = {p['dead_zone']:.4f}\n"
            f"DEAD_ZONE_HYSTERESIS = {p['hysteresis']:.1f}\n"
            f"ACCEL_SCALE          = {p['accel_scale']:.1f}\n"
        )
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._gesture_label.configure(text="config copied to clipboard!", fg=GREEN)

    def _save_config(self):
        p = self._params()
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile="wand_tuner_config.json",
            initialdir=os.path.dirname(os.path.abspath(__file__)),
        )
        if not path:
            return
        data = {
            "wand_gui_constants": {
                "IMU_ALPHA":            p["alpha"],
                "IMU_DEAD_ZONE":        p["dead_zone"],
                "DEAD_ZONE_HYSTERESIS": p["hysteresis"],
                "ACCEL_SCALE":          p["accel_scale"],
            },
            "axis": {
                "source":  "gyro" if p["use_gyro"] else "accel",
                "swap_xy": p["swap_xy"],
                "flip_x":  p["flip_x"],
                "flip_y":  p["flip_y"],
            },
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self._gesture_label.configure(
            text=f"saved → {os.path.basename(path)}", fg=GREEN)

    # ── Labelled raw captures (for replay_capture.py) ────────────────────────

    def _save_capture(self):
        if not self._last_raw:
            self._gesture_label.configure(text="nothing to save — cast a gesture first", fg=RED)
            return
        label = "".join(c for c in self._cap_label.get().strip()
                        if c.isalnum() or c in "-_") or "gesture"
        folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "captures")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{label}_{time.strftime('%Y%m%d-%H%M%S')}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["phase", "ax_raw", "ay_raw", "az_raw", "gx_raw", "gy_raw", "gz_raw"])
            for phase, rows in (("pre", self._last_pre), ("gesture", self._last_raw)):
                for ax, ay, az, gx, gy, gz in rows:
                    w.writerow([phase,
                                *(round(v / IMU_ACCEL_SCALE) for v in (ax, ay, az)),
                                *(round(v / IMU_GYRO_SCALE)  for v in (gx, gy, gz))])
        self._gesture_label.configure(
            text=f"saved → captures/{os.path.basename(path)}", fg=GREEN)

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def _on_close(self):
        if self._gesture_timer:
            self.root.after_cancel(self._gesture_timer)
        self.ble.stop()
        self.root.destroy()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()
    root.tk_setPalette(background=BG, foreground=TEXT)
    try:
        root.iconbitmap(default="")
    except Exception:
        pass
    WandTuner(root)
    root.mainloop()


if __name__ == "__main__":
    main()
