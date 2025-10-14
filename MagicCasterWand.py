import asyncio
from bleak import BleakClient, BleakScanner

TARGET_NAME = "MCW-7DFE"
UART_WRITE_UUID = "57420002-587e-48a0-974c-544d6163c577"
UART_NOTIFY_UUID = "57420003-587e-48a0-974c-544d6163c577"
BATTERY_NOTIFY_UUID = "00002a19-0000-1000-8000-00805f9b34fb"

KEEPALIVE_INTERVAL = 5  # seconds

def handle_notification(sender: str, data: bytearray):
    ascii_data = data.decode(errors='ignore')
    print(f"[{sender}] Notification: {data.hex()} | ASCII: {ascii_data}")

async def find_device():
    print("Scanning for BLE devices...")
    while True:
        devices = await BleakScanner.discover(timeout=5.0)
        for d in devices:
            if d.name == TARGET_NAME:
                print(f"Found target: {d.name} [{d.address}]")
                return d
        print("Device not found, rescanning...")

async def keep_alive(client: BleakClient):
    """Optional keep-alive write to avoid idle disconnects."""
    while True:
        try:
            if client.is_connected:
                await client.write_gatt_char(UART_WRITE_UUID, bytes([0x01]), response=False)
        except Exception as e:
            print(f"Keep-alive error: {e}")
            break
        await asyncio.sleep(KEEPALIVE_INTERVAL)

async def subscribe_with_retry(client: BleakClient, uuid: str, max_retries=3):
    for attempt in range(1, max_retries + 1):
        try:
            await client.start_notify(uuid, handle_notification)
            print(f"Subscribed to {uuid}")
            return True
        except Exception as e:
            print(f"Failed to subscribe to {uuid} (attempt {attempt}): {e}")
            await asyncio.sleep(1)
    print(f"Skipping {uuid} after {max_retries} failed attempts.")
    return False

async def connect_and_listen(device):
    async with BleakClient(device.address) as client:
        connected = client.is_connected
        if not connected:
            print("Failed to connect.")
            return

        print(f"Connected to {device.name}")

        # Subscribe ASAP after connecting
        await subscribe_with_retry(client, UART_NOTIFY_UUID)
        await subscribe_with_retry(client, BATTERY_NOTIFY_UUID)

        # Start keep-alive loop
        asyncio.create_task(keep_alive(client))

        # Print services once connected and stable
        services = client.services  # no await needed, services are loaded after connection
        print("Available services and characteristics:")
        for s in services:
            print(f"  Service {s.uuid}")
            for c in s.characteristics:
                print(f"    Characteristic {c.uuid} | Properties: {c.properties}")

        print("Listening for notifications (Ctrl+C to stop)...")
        while client.is_connected:
            await asyncio.sleep(1)
        print("Device disconnected.")


async def main():
    while True:
        device = await find_device()
        try:
            await connect_and_listen(device)
        except Exception as e:
            print(f"Error: {e}. Reconnecting...")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Exiting...")
