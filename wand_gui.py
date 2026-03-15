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
import os
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
    spell_success_animation, spell_fail_animation, cmd_delay,
)
from bleak import BleakClient, BleakScanner
from spell_shapes import SpellLibrary
from spell_matcher import SpellMatcher
from wand_calibrator import WandCalibrator, load_calibration
from wand_profiles import WandProfiles
import winsound

# ── Spell-colour table ─────────────────────────────────────────────────────────
# Maps spell name (lower-case) → (R, G, B) accent for the success animation.
# Unlisted spells fall back to the default gold/white in spell_success_animation.
SPELL_COLOURS: dict[str, tuple[int, int, int]] = {
    # ── Core / well-known ─────────────────────────────────────────────────────
    "lumos":                          (255, 255, 180),   # warm white / candlelight
    "nox":                            ( 30,  30,  80),   # deep blue-dark
    "incendio":                       (255,  80,   0),   # orange fire
    "confringo":                      (255,  50,   0),   # deep red-orange
    "expelliarmus":                   (200,   0,   0),   # red
    "protego":                        ( 80, 160, 255),   # shield blue
    "alohomora":                      (255, 215,   0),   # bright gold
    "wingardiumleviosa":              ( 80, 220, 120),   # levitation green
    "reducio":                        ( 60, 200, 255),   # ice blue
    "engorgio":                       (180,  50, 255),   # expanding purple
    "revelio":                        (255, 220,  80),   # reveal amber
    "episkey":                        (  0, 255, 160),   # healing teal
    "immobulus":                      (  0, 180, 255),   # freeze cyan
    "impedimenta":                    (  0, 100, 255),   # slow blue
    "silencio":                       (120,  60, 200),   # silence violet
    "reparo":                         (255, 200,  60),   # repair gold-yellow
    "scourgify":                      (  0, 220, 180),   # clean teal-green
    "orchideous":                     (255,  80, 180),   # flower pink
    "serpensortia":                   ( 50, 180,  50),   # snake green
    "riddikulus":                     (255, 200, 100),   # boggart warm yellow
    "rictusempra":                    (255, 160,  80),   # tickle orange
    "flipendo":                       (160,  80, 255),   # knockback purple
    "diffindo":                       (255,  40,  40),   # cutting red
    "incarcerous":                    (180, 120,  60),   # rope brown-gold
    "evanesco":                       (150, 150, 255),   # vanish lavender
    "colloportus":                    (100, 180, 255),   # lock blue
    "duro":                           (180, 130,  80),   # stone brown
    "bombarda":                       (255, 120,   0),   # explosion orange
    "colovaria":                      (200,   0, 200),   # colour-change magenta
    "melofors":                       (255, 160, 200),   # pumpkin head pink
    # ── New spells added from spells/ folder ──────────────────────────────────
    "araniaxumai":                    ( 80,  40,   0),   # dark brown (spider)
    "arrestomomentum":                (160, 200, 255),   # pale freeze blue
    "beetletobutton":                 (120, 100,  60),   # dull bronze transform
    "cauldrontoguitar":               (200, 140,  60),   # warm wood amber
    "charmtocurereluctantreversers":  (  0, 200, 140),   # healing green-teal
    "cheeringcharm":                  (255, 220,  60),   # sunny yellow
    "cistemaperio":                   (200, 160,  80),   # chest-unlock gold
    "countercurse":                   ( 80, 200,  80),   # counter-magic green
    "depulso":                        (160,  80, 220),   # repulsion purple
    "felifors":                       (255, 140,  40),   # cat-transform amber
    "ferrettofeatherduster":          (180, 160, 120),   # dusty beige
    "ferula":                         (180, 120,  60),   # bandage warm brown
    "finiteincantatum":               (200, 200, 200),   # neutral white-grey
    "homomorphus":                    ( 60, 120,  60),   # creature-green
    "hystrifors":                     (180,  60, 140),   # porcupine-spike magenta
    "locomotorwibbly":                (160, 100, 220),   # jelly-legs purple
    "mimblewimble":                   (100,  40, 160),   # tongue-tie deep purple
    "mousetosnuffbox":                (180, 140,  80),   # antique gold
    "petrifcustotalis":               (200, 200, 220),   # petrification pale grey
    "reparifarge":                    (255, 190,  50),   # untransfiguration gold
    "salviohexia":                    ( 60, 180, 120),   # protection sage green
    "spongify":                       (160, 220, 180),   # soft bouncy mint
    "strigiforma":                    (120,  80,  40),   # owl-transform brown
    "veraverto":                      (100, 200, 160),   # animal-to-goblet teal
    "vermillious":                    (220,  40,  40),   # red sparks
}


async def _lumos_animation(client: BleakClient) -> None:
    """Lumos: flicker → creep from base to tip → tip stays on.

    LED group layout (CORRECTED — tip is group 0, handle is group 3):
      group 0 = tip (top)
      group 1 = upper mid
      group 2 = lower mid
      group 3 = handle (bottom)

    Sequence:
      1. Short buzz                       — haptic cast confirmation
      2. Rapid flicker across all groups  — wand struggling to ignite
      3. Handle→tip cascade light-up      — light travels up the wand
      4. Groups 1-3 fade out              — only the tip remains
      5. Tip stays on permanently         — 65535 ms (wand's max duration cap)
    """
    W   = (255, 255, 200)   # warm candlelight white
    OFF = (0, 0, 0)

    step_ms = 150
    fade_ms = 200

    frame = buzz_frame(
        180,
        # ── Flicker (all groups) ──────────────────────────────────────────────
        cmd_changeled(0, 180, 180, 160, 40),
        cmd_changeled(1, 180, 180, 160, 40),
        cmd_changeled(2, 180, 180, 160, 40),
        cmd_changeled(3, 180, 180, 160, 40),
        cmd_delay(45),

        cmd_changeled(0, *OFF, 30), cmd_changeled(1, *OFF, 30),
        cmd_changeled(2, *OFF, 30), cmd_changeled(3, *OFF, 30),
        cmd_delay(35),

        cmd_changeled(0, 255, 255, 210, 50),
        cmd_changeled(1, 255, 255, 210, 50),
        cmd_changeled(2, 255, 255, 210, 50),
        cmd_changeled(3, 255, 255, 210, 50),
        cmd_delay(55),

        cmd_changeled(0, *OFF, 25), cmd_changeled(1, *OFF, 25),
        cmd_changeled(2, *OFF, 25), cmd_changeled(3, *OFF, 25),
        cmd_delay(30),

        # ── Cascade: handle(3) → lower-mid(2) → upper-mid(1) ─────────────────
        cmd_changeled(3, *W, step_ms), cmd_delay(step_ms),
        cmd_changeled(3, *OFF, fade_ms),

        cmd_changeled(2, *W, step_ms), cmd_delay(step_ms),
        cmd_changeled(2, *OFF, fade_ms),

        cmd_changeled(1, *W, step_ms), cmd_delay(step_ms),
        cmd_changeled(1, *OFF, fade_ms),

        # ── Tip on permanently — pure white at max brightness ─────────────────
        cmd_changeled(0, 255, 255, 255, 65535),
    )

    await client.write_gatt_char(WRITE_UUID, bytes([0x60]), response=False)
    await client.write_gatt_char(WRITE_UUID, frame, response=False)
    # No clear — tip stays lit until Nox or disconnect.


async def _spell_success_with_colour(client: BleakClient, spell_name: str) -> None:
    """Success animation with a spell-specific accent colour.

    Lumos gets its own bespoke animation (_lumos_animation).
    All other spells get: buzz → spell-colour burst → white flash → fade.
    Falls back to gold if the spell has no entry in SPELL_COLOURS.
    """
    if spell_name.lower() == "lumos":
        await _lumos_animation(client)
        return

    r, g, b = SPELL_COLOURS.get(spell_name.lower(), (255, 180, 0))  # default gold

    # ── 1. Buzz ───────────────────────────────────────────────────────────────
    await client.write_gatt_char(WRITE_UUID, bytes([0x60]), response=False)
    await client.write_gatt_char(WRITE_UUID, buzz_frame(200), response=False)
    await asyncio.sleep(0.12)
    await client.write_gatt_char(WRITE_UUID, bytes([0x40]), response=False)
    await asyncio.sleep(0.05)

    # ── 2. Spell-coloured burst ───────────────────────────────────────────────
    frame = build_frame(*[cmd_changeled(grp, r, g, b, 300) for grp in range(4)])
    await client.write_gatt_char(WRITE_UUID, bytes([0x60]), response=False)
    await client.write_gatt_char(WRITE_UUID, frame, response=False)
    await asyncio.sleep(0.35)

    # ── 3. White flash ────────────────────────────────────────────────────────
    frame = build_frame(*[cmd_changeled(grp, 255, 255, 255, 150) for grp in range(4)])
    await client.write_gatt_char(WRITE_UUID, bytes([0x60]), response=False)
    await client.write_gatt_char(WRITE_UUID, frame, response=False)
    await asyncio.sleep(0.2)

    # ── 4. Fade out ───────────────────────────────────────────────────────────
    await client.write_gatt_char(WRITE_UUID, clear_all(), response=False)

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
    """Decode an IMU burst packet from handle 0x0015.

    Burst format:
      [0]      0x2c  burst marker
      [1:3]    sequence number (uint16 LE)
      [3]      0x13  = 19 samples
      then 19 x 12-byte samples:
        [ax:i16][ay:i16][az:i16][gx:i16][gy:i16][gz:i16]

    Returns list of (ax, ay, az) tuples for all samples, or None."""
    if len(data) < 16 or data[0] != 0x2c:
        return None
    try:
        samples = []
        for i in range(19):
            off = 4 + i * 12
            if off + 6 > len(data):
                break
            ax, ay, az = struct.unpack_from('<hhh', data, off)
            samples.append((ax, ay, az))
        return samples if samples else None
    except Exception:
        return None


def decode_notification(data: bytes) -> dict:
    hex_str = data.hex()
    result = {"raw": hex_str, "type": "unknown", "code": None,
               "label": None, "category": "unknown", "text": None, "imu": None}

    if hex_str == "014001":
        result.update(type="heartbeat", label="Heartbeat", category="system")
        return result

    if data[0] == 0x24:
        # Wand broadcasts its own spell name — we ignore it and do our own matching
        result.update(type="gesture_end", label="Gesture ended", category="gesture")
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
    SCAN_TIMEOUT = 6.0

    def __init__(self, msg_queue: queue.Queue):
        self.q = msg_queue
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._client: Optional[BleakClient] = None
        self._stop = False
        self._target_name: Optional[str] = None
        self._target_address: Optional[str] = None
        self._connect_event = asyncio.Event()   # set when a new target is chosen

    def start(self):
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def stop(self):
        """Signal the worker to stop. The loop is stopped by _on_close shutdown."""
        self._stop = True
        self._connect_event_set_threadsafe()

    def _connect_event_set_threadsafe(self):
        """Wake the idle loop from any thread safely."""
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self._connect_event.set)

    def _run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._connect_event = asyncio.Event()   # create in the correct loop
        try:
            self.loop.run_until_complete(self._idle_loop())
        except RuntimeError:
            pass   # loop stopped by _on_close before idle_loop completed — expected

    def scan_for_wands(self, callback):
        """Start a BLE scan in a background thread; call callback(list[(name,addr)])."""
        def _worker():
            async def _scan():
                devices = await BleakScanner.discover(timeout=self.SCAN_TIMEOUT)
                return [(d.name, d.address)
                        for d in devices if d.name and d.name.startswith("MCW")]
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
        """Tell the worker to connect to a specific wand (thread-safe)."""
        self._target_name    = name
        self._target_address = address
        self._connect_event_set_threadsafe()

    async def _idle_loop(self):
        """Wait for a target then connect; reconnect if dropped."""
        while not self._stop:
            # Wait until the GUI picks a wand
            await self._connect_event.wait()
            self._connect_event.clear()
            if self._stop:
                break
            await self._connect_loop()

    async def _connect_loop(self):
        self.q.put({"type": "status_msg",
                    "text": f"Connecting to {self._target_name}…"})
        retry_delay = 2.0
        while not self._stop:
            # If the user picks a different wand mid-retry, restart
            if self._connect_event.is_set():
                self._connect_event.clear()
                self.q.put({"type": "status_msg",
                            "text": f"Switching to {self._target_name}…"})
                retry_delay = 2.0

            try:
                async with BleakClient(self._target_address, timeout=20.0) as client:
                    self._client = client
                    self.q.put({"type": "connected", "name": self._target_name})
                    retry_delay = 2.0
                    await asyncio.sleep(1.5)
                    await hw_init(client)
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
                    await self._welcome(client)   # after IMU is established
                    # Stay connected until dropped or user picks new wand
                    while not self._stop and client.is_connected:
                        if self._connect_event.is_set():
                            break   # new wand chosen — drop this connection
                        await asyncio.sleep(0.5)
                    await client.stop_notify(NOTIFY_UUID)
                self._client = None
                self.q.put({"type": "disconnected"})
                # If a new wand was chosen, hand control back to _idle_loop
                if self._connect_event.is_set():
                    return
                if not self._stop:
                    self.q.put({"type": "status_msg",
                                "text": "Disconnected — reconnecting…"})
                    await asyncio.sleep(1.0)
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
        """Rainbow sweep + immediate buzz on connect. Runs after IMU is ready."""
        steps, step_ms = 12, 80
        for i in range(steps):
            r, g, b = hsv_to_rgb(i / steps)
            if i == 0:
                # First frame — embed buzz so haptic fires instantly with the LEDs
                frame = buzz_frame(
                    120,
                    *[cmd_changeled(g2, r, g, b, step_ms) for g2 in range(4)]
                )
            else:
                frame = build_frame(*[cmd_changeled(g2, r, g, b, step_ms) for g2 in range(4)])
            await client.write_gatt_char(WRITE_UUID, bytes([0x60]), response=False)
            await client.write_gatt_char(WRITE_UUID, frame, response=False)
            await asyncio.sleep(step_ms / 1000)
        await client.write_gatt_char(WRITE_UUID, clear_all(), response=False)

    async def send_blue(self, client):
        # Groups 1-3 only (upper-mid → handle). Group 0 (tip) stays dark
        # until a spell is successfully cast.
        frame = build_frame(*[cmd_changeled(g, 0, 0, 255, 2000) for g in range(1, 4)])
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

    def trigger_success(self, spell_name: str = ""):
        """Fire the success buzz + LED animation, optionally spell-tinted."""
        if self._client and self.loop:
            asyncio.run_coroutine_threadsafe(
                _spell_success_with_colour(self._client, spell_name), self.loop)

    def trigger_fail(self):
        if self._client and self.loop:
            asyncio.run_coroutine_threadsafe(
                spell_fail_animation(self._client), self.loop)


# ── Main GUI ───────────────────────────────────────────────────────────────────

class WandGUI:
    LOG_MAX    = 200
    TRAIL_MAX  = 512

    # ── IMU filtering constants ────────────────────────────────────────────────
    # EMA smoothing factor: 0.0 = frozen, 1.0 = raw (no smoothing).
    # At 0.8, each sample is 80% current reading — direction changes register
    # within 1-2 samples while still smoothing sensor noise.
    IMU_ALPHA     = 0.8
    # Dead-zone: EMA accel below this is treated as stillness (no movement).
    # Raised to 300 to suppress phantom pre-move draws from wrist settling.
    # At ~30 Hz the wand returns several samples before intentional motion
    # begins; this value sits comfortably above that resting noise floor
    # (~50-150 counts) while still being well below a deliberate cast push.
    IMU_DEAD_ZONE = 300
    # Dead-zone hysteresis multiplier.
    # Once the signal drops below IMU_DEAD_ZONE (motion stops), it must rise
    # above IMU_DEAD_ZONE * DEAD_ZONE_HYSTERESIS before drawing resumes.
    # Prevents the trail stuttering on/off at the threshold boundary.
    # 1.5× means: stop drawing at 300, only restart above 450.
    DEAD_ZONE_HYSTERESIS = 1.5
    # Scale: how many position units per raw accel unit per sample.
    # Larger = bigger gestures drawn for the same wand movement.
    ACCEL_SCALE   = 18.0

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("✦ OpenCaster — Magic Wand Monitor")
        self.root.configure(bg=BG)
        self.root.geometry("1280x780")
        self.root.minsize(1100, 680)

        self.q: queue.Queue = queue.Queue()
        self.ble = BLEWorker(self.q)

        self.battery_pct   = tk.StringVar(value="—")
        self.status_var    = tk.StringVar(value="Select a wand and press Connect")
        self.conn_color    = tk.StringVar(value=RED)
        self.last_spell    = tk.StringVar(value="—")
        self.spell_history: list[str] = []

        # Wand selector state
        self._found_wands: dict = {}          # address → name
        self._scanning    = False
        self._wand_var    = tk.StringVar(value="")

        # Gesture trail buffers — X (accel X) and Y (accel Y), matching app's 2D view
        self.trail_x: deque = deque(maxlen=self.TRAIL_MAX)
        self.trail_y: deque = deque(maxlen=self.TRAIL_MAX)
        self.gesture_active = False
        self.frozen_trail: Optional[tuple] = None   # (x, y, spell) after cast

        # Grip / sensor circle state
        self._grip_active   = False          # True while wand is gripped (1008 on)
        self._sensor_level  = 0             # 0-4: how many circles are lit

        # EMA filter state (reset each gesture window)
        self._ema_x: Optional[float] = None
        self._ema_y: Optional[float] = None
        # Position integration state (reset each gesture window)
        self._pos_x: float = 0.0
        self._pos_y: float = 0.0
        # Hysteresis state: True = currently drawing (above threshold),
        # False = waiting for signal to rise above the re-entry threshold.
        # Reset to False at gesture open so we never start mid-dead-zone.
        self._dz_active: bool = False

        # Spell matching
        self._spell_lib     = SpellLibrary("spells")
        self._spell_matcher = SpellMatcher(threshold=0.18)
        self._last_cast_spell: Optional[str] = None
        self._spell_select_var = tk.StringVar(value="— select spell —")

        # Active calibrator window (only one at a time)
        self._calibrator: Optional[WandCalibrator] = None

        # Per-wand profile storage
        self._profiles = WandProfiles()
        self._connected_address: Optional[str] = None
        self._connected_name:    Optional[str] = None

        # Calibration-derived IMU parameters (overrides class constants if loaded)
        self._cal_x_idx:    int   = 0
        self._cal_y_idx:    int   = 2
        self._cal_dead:     float = float(self.IMU_DEAD_ZONE)
        self._cal_scale_x:  float = float(self.ACCEL_SCALE)
        self._cal_scale_y:  float = float(self.ACCEL_SCALE)

        self._apply_calibration()

        # Feedback state — populated after each match, cleared on next gesture
        self._feedback_spell:   Optional[str]   = None
        self._feedback_score:   Optional[float] = None
        self._feedback_matched: Optional[bool]  = None
        self._feedback_trail:   Optional[list]  = None   # normalised trail pts

        FEEDBACK_LOG = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "feedback_log.csv")
        self._feedback_log_path = FEEDBACK_LOG
        if not os.path.isfile(FEEDBACK_LOG):
            with open(FEEDBACK_LOG, "w", encoding="utf-8", newline="") as f:
                import csv
                csv.writer(f).writerow([
                    "timestamp", "matched_spell", "score",
                    "matcher_success", "user_confirmed", "trail_pts"])

        self._build_ui()
        self.ble.start()
        self.root.after(50, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # Auto-connect to the last-used wand shortly after the UI is ready
        self.root.after(600, self._autoconnect_last_wand)

    def _build_ui(self):
        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(self.root, bg=BG, pady=8)
        hdr.pack(fill="x", padx=16, pady=(12, 0))

        tk.Label(hdr, text="✦  OPENCASTER", bg=BG, fg=GOLD,
                 font=("Georgia", 22, "bold")).pack(side="left")
        tk.Label(hdr, text="Magic Wand Monitor", bg=BG, fg=TEXT_DIM,
                 font=("Georgia", 11, "italic")).pack(side="left", padx=(10, 0), pady=(6, 0))

        # ── Right side: battery + conn dot + wand selector ────────────────────
        right_hdr = tk.Frame(hdr, bg=BG)
        right_hdr.pack(side="right")

        # Battery + connection dot
        tk.Label(right_hdr, text="🔋", bg=BG, fg=TEXT_DIM,
                 font=("Segoe UI", 11)).pack(side="left")
        tk.Label(right_hdr, textvariable=self.battery_pct, bg=BG, fg=GREEN,
                 font=("Courier New", 11, "bold")).pack(side="left", padx=(2, 16))
        self._conn_dot = tk.Label(right_hdr, text="⬤", bg=BG, fg=RED,
                                   font=("Segoe UI", 14))
        self._conn_dot.pack(side="left")
        tk.Label(right_hdr, textvariable=self.status_var, bg=BG, fg=TEXT_DIM,
                 font=("Courier New", 10)).pack(side="left", padx=(6, 16))

        # Wand selector: [Scan] [▾ dropdown] [Connect]
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Wand.TCombobox",
                        fieldbackground=BG3, background=BG3,
                        foreground=TEXT, selectbackground=BG3,
                        selectforeground=TEXT, arrowcolor=GOLD_DIM,
                        bordercolor=BORDER, lightcolor=BORDER,
                        darkcolor=BORDER)
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

        tk.Button(right_hdr, text="Calibrate", bg=BG3, fg=BLUE_GLOW, bd=0,
                  padx=10, pady=3, font=("Courier New", 9),
                  activebackground=BORDER,
                  command=self._open_calibrator).pack(side="left", padx=(8, 0))

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
        panel = self._panel(body, 1, "GESTURE TRAIL  (accel X · Z)· Y)")
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

        # ── Feedback buttons (shown after a match attempt) ────────────────────
        self._feedback_frame = tk.Frame(panel, bg=BG2)
        self._feedback_frame.pack(pady=(0, 4))

        tk.Label(self._feedback_frame, text="Was this correct?", bg=BG2,
                 fg=TEXT_DIM, font=("Courier New", 8)).pack(side="left", padx=(0, 8))

        self._confirm_btn = tk.Button(
            self._feedback_frame, text="✓  Yes", bg=BG3, fg=GREEN, bd=0,
            padx=10, pady=3, font=("Courier New", 9, "bold"),
            activebackground=BORDER,
            command=lambda: self._save_feedback(True))
        self._confirm_btn.pack(side="left", padx=3)

        tk.Label(self._feedback_frame,
                 text="= spell identified correctly",
                 bg=BG2, fg=TEXT_DIM, font=("Courier New", 7)).pack(side="left", padx=(0, 12))

        self._deny_btn = tk.Button(
            self._feedback_frame, text="✗  No", bg=BG3, fg=RED, bd=0,
            padx=10, pady=3, font=("Courier New", 9, "bold"),
            activebackground=BORDER,
            command=lambda: self._save_feedback(False))
        self._deny_btn.pack(side="left", padx=3)

        tk.Label(self._feedback_frame,
                 text="= wrong spell / bad draw",
                 bg=BG2, fg=TEXT_DIM, font=("Courier New", 7)).pack(side="left")

        self._feedback_frame.pack_forget()   # hidden until a match runs

    def _style_ax(self, ax=None):
        if ax is None:
            ax = self.ax
        ax.set_facecolor(BG3)
        ax.tick_params(colors=TEXT_DIM, labelsize=6)
        ax.xaxis.label.set_color(TEXT_DIM)
        ax.yaxis.label.set_color(TEXT_DIM)
        ax.set_xlabel("X  (accel)", labelpad=4, fontsize=7)
        ax.set_ylabel("Z  (accel)", labelpad=4, fontsize=7)
        for spine in ax.spines.values():
            spine.set_color(BORDER)

    def _build_status_panel(self, body):
        panel = self._panel(body, 2, "STATUS")

        # ── Grip indicator ────────────────────────────────────────────────────
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

        # ── Four sensor circles ───────────────────────────────────────────────
        tk.Label(panel, text="SENSORS", bg=BG2, fg=GOLD_DIM,
                 font=("Georgia", 7, "bold")).pack(anchor="w", padx=14, pady=(10, 2))

        circles_frame = tk.Frame(panel, bg=BG2)
        circles_frame.pack(fill="x", padx=10, pady=(0, 6))

        self._sensor_canvas = tk.Canvas(circles_frame, bg=BG2, bd=0,
                                         highlightthickness=0, height=52)
        self._sensor_canvas.pack(fill="x")

        # We'll draw the circles after the widget is mapped so we know the width
        self._sensor_circles = []   # canvas item ids
        self._sensor_canvas.bind("<Configure>", self._on_sensor_canvas_resize)

        # ── Last spell big display ────────────────────────────────────────────
        spell_frame = tk.Frame(panel, bg=BG3, pady=12)
        spell_frame.pack(fill="x", padx=10, pady=(8, 0))
        tk.Label(spell_frame, text="LAST SPELL", bg=BG3, fg=GOLD_DIM,
                 font=("Georgia", 7, "bold")).pack()
        tk.Label(spell_frame, textvariable=self.last_spell, bg=BG3, fg=PURPLE,
                 font=("Georgia", 16, "bold"), wraplength=200).pack(pady=(2, 0))

        # ── Spell template preview dropdown ──────────────────────────────────
        tk.Label(panel, text="PREVIEW TEMPLATE", bg=BG2, fg=GOLD_DIM,
                 font=("Georgia", 7, "bold")).pack(anchor="w", padx=14, pady=(10, 2))

        spell_sel_frame = tk.Frame(panel, bg=BG2)
        spell_sel_frame.pack(fill="x", padx=10, pady=(0, 4))

        spell_names = sorted(self._spell_lib.names())
        self._spell_combo = ttk.Combobox(
            spell_sel_frame, textvariable=self._spell_select_var,
            style="Wand.TCombobox", state="readonly",
            font=("Courier New", 9))
        self._spell_combo["values"] = ["— select spell —"] + spell_names
        self._spell_combo.pack(fill="x")
        self._spell_combo.bind("<<ComboboxSelected>>", self._on_spell_selected)

        # ── Spell history list ────────────────────────────────────────────────
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

    def _on_sensor_canvas_resize(self, event):
        """Redraw sensor circles whenever the canvas is resized."""
        self._draw_sensor_circles(self._sensor_level)

    def _draw_sensor_circles(self, level: int):
        """Draw 4 circles; the first `level` are lit, the rest are dim."""
        c = self._sensor_canvas
        c.delete("all")
        self._sensor_circles = []

        w = c.winfo_width()
        if w < 10:
            return  # not yet mapped

        n      = 4
        r      = 18          # radius
        gap    = 10
        total  = n * r * 2 + (n - 1) * gap
        start  = (w - total) // 2
        cy     = 26          # vertical centre

        lit_colors = [GREEN, BLUE_GLOW, GOLD, PURPLE]   # one per circle
        dim_color  = BG3
        dim_outline = BORDER
        lit_outline = BG2

        for i in range(n):
            cx  = start + i * (r * 2 + gap) + r
            x0, y0 = cx - r, cy - r
            x1, y1 = cx + r, cy + r
            lit = i < level
            fill    = lit_colors[i] if lit else dim_color
            outline = lit_outline   if lit else dim_outline
            # Glow halo for lit circles
            if lit:
                hr = r + 4
                c.create_oval(cx - hr, cy - hr, cx + hr, cy + hr,
                              fill="", outline=fill, width=2)
            oid = c.create_oval(x0, y0, x1, y1, fill=fill,
                                outline=outline, width=1)
            self._sensor_circles.append(oid)

    def _set_grip(self, active: bool):
        self._grip_active = active
        if active:
            self._grip_dot.configure(fg=GREEN)
            self._grip_label.configure(text="gripped", fg=GREEN)
        else:
            self._grip_dot.configure(fg=TEXT_DIM)
            self._grip_label.configure(text="not gripped", fg=TEXT_DIM)
            # Also reset circles when grip is released
            self._sensor_level = 0
            self._draw_sensor_circles(0)

    def _set_sensor_level(self, level: int):
        self._sensor_level = max(0, min(4, level))
        self._draw_sensor_circles(self._sensor_level)

    # ── Calibration ────────────────────────────────────────────────────────────

    def _apply_calibration(self):
        """Load calibration.json and apply to IMU drawing parameters."""
        cal = load_calibration()
        if not cal:
            return
        self._apply_calibration_data(cal)

    def _apply_calibration_data(self, cal: dict):
        """Apply a calibration dict to the live IMU drawing parameters.

        Calibration corrects three things:
          1. Axis selection  — which raw axis is horizontal vs vertical
          2. Dead-zone       — derived from non-primary axis noise during casts
          3. Per-axis scale  — so a full-force gesture fills ±5000 on both axes

        Orientation is intentionally NOT corrected here.  A slight casting angle
        should appear as a slight angle in the drawing — the spell matcher already
        handles this via its 8-rotation search.  Correcting orientation here would
        remove meaningful directional information (vertical ≠ horizontal).
        """
        axes     = cal.get("axes", {})
        axis_map = {"ax": 0, "ay": 1, "az": 2}

        # ── 1. Axis selection ─────────────────────────────────────────────────
        horiz = cal.get("horizontal_axis", "ax")
        vert  = cal.get("vertical_axis",   "az")
        self._cal_x_idx = axis_map.get(horiz, 0)
        self._cal_y_idx = axis_map.get(vert,  2)

        # ── 2. Dead-zone ──────────────────────────────────────────────────────
        # Set the dead-zone to 10% of the smaller axis's peak response.
        # Anything below that threshold isn't meaningful casting motion.
        #
        # We use the peak response (half the difference between opposing
        # directions) on each cast axis because that's the actual signal
        # amplitude we're trying to gate.  10% of that is well above resting
        # sensor noise (~50-100 counts) but well below any intentional motion.
        #
        # This value is applied AFTER baseline subtraction, so it is compared
        # against a zero-centred signal — do not derive it from mean_ay
        # (which measures signal magnitude during active motion, not noise).
        responses = []
        if "up" in axes and "down" in axes:
            responses.append(
                abs(axes["up"][f"mean_{vert}"] - axes["down"][f"mean_{vert}"]) / 2)
        if "left" in axes and "right" in axes:
            responses.append(
                abs(axes["left"][f"mean_{horiz}"] - axes["right"][f"mean_{horiz}"]) / 2)
        if responses:
            self._cal_dead = max(min(responses) * 0.10, 300.0)
        else:
            self._cal_dead = float(self.IMU_DEAD_ZONE)

        # ── 3. Per-axis scale ─────────────────────────────────────────────────
        # With direct accel→position (pos += accel * scale each sample),
        # a gesture with mean response R over N_SIM samples fills TARGET_POS.
        # So: scale = TARGET_POS / (R * N_SIM)
        TARGET_POS = 5000.0
        N_SIM      = 100

        def find_scale(response: float) -> float:
            if response < 1.0:
                return float(self.ACCEL_SCALE)
            return TARGET_POS / (response * N_SIM)

        if "up" in axes and "down" in axes:
            vert_resp = abs(axes["up"][f"mean_{vert}"] -
                            axes["down"][f"mean_{vert}"]) / 2
            self._cal_scale_y = find_scale(vert_resp)

        if "left" in axes and "right" in axes:
            horiz_resp = abs(axes["left"][f"mean_{horiz}"] -
                             axes["right"][f"mean_{horiz}"]) / 2
            self._cal_scale_x = find_scale(horiz_resp)



    def _on_calibration_saved(self, cal: dict):
        """Called by WandCalibrator when a calibration is successfully saved."""
        self._apply_calibration_data(cal)
        if self._connected_address and self._connected_name:
            self._profiles.save(
                self._connected_address, self._connected_name, cal)

    def _open_calibrator(self):
        """Open the calibration wizard. Only one instance allowed at a time."""
        if self._calibrator and self._calibrator.winfo_exists():
            self._calibrator.lift()
            return
        self._calibrator = WandCalibrator(
            self.root, on_saved=self._on_calibration_saved)
        self._cal_watch_close()

    def _cal_watch_close(self):
        """Poll until the calibrator closes, then reload calibration."""
        if self._calibrator and self._calibrator.winfo_exists():
            self.root.after(500, self._cal_watch_close)
        else:
            self._apply_calibration()

    def _on_wand_connected(self, name: str, address: str):
        """Called when a wand connects — load its profile or trigger calibration."""
        if not address:
            return
        cal = self._profiles.load(address)
        if cal:
            self._apply_calibration_data(cal)
        else:
            self.root.after(4000, self._prompt_new_wand_calibration)

    def _prompt_new_wand_calibration(self):
        """Show a dialog prompting the user to calibrate a new wand."""
        if not self._connected_address:
            return   # disconnected before we got here
        dialog = tk.Toplevel(self.root)
        dialog.title("New Wand Detected")
        dialog.configure(bg=BG)
        dialog.resizable(False, False)
        dialog.grab_set()

        # Centre over main window
        self.root.update_idletasks()
        px, py = self.root.winfo_x(), self.root.winfo_y()
        dialog.geometry(f"+{px+400}+{py+280}")

        tk.Label(dialog, text="✦  New Wand", bg=BG, fg=GOLD,
                 font=("Georgia", 14, "bold"), pady=12).pack(padx=30)
        tk.Label(dialog,
                 text=f"{self._connected_name}\nhas not been calibrated yet.\n\nCalibrate now for best spell recognition.",
                 bg=BG, fg=TEXT, font=("Georgia", 10),
                 justify="center", pady=4).pack(padx=30)
        tk.Frame(dialog, bg=BORDER, height=1).pack(fill="x", padx=16, pady=8)

        btn_row = tk.Frame(dialog, bg=BG, pady=10)
        btn_row.pack()

        def _do_cal():
            dialog.destroy()
            self._open_calibrator()

        tk.Button(btn_row, text="Calibrate Now", bg=GOLD_DIM, fg=BG, bd=0,
                  padx=14, pady=5, font=("Courier New", 9, "bold"),
                  activebackground=GOLD, command=_do_cal).pack(side="left", padx=6)
        tk.Button(btn_row, text="Later", bg=BG3, fg=TEXT_DIM, bd=0,
                  padx=14, pady=5, font=("Courier New", 9),
                  activebackground=BORDER, command=dialog.destroy).pack(side="left", padx=6)

    # ── Wand selector logic ────────────────────────────────────────────────────

    def _autoconnect_last_wand(self):
        """On startup, silently scan for the last-used wand and connect if found.

        - Reads the last-used wand from wand_profiles.json.
        - Kicks off a background scan (same as pressing Scan).
        - If the wand is found, populates the dropdown and connects automatically.
        - If it's not found (out of range / off), falls back gracefully with a
          status message — the user can still scan and connect manually.
        """
        last = self._profiles.last_used()
        if last is None:
            # No known wands yet — nothing to do
            return

        name = last["name"]
        addr = last["address"]
        self.status_var.set(f"Looking for {name}…")
        self._scan_btn.configure(text="Scanning…", state="disabled", fg=GOLD_DIM)
        self._wand_var.set(f"Looking for {name}…")

        def _on_result(results):
            self._scanning = False
            # Check if the last-used wand showed up in the scan
            found = next(
                ((n, a) for n, a in results if a.upper() == addr.upper()), None)

            # Always populate the dropdown with whatever was found
            for n, a in results:
                self._found_wands[a] = n

            if found:
                found_name, found_addr = found
                labels = [f"{n}  ({a})"
                          for a, n in sorted(self._found_wands.items())]
                self._wand_combo["values"] = labels
                target_label = f"{found_name}  ({found_addr})"
                self._wand_var.set(target_label)
                self._scan_btn.configure(text="Scan", state="normal", fg=TEXT_DIM)
                # Connect directly — no user action needed
                self.root.title(f"✦ OpenCaster — {found_name}")
                self.ble.connect_to(found_name, found_addr)
            else:
                # Wand not in range — reset UI for manual use
                self._scan_btn.configure(text="Scan", state="normal", fg=TEXT_DIM)
                if self._found_wands:
                    labels = [f"{n}  ({a})"
                              for a, n in sorted(self._found_wands.items())]
                    self._wand_combo["values"] = labels
                    self._wand_var.set(labels[0])
                else:
                    self._wand_combo["values"] = ["— no wands found —"]
                    self._wand_var.set("— no wands found —")
                self.status_var.set(f"{name} not found — press Scan to retry")

        self._scanning = True
        self.ble.scan_for_wands(lambda results: self.root.after(0, _on_result, results))

    def _do_scan(self):
        if self._scanning:
            return
        self._scanning = True
        self._scan_btn.configure(text="Scanning…", state="disabled", fg=GOLD_DIM)
        self._wand_combo["values"] = ["Scanning…"]
        self._wand_var.set("Scanning…")
        self.ble.scan_for_wands(lambda results: self.root.after(0, self._on_scan_done, results))

    def _on_scan_done(self, results: list):
        self._scanning = False
        self._scan_btn.configure(text="Scan", state="normal", fg=TEXT_DIM)

        for name, addr in results:
            self._found_wands[addr] = name

        if not self._found_wands:
            self._wand_combo["values"] = ["— no wands found —"]
            self._wand_var.set("— no wands found —")
            return

        labels = [f"{name}  ({addr})"
                  for addr, name in sorted(self._found_wands.items())]
        self._wand_combo["values"] = labels
        self._wand_var.set(labels[0])

    def _do_connect(self):
        label = self._wand_var.get()
        # Find address embedded in the label "MCW-XXXX  (AA:BB:...)"
        for addr, name in self._found_wands.items():
            if addr in label:
                self.root.title(f"✦ OpenCaster — {name}")
                self.ble.connect_to(name, addr)
                return
        self.status_var.set("Select a wand from the dropdown first")

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
            name = msg["name"]
            addr = self.ble._target_address or ""
            self.status_var.set(name)
            self._conn_dot.configure(fg=GREEN)
            self._connected_name    = name
            self._connected_address = addr
            # Stamp this wand as last-used so next launch auto-connects to it.
            # Pass name so a stub entry is created even before calibration.
            if addr:
                self._profiles.set_last_used(addr, name)
            self._on_wand_connected(name, addr)
        elif t == "disconnected":
            self.status_var.set("Disconnected")
            self._conn_dot.configure(fg=RED)
            self._connected_address = None
            self._connected_name    = None
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

        # ── Grip detection ────────────────────────────────────────────────────
        if code == "1008":                      # grip on
            self._set_grip(True)
            self._set_sensor_level(1)
        elif code == "1009":                    # grip deepening
            if self._grip_active:
                self._set_sensor_level(2)
        elif code == "100a":                    # sensor zone 3
            if self._grip_active:
                self._set_sensor_level(3)

        # ── Gesture window open — start collecting trail, glow blue ──────────
        if code == "100b" and not self.gesture_active:
            self.gesture_active = True
            self.trail_x.clear(); self.trail_y.clear()
            self.frozen_trail = None
            self._ema_x = None
            self._ema_y = None
            self._pos_x = 0.0
            self._pos_y = 0.0
            self._dz_active = False   # must cross re-entry threshold before drawing
            # Velocity-zeroing baseline: collect first few IMU samples to
            # measure the steady-state offset before integrating, then subtract
            # it so the trail starts from true zero acceleration.
            self._baseline_buf: list = []
            self._baseline_done: bool = False
            self._baseline_x: float = 0.0
            self._baseline_y: float = 0.0
            self._feedback_frame.pack_forget()
            self._gesture_label.configure(text="● gesture window open", fg=GOLD)
            self._set_sensor_level(4)
            self.ble.trigger_blue()
            # Notify calibrator if open
            if self._calibrator and self._calibrator.winfo_exists():
                self._calibrator.feed_gesture_open()

        # IMU samples arrive on IMU_UUID, handled by _handle_imu

        # Gesture ended — run our own shape matching against all templates
        elif dec.get("type") == "gesture_end":
            self._run_spell_match()

        # Gesture close / ack / idle — clear LEDs, stop trail
        # Only 100f and 1000 are genuine end-of-gesture signals.
        # 1002 fires mid-gesture and must NOT trigger matching.
        if code in ("100f", "1000"):
            if self.gesture_active and not self.frozen_trail:
                # Notify calibrator before spell match consumes the gesture
                if self._calibrator and self._calibrator.winfo_exists():
                    self._calibrator.feed_gesture_close()
                else:
                    self._run_spell_match()
            self.gesture_active = False
            # Some spells (e.g. Lumos) intentionally leave LEDs on after cast.
            # Don't clear if the last matched spell owns the current LED state.
            PERSISTENT_SPELLS = {"lumos"}
            if self._last_cast_spell and self._last_cast_spell.lower() in PERSISTENT_SPELLS:
                pass  # leave LEDs alone — spell animation manages them
            else:
                self.ble.trigger_clear()
            if code == "1000":
                self._set_grip(False)

    def _run_spell_match(self):
        """Match the current trail against every loaded template using match_all().

        match_all() pre-processes the trail once, scores all templates, and
        returns a ranked list sorted by score (best first).  We use the top
        result to decide success/failure and show the next two as hint lines
        in the MissCast display so you can see what the recogniser was closest
        to guessing.
        """
        if not self.trail_x:
            self._gesture_label.configure(text="no trail recorded", fg=TEXT_DIM)
            return

        # Trim trailing stillness: drop the last 5 trail points, which are
        # typically the wrist-settling artifact at gesture close.
        tx = list(self.trail_x)
        ty = list(self.trail_y)
        if len(tx) > 10:
            tx = tx[:-5]
            ty = ty[:-5]

        trail_arr = np.array(list(zip(tx, ty)))

        ranked = self._spell_matcher.match_all(trail_arr, self._spell_lib)
        print(f"  [match] trail pts={len(trail_arr)}  templates={len(ranked)}")
        if ranked:
            top3 = ranked[:3]
            print("  [match] top-3: " +
                  "  |  ".join(f"{r['spell']} {r['score']:.3f}" for r in top3))

        best = ranked[0] if ranked else None

        if self.trail_x:
            self.frozen_trail = (list(self.trail_x), list(self.trail_y),
                                 best["spell"] if best else "?")

        if best and best["success"]:
            spell     = best["spell"].capitalize()
            score_pct = int((1 - best["score"]) * 100)
            self._last_cast_spell = spell
            self.last_spell.set(spell)
            self.spell_history.insert(
                0, f"{datetime.now().strftime('%H:%M:%S')}  ✦ {spell}")
            self._update_history()
            self._gesture_label.configure(
                text=f"✦ {spell}  ✓  {score_pct}%", fg=GREEN)
            self._redraw_trail(frozen=True, success=True)
            self.ble.trigger_success(best["spell"])
            self._play_sound(spell)
        else:
            # Build a hint string from top-3 runner-ups
            if ranked:
                hints = "  ".join(
                    f"{r['spell']} {int((1 - r['score']) * 100)}%"
                    for r in ranked[:3]
                )
                hint_line = f"\n  closest: {hints}"
            else:
                hint_line = ""
            self._gesture_label.configure(
                text=f"✗ MissCast{hint_line}", fg=RED)
            self.last_spell.set("MissCast")
            self.spell_history.insert(
                0, f"{datetime.now().strftime('%H:%M:%S')}  ✗ MissCast")
            self._update_history()
            self._redraw_trail(frozen=True, success=False)
            self.ble.trigger_fail()

        # ── Store feedback state and show buttons ─────────────────────────────
        self._feedback_spell   = best["spell"] if best else None
        self._feedback_score   = best["score"] if best else 1.0
        self._feedback_matched = bool(best and best["success"])
        # Normalise trail for storage — same transform as matcher
        if self.trail_x:
            pts = np.array(list(zip(self.trail_x, self.trail_y)), dtype=float)
            pts = pts - pts.mean(axis=0)
            s = np.abs(pts).max()
            if s > 1e-9:
                pts = pts / s
            self._feedback_trail = pts.tolist()
        self._feedback_frame.pack(pady=(0, 4))

    def _handle_imu(self, data: bytes):
        samples = decode_imu_packet(data)
        if not samples:
            return
        ax, ay, az = samples[0]
        self._imu_label.configure(text=f"ax={ax:6d}  ay={ay:6d}  az={az:6d}")
        # Feed raw samples to calibrator if it's open and collecting
        if self._calibrator and self._calibrator.winfo_exists():
            for sax, say, saz in samples:
                self._calibrator.feed_sample(sax, say, saz)
        if self.gesture_active:
            for ax, ay, az in samples:
                # ── Select axes from calibration ──────────────────────────────
                raw_vals = (float(ax), float(ay), float(az))
                raw_x = raw_vals[self._cal_x_idx]
                raw_y = raw_vals[self._cal_y_idx]

                # ── Velocity-zeroing baseline (first 3 samples) ───────────────
                # Collect the first 3 samples to measure the DC offset before
                # motion begins (gravity component + sensor bias), then subtract
                # it for the rest of the gesture so the trail starts from zero.
                if not self._baseline_done:
                    self._baseline_buf.append((raw_x, raw_y))
                    if len(self._baseline_buf) >= 3:
                        xs = [s[0] for s in self._baseline_buf]
                        ys = [s[1] for s in self._baseline_buf]
                        self._baseline_x = sum(xs) / len(xs)
                        self._baseline_y = sum(ys) / len(ys)
                        self._baseline_done = True
                    continue   # don't add baseline samples to the trail

                # Subtract baseline offset
                raw_x -= self._baseline_x
                raw_y -= self._baseline_y

                # ── EMA smoothing ─────────────────────────────────────────────
                if self._ema_x is None:
                    self._ema_x, self._ema_y = raw_x, raw_y
                else:
                    a = self.IMU_ALPHA
                    self._ema_x = a * raw_x + (1 - a) * self._ema_x
                    self._ema_y = a * raw_y + (1 - a) * self._ema_y

                # ── Dead-zone with hysteresis ─────────────────────────────────
                # Magnitude of smoothed acceleration on the two drawing axes.
                mag = max(abs(self._ema_x), abs(self._ema_y))
                dead    = self._cal_dead
                re_entry = dead * self.DEAD_ZONE_HYSTERESIS

                if self._dz_active:
                    # Currently drawing — stop if signal falls below dead zone
                    if mag < dead:
                        self._dz_active = False
                else:
                    # Currently idle — only start drawing above the re-entry threshold
                    if mag >= re_entry:
                        self._dz_active = True

                if not self._dz_active:
                    continue

                # ── Direct accel → position (no velocity accumulation) ────────
                # Position moves proportionally to current smoothed acceleration.
                # Direction changes register immediately — no old velocity to
                # bleed off before the new direction shows in the trail.
                self._pos_x += self._ema_x * self._cal_scale_x
                self._pos_y += self._ema_y * self._cal_scale_y

                self.trail_x.append(self._pos_x)
                self.trail_y.append(self._pos_y)
            self._redraw_trail()

    def _log_event(self, dec: dict):
        # Skip heartbeats and raw IMU burst packets — noise in the event log
        if dec.get("type") == "heartbeat":
            return
        if dec.get("type") == "unknown" and len(dec.get("raw", "")) > 16:
            return
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

    def _on_spell_selected(self, _event=None):
        name = self._spell_select_var.get()
        if name and name != "— select spell —":
            self._show_spell_template(name)

    def _show_spell_template(self, spell_name: str):
        """Draw the selected spell's SVG template onto the gesture trail plot."""
        template = self._spell_lib.get(spell_name)
        if template is None:
            return

        self.fig.clear()
        self.ax = self.fig.add_subplot(111)
        self._style_ax()
        self.ax.set_xlim(-10000, 10000)
        self.ax.set_ylim(-10000, 10000)

        xs = template[:, 0] * 9000
        ys = template[:, 1] * 9000
        n = len(xs)
        cmap = plt.get_cmap("cool")
        for i in range(n - 1):
            t = i / max(n - 2, 1)
            self.ax.plot(xs[i:i+2], ys[i:i+2], color=cmap(t),
                         linewidth=2.5, alpha=0.9, solid_capstyle="round")
        self.ax.scatter([xs[0]],  [ys[0]],  color=TEXT_DIM, s=30, zorder=5)
        self.ax.scatter([xs[-1]], [ys[-1]], color=GOLD,     s=50, zorder=6)
        self.ax.set_title(f"{spell_name}  (template)", color=GOLD_DIM,
                          fontsize=9, pad=6, fontfamily="serif")
        self._gesture_label.configure(text=f"template: {spell_name}", fg=GOLD_DIM)
        self.canvas.draw_idle()

    def _save_feedback(self, confirmed: bool):
        """Save user feedback on the last match result and hide the buttons."""
        import csv, json
        self._feedback_frame.pack_forget()

        if self._feedback_spell is None:
            return

        row = [
            datetime.now().isoformat(),
            self._feedback_spell,
            round(self._feedback_score, 6) if self._feedback_score is not None else "",
            self._feedback_matched,
            confirmed,
            json.dumps(self._feedback_trail) if self._feedback_trail else "",
        ]

        try:
            with open(self._feedback_log_path, "a", encoding="utf-8", newline="") as f:
                csv.writer(f).writerow(row)
            status = "✓ saved" if confirmed else "✗ saved"
            self._gesture_label.configure(
                text=f"{self._gesture_label.cget('text')}  [{status}]",
                fg=GREEN if confirmed else RED)
        except Exception:
            pass

        # Clear feedback state
        self._feedback_spell   = None
        self._feedback_score   = None
        self._feedback_matched = None
        self._feedback_trail   = None

    def _play_sound(self, spell_name: str):
        """Play sounds/{spell}.wav asynchronously if it exists."""
        path = os.path.join("sounds", f"{spell_name.lower()}.wav")
        if os.path.isfile(path):
            threading.Thread(
                target=winsound.PlaySound,
                args=(path, winsound.SND_FILENAME),
                daemon=True
            ).start()

    # ── 2D trail rendering ─────────────────────────────────────────────────────

    def _redraw_trail(self, frozen=False, success: Optional[bool] = None):
        self.fig.clear()

        if frozen and self.frozen_trail:
            xs, ys, spell = self.frozen_trail
            template = self._spell_lib.get(spell) if spell else None
            self._draw_frozen(xs, ys, spell, template, success)
        else:
            # Live drawing — single full-width subplot
            self.ax = self.fig.add_subplot(111)
            self._style_ax()
            xs = list(self.trail_x)
            ys = list(self.trail_y)
            if len(xs) >= 2:
                self._draw_gradient(self.ax,
                                    np.array(xs, dtype=float),
                                    np.array(ys, dtype=float))
                self.ax.set_xlim(-10000, 10000)
                self.ax.set_ylim(-10000, 10000)
        self.canvas.draw_idle()

    def _draw_gradient(self, ax, xs, ys, alpha=0.9, lw=2.0, color_override=None):
        """Draw a colour-gradient polyline on ax."""
        n = len(xs)
        cmap = plt.get_cmap("cool")
        for i in range(n - 1):
            t = i / max(n - 2, 1)
            c = color_override if color_override else cmap(t)
            ax.plot(xs[i:i+2], ys[i:i+2], color=c, linewidth=lw,
                    alpha=alpha, solid_capstyle='round')
        ax.scatter([xs[0]],  [ys[0]],  color=TEXT_DIM, s=20, zorder=5)
        ax.scatter([xs[-1]], [ys[-1]], color=GOLD,     s=35, zorder=6)

    def _draw_frozen(self, xs_raw, ys_raw, spell, template, success):
        """Single plot: user trail in colour with template overlaid in white below."""
        self.ax = self.fig.add_subplot(111)
        ax = self.ax
        self._style_ax(ax)
        ax.set_xlim(-10000, 10000)
        ax.set_ylim(-10000, 10000)

        # ── Template overlay (drawn first so trail sits on top) ───────────────
        if template is not None:
            tmpl_xs = template[:, 0] * 8000
            tmpl_ys = template[:, 1] * 8000
            ax.plot(tmpl_xs, tmpl_ys,
                    color="white", linewidth=3.0, alpha=0.25,
                    solid_capstyle='round', zorder=1)

        # ── User's normalised trail ───────────────────────────────────────────
        xs = np.array(xs_raw, dtype=float)
        ys = np.array(ys_raw, dtype=float)
        if len(xs) >= 2:
            pts = np.stack([xs, ys], axis=1)
            pts = pts - pts.mean(axis=0)
            s = np.abs(pts).max()
            if s > 1e-9:
                pts /= s
            xs = pts[:, 0] * 8000
            ys = pts[:, 1] * 8000
            self._draw_gradient(ax, xs, ys)

        # ── Title: spell name + result ────────────────────────────────────────
        if spell:
            title_color = GREEN if success else RED
            label = "Expected shape  (white)" if template is not None else ""
            ax.set_title(f"{spell}  |  {label}",
                         color=title_color, fontsize=9,
                         pad=5, fontfamily="serif")

    def _clear_trail(self):
        self.trail_x.clear()
        self.trail_y.clear()
        self.frozen_trail = None
        self.gesture_active = False
        self._gesture_label.configure(text="waiting for gesture...", fg=TEXT_DIM)
        self._feedback_frame.pack_forget()
        self.fig.clear()
        self.ax = self.fig.add_subplot(111)
        self._style_ax()
        self.canvas.draw_idle()

    def _on_close(self):
        """Shut down cleanly: clear LEDs, disconnect BLE, then destroy window."""
        self.status_var.set("Closing…")
        self.root.update_idletasks()

        # Signal the BLE worker to stop reconnecting
        self.ble._stop = True

        # If connected, fire-and-forget a clear + disconnect on the worker loop
        if self.ble._client and self.ble.loop and self.ble.loop.is_running():
            async def _shutdown(client):
                try:
                    await client.write_gatt_char(
                        WRITE_UUID, clear_all(), response=False)
                    await asyncio.sleep(0.2)
                    await client.disconnect()
                except Exception:
                    pass
                finally:
                    self.ble.loop.call_soon_threadsafe(self.ble.loop.stop)

            asyncio.run_coroutine_threadsafe(
                _shutdown(self.ble._client), self.ble.loop)

            # Give it up to 1.5 s to finish, then force-stop regardless
            self.root.after(1500, self._finish_close)
        else:
            if self.ble.loop and self.ble.loop.is_running():
                self.ble.loop.call_soon_threadsafe(self.ble.loop.stop)
            self._finish_close()

    def _finish_close(self):
        try:
            self.root.destroy()
        except Exception:
            pass


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
