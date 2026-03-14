"""
wand.py — Shared MCW wand protocol helpers
===========================================
Import this in any script rather than duplicating code.

Provides:
  - UUIDs
  - BLE frame builders (LED + haptic)
  - find_wand() scanner
  - hw_init() haptic init sequence
"""

import asyncio
import struct
from bleak import BleakScanner, BleakClient
from bleak.backends.device import BLEDevice
from typing import Optional

# ── UUIDs ──────────────────────────────────────────────────────────────────────
WRITE_UUID   = "57420002-587e-48a0-974c-544d6163c577"
NOTIFY_UUID  = "57420003-587e-48a0-974c-544d6163c577"
BATTERY_UUID = "00002a19-0000-1000-8000-00805f9b34fb"

# ── Frame opcodes ──────────────────────────────────────────────────────────────
FRAME_START  = 0x68
OP_CHANGELED = 0x22
OP_DELAY     = 0x10


# ── LED frame builders ─────────────────────────────────────────────────────────

def cmd_changeled(group: int, r: int, g: int, b: int, duration_ms: int) -> bytes:
    dur = min(max(duration_ms, 0), 65535)
    return struct.pack("<BBBBBH", OP_CHANGELED, group, r, g, b, dur)

def cmd_delay(duration_ms: int) -> bytes:
    dur = min(max(duration_ms, 0), 65535)
    return struct.pack("<BH", OP_DELAY, dur)

def build_frame(*commands: bytes) -> bytes:
    return bytes([FRAME_START]) + b"".join(commands)

def set_all_groups(r: int, g: int, b: int, duration_ms: int) -> bytes:
    return build_frame(*[cmd_changeled(grp, r, g, b, duration_ms) for grp in range(4)])

def set_group(group: int, r: int, g: int, b: int, duration_ms: int) -> bytes:
    return build_frame(cmd_changeled(group, r, g, b, duration_ms))

def set_groups_dict(colors: dict, duration_ms: int) -> bytes:
    """colors = {group_int: (r, g, b)}"""
    return build_frame(*[cmd_changeled(grp, *rgb, duration_ms) for grp, rgb in sorted(colors.items())])

def clear_all() -> bytes:
    return set_all_groups(0, 0, 0, 500)

def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#").lower()
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

def hsv_to_rgb(h: float) -> tuple[int, int, int]:
    """Hue 0.0–1.0 → RGB at full saturation and value."""
    h6 = h * 6.0
    i  = int(h6)
    f  = h6 - i
    q, t = int(255 * (1 - f)), int(255 * f)
    return [(255,t,0),(q,255,0),(0,255,t),(0,q,255),(t,0,255),(255,0,q)][i % 6]


# ── Haptic frame builders ──────────────────────────────────────────────────────

def buzz_frame(intensity: int, *cmds: bytes) -> bytes:
    """0x68 frame with haptic intensity prefix (0x50 + LE uint16)."""
    return bytes([FRAME_START, 0x50]) + struct.pack("<H", min(intensity, 65535)) + b"".join(cmds)


# ── BLE helpers ────────────────────────────────────────────────────────────────

async def find_wand() -> BLEDevice:
    """Scan until an MCW-* wand is found, then return it."""
    print("  Scanning for MCW wand...")
    found = asyncio.Event()
    target: Optional[BLEDevice] = None

    def cb(device, _adv):
        nonlocal target
        if device.name and device.name.startswith("MCW") and not found.is_set():
            target = device
            found.set()

    async with BleakScanner(detection_callback=cb):
        while not found.is_set():
            try:
                await asyncio.wait_for(found.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                print("  Not found — retrying...")
                found.clear()

    assert target is not None
    print(f"  Found: {target.name} ({target.address})")
    return target


async def hw_write(client: BleakClient, data: bytes) -> None:
    await client.write_gatt_char(WRITE_UUID, data, response=False)
    await asyncio.sleep(0.04)

async def hw_init(client: BleakClient) -> None:
    """One-time haptic init sequence (from snoop log). Call once per connection."""
    cmds = [
        bytes([0x00]), bytes([0x08]), bytes([0x09]),
        bytes([0x0e,0x02]), bytes([0x0e,0x04]), bytes([0x0e,0x08]),
        bytes([0x0e,0x09]), bytes([0x0e,0x01]),
        bytes([0xdd,0x00]), bytes([0xdd,0x04]), bytes([0xdd,0x01]), bytes([0xdd,0x05]),
        bytes([0xdd,0x02]), bytes([0xdd,0x06]), bytes([0xdd,0x03]), bytes([0xdd,0x07]),
        bytes([0xdc,0x00,0x07]), bytes([0xdc,0x04,0x0a]),
        bytes([0xdc,0x01,0x07]), bytes([0xdc,0x05,0x0a]),
        bytes([0xdc,0x02,0x07]), bytes([0xdc,0x06,0x0a]),
        bytes([0xdc,0x03,0x07]), bytes([0xdc,0x07,0x0a]),
        bytes([0xdd,0x00]), bytes([0xdd,0x04]), bytes([0xdd,0x01]), bytes([0xdd,0x05]),
        bytes([0xdd,0x02]), bytes([0xdd,0x06]), bytes([0xdd,0x03]), bytes([0xdd,0x07]),
    ]
    for cmd in cmds:
        await hw_write(client, cmd)
    await asyncio.sleep(0.1)

async def connect_with_retry(address: str, attempts: int = 5) -> BleakClient:
    """Return a connected BleakClient, retrying up to `attempts` times."""
    for attempt in range(1, attempts + 1):
        try:
            print(f"  Connecting (attempt {attempt}/{attempts})...")
            client = BleakClient(address, timeout=20.0)
            await client.connect()
            if client.is_connected:
                print("  Connected.")
                await asyncio.sleep(2.0)
                return client
        except Exception as e:
            print(f"  Error: {e}")
            if attempt < attempts:
                await asyncio.sleep(min(attempt * 2, 8))
    raise RuntimeError("Could not connect to wand")
