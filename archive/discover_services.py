"""
discover_services.py — Dump every service, characteristic, and descriptor
the wand exposes, with properties and handle numbers.
Usage: python discover_services.py
"""
import asyncio
from wand import find_wand
from bleak import BleakClient

async def main():
    wand = await find_wand()
    async with BleakClient(wand, timeout=20.0) as client:
        await asyncio.sleep(2.0)
        print(f"\nConnected to {wand.name}  ({wand.address})\n")
        print(f"{'Handle':<8} {'UUID':<42} {'Properties'}")
        print("-" * 85)
        for svc in client.services:
            print(f"\n[SERVICE]  {svc.uuid}  (handles {svc.handle:#06x})")
            for char in svc.characteristics:
                props = ", ".join(char.properties)
                print(f"  {char.handle:#06x}  {char.uuid}  [{props}]")
                for desc in char.descriptors:
                    print(f"    {desc.handle:#06x}  {desc.uuid}  (descriptor)")

if __name__ == "__main__":
    asyncio.run(main())
