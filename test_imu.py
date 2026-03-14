"""Quick test: connect, run IMU enable sequence, print any IMU packets received."""
import asyncio
from bleak import BleakClient
from wand import find_wand, hw_init, imu_subscribe, NOTIFY_UUID

def imu_callback(data: bytes):
    print(f"  [IMU DATA] {len(data)}b: {data.hex()}")
    if len(data) >= 6:
        import struct
        ax, ay, az = struct.unpack_from('<hhh', data, 0)
        print(f"             ax={ax:6d} ay={ay:6d} az={az:6d}")

async def main():
    wand = await find_wand()
    async with BleakClient(wand, timeout=20.0) as client:
        print(f"Connected to {wand.name}")
        await asyncio.sleep(1.5)
        await hw_init(client)
        await imu_subscribe(client, imu_callback)
        print("\nListening for IMU data for 15 seconds — wave the wand!")
        await asyncio.sleep(15)

asyncio.run(main())
