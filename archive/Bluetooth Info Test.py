"""
mcw_researcher.py — Magic Caster Wand BLE Research Tool
========================================================
Modes:
  1. listen      — Passive listener on wand only (default)
  2. dual        — Connect to both wand (MCW) and box (MCB) simultaneously
  3. gesture_map — Record gesture windows, correlate with spell names
  4. state_probe — Send specific packets and log response sequences
  5. command     — Send a single hex packet and watch the response

Usage:
  python mcw_researcher.py --mode listen
  python mcw_researcher.py --mode dual
  python mcw_researcher.py --mode gesture_map
  python mcw_researcher.py --mode state_probe
  python mcw_researcher.py --mode command --packet 021006
"""

import asyncio
import argparse
import csv
import json
import signal
import struct
from collections import defaultdict
from datetime import datetime
from bleak import BleakScanner, BleakClient
from bleak.backends.device import BLEDevice
from typing import Optional
from wand import (
    WRITE_UUID, NOTIFY_UUID, BATTERY_UUID,
    find_wand, hw_init, hw_write,
    cmd_changeled, cmd_delay, build_frame, set_all_groups, clear_all,
    buzz_frame, hsv_to_rgb,
)

# Global stop event — set by Ctrl+C, checked by all loops
_stop = asyncio.Event()

# ── Known decoding ─────────────────────────────────────────────────────────────
STATUS_CODES = {
    "1000": ("Idle / Ready",            "state"),
    "1001": ("Button / Motion trigger", "state"),
    "1002": ("Action Ack / End",        "state"),
    "1003": ("Event 3",                 "state"),
    "1006": ("Event 6",                 "state"),
    "1008": ("IMU motion burst start",  "imu"),
    "1009": ("IMU motion sample",       "imu"),
    "100a": ("IMU axis A",              "imu"),
    "100b": ("Gesture window open",     "gesture"),
    "100c": ("Gesture alt C",           "gesture"),
    "100d": ("Gesture alt D",           "gesture"),
    "100e": ("Orientation change",      "imu"),
    "100f": ("Gesture window close",    "gesture"),
}

PROBE_PACKETS = [
    ("021000", "opcode 0x00 — baseline"),
    ("021001", "opcode 0x01 — action start?"),
    ("021002", "opcode 0x02 — known fuzz hit"),
    ("021003", "opcode 0x03 — event 3"),
    ("021004", "opcode 0x04 — unknown"),
    ("021005", "opcode 0x05 — unknown"),
    ("021006", "opcode 0x06 — rare event 6 trigger"),
    ("021007", "opcode 0x07 — unknown"),
    ("021008", "opcode 0x08 — IMU burst trigger?"),
    ("021009", "opcode 0x09 — IMU sample trigger?"),
    ("02100a", "opcode 0x0A — setloops?"),
    ("02100b", "opcode 0x0B — gesture window open?"),
    ("02100c", "opcode 0x0C — gesture alt C?"),
    ("02100d", "opcode 0x0D — gesture alt D?"),
    ("02100e", "opcode 0x0E — orientation?"),
    ("02100f", "opcode 0x0F — gesture window close?"),
    ("0402100300", "4-byte: event 3 + payload 0x00"),
    ("0402100301", "4-byte: event 3 + payload 0x01"),
    ("0402100302", "4-byte: event 3 + payload 0x02"),
    ("021002ff", "opcode 0x02 with 0xFF payload"),
    ("021006ff", "opcode 0x06 with 0xFF payload"),
]

# ── Helpers ────────────────────────────────────────────────────────────────────

def decode_notification(data: bytes) -> dict:
    hex_str = data.hex()
    result = {
        "raw": hex_str, "bytes": list(data),
        "type": "unknown", "code": None,
        "label": None, "category": None, "text": None,
        "imu": None,
    }
    if hex_str == "014001":
        result.update(type="heartbeat", label="Periodic heartbeat", category="system")
        return result
    if data[0] == 0x24:
        try:
            text = data[4:].decode("utf-8")
            result.update(type="spell", label=f'Spell: "{text}"', category="spell", text=text)
        except (UnicodeDecodeError, IndexError):
            result.update(type="spell_raw", label="Spell (decode error)", category="spell")
        return result
    if data[0] == 0x10 and len(data) >= 2:
        code = data[:2].hex()
        label, category = STATUS_CODES.get(code, (f"Unknown 0x{code}", "unknown"))
        result.update(type="status", code=code, label=label, category=category)

        # IMU packets carry additional signed int16 LE samples after the 2-byte code
        if data[1] in (0x08, 0x09, 0x0a) and len(data) > 2:
            payload = data[2:]
            samples = [struct.unpack_from('<h', payload, i)[0]
                       for i in range(0, len(payload) - 1, 2)]
            result["imu"] = samples
            result["label"] = f"{label}  [{', '.join(str(s) for s in samples[:6])}]"
        return result
    return result


def color(text, code):
    colors = {
        "red": "\033[91m", "green": "\033[92m", "yellow": "\033[93m",
        "blue": "\033[94m", "purple": "\033[95m", "cyan": "\033[96m",
        "gray": "\033[90m", "reset": "\033[0m", "bold": "\033[1m",
    }
    return f"{colors.get(code, '')}{text}{colors['reset']}"


category_colors = {
    "state": "green", "imu": "cyan", "gesture": "yellow",
    "spell": "purple", "system": "gray", "heartbeat": "gray", "unknown": "red",
}


def pretty_print(decoded: dict, source: str = "wand"):
    cat   = decoded.get("category", "unknown")
    label = decoded.get("label") or decoded.get("raw")
    raw   = decoded.get("raw", "")
    c     = category_colors.get(cat, "reset")
    ts    = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    src   = color(f"[{source:4s}]", "blue" if source == "wand" else "yellow")
    print(f"  {color(ts, 'gray')}  {src}  {color(f'[{cat:8s}]', c)}  {color(label, c)}  {color(raw, 'gray')}")

# ── Greeting + shutdown ────────────────────────────────────────────────────────

async def wand_hello(client: BleakClient) -> None:
    """Connection greeting — rainbow sweep."""
    print(color("  ✦ Wand connected — playing greeting...", "purple"))
    await hw_init(client)
    steps, step_ms = 12, 80
    for i in range(steps):
        r, g, b = hsv_to_rgb(i / steps)
        frame = build_frame(*[cmd_changeled(grp, r, g, b, step_ms) for grp in range(4)])
        await hw_write(client, bytes([0x60]))
        await hw_write(client, frame)
        await asyncio.sleep(step_ms / 1000)
    clear = build_frame(*[cmd_changeled(grp, 0, 0, 0, 300) for grp in range(4)])
    await hw_write(client, bytes([0x60]))
    await hw_write(client, clear)
    await hw_write(client, bytes([0x40]))
    await asyncio.sleep(0.3)

    # Short buzz
    await hw_write(client, bytes([0x60]))
    await hw_write(client, buzz_frame(100))
    await asyncio.sleep(0.15)
    await hw_write(client, bytes([0x40]))
    await asyncio.sleep(0.25)

    # Long buzz
    await hw_write(client, bytes([0x60]))
    await hw_write(client, buzz_frame(100))
    await asyncio.sleep(0.4)
    await hw_write(client, bytes([0x40]))
    await asyncio.sleep(0.2)

    print(color("  ✦ Ready.\n", "purple"))


async def _wand_shutdown(client: BleakClient) -> None:
    """Clear LEDs and stop motor before disconnecting."""
    try:
        clear = build_frame(*[cmd_changeled(grp, 0, 0, 0, 200) for grp in range(4)])
        await client.write_gatt_char(WRITE_UUID, bytes([0x60]), response=False)
        await client.write_gatt_char(WRITE_UUID, clear, response=False)
        await client.write_gatt_char(WRITE_UUID, bytes([0x40]), response=False)
        await asyncio.sleep(0.2)
    except Exception:
        pass


# ── Device scanning ────────────────────────────────────────────────────────────

async def find_device(name_prefix: str) -> BLEDevice:
    """Scan until a device whose name starts with name_prefix is found."""
    print(color(f"  Scanning for {name_prefix}-* ...", "cyan"))
    found = asyncio.Event()
    target_device: Optional[BLEDevice] = None

    def detection_callback(device, _adv):
        nonlocal target_device
        if device.name and device.name.startswith(name_prefix) and not found.is_set():
            target_device = device
            found.set()

    async with BleakScanner(detection_callback=detection_callback):
        while not found.is_set() and not _stop.is_set():
            try:
                await asyncio.wait_for(found.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                if not _stop.is_set():
                    print(color(f"  {name_prefix} not found — retrying...", "yellow"))
                found.clear()

    if _stop.is_set():
        raise asyncio.CancelledError()

    assert target_device is not None
    print(color(f"  Found: {target_device.name}  ({target_device.address})", "green"))
    return target_device


async def find_both_devices() -> tuple[BLEDevice, Optional[BLEDevice]]:
    """
    Scan for both wand (MCW) and box (MCB) simultaneously.
    Returns (wand, box) — box may be None if not found within timeout.
    """
    print(color("Scanning for MCW and MCB devices...", "cyan"))
    results: dict[str, Optional[BLEDevice]] = {"MCW": None, "MCB": None}
    events = {"MCW": asyncio.Event(), "MCB": asyncio.Event()}

    def detection_callback(device, _adv):
        for prefix in ("MCW", "MCB"):
            if device.name and device.name.startswith(prefix) and not events[prefix].is_set():
                results[prefix] = device
                events[prefix].set()
                print(color(f"  Found: {device.name}  ({device.address})", "green"))

    async with BleakScanner(detection_callback=detection_callback):
        # Wait up to 15s for the wand; box is optional
        try:
            await asyncio.wait_for(events["MCW"].wait(), timeout=15.0)
        except asyncio.TimeoutError:
            print(color("  MCW wand not found — aborting.", "red"))
            raise RuntimeError("Wand not found")

        if not events["MCB"].is_set():
            print(color("  Waiting 5s more for MCB box...", "yellow"))
            try:
                await asyncio.wait_for(events["MCB"].wait(), timeout=5.0)
            except asyncio.TimeoutError:
                print(color("  MCB box not found — continuing with wand only.", "yellow"))

    assert results["MCW"] is not None
    return results["MCW"], results["MCB"]

# ── Mode: dual ─────────────────────────────────────────────────────────────────

async def mode_dual(wand: BLEDevice, box: BLEDevice, log_file: str = "mcw_dual.csv"):
    """
    Connect to wand and box simultaneously. Log all events from both with a
    shared timestamp so you can correlate wand gestures with box responses.
    Spell names should now appear from whichever device does recognition.
    """
    print(color("\n[dual] Connecting to wand + box simultaneously...\n", "bold"))
    rows: list[dict] = []
    stop_event = asyncio.Event()

    def make_handler(source: str):
        def handler(_sender, data):
            decoded = decode_notification(data)
            decoded["source"] = source
            pretty_print(decoded, source=source)
            rows.append({
                "timestamp": datetime.now().isoformat(),
                "source":    source,
                "raw":       decoded["raw"],
                "type":      decoded["type"],
                "category":  decoded["category"],
                "label":     decoded["label"],
                "spell":     decoded.get("text") or "",
            })
            if decoded["type"] == "spell":
                print(color(f"\n  ★ SPELL from {source}: {decoded['text']} ★\n", "purple"))
        return handler

    async def connect_and_listen(device: BLEDevice, source: str):
        max_attempts = 5
        for attempt in range(1, max_attempts + 1):
            try:
                print(color(f"  [{source}] Connecting (attempt {attempt})...", "cyan"))
                async with BleakClient(device, timeout=20.0) as client:
                    print(color(f"  [{source}] Connected.", "green"))
                    await asyncio.sleep(2.0)
                    await client.start_notify(NOTIFY_UUID, make_handler(source))
                    try:
                        await client.start_notify(BATTERY_UUID,
                            lambda _s, d, src=source: print(color(f"  [{src}] Battery: {d[0]}%", "green")))
                    except Exception:
                        pass  # box may not have battery characteristic
                    await stop_event.wait()
                    await client.stop_notify(NOTIFY_UUID)
                break
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(color(f"  [{source}] Error: {e}", "red"))
                if attempt < max_attempts:
                    await asyncio.sleep(min(attempt * 2, 8))

    async def wait_for_stop():
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            stop_event.set()

    print(color("  Listening — Ctrl+C to stop\n", "bold"))
    await asyncio.gather(
        connect_and_listen(wand, "wand"),
        connect_and_listen(box,  "box"),
        wait_for_stop(),
        return_exceptions=True,
    )

    _write_csv(log_file, rows)
    print(color(f"\n  Saved {len(rows)} events → {log_file}", "green"))

    spells = [r for r in rows if r["type"] == "spell"]
    if spells:
        print(color(f"\n  Spells captured ({len(spells)}):", "purple"))
        for s in spells:
            print(f"    {s['timestamp']}  [{s['source']}]  {s['spell']}")
    else:
        print(color("  No spell names captured.", "yellow"))

# ── Mode: spell_capture ────────────────────────────────────────────────────────

async def mode_spell_capture(client: BleakClient, log_file: str = "mcw_spells.json"):
    """
    Focused spell capture mode. Maintains a rolling 30-event buffer.
    When a spell fires, snapshots the buffer as the pre-spell signature.
    Builds a JSON map of spell → [signatures] for pattern analysis.
    Cast each spell multiple times for reliable signatures.
    """
    print(color("\n[spell_capture] Cast spells — each one will be recorded.", "bold"))
    print(color("  Ctrl+C when done. Cast each spell several times for best results.\n", "gray"))

    BUFFER_SIZE  = 30   # events to keep before a spell fires
    TAIL_SIZE    = 8    # events to capture after a spell fires (settling pattern)

    captures: list[dict] = []   # all spell captures this session
    buffer:   list[dict] = []   # rolling pre-spell buffer
    tail_collecting = {"active": False, "spell": "", "tail": [], "pre": []}

    def handler(_sender, data):
        decoded = decode_notification(data)
        pretty_print(decoded)

        # Always feed the rolling buffer (non-spell events only)
        if decoded["type"] != "spell":
            buffer.append(decoded)
            if len(buffer) > BUFFER_SIZE:
                buffer.pop(0)

            # If we're collecting tail events after a spell, gather them
            if tail_collecting["active"]:
                tail_collecting["tail"].append(decoded["raw"])
                if len(tail_collecting["tail"]) >= TAIL_SIZE:
                    _save_capture(tail_collecting, captures, log_file)
                    tail_collecting["active"] = False
                    tail_collecting["tail"] = []

        if decoded["type"] == "spell":
            spell_name = decoded["text"] or "unknown"
            print(color(f"\n  ★ SPELL: {spell_name}  ({len(captures)+1} captured so far) ★\n", "purple"))

            # Snapshot pre-spell buffer
            pre = [e["raw"] for e in buffer]

            # Start collecting tail
            tail_collecting.update(active=True, spell=spell_name, pre=pre, tail=[])

    def _save_capture(tc: dict, caps: list, path: str):
        entry = {
            "spell":     tc["spell"],
            "timestamp": datetime.now().isoformat(),
            "pre_spell": tc["pre"],
            "post_spell": tc["tail"],
            # Key signature: last 10 pre-spell events (most discriminating)
            "signature": tc["pre"][-10:],
        }
        caps.append(entry)
        _flush_spells(caps, path)
        print(color(f"  Saved capture #{len(caps)} for '{tc['spell']}'", "green"))

    await client.start_notify(NOTIFY_UUID, handler)
    await client.start_notify(BATTERY_UUID,
        lambda _s, d: print(color(f"  Battery: {d[0]}%", "green")))
    await _stop.wait()
    await client.stop_notify(NOTIFY_UUID)

    if not captures:
        print(color("\n  No spells captured.", "yellow"))
        return

    # Build summary: spell → common signature patterns
    by_spell: dict = defaultdict(list)
    for c in captures:
        by_spell[c["spell"]].append(c["signature"])

    print(color(f"\n  ── Capture summary ({len(captures)} total) ──", "bold"))
    for spell, sigs in sorted(by_spell.items()):
        print(color(f"\n  {spell}  ({len(sigs)} capture(s))", "purple"))
        # Find the most common trailing events across captures
        if len(sigs) > 1:
            # Count how often each code appears in last 5 events
            from collections import Counter
            tail_counts: Counter = Counter()
            for sig in sigs:
                for code in sig[-5:]:
                    tail_counts[code] += 1
            common = [c for c, n in tail_counts.most_common(5) if n >= len(sigs) * 0.5]
            print(color(f"    Common tail events: {' → '.join(common) or 'none'}", "cyan"))
        for i, sig in enumerate(sigs):
            print(color(f"    [{i+1}] {' → '.join(sig[-8:])}", "gray"))

    _flush_spells(captures, log_file)
    print(color(f"\n  Full data → {log_file}", "green"))


def _flush_spells(captures: list, path: str):
    """Write captures to JSON, grouped by spell."""
    by_spell: dict = defaultdict(list)
    for c in captures:
        by_spell[c["spell"]].append(c)
    with open(path, "w") as f:
        json.dump({"captures": captures, "by_spell": dict(by_spell)}, f, indent=2)


async def _gesture_buzz_sustained(client: BleakClient, stop_event: asyncio.Event) -> None:
    """Buzz continuously until stop_event is set, then send motor stop."""
    frame = buzz_frame(15)
    try:
        while not stop_event.is_set():
            await client.write_gatt_char(WRITE_UUID, bytes([0x60]), response=False)
            await client.write_gatt_char(WRITE_UUID, frame, response=False)
            await asyncio.sleep(0.1)
        await client.write_gatt_char(WRITE_UUID, bytes([0x40]), response=False)
    except Exception:
        pass


# ── Mode: listen ───────────────────────────────────────────────────────────────

async def mode_listen(client: BleakClient, log_file: str = "mcw_listen.csv"):
    print(color("\n[listen] Passive capture — Ctrl+C to stop\n", "bold"))
    rows = []

    def handler(_sender, data):
        decoded = decode_notification(data)
        pretty_print(decoded)
        rows.append({
            "timestamp": datetime.now().isoformat(),
            "raw": decoded["raw"], "type": decoded["type"],
            "category": decoded["category"], "label": decoded["label"],
            "spell": decoded.get("text", ""),
            "imu": json.dumps(decoded["imu"]) if decoded.get("imu") else "",
        })

        code = decoded.get("code")

        # Gesture window open — glow blue
        if code == "100b":
            blue_frame = build_frame(*[cmd_changeled(grp, 0, 0, 255, 2000) for grp in range(4)])
            asyncio.ensure_future(client.write_gatt_char(WRITE_UUID, bytes([0x60]), response=False))
            asyncio.ensure_future(client.write_gatt_char(WRITE_UUID, blue_frame, response=False))

        # Gesture window close or Action Ack/End — clear LEDs
        elif code in ("100f", "1002"):
            clear_frame = build_frame(*[cmd_changeled(grp, 0, 0, 0, 300) for grp in range(4)])
            asyncio.ensure_future(client.write_gatt_char(WRITE_UUID, bytes([0x60]), response=False))
            asyncio.ensure_future(client.write_gatt_char(WRITE_UUID, clear_frame, response=False))
            asyncio.ensure_future(client.write_gatt_char(WRITE_UUID, bytes([0x40]), response=False))

    await client.start_notify(NOTIFY_UUID, handler)
    await client.start_notify(BATTERY_UUID, lambda _s, d: print(color(f"  Battery: {d[0]}%", "green")))
    await _stop.wait()
    await client.stop_notify(NOTIFY_UUID)
    await _wand_shutdown(client)
    _write_csv(log_file, rows)
    print(color(f"\n  Saved {len(rows)} rows → {log_file}", "green"))


# ── Mode: gesture_map ──────────────────────────────────────────────────────────

async def mode_gesture_map(client: BleakClient, log_file: str = "mcw_gesture_map.json"):
    print(color("\n[gesture_map] Cast spells — Ctrl+C when done.\n", "bold"))
    windows, current = [], []
    pending_spell = None

    def handler(_sender, data):
        nonlocal pending_spell, current
        decoded = decode_notification(data)
        pretty_print(decoded)
        if decoded["type"] == "heartbeat":
            if current:
                windows.append({"sequence": [e["raw"] for e in current],
                                 "decoded":  [e["label"] for e in current],
                                 "spell":    pending_spell})
                pending_spell = None
            current = []
            return
        if decoded["type"] == "spell":
            pending_spell = decoded["text"]
            if current:
                windows.append({"sequence": [e["raw"] for e in current],
                                 "decoded":  [e["label"] for e in current],
                                 "spell":    pending_spell})
                pending_spell = None
                current = []
            return
        current.append(decoded)

    await client.start_notify(NOTIFY_UUID, handler)
    await _stop.wait()
    await client.stop_notify(NOTIFY_UUID)

    aggregated: dict = defaultdict(lambda: {"count": 0, "spells": defaultdict(int)})
    for w in windows:
        key = " → ".join(w["sequence"])
        aggregated[key]["count"] += 1
        if w["spell"]:
            aggregated[key]["spells"][w["spell"]] += 1

    summary = sorted(
        [{"sequence": k, "count": v["count"], "spells": dict(v["spells"])}
         for k, v in aggregated.items()], key=lambda x: -x["count"])

    with open(log_file, "w") as f:
        json.dump({"windows": windows, "summary": summary}, f, indent=2)
    print(color(f"\n  {len(windows)} windows → {log_file}", "green"))
    for entry in summary[:10]:
        spell_str = ", ".join(f'{s}×{c}' for s, c in entry["spells"].items()) or "—"
        print(f"    [{entry['count']:3d}×]  {entry['sequence'][:80]}  {color(spell_str, 'purple')}")

# ── Mode: state_probe ──────────────────────────────────────────────────────────

async def mode_state_probe(client: BleakClient, log_file: str = "mcw_probe_results.csv"):
    print(color("\n[state_probe] Probing all opcodes...\n", "bold"))
    results = []
    for hex_pkt, description in PROBE_PACKETS:
        responses, collect = [], [True]

        def handler(_sender, data):
            if collect[0]:
                responses.append(decode_notification(data))

        await client.start_notify(NOTIFY_UUID, handler)
        await asyncio.sleep(0.3)
        try:
            await client.write_gatt_char(WRITE_UUID, bytes.fromhex(hex_pkt))
            print(f"  {color('→', 'blue')} {hex_pkt:20s}  {description}")
        except Exception as e:
            print(color(f"  Write failed: {e}", "red"))
            await client.stop_notify(NOTIFY_UUID)
            continue
        await asyncio.sleep(1.2)
        collect[0] = False
        await client.stop_notify(NOTIFY_UUID)

        response_str = "  ".join(r["raw"] for r in responses)
        spell_found  = next((r["text"] for r in responses if r.get("text")), None)
        print(f"    {color('←', 'purple')} {response_str or '(no response)'}")
        if spell_found:
            print(color(f"    ✦ SPELL: {spell_found}", "purple"))
        results.append({"packet": hex_pkt, "description": description,
                         "responses": response_str,
                         "labels": "  ".join(r["label"] or r["raw"] for r in responses),
                         "spell": spell_found or ""})
        await asyncio.sleep(0.5)

    _write_csv(log_file, results)
    print(color(f"\n  Saved → {log_file}", "green"))


# ── Mode: command ──────────────────────────────────────────────────────────────

async def mode_command(client: BleakClient, packet_hex: str):
    print(color(f"\n[command] Sending {packet_hex}...\n", "bold"))
    responses = []

    def handler(_sender, data):
        decoded = decode_notification(data)
        pretty_print(decoded)
        responses.append(decoded)

    await client.start_notify(NOTIFY_UUID, handler)
    await client.start_notify(BATTERY_UUID, lambda _s, d: print(color(f"  Battery: {d[0]}%", "green")))
    try:
        await client.write_gatt_char(WRITE_UUID, bytes.fromhex(packet_hex))
        print(color(f"  Sent: {packet_hex}", "blue"))
    except Exception as e:
        print(color(f"  Failed: {e}", "red"))
    await asyncio.sleep(3.0)
    await client.stop_notify(NOTIFY_UUID)
    spells = [r["text"] for r in responses if r.get("text")]
    if spells:
        print(color(f"  Spells triggered: {spells}", "purple"))


# ── CSV helper ─────────────────────────────────────────────────────────────────

def _write_csv(path: str, rows: list):
    if not rows:
        return
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

# ── Connection helper ──────────────────────────────────────────────────────────

async def connect_with_retry(device: BLEDevice, args) -> None:
    """Connect to a single device with retry logic, then run the selected mode."""
    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        if _stop.is_set():
            break
        try:
            print(color(f"  Connecting (attempt {attempt}/{max_attempts})...", "cyan"))
            async with BleakClient(device, timeout=20.0) as client:
                print(color(f"  Connected: {client.is_connected}", "green"))
                await asyncio.sleep(2.0)
                await wand_hello(client)
                if args.verbose:
                    print(color("\n  Services:", "gray"))
                    for svc in client.services:
                        for ch in svc.characteristics:
                            print(color(f"    {ch.uuid}  {ch.properties}", "gray"))
                    print()
                await _run_mode(client, args)
                await _wand_shutdown(client)
            break
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(color(f"  Connection error: {e}", "red"))
            if _stop.is_set():
                break
            if attempt < max_attempts:
                wait = min(attempt * 2, 8)
                print(color(f"  Retrying in {wait}s — keep wand awake...", "yellow"))
                await asyncio.sleep(wait)
            else:
                print(color("  All attempts failed.", "red"))
                print(color("  → Remove MCW from Windows Bluetooth settings and re-run.", "yellow"))


async def _run_mode(client: BleakClient, args) -> None:
    if args.mode == "listen":
        await mode_listen(client, log_file=args.output or "mcw_listen.csv")
    elif args.mode == "spell_capture":
        await mode_spell_capture(client, log_file=args.output or "mcw_spells.json")
    elif args.mode == "gesture_map":
        await mode_gesture_map(client, log_file=args.output or "mcw_gesture_map.json")
    elif args.mode == "state_probe":
        await mode_state_probe(client, log_file=args.output or "mcw_probe_results.csv")
    elif args.mode == "command":
        if not args.packet:
            print(color("  --packet is required for command mode", "red"))
            return
        await mode_command(client, args.packet)


# ── Main ───────────────────────────────────────────────────────────────────────

async def main(args):
    # Windows doesn't support loop.add_signal_handler — use call_soon_threadsafe instead
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: loop.call_soon_threadsafe(_stop.set))

    try:
        if args.mode == "dual":
            wand, box = await find_both_devices()
            if box is None:
                print(color("  Box not found — falling back to wand-only listen.", "yellow"))
                await connect_with_retry(wand, args)
            else:
                await mode_dual(wand, box, log_file=args.output or "mcw_dual.csv")
        else:
            wand = await find_device("MCW")
            await connect_with_retry(wand, args)
    except asyncio.CancelledError:
        pass

    if _stop.is_set():
        print(color("\n  Stopped.", "yellow"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MCW BLE Research Tool")
    parser.add_argument("--mode", default="listen",
                        choices=["listen", "dual", "spell_capture", "gesture_map", "state_probe", "command"],
                        help="Operating mode")
    parser.add_argument("--packet",  default=None, help="Hex packet (command mode only)")
    parser.add_argument("--output",  default=None, help="Output file path")
    parser.add_argument("--verbose", action="store_true", help="Print service list on connect")
    cli_args = parser.parse_args()
    try:
        asyncio.run(main(cli_args))
    except KeyboardInterrupt:
        pass   # already handled cleanly inside main
