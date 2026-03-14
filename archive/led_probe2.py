"""
led_probe2.py — LED packet probe round 2
==========================================
Key finding from round 1:
- Raw opcodes (no 02 10 prefix) get acks but no LED change
- Full framed packets (with length byte) get NO response at all
- Correct format from fuzz data is simply: 02 10 [opcode] [optional payload]
  e.g. 021002, 02100a, 0402100300

This round tests 02 10 XX payloads specifically for LED/color commands,
trying every plausible opcode and color encoding.

Usage: python led_probe2.py
"""

import asyncio
from bleak import BleakScanner, BleakClient
from bleak.backends.device import BLEDevice
from typing import Optional

WRITE_UUID  = "57420002-587e-48a0-974c-544d6163c577"
NOTIFY_UUID = "57420003-587e-48a0-974c-544d6163c577"
BASELINE    = {"1000", "1001", "1002", "1003"}


async def find_wand() -> BLEDevice:
    found, target = asyncio.Event(), None
    def cb(d, _a):
        nonlocal target
        if d.name and d.name.startswith("MCW") and not found.is_set():
            target = d; found.set()
    async with BleakScanner(detection_callback=cb):
        await found.wait()
    assert target is not None
    print(f"Found: {target.name} ({target.address})\n")
    return target


async def probe(client, pkt: bytes, label: str, results: list):
    responses = []
    def handler(_s, data): responses.append(data.hex())
    await client.start_notify(NOTIFY_UUID, handler)
    await asyncio.sleep(0.15)
    responses.clear()
    try:
        await client.write_gatt_char(WRITE_UUID, pkt)
    except Exception as e:
        await client.stop_notify(NOTIFY_UUID)
        print(f"  ERR  {pkt.hex():<28} {e}")
        return
    await asyncio.sleep(0.9)
    await client.stop_notify(NOTIFY_UUID)
    novel  = set(responses) - BASELINE
    marker = "  ★" if novel else ""
    print(f"  {pkt.hex():<28}  {label:<38}  ← {' '.join(responses[:5]) or '—'}{marker}")
    results.append({"packet": pkt.hex(), "label": label, "responses": responses, "novel": list(novel)})
    await asyncio.sleep(0.25)


async def run_probes(client):
    results = []
    print(f"  {'Packet':<28}  {'Label':<38}  Responses")
    print("─" * 90)

    # ── Round A: scan all 02 10 XX opcodes with red payload ──────────────────
    # Format: 02 10 [opcode] [group=0] [r=ff] [g=00] [b=00] [dur_lo] [dur_hi]
    print("\n[A] All opcodes 0x00-0x0F with 02 10 prefix + red color payload")
    for op in range(0x00, 0x10):
        pkt = bytes([0x02, 0x10, op, 0x00, 0xff, 0x00, 0x00, 0xe8, 0x03])
        await probe(client, pkt, f"02 10 {op:02x} + red payload", results)

    # ── Round B: 3-byte format (02 10 opcode only, no payload) ───────────────
    print("\n[B] Bare 02 10 XX (no payload) — matches known working fuzz packets")
    for op in range(0x00, 0x10):
        pkt = bytes([0x02, 0x10, op])
        await probe(client, pkt, f"02 10 {op:02x} bare", results)

    # ── Round C: 02 10 XX with single byte payload (like 0402100300) ─────────
    print("\n[C] 02 10 XX + single payload byte 0x00-0x05")
    for op in [0x03, 0x05, 0x06, 0x07, 0x09]:
        for val in [0x00, 0x01, 0x02, 0x03, 0xff]:
            pkt = bytes([0x02, 0x10, op, val])
            await probe(client, pkt, f"02 10 {op:02x} {val:02x}", results)

    # ── Round D: color as 02 10 XX RRGGBB (no group, no duration) ────────────
    print("\n[D] 02 10 XX + raw RGB bytes only")
    for op in [0x05, 0x06, 0x07, 0x09, 0x0a]:
        pkt = bytes([0x02, 0x10, op, 0xff, 0x00, 0x00])
        await probe(client, pkt, f"02 10 {op:02x} ff0000", results)

    # ── Round E: try the DFU/config characteristic ───────────────────────────
    print("\n[E] Known working macro packets from original fuzz data")
    known = [
        ("021002",     "known fuzz — ack"),
        ("02100a",     "known fuzz — setloops?"),
        ("02100b",     "known fuzz — gesture open?"),
        ("0402100300", "known fuzz — 4-byte event3+0x00"),
        ("021006",     "known fuzz — event6"),
        ("021006ff",   "known fuzz — event6+0xff"),
    ]
    for hex_str, label in known:
        await probe(client, bytes.fromhex(hex_str), label, results)

    print("\n" + "─" * 90)
    novel = [r for r in results if r["novel"]]
    if novel:
        print(f"\n★ {len(novel)} novel response(s):")
        for r in novel:
            print(f"  {r['packet']:<28} → {r['novel']}")
    else:
        print("\nNo novel responses. The wand may require pairing with the box to accept LED commands.")
    return results


async def main():
    wand = await find_wand()
    for attempt in range(1, 6):
        try:
            print(f"Connecting (attempt {attempt}/5)...")
            async with BleakClient(wand, timeout=20.0) as client:
                print("Connected.\n")
                await asyncio.sleep(2.0)
                await run_probes(client)
            break
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")
            if attempt < 5:
                await asyncio.sleep(min(attempt * 2, 8))


if __name__ == "__main__":
    asyncio.run(main())
