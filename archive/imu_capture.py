"""
imu_capture.py — MCW Wand IMU / Motion Data Capture
=====================================================
Captures the full raw bytes of every BLE notification during gesture windows,
with timestamps precise enough to reconstruct movement timing.

Logs everything to imu_capture.csv for offline analysis, and prints a
live ASCII trail showing the event sequence as you move the wand.

Usage:
  python imu_capture.py
  python imu_capture.py --output my_session.csv
"""

import asyncio
import argparse
import csv
import struct
from datetime import datetime
from bleak import BleakClient
from wand import WRITE_UUID, NOTIFY_UUID, find_wand, hw_init, build_frame, cmd_changeled


# ── Known 2-byte event codes ───────────────────────────────────────────────────
EVENT_CODES = {
    "1000": "idle",
    "1001": "trigger",
    "1002": "ack",
    "1003": "event3",
    "1006": "event6",
    "1008": "imu_burst",
    "1009": "imu_sample",
    "100a": "imu_axis_a",
    "100b": "gesture_open",
    "100c": "gesture_c",
    "100d": "gesture_d",
    "100e": "orient",
    "100f": "gesture_close",
}

# Trail symbols for live display
TRAIL_SYMBOLS = {
    "imu_burst":    "◉",
    "imu_sample":   "·",
    "imu_axis_a":   "→",
    "gesture_open":  "[ ",
    "gesture_close": " ]",
    "orient":       "↻",
    "trigger":      "▲",
    "ack":          "✓",
    "idle":         "○",
    "event3":       "3",
}

def color(text, code):
    codes = {"cyan": "\033[96m", "yellow": "\033[93m", "green": "\033[92m",
             "purple": "\033[95m", "gray": "\033[90m", "red": "\033[91m",
             "bold": "\033[1m", "reset": "\033[0m"}
    return f"{codes.get(code,'')}{text}{codes['reset']}"

def decode_packet(data: bytes) -> dict:
    """
    Fully decode a raw BLE notification packet.
    Returns a dict with all fields we can extract.
    """
    hex_str  = data.hex()
    length   = len(data)
    ts       = datetime.now()

    result = {
        "timestamp":    ts.isoformat(),
        "timestamp_ms": ts.timestamp() * 1000,
        "raw_hex":      hex_str,
        "length":       length,
        "byte0":        f"0x{data[0]:02x}",
        "event_code":   None,
        "event_label":  None,
        "payload_hex":  None,
        "payload_len":  0,
        "type":         "unknown",
        # Parsed fields (filled if format recognised)
        "x": None, "y": None, "z": None,
        "int16_0": None, "int16_1": None, "int16_2": None,
        "spell": None,
    }

    # Heartbeat
    if hex_str == "014001":
        result.update(type="heartbeat", event_label="heartbeat")
        return result

    # Spell name: 24 00 00 <len> <utf-8>
    if data[0] == 0x24:
        try:
            spell = data[4:].decode("utf-8")
            result.update(type="spell", event_label=f"spell:{spell}", spell=spell)
        except Exception:
            result.update(type="spell_raw", event_label="spell_raw")
        return result

    # Standard 2-byte event code
    if data[0] == 0x10 and length == 2:
        label = EVENT_CODES.get(hex_str, f"unknown_{hex_str}")
        result.update(type="event2", event_code=hex_str, event_label=label)
        return result

    # Longer packet starting with 0x10 — this is what we're hunting for
    if data[0] == 0x10 and length > 2:
        code  = hex_str[:4]   # first 2 bytes = event code
        label = EVENT_CODES.get(code, f"unknown_{code}")
        payload = data[2:]
        result.update(
            type="event_extended",
            event_code=code,
            event_label=f"{label}+payload",
            payload_hex=payload.hex(),
            payload_len=len(payload),
        )
        # Try interpreting payload as signed int16 LE values (IMU axes)
        if len(payload) >= 2:
            result["int16_0"] = struct.unpack_from("<h", payload, 0)[0]
        if len(payload) >= 4:
            result["int16_1"] = struct.unpack_from("<h", payload, 2)[0]
        if len(payload) >= 6:
            result["int16_2"] = struct.unpack_from("<h", payload, 4)[0]
            result["x"] = result["int16_0"]
            result["y"] = result["int16_1"]
            result["z"] = result["int16_2"]
        return result

    # Anything else — log it raw
    if length > 2:
        result.update(type="raw_extended", payload_hex=hex_str[2:], payload_len=length - 1)
    return result


CSV_FIELDS = [
    "timestamp", "timestamp_ms", "raw_hex", "length",
    "type", "event_code", "event_label",
    "payload_hex", "payload_len",
    "x", "y", "z", "int16_0", "int16_1", "int16_2",
    "spell",
]

async def run_capture(client: BleakClient, output_file: str):
    print(color("\n[imu_capture] Capturing all BLE notifications with full raw bytes.", "bold"))
    print(color("  Move the wand — gesture windows shown as [ ... ]", "cyan"))
    print(color("  Extended packets (>2 bytes from 0x10) will be flagged with ★\n", "yellow"))
    print(color("  Ctrl+C to stop.\n", "gray"))

    rows = []
    in_gesture = False
    gesture_trail = []
    packet_counts = {}

    csvfile = open(output_file, "w", newline="")
    writer  = csv.DictWriter(csvfile, fieldnames=CSV_FIELDS)
    writer.writeheader()

    def handler(_sender, data: bytes):
        nonlocal in_gesture
        pkt = decode_packet(data)
        rows.append(pkt)

        # Track packet type frequencies
        key = pkt.get("event_label") or pkt["type"]
        packet_counts[key] = packet_counts.get(key, 0) + 1

        # Write to CSV immediately (don't buffer — want data even if Ctrl+C)
        writer.writerow({f: pkt.get(f, "") for f in CSV_FIELDS})
        csvfile.flush()

        label = pkt.get("event_label") or pkt["type"]
        sym   = TRAIL_SYMBOLS.get(label, "?")

        # Flag extended packets loudly
        if pkt["type"] == "event_extended":
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            print(color(f"\n  ★ EXTENDED [{ts}]  {pkt['raw_hex']}  "
                        f"→ {label}  payload={pkt['payload_hex']}"
                        + (f"  xyz=({pkt['x']},{pkt['y']},{pkt['z']})"
                           if pkt['x'] is not None else ""), "yellow"))
            return

        if pkt["type"] == "raw_extended":
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            print(color(f"\n  ★ RAW_EXT  [{ts}]  {pkt['raw_hex']}", "red"))
            return

        if pkt["type"] == "spell":
            print(color(f"\n  ★ SPELL: {pkt['spell']} ★\n", "purple"))
            in_gesture = False
            gesture_trail.clear()
            return

        # Live trail display
        if label == "gesture_open":
            in_gesture = True
            gesture_trail.clear()
            print(color("\n  [", "cyan"), end="", flush=True)
        elif label in ("gesture_close", "ack", "idle"):
            if in_gesture:
                print(color("]", "cyan"), flush=True)
                in_gesture = False
                gesture_trail.clear()
        elif in_gesture:
            gesture_trail.append(sym)
            print(color(sym, "cyan"), end="", flush=True)
        else:
            print(color(sym, "gray"), end="", flush=True)

    await client.start_notify(NOTIFY_UUID, handler)

    stop = asyncio.Event()
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass

    await client.stop_notify(NOTIFY_UUID)
    csvfile.close()

    print(color(f"\n\n  ── Session summary ──", "bold"))
    print(color(f"  {len(rows)} total packets → {output_file}", "green"))
    print(color(f"\n  Packet type counts:", "cyan"))
    for label, count in sorted(packet_counts.items(), key=lambda x: -x[1]):
        print(f"    {count:5d}×  {label}")

    extended = [r for r in rows if r["type"] in ("event_extended", "raw_extended")]
    if extended:
        print(color(f"\n  ★ {len(extended)} extended packets captured — IMU payload data found!", "yellow"))
        print(color("  Check payload_hex / x / y / z columns in the CSV.", "yellow"))
    else:
        print(color("\n  No extended IMU packets found this session.", "gray"))
        print(color("  The wand likely does all gesture recognition onboard.", "gray"))
        print(color("  Try covering all 4 grip sensors and making a spell gesture.", "gray"))


async def main(args):
    wand = await find_wand()
    async with BleakClient(wand, timeout=20.0) as client:
        print(f"  Connected to {wand.name}")
        await asyncio.sleep(2.0)
        await hw_init(client)
        # Brief blue flash so you know it's ready
        frame = build_frame(*[cmd_changeled(g, 0, 0, 255, 300) for g in range(4)])
        await client.write_gatt_char(WRITE_UUID, bytes([0x60]), response=False)
        await client.write_gatt_char(WRITE_UUID, frame, response=False)
        await asyncio.sleep(0.4)
        await client.write_gatt_char(WRITE_UUID,
            build_frame(*[cmd_changeled(g, 0, 0, 0, 200) for g in range(4)]),
            response=False)
        await run_capture(client, args.output)

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="MCW IMU Capture")
    p.add_argument("--output", default="imu_capture.csv")
    asyncio.run(main(p.parse_args()))
