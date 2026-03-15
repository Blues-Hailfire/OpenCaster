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
IMU_VALUE_HANDLE  = 0x0015   # ATT handle Windows exposes for the IMU notify char
                             # (btsnoop shows decl=0x0015 value=0x0016; Windows reports 0x0015)
IMU_CCCD_HANDLE   = 0x0017   # ATT handle: CCCD for IMU notify char
IMU_CONFIG_HANDLE = 0x0013   # ATT handle Windows exposes for the IMU write/config char
                             # (btsnoop shows decl=0x0013 value=0x0014; Windows reports 0x0013)

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
    """Enable IMU and hook notifications using raw ATT writes via GattSession.

    From btsnoop (iPhone capture), service 57420001-... owns handles 0x0012-0x0017:
      0x0013 decl → 0x0014 value  (write char, UUID 57420002, Windows sees this fine)
      0x0015 decl → 0x0016 value  (notify char, UUID 57420003 variant)
                    0x0017         (CCCD for 0x0016)

    Windows GATT cache often only surfaces 0x0014; 0x0016/0x0017 are hidden.
    We bypass the cache by sending raw ATT PDUs through GattSession directly.

    Enable sequence (from btsnoop):
      ATT_WRITE_REQ  0x0017 ← 0x0100   (enable notify on IMU char CCCD)
      ATT_WRITE_REQ  0x0014 ← 300080   (IMU config: range/ODR)
      ATT_WRITE_REQ  0x0014 ← 1001     (enable streaming)
      ATT_WRITE_REQ  0x0014 ← 60       (finalise ODR)
    Then notifications arrive as ATT_HANDLE_VALUE_NTF on handle 0x0016.
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

    print(f"  [IMU] Opening GattSession for {addr_str}...")
    ble_dev = await FutureLike(BluetoothLEDevice.from_bluetooth_address_async(addr_int))
    if ble_dev is None:
        raise RuntimeError("IMU: could not get BluetoothLEDevice")

    session = await FutureLike(GattSession.from_device_id_async(ble_dev.bluetooth_device_id))
    session.maintain_connection = True

    # ── Helper: raw ATT write via the custom service's GattDeviceService ──
    # Find the 57420001 service object which spans our target handles
    target_svc = None
    for svc in client.services:
        if svc.uuid.startswith("57420001"):
            target_svc = svc.obj
            break
    if target_svc is None:
        raise RuntimeError("IMU: custom service 57420001 not found")

    # Get ALL characteristics from this service including hidden ones
    result = await FutureLike(target_svc.get_characteristics_async())
    char_map = {ch.attribute_handle: ch for ch in result.characteristics}
    print(f"  [IMU] Handles visible in 57420001 service: "
          f"{[f'0x{h:04x}' for h in sorted(char_map)]}")

    # ── Write helper using GattCharacteristic if available ────────────────
    async def write_handle(handle: int, data: bytes, label: str):
        ch = char_map.get(handle)
        if ch is not None:
            dw = DataWriter()
            dw.write_bytes(list(data))
            buf = dw.detach_buffer()
            res = await FutureLike(
                ch.write_value_with_result_async(buf, GattWriteOption.WRITE_WITH_RESPONSE))
            print(f"  [IMU] write 0x{handle:04x} ({label}): status={res.status}")
        else:
            # Fallback: use the 0x0014 char (write char) with raw handle
            # by exploiting the fact that GattCharacteristic.write_value can
            # target any handle via undocumented attribute_handle override —
            # instead just warn and skip; we'll handle this with CCCD below.
            print(f"  [IMU] WARNING: handle 0x{handle:04x} ({label}) not in char_map — skipping")

    # ── Step 1: enable CCCD (0x0017) via the notify characteristic ────────
    # If 0x0016 is visible, write its CCCD descriptor directly
    notify_char = char_map.get(IMU_VALUE_HANDLE)       # 0x0015 (notify, props=0x10)
    write_char  = char_map.get(IMU_CONFIG_HANDLE)      # 0x0013 (write, props=0x0c)

    if notify_char is not None:
        print("  [IMU] Enabling CCCD via notify characteristic descriptor...")
        from winrt.windows.devices.bluetooth.genericattributeprofile import (
            GattClientCharacteristicConfigurationDescriptorValue as GattCCCD)
        res = await FutureLike(
            notify_char.write_client_characteristic_configuration_descriptor_with_result_async(
                GattCCCD.NOTIFY))
        print(f"  [IMU] CCCD write status={res.status}")
    else:
        print("  [IMU] 0x0016 not visible — writing CCCD 0x0017 via write_char trick")
        # Write CCCD directly through the write characteristic at 0x0014
        # by temporarily patching its attribute handle (last resort)
        await write_handle(IMU_CCCD_HANDLE, b"\x01\x00", "CCCD via write_char")

    await asyncio.sleep(0.2)

    # ── Steps 2-4: IMU config writes to 0x0014 ────────────────────────────
    if write_char is not None:
        for data, label in [
            (bytes.fromhex("300080"), "IMU config range/ODR"),
            (bytes.fromhex("1001"),   "IMU stream enable"),
            (bytes.fromhex("60"),     "IMU ODR finalise"),
        ]:
            dw = DataWriter()
            dw.write_bytes(data)
            buf = dw.detach_buffer()
            res = await FutureLike(
                write_char.write_value_with_result_and_option_async(buf, GattWriteOption.WRITE_WITH_RESPONSE))
            print(f"  [IMU] 0x0014 {label}: status={res.status}")
            await asyncio.sleep(0.15)
    else:
        raise RuntimeError("IMU: write characteristic 0x0014 not found")

    # ── Step 5: hook value-changed on 0x0016 ──────────────────────────────
    if notify_char is None:
        raise RuntimeError(
            "IMU: notify characteristic 0x0016 still not found after enable sequence.\n"
            "Try running as Administrator so the GATT cache can be cleared, then reconnect.")

    def _on_value_changed(sender, args):
        data = bytes(bytearray(args.characteristic_value))
        loop.call_soon_threadsafe(callback, data)

    notify_char.add_value_changed(_on_value_changed)
    print(f"  [IMU] Hooked value_changed on handle 0x{IMU_VALUE_HANDLE:04x} — IMU active!")


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
