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

# The wand streams 6-axis IMU (accel + gyro) on NOTIFY_UUID as opcode 0x2C packets.
# Enable by writing IMUFLAG_RESET (0x31) then IMUFLAG_SET (0x30 0x00 0x80) to WRITE_UUID.
# See imu_subscribe() below.
#
# IMU packet format (opcode 0x2C):
#   [2C][idx_lo][idx_hi][sample_count][12B × sample_count]
#   Each sample: gyroX gyroY gyroZ accelX accelY accelZ  (all int16 LE)
#   Scale: accel × IMU_ACCEL_SCALE → G-forces,  gyro × IMU_GYRO_SCALE → rad/s
#
# Physical sensor orientation: mounted at 90° rotation on the PCB.
# Correct axis mapping for gesture drawing:
#   accel (ax=ay, ay=-ax, az=az)   gyro (gx=gy, gy=-gx, gz=gz)

# ── Message / Response opcodes (from mcw_ble.py / APK reverse engineering) ─────
class MSG:
    FIRMWARE_VERSION_READ       = 0x00
    CHALLENGE                   = 0x01
    PAIR_WITH_ME                = 0x03
    BOX_ADDRESS_READ            = 0x09
    WAND_PRODUCT_INFO_READ      = 0x0E
    IMUFLAG_SET                 = 0x30   # args: 0x00 0x80 → start IMU streaming
    IMUFLAG_RESET               = 0x31   # stop IMU streaming
    LIGHT_CONTROL_CLEAR_ALL     = 0x40
    LIGHT_CONTROL_SET_LED       = 0x42   # args: group r g b
    BUTTON_SET_THRESHOLD        = 0xDC   # args: pad_index value
    BUTTON_CALIBRATION_BASELINE = 0xFB   # requires FACTORY_UNLOCK first
    IMU_CALIBRATION             = 0xFC   # requires FACTORY_UNLOCK first
    FACTORY_UNLOCK              = 0xFE   # args: 0x55 0xAA

class RESP:
    FIRMWARE_VERSION            = 0x00
    CHALLENGE                   = 0x01   # keepalive ping — fires periodically
    PONG                        = 0x02
    BOX_ADDRESS                 = 0x09
    WAND_PRODUCT_INFO           = 0x0E
    BUTTON_PAYLOAD              = 0x10   # second byte = bitmask (bit0=btn1 … bit3=btn4)
    SPELL_CAST                  = 0x24   # [0x24][?][?][len][utf-8 name]
    IMU_PAYLOAD                 = 0x2C   # [0x2C][idx_lo][idx_hi][count][12B×count]
    BUTTON_CALIBRATION_BASELINE = 0xFB
    IMU_CALIBRATION             = 0xFC

# Button bitmask helpers
BUTTON_BITS = {"button_1": 0x01, "button_2": 0x02, "button_3": 0x04, "button_4": 0x08}

def decode_button_mask(mask: int) -> dict:
    """Return per-button state dict from a BUTTON_PAYLOAD second byte."""
    states = {name: bool(mask & bit) for name, bit in BUTTON_BITS.items()}
    states["button_all"] = (mask & 0x0F) == 0x0F
    return states

# IMU scale factors (from Android IMUSample.java)
IMU_ACCEL_SCALE = 0.00048828125   # raw int16 → G-forces
IMU_GYRO_SCALE  = 0.0010908308    # raw int16 → rad/s

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

def clear_gatt_cache(address: str) -> bool:
    """Delete the Windows BLE GATT cache for this device so the next
    connection does a fresh service discovery instead of using stale data.

    The cache lives at:
      HKLM\\SYSTEM\\CurrentControlSet\\Services\\BthLEEnum\\Parameters\\Devices\\<addr>
    Deleting the key forces Windows to re-enumerate all GATT services.
    Returns True if the key was found and deleted, False otherwise.
    Requires admin rights — fails silently if not elevated.
    """
    import winreg, re
    # Normalise address: "E0:62:21:56:7D:FE" → "e0622156 7dfe" style keys vary;
    # Windows stores them as hex without separators, upper-case.
    addr_clean = address.replace(":", "").upper()

    base = r"SYSTEM\CurrentControlSet\Services\BthLEEnum\Parameters\Devices"
    try:
        root = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base, 0,
                              winreg.KEY_READ | winreg.KEY_WRITE)
    except OSError:
        return False

    try:
        i = 0
        while True:
            subkey_name = winreg.EnumKey(root, i)
            if addr_clean in subkey_name.upper().replace("_", ""):
                winreg.DeleteKey(root, subkey_name)
                winreg.CloseKey(root)
                return True
            i += 1
    except OSError:
        pass
    winreg.CloseKey(root)
    return False


async def imu_subscribe(client: BleakClient, callback) -> None:
    """Enable IMU streaming and subscribe to notifications.

    Protocol (confirmed via mcw_ble.py cross-platform implementation):
      1. Subscribe to NOTIFY_UUID (57420003) — this is where IMU packets arrive
         as opcode 0x2C payloads, same channel as button/spell notifications.
      2. Write IMUFLAG_RESET (0x31) to stop any existing stream.
      3. Write IMUFLAG_SET (0x30 0x00 0x80) to start streaming.

    The old approach used raw ATT handle writes (GattSession / WinRT) derived
    from a btsnoop capture without understanding the command layer. That sequence
    (300080 → 1001 → 60) was partially correct but fragile and Windows-only.
    The correct commands are just two writes to the standard write characteristic.

    IMU packets arrive on NOTIFY_UUID with opcode 0x2C:
      [0x2C][idx_lo][idx_hi][sample_count][12 bytes × sample_count]
    Each sample: gyroX gyroY gyroZ accelX accelY accelZ (all int16 LE)
    Scale: accel × 0.00048828125 → G,  gyro × 0.0010908308 → rad/s

    NOTE: The sensor is physically mounted at 90° rotation. To get correct
    orientation for gesture drawing, remap axes before processing:
      accel: (ax=ay, ay=-ax, az=az)   gyro: (gx=gy, gy=-gx, gz=gz)
    """
    import ctypes
    from winrt.windows.devices.bluetooth import BluetoothLEDevice
    from winrt.windows.devices.bluetooth.genericattributeprofile import (
        GattSession, GattSessionStatus,
        GattWriteOption,
    )
    from winrt.windows.storage.streams import DataWriter, DataReader
    from bleak.backends.winrt.client import FutureLike

    loop = asyncio.get_running_loop()

    # ── Get the raw BluetoothLEDevice address (uint64) ────────────────────
    # Bleak stores it on the backend as _address_bytes or similar; safest to
    # parse from the string address we already know.
    addr_str = client.address  # "E0:62:21:56:7D:FE"
    addr_int = int(addr_str.replace(":", ""), 16)

    print(f"  [IMU] Subscribing to NOTIFY_UUID for IMU packets...")
    await client.start_notify(NOTIFY_UUID, lambda _s, d: callback(bytes(d)))
    await asyncio.sleep(0.1)

    # Reset any existing stream, then start fresh
    print("  [IMU] Sending IMUFLAG_RESET (0x31)...")
    await client.write_gatt_char(WRITE_UUID, struct.pack('B', MSG.IMUFLAG_RESET), response=False)
    await asyncio.sleep(0.1)

    print("  [IMU] Sending IMUFLAG_SET (0x30 0x00 0x80)...")
    await client.write_gatt_char(WRITE_UUID, struct.pack('BBB', MSG.IMUFLAG_SET, 0x00, 0x80), response=False)
    print("  [IMU] IMU streaming active — packets arrive as opcode 0x2C on NOTIFY_UUID")

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
            cleared = clear_gatt_cache(found.address)
            if cleared:
                print("  GATT cache cleared — fresh service discovery on next connect.")
            return found

        print("  No MCW wand found — retrying in 2s...")
        await asyncio.sleep(2.0)


async def spell_success_animation(client: BleakClient) -> None:
    """Buzz + gold pulse → white flash → fade: plays on successful spell cast.

    Sequence:
      1. Short sharp buzz  (haptic confirmation)
      2. Gold burst across all LED groups
      3. Wait for gold to register
      4. White flash
      5. Fade to off
    """
    # ── 1. Haptic: short buzz ──────────────────────────────────────────────────
    await client.write_gatt_char(WRITE_UUID, bytes([0x60]), response=False)
    await client.write_gatt_char(WRITE_UUID, buzz_frame(200), response=False)
    await asyncio.sleep(0.12)
    await client.write_gatt_char(WRITE_UUID, bytes([0x40]), response=False)
    await asyncio.sleep(0.05)

    # ── 2. Gold burst ──────────────────────────────────────────────────────────
    frame = build_frame(*[cmd_changeled(g, 255, 180, 0, 300) for g in range(4)])
    await client.write_gatt_char(WRITE_UUID, bytes([0x60]), response=False)
    await client.write_gatt_char(WRITE_UUID, frame, response=False)
    await asyncio.sleep(0.35)

    # ── 3. White flash ─────────────────────────────────────────────────────────
    frame = build_frame(*[cmd_changeled(g, 255, 255, 255, 150) for g in range(4)])
    await client.write_gatt_char(WRITE_UUID, bytes([0x60]), response=False)
    await client.write_gatt_char(WRITE_UUID, frame, response=False)
    await asyncio.sleep(0.2)

    # ── 4. Fade out ────────────────────────────────────────────────────────────
    await client.write_gatt_char(WRITE_UUID, clear_all(), response=False)


async def spell_fail_animation(client: BleakClient) -> None:
    """Brief very dim red flash, no buzz: unrecognised cast.

    Silent and subtle — just a faint red wash so the user knows
    the gesture registered, with no haptic weight at all.
    """
    # Dim red flash on groups 1-3 (not tip), low brightness
    frame = build_frame(*[cmd_changeled(g, 45, 0, 0, 150) for g in range(1, 4)])
    await client.write_gatt_char(WRITE_UUID, bytes([0x60]), response=False)
    await client.write_gatt_char(WRITE_UUID, frame, response=False)
    await asyncio.sleep(0.18)
    await client.write_gatt_char(WRITE_UUID, clear_all(), response=False)


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
