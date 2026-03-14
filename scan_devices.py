"""
scan_devices.py — BLE scanner with diagnostics
Lists all nearby BLE devices, highlighting MCW/MCB wands and boxes.

Usage:
  python scan_devices.py           # 10-second scan
  python scan_devices.py --time 30 # longer scan
  python scan_devices.py --all     # show all devices, not just named ones
"""

import asyncio
import argparse
from bleak import BleakScanner


async def main(scan_time: int, show_all: bool):
    print(f"Scanning for {scan_time} seconds...\n")
    print(f"  {'Name':<32} {'Address':<20} {'RSSI':>6}")
    print("  " + "-" * 62)
    seen: dict = {}

    def callback(device, adv):
        addr = device.address
        name = device.name or ""
        rssi = adv.rssi if adv.rssi else 0

        is_wand = name.startswith("MCW")
        is_box  = name.startswith("MCB")

        # Update best RSSI seen for this device
        prev = seen.get(addr)
        if prev is None or rssi > prev[1]:
            seen[addr] = (name or "Unknown", rssi)

        # Print on first sight, or if it's a wand/box appearing
        if prev is None:
            if is_wand or is_box or show_all or name:
                tag = "  ← WAND" if is_wand else ("  ← BOX" if is_box else "")
                display = name if name else "(no name)"
                print(f"  {display:<32} {addr:<20} {rssi:>5} dBm{tag}")

    async with BleakScanner(detection_callback=callback):
        await asyncio.sleep(scan_time)

    print(f"\n  Scan complete — {len(seen)} total devices seen")
    mcw = [(n, r) for n, r in seen.values() if n.startswith("MCW")]
    mcb = [(n, r) for n, r in seen.values() if n.startswith("MCB")]

    if mcw:
        for name, rssi in mcw:
            print(f"  + Wand found:  {name}  (RSSI {rssi} dBm)")
    else:
        print("  - No wand found (MCW-*)")
        print()
        print("  Troubleshooting:")
        print("  1. Press & hold wand button 2-3s to wake it")
        print("  2. Toggle Bluetooth off/on in Windows Settings")
        print("  3. Windows Settings > Bluetooth > remove MCW device > rescan")
        print("  4. Check wand battery -- low battery stops advertising")

    if mcb:
        for name, rssi in mcb:
            print(f"  + Box found:   {name}  (RSSI {rssi} dBm)")
    else:
        print("  - No box found  (MCB-*)")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--time", type=int, default=10, help="Scan duration in seconds")
    p.add_argument("--all",  action="store_true", help="Show all devices, not just named")
    args = p.parse_args()
    asyncio.run(main(args.time, args.all))
