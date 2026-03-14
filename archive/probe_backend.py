import asyncio
from bleak import BleakScanner, BleakClient

async def probe():
    print("Scanning...")
    devices = await BleakScanner.discover(timeout=5.0)
    wand = next((d for d in devices if d.name and d.name.startswith("MCW")), None)
    if not wand:
        print("No wand found")
        return
    print(f"Found {wand.name}")
    async with BleakClient(wand, timeout=20.0) as client:
        await asyncio.sleep(1.0)
        backend = client._backend
        print("Backend type:", type(backend).__name__)
        attrs = [a for a in dir(backend) if 'notif' in a.lower() or 'callback' in a.lower()]
        print("Notify/callback attrs:", attrs)
        for attr in ('_notify_callbacks', '_notification_callbacks', '_callbacks',
                     '_char_callbacks', '_notify_callback'):
            if hasattr(backend, attr):
                val = getattr(backend, attr)
                print(f"  HIT: backend.{attr} = {type(val).__name__} = {val}")

asyncio.run(probe())
