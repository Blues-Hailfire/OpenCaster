"""
wand_gui.py — Magic Caster Wand Live GUI
=========================================
Dark Harry Potter-themed dashboard showing live BLE events,
3D gesture motion trail, and spell history.

Usage:
  python wand_gui.py

Requires: bleak, matplotlib, numpy, scipy (all already installed)
"""

import asyncio
import queue
import struct
import threading
import time
import tkinter as tk
from tkinter import ttk, font as tkfont
from datetime import datetime
from typing import Optional

import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from wand import (
    WRITE_UUID, NOTIFY_UUID, BATTERY_UUID,
    find_wand, hw_init, hw_write,
    spell_success_animation, spell_fail_animation,
    build_frame, cmd_changeled, clear_all, buzz_frame, hsv_to_rgb,
    MSG, RESP, decode_button_mask,
)
from matplotlib.collections import LineCollection
from motion import decode_imu_packet, GestureTracker
from spell_shapes import SpellLibrary
from spell_matcher import SpellMatcher
from wand_profiles import WandProfiles
from wand_calibrator import WandCalibrator
from cast_log import append_cast, count_casts, load_casts, NOT_A_SPELL
from spell_effects import SpellEffects, play_wand_macro
from bleak import BleakClient, BleakScanner

# ── Palette ────────────────────────────────────────────────────────────────────
BG         = "#0a0c1a"
BG2        = "#0f1228"
BG3        = "#161a38"
GOLD       = "#c9a84c"
GOLD_DIM   = "#7a6328"
BLUE_GLOW  = "#4a9eff"
PURPLE     = "#8b5cf6"
GREEN      = "#34d399"
RED        = "#f87171"
TEXT       = "#e8e4d8"
TEXT_DIM   = "#6b6880"
BORDER     = "#2a2d4a"

ANY_SPELL = "Any"    # target-spell dropdown entry that accepts every spell

STATUS_COLORS = {
    "state":   GREEN,
    "imu":     BLUE_GLOW,
    "gesture": GOLD,
    "spell":   PURPLE,
    "system":  TEXT_DIM,
    "unknown": RED,
}

# Button payload (0x10) second-byte bitmask meanings
BUTTON_NAMES = {
    0x00: ("No buttons",          "state"),
    0x01: ("Button 1",            "state"),
    0x02: ("Button 2",            "state"),
    0x03: ("Buttons 1+2",         "state"),
    0x04: ("Button 3",            "state"),
    0x08: ("Button 4",            "state"),
    0x0F: ("All buttons",         "state"),
}


# ── BLE decode ─────────────────────────────────────────────────────────────────

def decode_notification(data: bytes) -> dict:
    """Decode a NOTIFY_UUID packet into a structured event dict.

    Opcodes from RESP class (wand.py / mcw_ble.py):
      0x00  Firmware version response
      0x01  Challenge response (keepalive, fires periodically)
      0x02  Pong
      0x09  Box address
      0x0E  Wand product info
      0x10  Button payload — second byte is bitmask (bit0=btn1 … bit3=btn4)
      0x24  Spell cast — [0x24][?][?][len][utf-8 name]
      0x2C  IMU payload (handled separately via decode_imu_packet)
      0xFB  Button calibration baseline response
      0xFC  IMU calibration response
      0xDD  Button threshold read response
    """
    result = {
        "raw": data.hex(), "type": "unknown", "opcode": data[0] if data else None,
        "label": None, "category": "unknown", "text": None,
        "buttons": None,
    }

    if not data:
        return result

    opcode = data[0]

    if opcode in (RESP.CHALLENGE, RESP.PONG):
        # Challenge/pong keepalive — very frequent, treat as system heartbeat
        result.update(type="heartbeat", label="Heartbeat", category="system")
        return result

    if opcode == RESP.FIRMWARE_VERSION:
        version = ".".join(str(b) for b in data[1:])
        result.update(type="info", label=f"FW v{version}", category="system")
        return result

    if opcode == RESP.SPELL_CAST:
        # [0x24][?][?][len][utf-8 name]
        try:
            if len(data) >= 5:
                spell_len = data[3]
                raw_name = data[4: 4 + spell_len]
                text = raw_name.decode("utf-8", errors="ignore").strip().replace("\x00", "").replace("_", " ")
                if text:
                    result.update(type="spell", label=f"✦ {text}", category="spell", text=text)
                    return result
        except Exception:
            pass
        result.update(type="spell", label="Spell (decode err)", category="spell")
        return result

    if opcode == RESP.BUTTON_PAYLOAD:
        # Second byte is a bitmask: bit0=btn1, bit1=btn2, bit2=btn3, bit3=btn4
        mask = data[1] if len(data) >= 2 else 0
        states = decode_button_mask(mask)
        label_text, cat = BUTTON_NAMES.get(mask & 0x0F, (f"Buttons 0x{mask:02X}", "state"))
        result.update(type="buttons", label=label_text, category=cat, buttons=states)
        return result

    if opcode == RESP.IMU_PAYLOAD:
        result.update(type="imu", label="IMU burst", category="imu")
        return result

    if opcode in (RESP.BUTTON_CALIBRATION_BASELINE, RESP.IMU_CALIBRATION):
        label = "Button cal done" if opcode == RESP.BUTTON_CALIBRATION_BASELINE else "IMU cal done"
        result.update(type="calibration", label=label, category="system")
        return result

    result.update(label=f"0x{opcode:02X} ({data.hex()})")
    return result


# ── BLE background thread ──────────────────────────────────────────────────────

class BLEWorker:
    SCAN_TIMEOUT = 6.0

    def __init__(self, msg_queue: queue.Queue):
        self.q = msg_queue
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._client: Optional[BleakClient] = None
        self._boxes: dict = {}          # address → connected BleakClient
        self._box_tasks: dict = {}      # address → running _box_loop future
        self._stop = False
        self._target_name: Optional[str] = None
        self._target_address: Optional[str] = None
        self._connect_event = asyncio.Event()

    def start(self):
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def stop(self):
        self._stop = True
        if self.loop and self._connect_event:
            # Wake the idle loop so it can see _stop=True and exit cleanly
            self.loop.call_soon_threadsafe(self._connect_event.set)

    def _run(self):
        asyncio.run(self._thread_main())

    async def _thread_main(self):
        self.loop = asyncio.get_running_loop()
        self._connect_event = asyncio.Event()
        await self._idle_loop()

    def scan_for_wands(self, callback):
        """Scan for wands (MCW-*) and boxes (MCB-*); callback gets
        [(name, address), ...] for both — callers split them by prefix."""
        def _worker():
            async def _scan():
                devices = await BleakScanner.discover(timeout=self.SCAN_TIMEOUT)
                return [(d.name, d.address) for d in devices
                        if d.name and d.name.startswith(("MCW", "MCB"))]
            loop = asyncio.new_event_loop()
            try:
                results = loop.run_until_complete(_scan())
            except Exception:
                results = []
            finally:
                loop.close()
            callback(results)
        threading.Thread(target=_worker, daemon=True).start()

    def connect_to(self, name: str, address: str):
        self._target_name    = name
        self._target_address = address
        if self.loop:
            self.loop.call_soon_threadsafe(self._connect_event.set)

    async def _idle_loop(self):
        while not self._stop:
            await self._connect_event.wait()
            self._connect_event.clear()
            if self._stop:
                break
            await self._connect_loop()

    async def _connect_loop(self):
        self.q.put({"type": "status_msg", "text": f"Connecting to {self._target_name}…"})
        retry_delay = 2.0
        while not self._stop:
            if self._connect_event.is_set():
                self._connect_event.clear()
                self.q.put({"type": "status_msg", "text": f"Switching to {self._target_name}…"})
                retry_delay = 2.0

            try:
                async with BleakClient(self._target_address, timeout=20.0) as client:
                    self._client = client
                    self.q.put({"type": "connected", "name": self._target_name,
                                "address": self._target_address})
                    retry_delay = 2.0

                    # Subscribe FIRST so CHALLENGE pings are answered during init
                    await client.start_notify(
                        NOTIFY_UUID,
                        lambda _s, d: self.q.put({"type": "ble", "data": bytes(d)}))

                    await asyncio.sleep(0.3)  # brief settle before init writes
                    await hw_init(client)
                    await self._welcome(client)

                    # Enable IMU streaming: reset then start
                    await client.write_gatt_char(
                        WRITE_UUID, struct.pack('B', MSG.IMUFLAG_RESET), response=False)
                    await asyncio.sleep(0.1)
                    await client.write_gatt_char(
                        WRITE_UUID, struct.pack('BBB', MSG.IMUFLAG_SET, 0x00, 0x80), response=False)

                    # Battery notifications on a separate characteristic
                    try:
                        await client.start_notify(
                            BATTERY_UUID,
                            lambda _s, d: self.q.put({"type": "battery", "pct": d[0]}))
                    except Exception:
                        pass

                    while not self._stop and client.is_connected:
                        if self._connect_event.is_set():
                            break
                        await asyncio.sleep(0.5)

                    # Clean up: stop IMU streaming before disconnect
                    try:
                        await client.write_gatt_char(
                            WRITE_UUID, struct.pack('B', MSG.IMUFLAG_RESET), response=False)
                    except Exception:
                        pass
                    await client.stop_notify(NOTIFY_UUID)

                self._client = None
                self.q.put({"type": "disconnected"})
                if self._connect_event.is_set():
                    return
                if not self._stop:
                    self.q.put({"type": "status_msg", "text": "Disconnected — reconnecting…"})
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                # WinRT service-discovery can raise CancelledError on Windows —
                # treat it as a transient failure and retry.
                self._client = None
                self.q.put({"type": "disconnected"})
                self.q.put({"type": "status_msg",
                            "text": "BLE service discovery interrupted — retrying…"})
                if self._connect_event.is_set():
                    return
                if not self._stop:
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 1.5, 15.0)
            except Exception as e:
                self._client = None
                self.q.put({"type": "disconnected"})
                self.q.put({"type": "status_msg", "text": f"Error: {e}"})
                if self._connect_event.is_set():
                    return
                if not self._stop:
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 1.5, 15.0)

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

    async def _send_blue(self, client):
        frame = build_frame(*[cmd_changeled(g, 0, 0, 255, 2000) for g in range(4)])
        await client.write_gatt_char(WRITE_UUID, bytes([0x60]), response=False)
        await client.write_gatt_char(WRITE_UUID, frame, response=False)

    async def _send_clear(self, client):
        await client.write_gatt_char(WRITE_UUID, clear_all(), response=False)

    async def _send_pong(self, client):
        """Reply to a CHALLENGE (0x01) keepalive ping with PONG (0x02)."""
        try:
            await client.write_gatt_char(
                WRITE_UUID, bytes([MSG.CHALLENGE]), response=False)
        except Exception:
            pass  # If we're mid-disconnect, silently ignore

    def trigger_blue(self):
        if self._client and self.loop:
            asyncio.run_coroutine_threadsafe(self._send_blue(self._client), self.loop)

    def trigger_clear(self):
        if self._client and self.loop:
            asyncio.run_coroutine_threadsafe(self._send_clear(self._client), self.loop)

    def trigger_cast_animation(self, success: bool, macro: Optional[list] = None):
        """Thread-safe: play a spell's original wand macro if given, otherwise
        the generic success or fail animation."""
        if self._client and self.loop:
            if success and macro:
                coro = play_wand_macro(self._client, macro)
            else:
                anim = spell_success_animation if success else spell_fail_animation
                coro = anim(self._client)
            asyncio.run_coroutine_threadsafe(coro, self.loop)

    # ── Boxes (MCB-*) ─────────────────────────────────────────────────────────
    # Each box gets its own reconnecting link on the worker loop.  Box
    # notifications are forwarded as "box_ble" messages; the GUI only logs
    # them and answers keepalive challenges.

    def connect_box(self, name: str, address: str):
        if self.loop and address not in self._box_tasks:
            self._box_tasks[address] = asyncio.run_coroutine_threadsafe(
                self._box_loop(name, address), self.loop)

    BOX_MAX_FAILURES = 5    # consecutive failed connects before giving up on a box

    async def _box_loop(self, name: str, address: str):
        retry_delay, failures = 2.0, 0
        while not self._stop and failures < self.BOX_MAX_FAILURES:
            try:
                async with BleakClient(address, timeout=20.0) as client:
                    self._boxes[address] = client
                    self.q.put({"type": "box_connected", "name": name, "address": address})
                    retry_delay, failures = 2.0, 0
                    await client.start_notify(
                        NOTIFY_UUID,
                        lambda _s, d: self.q.put({"type": "box_ble", "name": name,
                                                  "address": address, "data": bytes(d)}))
                    while not self._stop and client.is_connected:
                        await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                failures += 1   # WinRT service discovery hiccup — retry below
            except Exception as e:
                failures += 1
                self.q.put({"type": "status_msg", "text": f"{name}: {e}"})
            self._boxes.pop(address, None)
            self.q.put({"type": "box_disconnected", "name": name, "address": address})
            if not self._stop:
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 1.5, 15.0)
        self._box_tasks.pop(address, None)     # a later scan may try again
        if failures >= self.BOX_MAX_FAILURES:
            self.q.put({"type": "status_msg", "text": f"Gave up connecting to {name}"})

    def trigger_box_macro(self, macro: Optional[list]):
        """Thread-safe: play an original-app box macro on every connected box."""
        if not (macro and self.loop):
            return
        for address, client in list(self._boxes.items()):
            fut = asyncio.run_coroutine_threadsafe(play_wand_macro(client, macro), self.loop)
            fut.add_done_callback(lambda f, a=address: f.exception() and self.q.put(
                {"type": "status_msg", "text": f"Box {a}: effect failed — {f.exception()}"}))

    def reply_box_challenge(self, address: str):
        client = self._boxes.get(address)
        if client and self.loop:
            asyncio.run_coroutine_threadsafe(self._send_pong(client), self.loop)

    def reply_challenge(self):
        """Thread-safe: schedule a pong reply for the wand's keepalive challenge."""
        if self._client and self.loop:
            asyncio.run_coroutine_threadsafe(self._send_pong(self._client), self.loop)


# ── Main GUI ───────────────────────────────────────────────────────────────────

class WandGUI:
    LOG_MAX    = 200
    GESTURE_TIMEOUT_S = 8.0   # auto-close gesture window after this many seconds
    MIN_CAST_S        = 0.5   # sensors held for less than this = a quick tap, not a cast
    MIN_GESTURE_DEG   = 15.0  # trail bounding box must span this many degrees to match
    RESCAN_S          = 10.0  # rescan interval while no wand has been found
    DEFAULT_CAST_DEG  = 45.0  # typical cast size until labelled casts say otherwise

    # Gesture trail comes from motion.GestureTracker: gyro-integrated tip
    # direction in degrees (right / up), gravity-referenced so wrist roll and
    # how the wand is held don't matter.  Per-wand tip axis and gyro bias are
    # loaded from wand_profiles.json ("motion" block) on connect.

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("✦ OpenCaster — Magic Wand Monitor")
        self.root.configure(bg=BG)
        self.root.geometry("1280x780")
        self.root.minsize(1100, 680)

        self.q: queue.Queue = queue.Queue()
        self.ble = BLEWorker(self.q)

        # Spell recognition
        self.library  = SpellLibrary(folder="spells")
        self.matcher  = SpellMatcher()
        self.effects  = SpellEffects()      # original wand macros + sounds (media/)

        self.battery_pct   = tk.StringVar(value="—")
        self.status_var    = tk.StringVar(value="Select a wand and press Connect")
        self.last_spell    = tk.StringVar(value="—")
        self.spell_history: list[str] = []

        # Wand selector state
        self._found_wands: dict = {}
        self._found_boxes: dict = {}
        self._boxes_up: set = set()         # addresses of connected boxes
        self._auto_connected = False        # startup auto-connect done
        self._scanning    = False
        self._wand_var    = tk.StringVar(value="")

        # Gesture trail in degrees of tip travel (owned by the tracker)
        self._profiles = WandProfiles()
        self._tracker  = GestureTracker()
        self._wand_id: Optional[tuple] = None          # (address, name) once connected
        self._calibrator: Optional[WandCalibrator] = None
        self.trail_x: list = self._tracker.trail_x
        self.trail_y: list = self._tracker.trail_y
        self.gesture_active = False
        self.frozen_trail: Optional[tuple] = None

        # Button state
        self._button_states: dict = {}
        self._button_overrides: dict = {}   # per-button forced-on overrides for broken hardware
        self._grip_active   = False
        self._sensor_level  = 0
        self._gesture_timer = None          # root.after ID for auto-close timeout
        self._gesture_opened = 0.0          # time.monotonic() when the window opened

        # Typical cast sizes, from labelled casts (see _typical_extent)
        self._cast_sizes: dict = {}
        self._load_cast_sizes()

        # Target spell dropdown (see _on_target_changed)
        self._target_var = tk.StringVar(value=ANY_SPELL)
        self._target_names: dict = {}       # display name → library key

        # Cast labelling (see _request_label)
        self._label_casts = tk.BooleanVar(value=True)
        self._pending_cast: Optional[dict] = None

        # Template drawn over the finished trail: (spell, "match"|"guess"|"preview")
        self._overlay: Optional[tuple] = None
        self._cast_overlay: Optional[tuple] = None   # what the last cast matched

        self._build_ui()
        self._redraw_trail()                    # start the trail view at cast size
        self.ble.start()
        self.root.after(50, self._poll)
        self.root.after(500, self._do_scan)     # auto-scan + connect on launch
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        hdr = tk.Frame(self.root, bg=BG, pady=8)
        hdr.pack(fill="x", padx=16, pady=(12, 0))

        tk.Label(hdr, text="✦  OPENCASTER", bg=BG, fg=GOLD,
                 font=("Georgia", 22, "bold")).pack(side="left")
        tk.Label(hdr, text="Magic Wand Monitor", bg=BG, fg=TEXT_DIM,
                 font=("Georgia", 11, "italic")).pack(side="left", padx=(10, 0), pady=(6, 0))

        right_hdr = tk.Frame(hdr, bg=BG)
        right_hdr.pack(side="right")

        tk.Label(right_hdr, text="🔋", bg=BG, fg=TEXT_DIM,
                 font=("Segoe UI", 11)).pack(side="left")
        tk.Label(right_hdr, textvariable=self.battery_pct, bg=BG, fg=GREEN,
                 font=("Courier New", 11, "bold")).pack(side="left", padx=(2, 16))
        self._conn_dot = tk.Label(right_hdr, text="⬤", bg=BG, fg=RED,
                                   font=("Segoe UI", 14))
        self._conn_dot.pack(side="left")
        self._box_label = tk.Label(right_hdr, text="", bg=BG, fg=GREEN,
                                   font=("Segoe UI", 10))
        self._box_label.pack(side="left", padx=(6, 0))
        tk.Label(right_hdr, textvariable=self.status_var, bg=BG, fg=TEXT_DIM,
                 font=("Courier New", 10)).pack(side="left", padx=(6, 16))

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Wand.TCombobox",
                        fieldbackground=BG3, background=BG3,
                        foreground=TEXT, selectbackground=BG3,
                        selectforeground=TEXT, arrowcolor=GOLD_DIM,
                        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
        style.map("Wand.TCombobox",
                  fieldbackground=[("readonly", BG3)],
                  selectbackground=[("readonly", BG3)])

        self._scan_btn = tk.Button(
            right_hdr, text="Scan", bg=BG3, fg=TEXT_DIM, bd=0,
            padx=10, pady=3, font=("Courier New", 9),
            activebackground=BORDER, command=self._do_scan)
        self._scan_btn.pack(side="left", padx=(0, 4))

        self._wand_combo = ttk.Combobox(
            right_hdr, textvariable=self._wand_var,
            style="Wand.TCombobox", state="readonly",
            width=18, font=("Courier New", 9))
        self._wand_combo["values"] = ["— no wands found —"]
        self._wand_combo.pack(side="left", padx=(0, 4))

        self._conn_btn = tk.Button(
            right_hdr, text="Connect", bg=GOLD_DIM, fg=BG, bd=0,
            padx=10, pady=3, font=("Courier New", 9, "bold"),
            activebackground=GOLD, command=self._do_connect)
        self._conn_btn.pack(side="left")

        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x", padx=16, pady=8)

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        body.columnconfigure(0, weight=3, minsize=280)
        body.columnconfigure(1, weight=5, minsize=420)
        body.columnconfigure(2, weight=3, minsize=260)
        body.rowconfigure(0, weight=1)

        self._build_log_panel(body)
        self._build_plot_panel(body)
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
        for cat, clr in STATUS_COLORS.items():
            self._log_box.tag_configure(cat, foreground=clr)
        self._log_box.tag_configure("dim", foreground=TEXT_DIM)
        self._log_box.tag_configure("spell", foreground=PURPLE,
                                     font=("Courier New", 9, "bold"))

    def _build_plot_panel(self, body):
        panel = self._panel(body, 1, "GESTURE TRAIL  (tip direction, degrees)")

        # Target spell: "Any", or one spell that is shown as a guide and is
        # the only cast accepted
        spell_row = tk.Frame(panel, bg=BG2)
        spell_row.pack(fill="x", padx=10, pady=(6, 0))
        tk.Label(spell_row, text="SPELLS", bg=BG2, fg=GOLD_DIM,
                 font=("Georgia", 7, "bold")).pack(side="left", padx=(0, 8))
        self._target_combo = ttk.Combobox(
            spell_row, textvariable=self._target_var, style="Wand.TCombobox",
            state="readonly", width=26, font=("Courier New", 9))
        self._target_combo.pack(side="left")
        self._target_combo.bind("<<ComboboxSelected>>", lambda e: self._on_target_changed())
        self._refresh_target_list()

        self._gesture_label = tk.Label(panel, text="waiting for gesture...",
                                        bg=BG2, fg=TEXT_DIM,
                                        font=("Georgia", 10, "italic"))
        self._gesture_label.pack(pady=(4, 0))

        fig = plt.Figure(figsize=(8, 7), dpi=100)
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
        tk.Button(btn_row, text="↺ Reload Spells", bg=BG3, fg=TEXT_DIM, bd=0, padx=10, pady=3,
                  font=("Courier New", 8), activebackground=BORDER,
                  command=self._reload_spells).pack(side="left", padx=4)
        tk.Button(btn_row, text="Calibrate", bg=BG3, fg=BLUE_GLOW, bd=0, padx=10, pady=3,
                  font=("Courier New", 8), activebackground=BORDER,
                  command=self._open_calibrator).pack(side="left", padx=4)
        tk.Checkbutton(btn_row, text="Label casts", variable=self._label_casts,
                       bg=BG2, fg=TEXT_DIM, selectcolor=BG3, activebackground=BG2,
                       activeforeground=TEXT, bd=0, font=("Courier New", 8),
                       command=self._on_label_toggle).pack(side="left", padx=4)

        # Cast label picker — shown after each cast, blocks the next one
        self._label_frame = tk.Frame(panel, bg=BG3, padx=6, pady=6)
        self._label_prompt = tk.Label(self._label_frame, bg=BG3, fg=GOLD,
                                      font=("Georgia", 9, "bold"))
        self._label_prompt.pack(anchor="w", pady=(0, 4))
        self._label_btns = tk.Frame(self._label_frame, bg=BG3)
        self._label_btns.pack(fill="x")

    def _style_ax(self):
        ax = self.ax
        ax.set_facecolor(BG3)
        ax.tick_params(colors=TEXT_DIM, labelsize=6)
        ax.xaxis.label.set_color(TEXT_DIM)
        ax.yaxis.label.set_color(TEXT_DIM)
        ax.set_xlabel("right  (deg)", labelpad=4, fontsize=7)
        ax.set_ylabel("up  (deg)", labelpad=4, fontsize=7)
        for spine in ax.spines.values():
            spine.set_color(BORDER)

    def _build_status_panel(self, body):
        panel = self._panel(body, 2, "STATUS")

        # Grip indicator
        grip_frame = tk.Frame(panel, bg=BG2)
        grip_frame.pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(grip_frame, text="GRIP", bg=BG2, fg=GOLD_DIM,
                 font=("Georgia", 7, "bold")).pack(side="left", padx=(4, 8))
        self._grip_dot = tk.Label(grip_frame, text="⬤", bg=BG2, fg=TEXT_DIM,
                                   font=("Segoe UI", 13))
        self._grip_dot.pack(side="left")
        self._grip_label = tk.Label(grip_frame, text="not gripped", bg=BG2,
                                     fg=TEXT_DIM, font=("Courier New", 8))
        self._grip_label.pack(side="left", padx=(6, 0))

        # Button state display
        tk.Label(panel, text="BUTTONS", bg=BG2, fg=GOLD_DIM,
                 font=("Georgia", 7, "bold")).pack(anchor="w", padx=14, pady=(10, 2))
        self._btn_label = tk.Label(panel, text="—", bg=BG2, fg=TEXT_DIM,
                                    font=("Courier New", 8))
        self._btn_label.pack(anchor="w", padx=14)

        # Sensor circles
        tk.Label(panel, text="SENSORS", bg=BG2, fg=GOLD_DIM,
                 font=("Georgia", 7, "bold")).pack(anchor="w", padx=14, pady=(10, 2))
        circles_frame = tk.Frame(panel, bg=BG2)
        circles_frame.pack(fill="x", padx=10, pady=(0, 6))
        self._sensor_canvas = tk.Canvas(circles_frame, bg=BG2, bd=0,
                                         highlightthickness=0, height=52)
        self._sensor_canvas.pack(fill="x")
        self._sensor_circles = []
        self._sensor_canvas.bind("<Configure>", self._on_sensor_canvas_resize)

        # Last spell
        spell_frame = tk.Frame(panel, bg=BG3, pady=12)
        spell_frame.pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(spell_frame, text="LAST SPELL", bg=BG3, fg=GOLD_DIM,
                 font=("Georgia", 7, "bold")).pack()
        tk.Label(spell_frame, textvariable=self.last_spell, bg=BG3, fg=PURPLE,
                 font=("Georgia", 16, "bold"), wraplength=200).pack(pady=(2, 0))

        # Spell history
        tk.Label(panel, text="SPELL HISTORY", bg=BG2, fg=GOLD_DIM,
                 font=("Georgia", 7, "bold"), pady=8).pack(anchor="w", padx=14, pady=(10, 2))
        hist_outer = tk.Frame(panel, bg=BORDER, padx=1, pady=1)
        hist_outer.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._hist_box = tk.Text(hist_outer, bg=BG3, fg=PURPLE, bd=0, relief="flat",
                                  font=("Georgia", 10), wrap="word", state="disabled",
                                  selectbackground=BG2)
        self._hist_box.pack(fill="both", expand=True, padx=4, pady=4)

        # IMU readout
        tk.Label(panel, text="LAST IMU SAMPLE", bg=BG2, fg=GOLD_DIM,
                 font=("Georgia", 7, "bold")).pack(anchor="w", padx=14, pady=(4, 2))
        self._imu_label = tk.Label(panel, text="—", bg=BG2, fg=BLUE_GLOW,
                                    font=("Courier New", 8), wraplength=220, justify="left")
        self._imu_label.pack(anchor="w", padx=14, pady=(0, 8))

        # Spell match scores
        tk.Label(panel, text="MATCH SCORES", bg=BG2, fg=GOLD_DIM,
                 font=("Georgia", 7, "bold")).pack(anchor="w", padx=14, pady=(4, 2))
        self._scores_label = tk.Label(panel, text="—", bg=BG2, fg=TEXT_DIM,
                                       font=("Courier New", 7), wraplength=220, justify="left")
        self._scores_label.pack(anchor="w", padx=14, pady=(0, 8))


    # ── Sensor circle drawing ─────────────────────────────────────────────────

    def _effective_buttons(self) -> dict:
        """Merge hardware button state with any manual overrides."""
        merged = dict(self._button_states)
        for k, v in self._button_overrides.items():
            if v:
                merged[k] = True
        merged["button_all"] = all(merged.get(f"button_{i}", False) for i in range(1, 5))
        return merged

    def _toggle_button_override(self, button_key: str):
        """Toggle a button override on/off, then re-evaluate grip logic."""
        current = self._button_overrides.get(button_key, False)
        self._button_overrides[button_key] = not current
        # Re-run grip/gesture logic with new effective state
        self._evaluate_buttons(self._effective_buttons())
        self._draw_sensor_circles(self._sensor_level)

    def _on_sensor_canvas_resize(self, event):
        self._draw_sensor_circles(self._sensor_level)

    def _draw_sensor_circles(self, level: int):
        c = self._sensor_canvas
        c.delete("all")
        self._sensor_circles = []
        w = c.winfo_width()
        if w < 10:
            return
        n, r, gap = 4, 18, 10
        total  = n * r * 2 + (n - 1) * gap
        start  = (w - total) // 2
        cy     = 26
        lit_colors = [GREEN, BLUE_GLOW, GOLD, PURPLE]
        btn_keys   = ["button_1", "button_2", "button_3", "button_4"]

        for i in range(n):
            cx  = start + i * (r * 2 + gap) + r
            x0, y0, x1, y1 = cx - r, cy - r, cx + r, cy + r
            lit      = i < level
            override = self._button_overrides.get(btn_keys[i], False)
            fill     = lit_colors[i] if lit else BG3
            outline  = GOLD if override else (BG2 if lit else BORDER)
            width    = 2 if override else 1
            if lit:
                hr = r + 4
                c.create_oval(cx - hr, cy - hr, cx + hr, cy + hr,
                              fill="", outline=fill, width=2)
            oid = c.create_oval(x0, y0, x1, y1, fill=fill, outline=outline, width=width)
            self._sensor_circles.append(oid)
            # Bind click to toggle override for this button
            key = btn_keys[i]
            c.tag_bind(oid, "<Button-1>",
                       lambda e, k=key: self._toggle_button_override(k))

    def _set_grip(self, active: bool):
        self._grip_active = active
        if active:
            self._grip_dot.configure(fg=GREEN)
            self._grip_label.configure(text="gripped", fg=GREEN)
        else:
            self._grip_dot.configure(fg=TEXT_DIM)
            self._grip_label.configure(text="not gripped", fg=TEXT_DIM)
            self._sensor_level = 0
            self._draw_sensor_circles(0)

    def _set_sensor_level(self, level: int):
        self._sensor_level = max(0, min(4, level))
        self._draw_sensor_circles(self._sensor_level)

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
            if name.startswith("MCB"):
                self._found_boxes[addr] = name
                self.ble.connect_box(name, addr)    # no-op if already linked
            else:
                self._found_wands[addr] = name

        if not self._found_wands:
            self._wand_combo["values"] = ["— no wands found —"]
            self._wand_var.set("— no wands found —")
            if self._wand_id is None:
                self.status_var.set("No wand found — scanning again…")
                self.root.after(int(self.RESCAN_S * 1000), self._do_scan)
            return
        labels = [f"{name}  ({addr})"
                  for addr, name in sorted(self._found_wands.items())]
        self._wand_combo["values"] = labels

        # Auto-connect: last-used wand if it's here, otherwise the first found.
        # Only while nothing is connected/selected, so manual picks stand.
        if self._wand_id is None and not self._auto_connected:
            last = self._profiles.last_used()
            pick = next((l for l in labels if last and last["address"] in l), labels[0])
            self._wand_var.set(pick)
            self._auto_connected = True
            self._do_connect()
        else:
            # Keep the connected wand selected after a rescan
            current = self.ble._target_address
            self._wand_var.set(next((l for l in labels if current and current in l), labels[0]))

    def _do_connect(self):
        label = self._wand_var.get()
        for addr, name in self._found_wands.items():
            if addr in label:
                self.root.title(f"✦ OpenCaster — {name}")
                self.ble.connect_to(name, addr)
                return
        self.status_var.set("Select a wand from the dropdown first")

    def _reload_spells(self):
        self.library.reload()
        self.effects.reload()
        self._refresh_target_list()
        self._redraw_trail(frozen=bool(self.frozen_trail))
        names = self.library.names()
        fx = self.effects.summary(names)
        n_macro = sum(m for m, _ in fx.values())
        n_sound = sum(1 for _, s in fx.values() if s)
        self.status_var.set(f"Reloaded {len(names)} spell(s) — "
                            f"{n_macro} with wand effects, {n_sound} with sounds")

    # ── Event polling ─────────────────────────────────────────────────────────

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
            self._load_motion_profile(msg["address"], msg["name"])
        elif t == "disconnected":
            ts = datetime.now().strftime("%H:%M:%S")
            self.status_var.set("Disconnected")
            self._conn_dot.configure(fg=RED)
            self._set_grip(False)
            self._log_event({"type": "system", "label": f"[{ts}] ⚠ Disconnected",
                             "category": "system", "raw": ""})
        elif t == "battery":
            self.battery_pct.set(f"{msg['pct']}%")
        elif t == "status_msg":
            self.status_var.set(msg["text"])
        elif t == "ble":
            self._handle_ble(msg["data"])
        elif t in ("box_connected", "box_disconnected"):
            up = t == "box_connected"
            if up:
                self._boxes_up.add(msg["address"])
            else:
                self._boxes_up.discard(msg["address"])
            self._box_label.configure(
                text=f"📦 {len(self._boxes_up)}" if self._boxes_up else "",
                fg=GREEN)
            ts = datetime.now().strftime("%H:%M:%S")
            self._log_event({"type": "system", "category": "system", "raw": "",
                             "label": f"[{ts}] {'📦 Box connected' if up else '⚠ Box disconnected'}"
                                      f": {msg['name']}"})
        elif t == "box_ble":
            dec = decode_notification(msg["data"])
            if dec.get("type") == "heartbeat":
                self.ble.reply_box_challenge(msg["address"])
            dec["label"] = f"[{msg['name']}] {dec.get('label', '')}"
            self._log_event(dec)


    def _handle_ble(self, data: bytes):
        """Route an incoming BLE notification to the correct handler."""

        # IMU packets (0x2C) are high-frequency — handle before decoding to dict
        if data and data[0] == RESP.IMU_PAYLOAD:
            samples = decode_imu_packet(data)
            if samples:
                self._handle_imu_samples(samples)
            return

        dec = decode_notification(data)
        self._log_event(dec)

        evt_type = dec.get("type")
        opcode   = dec.get("opcode")

        # ── Keepalive challenge (0x01): wand expects a pong or it disconnects ─
        if evt_type == "heartbeat":
            self.ble.reply_challenge()
            return

        # ── Button payload (0x10): drives grip + sensor visualisation ─────────
        if evt_type == "buttons":
            self._button_states = dec.get("buttons") or {}
            self._evaluate_buttons(self._effective_buttons())

            # Update button label (show hardware + overrides)
            eff = self._effective_buttons()
            pressed = [f"Btn{i+1}" for i, k in enumerate(
                ("button_1","button_2","button_3","button_4")) if eff.get(k)]
            override_active = any(self._button_overrides.values())
            label = ", ".join(pressed) if pressed else "none"
            if override_active:
                label += " ⚡"  # indicator that an override is active
            self._btn_label.configure(
                text=label,
                fg=GOLD if override_active else (GREEN if pressed else TEXT_DIM))

        # ── Spell cast notification from wand (0x24) ─────────────────────────
        elif evt_type == "spell":
            spell = dec.get("text", "")
            if spell:
                self._on_spell_confirmed(spell)

    def _evaluate_buttons(self, states: dict):
        """Apply grip/gesture logic from an effective button state dict.

        Called both from BLE button events and from manual override toggles.
        """
        gripped = states.get("button_1", False)

        if gripped and not self._grip_active:
            self._set_grip(True)
            self._set_sensor_level(1)
        elif not gripped and self._grip_active:
            self._set_grip(False)

        if gripped:
            held = sum(1 for k in ("button_2", "button_3", "button_4")
                       if states.get(k, False))
            self._set_sensor_level(min(1 + held, 4))

        # All sensors active → open gesture window
        all_held = states.get("button_all", False)
        if all_held and not self.gesture_active and self._pending_cast is not None:
            self._gesture_label.configure(text="label the last cast first", fg=RED)
            self._label_prompt.configure(fg=RED)
        elif all_held and not self.gesture_active:
            self._open_gesture_window()

        # Any sensor released → close gesture window
        elif not all_held and self.gesture_active:
            self._close_gesture_window()

    def _gesture_timeout(self):
        """Called by the auto-close timer if gesture window has been open too long."""
        if self.gesture_active:
            self._gesture_label.configure(text="gesture timeout — closing", fg=RED)
            self._close_gesture_window()

    def _open_gesture_window(self):
        """Start collecting a new gesture trail."""
        self.gesture_active = True
        self._gesture_opened = time.monotonic()
        self._overlay = self._cast_overlay = None
        self._tracker.begin()
        self.trail_x, self.trail_y = self._tracker.trail_x, self._tracker.trail_y
        self.frozen_trail = None
        self._gesture_label.configure(text="● gesture window open", fg=GOLD)
        self._set_sensor_level(4)
        self.ble.trigger_blue()
        # Cancel any stale timer and set a fresh auto-close timeout
        if self._gesture_timer is not None:
            self.root.after_cancel(self._gesture_timer)
        self._gesture_timer = self.root.after(
            int(self.GESTURE_TIMEOUT_S * 1000), self._gesture_timeout)

    def _close_gesture_window(self):
        """End gesture collection and attempt spell matching."""
        self.gesture_active = False
        self._tracker.end()
        # Cancel the auto-close timer if we're closing normally
        if self._gesture_timer is not None:
            self.root.after_cancel(self._gesture_timer)
            self._gesture_timer = None
        self._set_sensor_level(0)

        # Quickly touching and releasing the sensors isn't a cast: no
        # matching, no wand animation, no label prompt — just drop the glow.
        held = time.monotonic() - self._gesture_opened
        if held < self.MIN_CAST_S:
            self.ble.trigger_clear()
            self._gesture_label.configure(
                text=f"ignored (quick tap, {held:.1f} s)", fg=TEXT_DIM)
            self._redraw_trail()
            return

        if self._calibrator is not None:
            self.ble.trigger_clear()
            self._gesture_label.configure(text="calibrating — matching paused", fg=TEXT_DIM)
            return

        trail = np.column_stack([list(self.trail_x), list(self.trail_y)])
        gate, results = self._match_trail(trail)

        # Overlay the template the cast was judged against: the target spell
        # if one is chosen, otherwise the best match
        if results:
            best = results[0]
            target = self._target()
            if target:
                self._cast_overlay = (target, "match" if best["success"] else "miss")
            else:
                self._cast_overlay = (best["spell"], "match" if best["success"] else "guess")
            self._overlay = self._cast_overlay
            self._redraw_trail(frozen=best["success"])

        if self._label_casts.get():
            best = results[0] if results else None
            self._request_label({
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "wand":      self._wand_id[0] if self._wand_id else None,
                "trail":     [[round(x, 3), round(y, 3)] for x, y in trail.tolist()],
                "gate":      gate,
                "predicted": best["spell"] if best else None,
                "accepted":  bool(best and best["success"]),
                "scores":    [[r["spell"], r["score"]] for r in results],
                "target":    self._target(),      # dropdown spell, or None for Any
            })

    def _match_trail(self, trail: np.ndarray) -> tuple:
        """Gate and match a finished trail; returns (gate, ranked results).

        Every completed cast ends with a wand animation: success is played
        by _on_spell_confirmed, every other outcome plays the fail one.
        """
        if len(trail) < 20:
            self.ble.trigger_cast_animation(success=False)
            self._gesture_label.configure(text="gesture too short", fg=RED)
            return "too_short", []

        extent = float(np.ptp(trail, axis=0).max())
        if extent < self.MIN_GESTURE_DEG:
            # The matcher normalises size away, so hand drift during a
            # grip-and-hold would otherwise be matched like a real stroke.
            self.ble.trigger_cast_animation(success=False)
            self._gesture_label.configure(
                text=f"gesture too small ({extent:.0f}°)", fg=RED)
            return "too_small", []

        results = self.matcher.match_all(trail, self.library)

        # With a target spell chosen, it is the only cast that can succeed.
        # Matching still ranks every spell, so a cast that looks more like
        # another spell is rejected rather than forced onto the target.
        target = self._target()
        if target:
            for r in results:
                r["success"] = r["success"] and r["spell"] == target

        if results:
            best = results[0]
            # Show top-3 scores
            score_lines = "\n".join(
                f"{'✓' if r['success'] else ' '} {r['spell']:<14} {r['score']:.3f}"
                for r in results[:3])
            if target and target not in [r["spell"] for r in results[:3]]:
                t = next(r for r in results if r["spell"] == target)
                score_lines += f"\n  {target:<14} {t['score']:.3f}  (target)"
            self._scores_label.configure(text=score_lines)

            if best["success"]:
                self._on_spell_confirmed(best["spell"])
            else:
                self.ble.trigger_cast_animation(success=False)
                miss = (f"not {self._spell_display(target)}  "
                        f"(closest: {self._spell_display(best['spell'])})") if target else "no match"
                self._gesture_label.configure(text=miss, fg=RED)
                self._redraw_trail(frozen=False)
            return "ok", results

        self.ble.trigger_cast_animation(success=False)
        self._gesture_label.configure(text="no spells loaded", fg=TEXT_DIM)
        self._scores_label.configure(text="—")
        return "no_spells", []

    # ── Cast labelling ────────────────────────────────────────────────────────
    # After every cast the user must say what they cast (or discard it) before
    # another gesture window can open.  Labelled casts go to casts/casts.jsonl
    # for eval_matcher.py.

    def _request_label(self, record: dict):
        self._pending_cast = record
        for w in self._label_btns.winfo_children():
            w.destroy()
        guess = record["predicted"] if record["accepted"] else None
        target = record.get("target")
        if target:
            # Practising one spell: just confirm it, or say it wasn't a spell
            choices = [target, NOT_A_SPELL]
            prompt = f"Was that {self._spell_display(target)}?  (required before the next cast)"
        else:
            choices = sorted(self.library.names()) + [NOT_A_SPELL]
            prompt = "What did you cast?  (required before the next cast)"
        for i, name in enumerate(choices):
            if name == NOT_A_SPELL:
                text = "Not a spell"
            elif target:
                text = f"Yes, {self._spell_display(name)}"
            else:
                text = self._spell_display(name)
            btn = tk.Button(self._label_btns, text=text,
                            bg=GOLD_DIM if name == guess else BG3,
                            fg=BG if name == guess else TEXT, bd=0, padx=8, pady=3,
                            font=("Courier New", 8), activebackground=BORDER,
                            command=lambda n=name: self._submit_label(n))
            btn.grid(row=i // 5, column=i % 5, padx=2, pady=2, sticky="ew")
            if name != NOT_A_SPELL:
                btn.bind("<Enter>", lambda e, n=name: self._preview_template(n))
                btn.bind("<Leave>", lambda e: self._preview_template(None))
        tk.Button(self._label_btns, text="Discard", bg=BG3, fg=RED, bd=0,
                  padx=8, pady=3, font=("Courier New", 8), activebackground=BORDER,
                  command=lambda: self._submit_label(None)
                  ).grid(row=len(choices) // 5, column=len(choices) % 5,
                         padx=2, pady=2, sticky="ew")
        self._label_prompt.configure(text=prompt, fg=GOLD)
        self._label_frame.pack(fill="x", padx=8, pady=(4, 0),
                               before=self.canvas.get_tk_widget())

    def _submit_label(self, label: Optional[str]):
        record, self._pending_cast = self._pending_cast, None
        self._label_frame.pack_forget()
        if record is None:
            return
        if label is None:
            self.status_var.set("Cast discarded")
            return
        record["label"] = label
        append_cast(record)
        self._note_cast_size(record)
        self.status_var.set(f"Cast saved as '{label}' — {count_casts()} labelled")

    def _on_label_toggle(self):
        """Turning labelling off drops any pending prompt so casting unblocks."""
        if not self._label_casts.get() and self._pending_cast is not None:
            self._submit_label(None)

    def _on_spell_confirmed(self, spell: str):
        """Handle a confirmed spell cast (from wand firmware or local matcher)."""
        self.ble.trigger_cast_animation(success=True, macro=self.effects.wand_macro(spell))
        self.ble.trigger_box_macro(self.effects.box_macro(spell))
        self.effects.play_sound(spell)
        self.last_spell.set(spell)
        self.spell_history.insert(0, f"{datetime.now().strftime('%H:%M:%S')}  {spell}")
        self._update_history()
        if self.trail_x:
            self.frozen_trail = (list(self.trail_x), list(self.trail_y), spell)
        self._gesture_label.configure(text=f"✦ {spell}", fg=PURPLE)
        self._redraw_trail(frozen=True)

    def _handle_imu_samples(self, samples: list):
        """Feed every sample to the tracker; it grows the trail only while a
        gesture window is open and tracks world-up / gyro bias otherwise."""
        ax, ay, az, gx, gy, gz = samples[0]
        self._imu_label.configure(
            text=f"a=({ax:+.2f} {ay:+.2f} {az:+.2f}) G\n"
                 f"w=({np.degrees(gx):+5.0f} {np.degrees(gy):+5.0f} {np.degrees(gz):+5.0f}) deg/s")

        if self._calibrator is not None:
            for s in samples:
                self._calibrator.feed_sample(*s)

        n_before = len(self.trail_x)
        self._tracker.feed_many(samples)
        if self.gesture_active and len(self.trail_x) != n_before:
            self._redraw_trail()

    def _open_calibrator(self):
        if self._wand_id is None:
            self.status_var.set("Connect a wand before calibrating")
            return
        if self._calibrator is not None:
            self._calibrator.lift()
            return
        self._calibrator = WandCalibrator(self.root, on_saved=self._on_calibration_saved)
        self._calibrator.bind("<Destroy>", lambda e: e.widget is self._calibrator
                              and setattr(self, "_calibrator", None))

    def _on_calibration_saved(self, motion: dict):
        address, name = self._wand_id
        self._profiles.save_motion(address, name, motion)
        self._load_motion_profile(address, name)

    def _load_motion_profile(self, address: str, name: str):
        """Rebuild the tracker from this wand's calibrated tip axis / gyro bias."""
        self._wand_id = (address, name)
        self._profiles.set_last_used(address, name)
        motion = self._profiles.load_motion(address)
        self._tracker = GestureTracker.from_profile(motion)
        self.trail_x, self.trail_y = self._tracker.trail_x, self._tracker.trail_y
        if motion:
            self.status_var.set(f"{name} — motion profile loaded")
        else:
            self.status_var.set(f"{name} — no motion calibration yet (using defaults)")

    def _log_event(self, dec: dict):
        """Append an event to the live log (skips heartbeats and raw IMU)."""
        evt_type = dec.get("type")
        if evt_type in ("heartbeat", "imu"):
            return
        box = self._log_box
        box.configure(state="normal")
        ts    = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        cat   = dec.get("category", "unknown")
        label = dec.get("label") or dec.get("raw", "")
        tag   = cat if cat in STATUS_COLORS else "dim"
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

    # ── Trail rendering ───────────────────────────────────────────────────────

    def _redraw_trail(self, frozen: bool = False):
        ax = self.ax
        ax.cla()
        self._style_ax()

        if frozen and self.frozen_trail:
            xs, ys, spell = self.frozen_trail
        else:
            xs = list(self.trail_x)
            ys = list(self.trail_y)
            spell = None

        target = self._target()
        if len(xs) < 2:
            if target:
                self._draw_target_guide(target, None)
            else:
                self._set_cast_view(None)
            self.canvas.draw_idle()
            return

        xs = np.array(xs, dtype=float)
        ys = np.array(ys, dtype=float)

        # One LineCollection instead of a plot() per segment — trails now hold
        # hundreds of points and redraw on every IMU packet.
        segs = np.stack([np.column_stack([xs[:-1], ys[:-1]]),
                         np.column_stack([xs[1:],  ys[1:]])], axis=1)
        lc = LineCollection(segs, cmap="cool", linewidth=2.0, alpha=0.9,
                            capstyle="round")
        lc.set_array(np.linspace(0, 1, len(segs)))
        ax.add_collection(lc)

        ax.scatter([xs[0]],  [ys[0]],  color=TEXT_DIM, s=25, zorder=5)
        ax.scatter([xs[-1]], [ys[-1]], color=GOLD,     s=45, zorder=6)

        if self.gesture_active:
            # Mid-cast: a steady view sized for a typical cast, instead of
            # zooming in on the first few degrees and rescaling every packet
            self._set_cast_view(np.column_stack([xs, ys]))
        else:
            # Finished trail: fit it with a small margin
            pad = max(abs(xs).max(), abs(ys).max()) * 0.15 or 5
            xc, yc = (xs.max() + xs.min()) / 2, (ys.max() + ys.min()) / 2
            half = max((xs.max() - xs.min()), (ys.max() - ys.min())) / 2 + pad
            ax.set_xlim(xc - half, xc + half)
            ax.set_ylim(yc - half, yc + half)

        if self._overlay and not self.gesture_active:
            self._draw_template_overlay(xs, ys, *self._overlay)
        elif target:
            self._draw_target_guide(target, np.column_stack([xs, ys]))
        elif spell:
            ax.set_title(spell, color=PURPLE, fontsize=10, pad=6, fontfamily="serif")

        self.canvas.draw_idle()

    def _draw_template_overlay(self, xs: np.ndarray, ys: np.ndarray,
                               spell: str, kind: str):
        """Draw a spell's SVG template over the trail, fitted to the trail's
        centroid and larger bounding-box side, so the user can compare shapes.

        kind: "match" (accepted), "guess" (best but rejected), "miss" (target
        spell not accepted), "preview" (hover).
        """
        tmpl = self.library.get(spell)
        if tmpl is None:
            return
        trail = np.column_stack([xs, ys])
        t_span = float(np.ptp(tmpl, axis=0).max()) or 1.0
        scale  = float(np.ptp(trail, axis=0).max()) / t_span
        pts    = (tmpl - tmpl.mean(axis=0)) * scale + trail.mean(axis=0)

        name = self._spell_display(spell)
        title = {"match": f"{name}  (dashed = template)",
                 "guess": f"closest: {name}  — not accepted",
                 "miss":  f"target: {name}  — not accepted",
                 "preview": f"template: {name}"}[kind]
        colour = {"match": PURPLE, "guess": RED, "miss": RED}.get(kind, BLUE_GLOW)
        self._draw_template(pts, colour, title, trail)

    def _set_cast_view(self, trail: Optional[np.ndarray]):
        """Axes for an Any-spell cast: centred on the start (the trail begins
        at 0, 0) and wide enough for a typical cast drawn from any point of
        the shape; it only grows if the trail goes beyond it."""
        half = self._typical_extent()
        if trail is not None and len(trail):
            half = max(half, float(np.abs(trail).max()) * 1.1)
        self.ax.set_xlim(-half, half)
        self.ax.set_ylim(-half, half)

    def _draw_target_guide(self, spell: str, trail: Optional[np.ndarray]):
        """Draw the target spell before/while casting, at the size you
        usually cast it, with its start point where the trail starts (the
        trail begins at 0, 0)."""
        tmpl = self.library.get(spell)
        if tmpl is None:
            return
        span = float(np.ptp(tmpl, axis=0).max()) or 1.0
        pts = (tmpl - tmpl[0]) * (self._typical_extent(spell) / span)
        if trail is not None:
            pts = pts + trail[0]
        self._draw_template(pts, BLUE_GLOW,
                            f"cast {self._spell_display(spell)}  (start at the dot)", trail)

    def _draw_template(self, pts: np.ndarray, colour: str, title: str,
                       trail: Optional[np.ndarray]):
        ax = self.ax
        ax.plot(pts[:, 0], pts[:, 1], color=colour, lw=6, alpha=0.25,
                solid_capstyle="round", zorder=2)
        ax.plot(pts[:, 0], pts[:, 1], color=colour, lw=1.2, ls="--", zorder=3)
        ax.scatter([pts[0, 0]], [pts[0, 1]], color=colour, s=40, marker="o", zorder=4)
        k = min(6, len(pts) - 1)
        ax.annotate("", xy=pts[k], xytext=pts[0], zorder=4,
                    arrowprops=dict(arrowstyle="->", color=colour, lw=1.5))
        ax.set_title(title, color=colour, fontsize=10, pad=6, fontfamily="serif")

        # Make sure the whole template (and trail) is visible
        both = pts if trail is None else np.vstack([pts, trail])
        lo, hi = both.min(axis=0), both.max(axis=0)
        c, half = (lo + hi) / 2, float((hi - lo).max()) / 2 * 1.15 or 5
        ax.set_xlim(c[0] - half, c[0] + half)
        ax.set_ylim(c[1] - half, c[1] + half)

    # ── Typical cast sizes ────────────────────────────────────────────────────
    # How big casts really are (degrees across), learned from labelled casts,
    # so the trail view and the practice guide start at a realistic size.

    def _load_cast_sizes(self):
        self._cast_sizes = {}
        for rec in load_casts():
            self._note_cast_size(rec)

    def _note_cast_size(self, rec: dict):
        if rec.get("label") in (None, NOT_A_SPELL) or len(rec.get("trail", [])) < 2:
            return
        extent = float(np.ptp(np.asarray(rec["trail"], float), axis=0).max())
        if extent >= self.MIN_GESTURE_DEG:          # skip attempts too small to match
            self._cast_sizes.setdefault(rec["label"], []).append(extent)

    def _typical_extent(self, spell: Optional[str] = None) -> float:
        """Median size of past casts of this spell (2+ needed), else of all
        spells (3+ needed), else DEFAULT_CAST_DEG."""
        own = self._cast_sizes.get(spell, []) if spell else []
        if len(own) >= 2:
            return float(np.median(own))
        every = [e for sizes in self._cast_sizes.values() for e in sizes]
        return float(np.median(every)) if len(every) >= 3 else self.DEFAULT_CAST_DEG

    # ── Target spell dropdown ─────────────────────────────────────────────────

    @staticmethod
    def _spell_display(name: str) -> str:
        """Library keys are lower-case file names: 'the cheering charm' → 'The Cheering Charm'."""
        return name.title()

    def _refresh_target_list(self):
        self._target_names = {self._spell_display(n): n for n in sorted(self.library.names())}
        values = [ANY_SPELL] + list(self._target_names)
        self._target_combo["values"] = values
        if self._target_var.get() not in values:
            self._target_var.set(ANY_SPELL)

    def _target(self) -> Optional[str]:
        """Library key of the selected target spell, or None for Any."""
        return self._target_names.get(self._target_var.get())

    def _on_target_changed(self):
        target = self._target()
        if not self.gesture_active:
            self._clear_trail()
        if target:
            self._gesture_label.configure(
                text=f"only {self._spell_display(target)} will be accepted", fg=BLUE_GLOW)
        self._redraw_trail()

    def _preview_template(self, spell: Optional[str]):
        """Hovering a label button previews that spell; leaving restores the match."""
        self._overlay = (spell, "preview") if spell else self._cast_overlay
        self._redraw_trail(frozen=bool(self.frozen_trail))

    def _clear_trail(self):
        self.trail_x.clear()
        self.trail_y.clear()
        self.frozen_trail = None
        self._overlay = self._cast_overlay = None
        self.gesture_active = False
        self._tracker.end()
        self._gesture_label.configure(text="waiting for gesture...", fg=TEXT_DIM)
        self._scores_label.configure(text="—")
        self._redraw_trail()            # empty axes, or the target spell's guide

    def _on_close(self):
        if self._gesture_timer is not None:
            self.root.after_cancel(self._gesture_timer)
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
