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

# The wand streams 6-axis IMU (accel + gyro) on handle 0x0016 at ~30Hz.
# The characteristic declaration is absent from GATT discovery responses
# (Windows BLE / Bleak never surfaces it), but the hardware responds fine.
# Enable by writing 0x0100 to the CCCD at handle 0x0017, then hook the
# backend notification dispatcher directly.
#
# Packet format (20 bytes):
#   [seq:uint16 LE][?:u8][count:u8][ax:i16][ay:i16][az:i16][gx:i16][gy:i16][gz:i16][?:2]
IMU_VALUE_HANDLE = 0x0016
IMU_CCCD_HANDLE  = 0x0017

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

async def imu_subscribe(client: BleakClient, callback) -> None:
    """Subscribe to the hidden IMU characteristic at handle 0x0016.
    Its characteristic declaration is absent from GATT discovery so Bleak
    never surfaces it — we bypass discovery entirely via WinRT raw APIs.

    Approach:
      1. Get the WinRT GattDeviceService for the custom service (57420001-...)
      2. Ask it for ALL characteristics including undiscovered ones via
         get_characteristics_async() on the raw service object
      3. Find the one at attribute handle 0x0016
      4. Wire up add_value_changed and write the CCCD ourselves
    """
    import asyncio
    from winrt.windows.devices.bluetooth.genericattributeprofile import (
        GattCharacteristicProperties,
        GattClientCharacteristicConfigurationDescriptorValue,
    )
    from bleak.backends.winrt.client import FutureLike

    backend = client._backend
    loop = asyncio.get_running_loop()

    # Walk raw WinRT service objects to find handle 0x0016
    winrt_char = None
    for svc in client.services:
        raw_svc = svc.obj  # GattDeviceService
        result = await FutureLike(raw_svc.get_characteristics_async())
        for ch in result.characteristics:
            if ch.attribute_handle == IMU_VALUE_HANDLE:
                winrt_char = ch
                break
        if winrt_char:
            break

    if winrt_char is None:
        raise RuntimeError(f"IMU characteristic at handle 0x{IMU_VALUE_HANDLE:04x} not found")

    # Register Python callback via WinRT value_changed event
    def handle_value_changed(sender, args):
        data = bytearray(args.characteristic_value)
        loop.call_soon_threadsafe(callback, bytes(data))

    token = winrt_char.add_value_changed(handle_value_changed)
    # Store token so disconnect can clean it up
    backend._notification_callbacks[IMU_VALUE_HANDLE] = token

    # Enable notifications by writing CCCD = 0x0100
    cccd = GattClientCharacteristicConfigurationDescriptorValue.NOTIFY
    from bleak.backends.winrt.client import _ensure_success
    _ensure_success(
        await winrt_char.write_client_characteristic_configuration_descriptor_with_result_async(cccd),
        None,
        f"Could not enable notify on IMU handle 0x{IMU_VALUE_HANDLE:04x}",
    )


async def find_wand(timeout: float = 8.0) -> BLEDevice:
    """Scan for an MCW-* wand and return a fresh BLEDevice.

    Keeps scanning until found. Each scan pass runs for `timeout` seconds.
    Returns a device discovered in the most recent scan pass so the address
    info is never stale when BleakClient goes to connect.
    """
    attempt = 0
    while True:
        attempt += 1
        if attempt == 1:
            print("  Scanning for MCW wand...")
        else:
            print(f"  Scan attempt {attempt}...")

        found: Optional[BLEDevice] = None
        try:
            devices = await BleakScanner.discover(timeout=timeout)
            found = next(
                (d for d in devices if d.name and d.name.startswith("MCW")),
                None,
            )
        except Exception as e:
            print(f"  Scan error: {e}")

        if found:
            print(f"  Found: {found.name} ({found.address})")
            return found

        print("  No MCW wand found — retrying in 2s...")
        await asyncio.sleep(2.0)


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
    """Return a connected BleakClient, retrying up to `attempts` times.
    Caller is responsible for disconnecting when done."""
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            print(f"  Connecting (attempt {attempt}/{attempts})...")
            client = BleakClient(address, timeout=20.0)
            await client.connect()
            if client.is_connected:
                print("  Connected.")
                await asyncio.sleep(1.5)
                return client
            await client.disconnect()
        except Exception as e:
            last_exc = e
            print(f"  Error: {e}")
            if attempt < attempts:
                await asyncio.sleep(min(attempt * 2, 8))
    raise RuntimeError(f"Could not connect to wand after {attempts} attempts") from last_exc
