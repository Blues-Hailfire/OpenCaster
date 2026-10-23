"""
opencaster.wand.protocol — Magic Caster BLE protocol (pure, no I/O)
====================================================================
UUIDs, opcodes, notification parsing, IMU decoding and LED/haptic frame
builders.  Everything here is a plain function or dataclass, so it can be
unit-tested and reused without a Bluetooth adapter.

Wire facts (see docs/protocol.md):
  - Commands go to WRITE_UUID with write-without-response.
  - Events arrive on NOTIFY_UUID; the first byte is the opcode.
  - Effects are frames: 0x68 followed by commands.  The app writes 0x60
    before each frame; 0x40 clears the LEDs and stops the motor.
"""

import struct
from dataclasses import dataclass
from typing import Optional, Union

# ── UUIDs ──────────────────────────────────────────────────────────────────────
SERVICE_UUID = "57420001-587e-48a0-974c-544d6163c577"
WRITE_UUID   = "57420002-587e-48a0-974c-544d6163c577"
NOTIFY_UUID  = "57420003-587e-48a0-974c-544d6163c577"
BATTERY_UUID = "00002a19-0000-1000-8000-00805f9b34fb"

WAND_PREFIX = "MCW"     # wands advertise as MCW-####
BOX_PREFIX  = "MCB"     # boxes advertise as MCB-####


# ── Opcodes ────────────────────────────────────────────────────────────────────
class Msg:
    """Host → device commands (from the official app's MessageType)."""
    FIRMWARE_VERSION_READ       = 0x00
    CHALLENGE                   = 0x01   # also the keepalive reply
    PAIR_WITH_ME                = 0x03
    BOX_ADDRESS_READ            = 0x09
    WAND_PRODUCT_INFO_READ      = 0x0E
    IMUFLAG_SET                 = 0x30   # + 0x00 0x80 → start IMU streaming
    IMUFLAG_RESET               = 0x31   # stop IMU streaming
    LIGHT_CONTROL_CLEAR_ALL     = 0x40   # LEDs off, motor off
    LIGHT_CONTROL_SET_LED       = 0x42   # + group r g b
    EFFECT_PREFIX               = 0x60   # written before every effect frame
    FRAME_START                 = 0x68
    BUTTON_SET_THRESHOLD        = 0xDC   # + pad_index value
    BUTTON_CALIBRATION_BASELINE = 0xFB   # requires FACTORY_UNLOCK first
    IMU_CALIBRATION             = 0xFC   # requires FACTORY_UNLOCK first
    FACTORY_UNLOCK              = 0xFE   # + 0x55 0xAA


class Resp:
    """Device → host notification opcodes."""
    FIRMWARE_VERSION            = 0x00
    CHALLENGE                   = 0x01   # keepalive: reply with Msg.CHALLENGE or the wand drops
    PONG                        = 0x02
    BOX_ADDRESS                 = 0x09
    WAND_PRODUCT_INFO           = 0x0E
    BUTTON_PAYLOAD              = 0x10   # [0x10][mask] bit0..3 = pads 1..4
    SPELL_CAST                  = 0x24   # [0x24][?][?][len][utf-8 name]
    IMU_PAYLOAD                 = 0x2C   # [0x2C][seq u16][count][12B × count]
    BUTTON_CALIBRATION_BASELINE = 0xFB
    IMU_CALIBRATION             = 0xFC


# Frame command opcodes (MacroFactory.java)
OP_DELAY     = 0x10
OP_CHANGELED = 0x22
OP_BUZZ      = 0x50

IMU_START = bytes([Msg.IMUFLAG_SET, 0x00, 0x80])
IMU_STOP  = bytes([Msg.IMUFLAG_RESET])
PONG      = bytes([Msg.CHALLENGE])
EFFECT_PREFIX = bytes([Msg.EFFECT_PREFIX])
LIGHTS_OFF    = bytes([Msg.LIGHT_CONTROL_CLEAR_ALL])

# Haptic init sequence observed in the app's snoop log; sent once per
# connection, 40 ms apart, or the motor stays silent.
HW_INIT = tuple(bytes(c) for c in (
    [0x00], [0x08], [0x09],
    [0x0e, 0x02], [0x0e, 0x04], [0x0e, 0x08], [0x0e, 0x09], [0x0e, 0x01],
    [0xdd, 0x00], [0xdd, 0x04], [0xdd, 0x01], [0xdd, 0x05],
    [0xdd, 0x02], [0xdd, 0x06], [0xdd, 0x03], [0xdd, 0x07],
    [0xdc, 0x00, 0x07], [0xdc, 0x04, 0x0a], [0xdc, 0x01, 0x07], [0xdc, 0x05, 0x0a],
    [0xdc, 0x02, 0x07], [0xdc, 0x06, 0x0a], [0xdc, 0x03, 0x07], [0xdc, 0x07, 0x0a],
    [0xdd, 0x00], [0xdd, 0x04], [0xdd, 0x01], [0xdd, 0x05],
    [0xdd, 0x02], [0xdd, 0x06], [0xdd, 0x03], [0xdd, 0x07],
))
HW_INIT_GAP_S = 0.04

# IMU scale factors (Android IMUSample.java): 2048 counts/g, 0.0625 deg/s per count
IMU_ACCEL_SCALE = 0.00048828125   # raw int16 → g
IMU_GYRO_SCALE  = 0.0010908308    # raw int16 → rad/s
IMU_SAMPLE_RATE_HZ = 220.0


# ── Notifications ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Buttons:
    """Touch-pad state.  mask bit 0..3 = pads 1..4 (tip to handle)."""
    mask: int

    @property
    def pressed(self) -> tuple:
        return tuple(bool(self.mask & (1 << i)) for i in range(4))

    @property
    def all_held(self) -> bool:
        return (self.mask & 0x0F) == 0x0F


@dataclass(frozen=True)
class SpellCast:
    """The wand firmware recognised a spell on its own."""
    name: str


@dataclass(frozen=True)
class ImuBatch:
    """One IMU packet: samples are (ax, ay, az, gx, gy, gz) in g and rad/s,
    sensor frame, oldest first.  All share one arrival time (220 Hz)."""
    seq: int
    samples: tuple


@dataclass(frozen=True)
class Challenge:
    """Keepalive ping; must be answered with PONG."""


@dataclass(frozen=True)
class Pong:
    pass


@dataclass(frozen=True)
class FirmwareVersion:
    version: str


@dataclass(frozen=True)
class CalibrationDone:
    kind: str           # "button" | "imu"


@dataclass(frozen=True)
class Unknown:
    opcode: Optional[int]
    raw: bytes


Notification = Union[Buttons, SpellCast, ImuBatch, Challenge, Pong,
                     FirmwareVersion, CalibrationDone, Unknown]

_IMU_SAMPLE = struct.Struct("<hhhhhh")


def decode_imu(data: bytes) -> Optional[tuple]:
    """Decode an 0x2C packet → tuple of (ax, ay, az, gx, gy, gz), or None if
    malformed.  Wire order per sample is gyro xyz then accel xyz (int16 LE)."""
    if len(data) < 4 or data[0] != Resp.IMU_PAYLOAD:
        return None
    count = data[3]
    if len(data) < 4 + count * 12 or (len(data) - 4) % 12 != 0:
        return None
    a, g = IMU_ACCEL_SCALE, IMU_GYRO_SCALE
    return tuple((ax * a, ay * a, az * a, gx * g, gy * g, gz * g)
                 for gx, gy, gz, ax, ay, az in _IMU_SAMPLE.iter_unpack(data[4:4 + count * 12]))


def parse_notification(data: bytes) -> Notification:
    """Turn one NOTIFY_UUID packet into a typed event."""
    if not data:
        return Unknown(None, b"")
    op = data[0]
    if op == Resp.IMU_PAYLOAD:
        samples = decode_imu(data)
        if samples is not None:
            return ImuBatch(data[1] | (data[2] << 8), samples)
        return Unknown(op, data)
    if op == Resp.BUTTON_PAYLOAD:
        return Buttons(data[1] if len(data) >= 2 else 0)
    if op == Resp.CHALLENGE:
        return Challenge()
    if op == Resp.PONG:
        return Pong()
    if op == Resp.SPELL_CAST:
        if len(data) >= 5:
            name = data[4:4 + data[3]].decode("utf-8", errors="ignore")
            name = name.strip().replace("\x00", "").replace("_", " ")
            if name:
                return SpellCast(name)
        return Unknown(op, data)
    if op == Resp.FIRMWARE_VERSION:
        return FirmwareVersion(".".join(str(b) for b in data[1:]))
    if op == Resp.BUTTON_CALIBRATION_BASELINE:
        return CalibrationDone("button")
    if op == Resp.IMU_CALIBRATION:
        return CalibrationDone("imu")
    return Unknown(op, data)


def _mac(b: bytes) -> str:
    return ":".join(f"{x:02X}" for x in reversed(b))


_PRODUCT_INFO = {0x01: "info 1", 0x02: "serial", 0x04: "SKU", 0x08: "info 8", 0x09: "info 9"}


def describe(event) -> str:
    """Short human-readable text for a notification (logs and CLIs)."""
    if isinstance(event, Buttons):
        return "pads [" + "".join("#" if b else "." for b in event.pressed) + "]"
    if isinstance(event, SpellCast):
        return f"firmware spell: {event.name}"
    if isinstance(event, ImuBatch):
        return f"IMU #{event.seq} x{len(event.samples)}"
    if isinstance(event, (Challenge, Pong)):
        return "keepalive"
    if isinstance(event, FirmwareVersion):
        return f"firmware v{event.version}"
    if isinstance(event, CalibrationDone):
        return f"{event.kind} calibration done"
    if isinstance(event, Unknown) and event.raw:
        op, body = event.opcode, event.raw[1:]
        if op == 0x08 and len(body) == 6:
            return f"wand address {_mac(body)}"
        if op == Resp.BOX_ADDRESS and len(body) == 6:
            return f"paired box {_mac(body)}"
        if op == Resp.WAND_PRODUCT_INFO and body:
            text = body[1:].decode("ascii", "replace") if body[1:].isascii() else body[1:].hex()
            return f"product {_PRODUCT_INFO.get(body[0], hex(body[0]))}: {text}"
        if op == 0xDD and len(body) == 2:
            return f"pad {body[0]} threshold {body[1]}"
        return f"0x{op:02X} {event.raw.hex()}"
    return str(event)


# ── Frame builders ─────────────────────────────────────────────────────────────

def _u16(ms: int) -> int:
    return min(max(int(ms), 0), 65535)


def changeled(group: int, r: int, g: int, b: int, duration_ms: int) -> bytes:
    """Fade LED group 0..3 (tip → handle) to r, g, b over duration_ms.
    Doesn't block: consecutive changeleds run together."""
    return struct.pack("<BBBBBH", OP_CHANGELED, group, r, g, b, _u16(duration_ms))


def delay(duration_ms: int) -> bytes:
    return struct.pack("<BH", OP_DELAY, _u16(duration_ms))


def buzz(value: int) -> bytes:
    """Haptic command.  The official app sends a duration in ms (≤32767)."""
    return struct.pack("<BH", OP_BUZZ, _u16(value))


def frame(*commands: bytes) -> bytes:
    return bytes([Msg.FRAME_START]) + b"".join(commands)


def all_groups(r: int, g: int, b: int, duration_ms: int, groups=range(4)) -> bytes:
    return frame(*(changeled(grp, r, g, b, duration_ms) for grp in groups))


def hex_to_rgb(color: str) -> tuple:
    h = color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def hue_to_rgb(h: float) -> tuple:
    """Hue 0..1 → fully saturated RGB."""
    h6 = h * 6.0
    i = int(h6)
    f = h6 - i
    q, t = int(255 * (1 - f)), int(255 * f)
    return [(255, t, 0), (q, 255, 0), (0, 255, t), (0, q, 255), (t, 0, 255), (255, 0, q)][i % 6]
