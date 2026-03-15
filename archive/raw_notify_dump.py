"""
raw_notify_dump.py — Dump raw bytes from 57420003 during gesture motion.
Hold the wand, cover grip sensors, wave it around, watch what comes in.
Usage: python raw_notify_dump.py
"""
import asyncio
from wand import find_wand, NOTIFY_UUID, WRITE_UUID, hw_init
from bleak import BleakClient

async def main():
    wand = await find_wand()
    async with BleakClient(wand, timeout=20.0) as client:
        await asyncio.sleep(2.0)
        await hw_init(client)
        print(f"Connected to {wand.name} — wave the wand! (Ctrl+C to stop)\n")
        print(f"{'Bytes':>5}  Hex")
        print("-" * 60)

        def handler(_sender, data: bytes):
            hex_str = data.hex()
            length = len(data)
            marker = " ◀ IMU!" if length > 2 else ""
            print(f"  {length:>3}B  {hex_str}{marker}")

        await client.start_notify(NOTIFY_UUID, handler)
        # Send the init packets the app sends
        for pkt in ["021002", "02100a", "02100b"]:
            await client.write_gatt_char(WRITE_UUID, bytes.fromhex(pkt), response=False)
            await asyncio.sleep(0.05)

        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass
        await client.stop_notify(NOTIFY_UUID)

if __name__ == "__main__":
    asyncio.run(main())
