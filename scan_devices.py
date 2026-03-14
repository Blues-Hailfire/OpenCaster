"""
scan_devices.py — Quick BLE scanner
Lists all nearby BLE devices for 10 seconds, highlighting MCW/MCB devices.
Usage: python scan_devices.py
"""

import asyncio
from bleak import BleakScanner


async def main():
    print("Scanning for 10 seconds...\n")
    seen: dict = {}

    def callback(device, adv):
        if device.address not in seen:
            seen[device.address] = (device.name or "Unknown", adv.rssi)
            name = device.name or "Unknown"
            tag = ""
            if name.startswith("MCW"):
                tag = "  ← WAND"
            elif name.startswith("MCB"):
                tag = "  ← BOX"
            rssi = adv.rssi if adv.rssi else "?"
            print(f"  {name:<30} {device.address}   RSSI: {rssi} dBm{tag}")

    async with BleakScanner(detection_callback=callback):
        await asyncio.sleep(10.0)

    print(f"\nTotal devices found: {len(seen)}")
    mcw = [n for n, _ in seen.values() if n.startswith("MCW")]
    mcb = [n for n, _ in seen.values() if n.startswith("MCB")]
    if mcw:
        print(f"  Wand:  {mcw}")
    else:
        print("  Wand:  NOT FOUND")
    if mcb:
        print(f"  Box:   {mcb}")
    else:
        print("  Box:   NOT FOUND — make sure it is powered on and not already connected to something else")


if __name__ == "__main__":
    asyncio.run(main())
