"""
wand_gui.py — Magic Caster Wand Live GUI
=========================================
Dark Harry Potter-themed dashboard showing live BLE events,
3D gesture motion trail, and spell history.

Usage:
  python wand_gui.py

Requires: bleak, matplotlib, numpy (all already installed)
"""

import asyncio
import queue
import struct
import threading
import tkinter as tk
from tkinter import ttk, font as tkfont
from collections import deque
from datetime import datetime
from typing import Optional

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from wand import (
    WRITE_UUID, NOTIFY_UUID, BATTERY_UUID,
    IMU_VALUE_HANDLE, IMU_CCCD_HANDLE, imu_subscribe,
    find_wand, hw_init, hw_write,
    build_frame, cmd_changeled, clear_all, buzz_frame, hsv_to_rgb,
)
from bleak import BleakClient

# ── Palette ────────────────────────────────────────────────────────────────────
BG         = "#0a0c1a"   # deep space
BG2        = "#0f1228"   # panel bg
BG3        = "#161a38"   # slightly lighter
GOLD       = "#c9a84c"
GOLD_DIM   = "#7a6328"
BLUE_GLOW  = "#4a9eff"
PURPLE     = "#8b5cf6"
GREEN      = "#34d399"
RED        = "#f87171"
TEXT       = "#e8e4d8"
TEXT_DIM   = "#6b6880"
BORDER     = "#2a2d4a"

STATUS_COLORS = {
    "state":   GREEN,
    "imu":     BLUE_GLOW,
    "gesture": GOLD,
    "spell":   PURPLE,
    "system":  TEXT_DIM,
    "unknown": RED,
}

STATUS_CODES = {
    "1000": ("Idle / Ready",            "state"),
    "1001": ("Button / Motion trigger", "state"),
    "1002": ("Action Ack / End",        "state"),
    "1003": ("Event 3",                 "state"),
    "1006": ("Event 6",                 "state"),
    "1008": ("IMU burst start",         "imu"),
    "1009": ("IMU sample",              "imu"),
    "100a": ("IMU axis A",              "imu"),
    "100b": ("Gesture window open",     "gesture"),
    "100c": ("Gesture alt C",           "gesture"),
    "100d": ("Gesture alt D",           "gesture"),
    "100e": ("Orientation change",      "imu"),
    "100f": ("Gesture window close",    "gesture"),
}

# ── BLE decode ─────────────────────────────────────────────────────────────────

def decode_imu_packet(data: bytes):
    """Decode a 20-byte IMU packet from handle 0x0016.
    Format: [seq:2][?:1][count:1][ax:2][ay:2][az:2][gx:2][gy:2][gz:2][?:2]
    Returns (ax, ay, az, gx, gy, gz) or None."""
    if len(data) < 16:
        return None
    ax = struct.unpack_from('<h', data, 4)[0]
    ay = struct.unpack_from('<h', data, 6)[0]
    az = struct.unpack_from('<h', data, 8)[0]
    gx = struct.unpack_from('<h', data, 10)[0]
    gy = struct.unpack_from('<h', data, 12)[0]
    gz = struct.unpack_from('<h', data, 14)[0]
    return ax, ay, az, gx, gy, gz


def decode_notification(data: bytes) -> dict:
    hex_str = data.hex()
    result = {"raw": hex_str, "type": "unknown", "code": None,
               "label": None, "category": "unknown", "text": None, "imu": None}

    if hex_str == "014001":
        result.update(type="heartbeat", label="Heartbeat", category="system")
        return result

    if data[0] == 0x24:
        try:
            text = data[4:].decode("utf-8")
            result.update(type="spell", label=f"✦ {text}", category="spell", text=text)
        except Exception:
            result.update(type="spell", label="Spell (decode err)", category="spell")
        return result

    if data[0] == 0x10 and len(data) >= 2:
        code = data[:2].hex()
        label, category = STATUS_CODES.get(code, (f"0x{code}", "unknown"))
        result.update(type="status", code=code, label=label, category=category)
        if data[1] in (0x08, 0x09, 0x0a) and len(data) > 2:
            payload = data[2:]
            samples = [struct.unpack_from('<h', payload, i)[0]
                       for i in range(0, len(payload) - 1, 2)]
            result["imu"] = samples
        return result

    return result


# ── BLE background thread ──────────────────────────────────────────────────────

class BLEWorker:
    def __init__(self, msg_queue: queue.Queue):
        self.q = msg_queue
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._client: Optional[BleakClient] = None
        self._stop = False

    def start(self):
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def stop(self):
        self._stop = True
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)

    def _run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._connect_loop())

    async def _connect_loop(self):
        self.q.put({"type": "status_msg", "text": "Scanning for MCW wand..."})
        retry_delay = 2.0
        while not self._stop:
            try:
                wand = await find_wand()
                self.q.put({"type": "status_msg", "text": f"Connecting to {wand.name}..."})
                async with BleakClient(wand, timeout=20.0) as client:
                    self._client = client
                    self.q.put({"type": "connected", "name": wand.name})
                    retry_delay = 2.0  # reset backoff on successful connect
                    await asyncio.sleep(1.5)
                    await hw_init(client)
                    await self._welcome(client)
                    await client.start_notify(NOTIFY_UUID,
                        lambda _s, d: self.q.put({"type": "ble", "data": d}))
                    try:
                        await imu_subscribe(client,
                            lambda d: self.q.put({"type": "imu", "data": d}))
                    except Exception as e:
                        self.q.put({"type": "status_msg", "text": f"IMU: {e}"})
                    try:
                        await client.start_notify(BATTERY_UUID,
                            lambda _s, d: self.q.put({"type": "battery", "pct": d[0]}))
                    except Exception:
                        pass
                    while not self._stop and client.is_connected:
                        await asyncio.sleep(0.5)
                    await client.stop_notify(NOTIFY_UUID)
                self._client = None
                self.q.put({"type": "disconnected"})
                if not self._stop:
                    self.q.put({"type": "status_msg", "text": "Disconnected — rescanning..."})
                    await asyncio.sleep(1.0)
            except Exception as e:
                self._client = None
                self.q.put({"type": "disconnected"})
                self.q.put({"type": "status_msg", "text": f"Error: {e}"})
                if not self._stop:
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 1.5, 15.0)  # cap at 15s

    async def _welcome(self, client):
        """Rainbow + two buzzes on connect."""
        steps, step_ms = 12, 80
        for i in range(steps):
            r, g, b = hsv_to_rgb(i / steps)
            frame = build_frame(*[cmd_changeled(g2, r, g, b, step_ms) for g2 in range(4)])
            await client.write_gatt_char(WRITE_UUID, bytes([0x60]), response=False)
            await client.write_gatt_char(WRITE_UUID, frame, response=False)
            await asyncio.sleep(step_ms / 1000)
        await client.write_gatt_char(WRITE_UUID, clear_all(), response=False)
        await asyncio.sleep(0.3)
        for dur in (0.15, 0.4):
            await hw_write(client, bytes([0x60]))
            await hw_write(client, buzz_frame(100))
            await asyncio.sleep(dur)
            await hw_write(client, bytes([0x40]))
            await asyncio.sleep(0.25)

    async def send_blue(self, client):
        frame = build_frame(*[cmd_changeled(g, 0, 0, 255, 2000) for g in range(4)])
        await client.write_gatt_char(WRITE_UUID, bytes([0x60]), response=False)
        await client.write_gatt_char(WRITE_UUID, frame, response=False)

    async def send_clear(self, client):
        await client.write_gatt_char(WRITE_UUID, clear_all(), response=False)

    def trigger_blue(self):
        if self._client and self.loop:
            asyncio.run_coroutine_threadsafe(self.send_blue(self._client), self.loop)

    def trigger_clear(self):
        if self._client and self.loop:
            asyncio.run_coroutine_threadsafe(self.send_clear(self._client), self.loop)


# ── Main GUI ───────────────────────────────────────────────────────────────────

class WandGUI:
    LOG_MAX    = 200
    TRAIL_MAX  = 512

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("✦ OpenCaster — Magic Wand Monitor")
        self.root.configure(bg=BG)
        self.root.geometry("1280x780")
        self.root.minsize(1100, 680)

        self.q: queue.Queue = queue.Queue()
        self.ble = BLEWorker(self.q)

        self.battery_pct   = tk.StringVar(value="—")
        self.status_var    = tk.StringVar(value="Disconnected")
        self.conn_color    = tk.StringVar(value=RED)
        self.last_spell    = tk.StringVar(value="—")
        self.spell_history: list[str] = []

        # Gesture trail buffers — X (accel X) and Y (accel Y), matching app's 2D view
        self.trail_x: deque = deque(maxlen=self.TRAIL_MAX)
        self.trail_y: deque = deque(maxlen=self.TRAIL_MAX)
        self.gesture_active = False
        self.frozen_trail: Optional[tuple] = None   # (x, y, spell) after cast

        self._build_ui()
        self.ble.start()
        self.root.after(50, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(self.root, bg=BG, pady=8)
        hdr.pack(fill="x", padx=16, pady=(12, 0))

        tk.Label(hdr, text="✦  OPENCASTER", bg=BG, fg=GOLD,
                 font=("Georgia", 22, "bold")).pack(side="left")
        tk.Label(hdr, text="Magic Wand Monitor", bg=BG, fg=TEXT_DIM,
                 font=("Georgia", 11, "italic")).pack(side="left", padx=(10, 0), pady=(6, 0))

        right_hdr = tk.Frame(hdr, bg=BG)
        right_hdr.pack(side="right")
        tk.Label(right_hdr, text="🔋", bg=BG, fg=TEXT_DIM, font=("Segoe UI", 11)).pack(side="left")
        tk.Label(right_hdr, textvariable=self.battery_pct, bg=BG, fg=GREEN,
                 font=("Courier New", 11, "bold")).pack(side="left", padx=(2, 16))
        self._conn_dot = tk.Label(right_hdr, text="⬤", bg=BG, fg=RED, font=("Segoe UI", 14))
        self._conn_dot.pack(side="left")
        tk.Label(right_hdr, textvariable=self.status_var, bg=BG, fg=TEXT_DIM,
                 font=("Courier New", 10)).pack(side="left", padx=(6, 0))

        sep = tk.Frame(self.root, bg=BORDER, height=1)
        sep.pack(fill="x", padx=16, pady=8)

        # ── Three column body ─────────────────────────────────────────────────
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        body.columnconfigure(0, weight=3, minsize=280)
        body.columnconfigure(1, weight=5, minsize=420)
        body.columnconfigure(2, weight=3, minsize=260)
        body.rowconfigure(0, weight=1)

        # Left: event log
        self._build_log_panel(body)

        # Center: 3D gesture plot
        self._build_plot_panel(body)

        # Right: status + spell history
        self._build_status_panel(body)

    def _panel(self, parent, col, title):
        outer = tk.Frame(parent, bg=BORDER, padx=1, pady=1)
        outer.grid(row=0, column=col, sticky="nsew",
                   padx=(0 if col == 0 else 6, 6 if col < 2 else 0))
        inner = tk.Frame(outer, bg=BG2)
        inner.pack(fill="both", expand=True)
        tk.Label(inner, text=title, bg=BG2, fg=GOLD_DIM,
                 font=("Georgia", 9, "bold"), pady=6).pack(fill="x", padx=10)
        tk.Frame(inner, bg=BORDER, height=1).pack(fill="x")
        return inner

    def _build_log_panel(self, body):
        panel = self._panel(body, 0, "LIVE EVENTS")
        self._log_box = tk.Text(panel, bg=BG2, fg=TEXT, bd=0, relief="flat",
                                font=("Courier New", 9), wrap="none",
                                state="disabled", selectbackground=BG3)
        sb = tk.Scrollbar(panel, orient="vertical", command=self._log_box.yview,
                          bg=BG3, troughcolor=BG2, width=8)
        self._log_box.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._log_box.pack(fill="both", expand=True, padx=2, pady=2)
        # Tag colours
        for cat, clr in STATUS_COLORS.items():
            self._log_box.tag_configure(cat, foreground=clr)
        self._log_box.tag_configure("dim", foreground=TEXT_DIM)
        self._log_box.tag_configure("spell", foreground=PURPLE,
                                     font=("Courier New", 9, "bold"))

    def _build_plot_panel(self, body):
        panel = self._panel(body, 1, "GESTURE TRAIL  (accel X · Y)")
        self._gesture_label = tk.Label(panel, text="waiting for gesture...",
                                        bg=BG2, fg=TEXT_DIM,
                                        font=("Georgia", 10, "italic"))
        self._gesture_label.pack(pady=(4, 0))

        fig = plt.Figure(figsize=(5, 4.2), dpi=100)
        fig.patch.set_facecolor(BG2)
        self.ax = fig.add_subplot(111)
        self._style_ax()

        self.canvas = FigureCanvasTkAgg(fig, master=panel)
        self.canvas.get_tk_widget().configure(bg=BG2, highlightthickness=0)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=4, pady=4)
        self.fig = fig

        btn_row = tk.Frame(panel, bg=BG2)
        btn_row.pack(pady=(0, 6))
        tk.Button(btn_row, text="Clear Trail", bg=BG3, fg=TEXT_DIM, bd=0, padx=10, pady=3,
                  font=("Courier New", 8), activebackground=BORDER,
                  command=self._clear_trail).pack(side="left", padx=4)

    def _style_ax(self):
        ax = self.ax
        ax.set_facecolor(BG3)
        ax.tick_params(colors=TEXT_DIM, labelsize=6)
        ax.xaxis.label.set_color(TEXT_DIM)
        ax.yaxis.label.set_color(TEXT_DIM)
        ax.set_xlabel("X  (accel)", labelpad=4, fontsize=7)
        ax.set_ylabel("Y  (accel)", labelpad=4, fontsize=7)
        ax.spines['bottom'].set_color(BORDER)
        ax.spines['top'].set_color(BORDER)
        ax.spines['left'].set_color(BORDER)
        ax.spines['right'].set_color(BORDER)
        ax.set_aspect('equal', adjustable='datalim')

    def _build_status_panel(self, body):
        panel = self._panel(body, 2, "STATUS")

        # Last spell big display
        spell_frame = tk.Frame(panel, bg=BG3, pady=12)
        spell_frame.pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(spell_frame, text="LAST SPELL", bg=BG3, fg=GOLD_DIM,
                 font=("Georgia", 7, "bold")).pack()
        tk.Label(spell_frame, textvariable=self.last_spell, bg=BG3, fg=PURPLE,
                 font=("Georgia", 16, "bold"), wraplength=200).pack(pady=(2, 0))

        # Spell history list
        tk.Label(panel, text="SPELL HISTORY", bg=BG2, fg=GOLD_DIM,
                 font=("Georgia", 7, "bold"), pady=(8)).pack(anchor="w", padx=14, pady=(10, 2))
        hist_outer = tk.Frame(panel, bg=BORDER, padx=1, pady=1)
        hist_outer.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._hist_box = tk.Text(hist_outer, bg=BG3, fg=PURPLE, bd=0, relief="flat",
                                  font=("Georgia", 10), wrap="word", state="disabled",
                                  selectbackground=BG2)
        self._hist_box.pack(fill="both", expand=True, padx=4, pady=4)

        # Raw IMU readout
        tk.Label(panel, text="LAST IMU SAMPLE", bg=BG2, fg=GOLD_DIM,
                 font=("Georgia", 7, "bold")).pack(anchor="w", padx=14, pady=(4, 2))
        self._imu_label = tk.Label(panel, text="—", bg=BG2, fg=BLUE_GLOW,
                                    font=("Courier New", 8), wraplength=220, justify="left")
        self._imu_label.pack(anchor="w", padx=14, pady=(0, 8))

    # ── Event polling ──────────────────────────────────────────────────────────

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                self._handle_msg(msg)
        except queue.Empty:
            pass
        self.root.after(50, self._poll)

    def _handle_msg(self, msg):
        t = msg["type"]
        if t == "connected":
            self.status_var.set(msg["name"])
            self._conn_dot.configure(fg=GREEN)
        elif t == "disconnected":
            self.status_var.set("Disconnected")
            self._conn_dot.configure(fg=RED)
        elif t == "battery":
            self.battery_pct.set(f"{msg['pct']}%")
        elif t == "status_msg":
            self.status_var.set(msg["text"])
        elif t == "ble":
            self._handle_ble(msg["data"])
        elif t == "imu":
            self._handle_imu(msg["data"])

    def _handle_ble(self, data: bytes):
        dec = decode_notification(data)
        self._log_event(dec)

        code = dec.get("code")

        # Gesture window open — start collecting trail, glow blue
        if code == "100b":
            self.gesture_active = True
            self.trail_x.clear(); self.trail_y.clear()
            self.frozen_trail = None
            self._gesture_label.configure(text="● gesture window open", fg=GOLD)
            self.ble.trigger_blue()

        # IMU samples arrive on IMU_UUID, handled by _handle_imu

        # Spell detected
        elif dec.get("type") == "spell" and dec.get("text"):
            spell = dec["text"]
            self.last_spell.set(spell)
            self.spell_history.insert(0, f"{datetime.now().strftime('%H:%M:%S')}  {spell}")
            self._update_history()
            if self.trail_x:
                self.frozen_trail = (list(self.trail_x), list(self.trail_y), spell)
            self._gesture_label.configure(text=f"✦ {spell}", fg=PURPLE)
            self._redraw_trail(frozen=True)

        # Gesture close / ack / idle — clear LEDs, stop trail
        if code in ("100f", "1002"):
            self.gesture_active = False
            self.ble.trigger_clear()
            if code == "100f" and not self.frozen_trail:
                self._gesture_label.configure(
                    text="gesture window closed", fg=TEXT_DIM)

    def _handle_imu(self, data: bytes):
        imu = decode_imu_packet(data)
        if imu is None:
            return
        ax, ay, az, gx, gy, gz = imu
        self._imu_label.configure(text=f"ax={ax:6d}  ay={ay:6d}  az={az:6d}")
        if self.gesture_active:
            self.trail_x.append(ax)
            self.trail_y.append(ay)
            self._redraw_trail()

    def _log_event(self, dec: dict):
        box = self._log_box
        box.configure(state="normal")
        ts   = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        cat  = dec.get("category", "unknown")
        label = dec.get("label") or dec.get("raw", "")
        tag  = cat if cat in STATUS_COLORS else "dim"
        # Keep log bounded
        lines = int(box.index("end-1c").split(".")[0])
        if lines > self.LOG_MAX:
            box.delete("1.0", f"{lines - self.LOG_MAX}.0")
        box.insert("end", f"{ts}  ", "dim")
        box.insert("end", f"{label}\n", "spell" if cat == "spell" else tag)
        box.see("end")
        box.configure(state="disabled")

    def _update_history(self):
        box = self._hist_box
        box.configure(state="normal")
        box.delete("1.0", "end")
        for line in self.spell_history[:30]:
            box.insert("end", line + "\n")
        box.configure(state="disabled")

    # ── 2D trail rendering ─────────────────────────────────────────────────────

    def _redraw_trail(self, frozen=False):
        ax = self.ax
        ax.cla()
        self._style_ax()

        if frozen and self.frozen_trail:
            xs, ys, spell = self.frozen_trail
        else:
            xs = list(self.trail_x)
            ys = list(self.trail_y)
            spell = None

        if len(xs) < 2:
            self.canvas.draw_idle()
            return

        xs = np.array(xs, dtype=float)
        ys = np.array(ys, dtype=float)

        # Colour gradient along the trail: cool (blue→magenta)
        n = len(xs)
        cmap = plt.get_cmap("cool")
        for i in range(n - 1):
            t = i / max(n - 2, 1)
            c = cmap(t)
            ax.plot(xs[i:i+2], ys[i:i+2], color=c, linewidth=2.0, alpha=0.9,
                    solid_capstyle='round')

        # Start dot (dim) and end dot (gold)
        ax.scatter([xs[0]],  [ys[0]],  color=TEXT_DIM, s=25, zorder=5)
        ax.scatter([xs[-1]], [ys[-1]], color=GOLD,     s=45, zorder=6)

        if spell:
            ax.set_title(spell, color=PURPLE, fontsize=10, pad=6, fontfamily="serif")

        self.canvas.draw_idle()

    def _clear_trail(self):
        self.trail_x.clear()
        self.trail_y.clear()
        self.frozen_trail = None
        self.gesture_active = False
        self._gesture_label.configure(text="waiting for gesture...", fg=TEXT_DIM)
        self.ax.cla()
        self._style_ax()
        self.canvas.draw_idle()

    def _on_close(self):
        self.ble.stop()
        self.root.destroy()


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()
    root.tk_setPalette(background=BG, foreground=TEXT)
    try:
        root.iconbitmap(default="")
    except Exception:
        pass
    WandGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
