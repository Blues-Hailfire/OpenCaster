"""
led_probe.py — Brute-force LED packet structure finder
=======================================================
The wand accepted our packets (1002 ack) but LEDs didn't change,
meaning the opcode is right but the payload structure is wrong.

This script tries every plausible byte layout for changeled and
logs which ones produce different responses — particularly looking
for any response other than the standard idle 1000/1002 pattern.

Usage:
  python led_probe.py
"""

import asyncio
import struct
from bleak import BleakScanner, BleakClient
from bleak.backends.device import BLEDevice
from typing import Optional

WRITE_UUID  = "57420002-587e-48a0-974c-544d6163c577"
NOTIFY_UUID = "57420003-587e-48a0-974c-544d6163c577"

BASELINE_RESPONSES = {"1000", "1001", "1002", "1003"}  # normal idle chatter


async def find_wand() -> BLEDevice:
    print("Scanning...")
    found, target = asyncio.Event(), None

    def cb(device, _adv):
        nonlocal target
        if device.name and device.name.startswith("MCW") and not found.is_set():
            target = device
            found.set()

    async with BleakScanner(detection_callback=cb):
        await found.wait()

    assert target is not None
    print(f"  Found: {target.name} ({target.address})\n")
    return target


async def probe(client: BleakClient, pkt: bytes, label: str, results: list):
    """Send a packet, collect responses for 1s, record anything unusual."""
    responses = []

    def handler(_s, data):
        responses.append(data.hex())

    await client.start_notify(NOTIFY_UUID, handler)
    await asyncio.sleep(0.15)  # drain any pending idle chatter
    responses.clear()

    try:
        await client.write_gatt_char(WRITE_UUID, pkt)
    except Exception as e:
        await client.stop_notify(NOTIFY_UUID)
        print(f"  WRITE ERROR  {pkt.hex():<30}  {e}")
        return

    await asyncio.sleep(0.8)
    await client.stop_notify(NOTIFY_UUID)

    unique = set(responses)
    novel  = unique - BASELINE_RESPONSES
    marker = "  ★ NOVEL" if novel else ""
    print(f"  {pkt.hex():<34}  {label:<40}  ← {' '.join(responses[:6]) or '—'}{marker}")
    results.append({
        "packet": pkt.hex(), "label": label,
        "responses": responses, "novel": list(novel)
    })
    await asyncio.sleep(0.3)


async def run_probes(client: BleakClient):
    results = []
    print("─" * 100)
    print(f"  {'Packet':<34}  {'Label':<40}  Responses")
    print("─" * 100)

    # ── Attempt 1: vary the header byte (byte 0) ──────────────────────────────
    # Our current header: [total_len 0x02 0x10 opcode payload_len] + payload
    # Try just [opcode] + payload directly (no header)
    # Red = ff0000, group=0, dur=1000ms=0x03e8

    # Candidate opcodes for changeled from APK class names
    for opcode in [0x04, 0x05, 0x06, 0x07, 0x09, 0x0a, 0x0c, 0x0d]:
        pkt = bytes([opcode, 0x00, 0xff, 0x00, 0x00, 0xe8, 0x03])
        await probe(client, pkt, f"raw opcode=0x{opcode:02x} group=0 red", results)

    print()

    # ── Attempt 2: try different header prefixes ───────────────────────────────
    # The APK wraps with [total_len][0x02][0x10][opcode][count]
    # Maybe count is number of sub-commands, not payload length
    for count in [0x01, 0x02, 0x03]:
        pkt = bytes([0x0b, 0x02, 0x10, 0x06, count, 0x00, 0xff, 0x00, 0x00, 0xe8, 0x03])
        await probe(client, pkt, f"header count={count} opcode=06 red", results)

    print()

    # ── Attempt 3: different payload byte order ────────────────────────────────
    # Try ARGB, BGR, GRB orderings
    orderings = [
        (bytes([0x00, 0xff, 0x00, 0x00]), "ARGB"),
        (bytes([0x00, 0x00, 0xff]),        "BGR 3B"),
        (bytes([0xff, 0x00, 0x00]),        "RGB 3B"),
        (bytes([0x00, 0x00, 0x00, 0xff]), "BGRA"),
    ]
    for color_bytes, name in orderings:
        pkt = bytes([0x06]) + bytes([0x00]) + color_bytes + bytes([0xe8, 0x03])
        await probe(client, pkt, f"no-header opcode=06 {name}", results)

    print()

    # ── Attempt 4: try the v.kt message wrapper format ─────────────────────────
    # buildMacroMessage wraps payloads in v objects — try [0x01][len][payload]
    for opcode in [0x06, 0x07, 0x08]:
        payload = bytes([0x00, 0xff, 0x00, 0x00, 0xe8, 0x03])  # group=0 red
        pkt = bytes([0x01, len(payload), opcode]) + payload
        await probe(client, pkt, f"v-wrapper opcode=0x{opcode:02x}", results)

    print()

    # ── Attempt 5: minimal 3-byte color, no group, no duration ────────────────
    for opcode in [0x04, 0x06, 0x07]:
        pkt = bytes([opcode, 0xff, 0x00, 0x00])
        await probe(client, pkt, f"3B color opcode=0x{opcode:02x} red", results)

    print()

    # ── Attempt 6: the READY_TO_CAST macro pattern ────────────────────────────
    # MacroType has READY_TO_CAST — maybe this triggers the LED sequence
    # Try sending a known-good macro type identifier
    for macro_id in [0x01, 0x02, 0x03, 0x04, 0x05]:
        pkt = bytes([0x01, 0x10, macro_id])
        await probe(client, pkt, f"macro trigger id=0x{macro_id:02x}", results)

    print("─" * 100)

    # Print novel responses
    novel_results = [r for r in results if r["novel"]]
    if novel_results:
        print(f"\n  ★ {len(novel_results)} packet(s) produced novel responses:")
        for r in novel_results:
            print(f"    {r['packet']}  →  {r['novel']}")
    else:
        print("\n  No novel responses found — all packets got standard idle acks.")
        print("  The opcode or header structure may need further investigation.")

    return results


async def main():
    wand = await find_wand()
    for attempt in range(1, 6):
        try:
            print(f"Connecting (attempt {attempt}/5)...")
            async with BleakClient(wand, timeout=20.0) as client:
                print(f"Connected.\n")
                await asyncio.sleep(2.0)
                await run_probes(client)
            break
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"  Error: {e}")
            if attempt < 5:
                await asyncio.sleep(min(attempt * 2, 8))


if __name__ == "__main__":
    asyncio.run(main())
