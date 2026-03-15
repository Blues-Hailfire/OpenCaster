"""Dump every raw WinRT characteristic handle visible after connecting."""
import asyncio
from bleak import BleakClient
from bleak.backends.winrt.client import FutureLike
from wand import find_wand

async def main():
    wand = await find_wand()
    async with BleakClient(wand, timeout=20.0) as client:
        await asyncio.sleep(1.5)
        print(f"\nConnected to {wand.name}\n")
        print(f"{'Handle':>8}  {'Service UUID':<40}  Properties")
        print("-" * 80)
        for svc in client.services:
            try:
                result = await FutureLike(svc.obj.get_characteristics_async())
                for ch in result.characteristics:
                    props = ch.characteristic_properties
                    print(f"  0x{ch.attribute_handle:04x}   {svc.uuid}   props={int(props):#010x}")
            except Exception as e:
                print(f"  [svc {svc.uuid}] ERROR: {e}")

asyncio.run(main())
