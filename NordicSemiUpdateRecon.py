import asyncio
import csv
from datetime import datetime
from bleak import BleakScanner, BleakClient

WRITE_CHAR_UUID = "57420002-587e-48a0-974c-544d6163c577"  # For safe writes later
PROBLEMATIC_UUIDS = {
    "00002a05-0000-1000-8000-00805f9b34fb",  # Service Changed
    "00002a19-0000-1000-8000-00805f9b34fb",  # Battery Level
}

LOG_FILE = "device_notifications.csv"

# Event type mapping (example, you can expand as you learn)
EVENT_TYPES = {
    0x10: "Device event"
}

# Prepare CSV file
with open(LOG_FILE, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["Timestamp", "Characteristic UUID", "Raw Bytes", "Event Type"])

def handle_notification(sender, data):
    """Callback for all notifications and indications."""
    timestamp = datetime.now().isoformat()
    raw_hex = data.hex()
    event_type = EVENT_TYPES.get(data[0], "Unknown")
    print(f"[{timestamp}] Characteristic {sender}: {raw_hex} | Event: {event_type}")

    # Append to CSV
    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([timestamp, sender, raw_hex, event_type])

async def find_device():
    """Scan until an MCW device is found."""
    print("Scanning for BLE devices...")
    while True:
        devices = await BleakScanner.discover()
        target = next((d for d in devices if d.name and d.name.startswith("MCW")), None)
        if target:
            print(f"Found device: {target.name} ({target.address})")
            return target
        else:
            print("No device found, scanning again...")
            await asyncio.sleep(2)

async def subscribe_notifications(client):
    """Subscribe to all safe notify/indicate characteristics."""
    notify_chars = [
        c for s in client.services
        for c in s.characteristics
        if ("notify" in c.properties or "indicate" in c.properties)
        and c.uuid not in PROBLEMATIC_UUIDS
    ]

    for char in notify_chars:
        if not client.is_connected:
            print("Lost connection, cannot subscribe.")
            return
        try:
            print(f"Subscribing to {char.uuid}")
            await client.start_notify(char.uuid, handle_notification)
            await asyncio.sleep(0.5)
        except Exception as e:
            print(f"Could not subscribe to {char.uuid}: {e}")

async def main():
    target_device = await find_device()

    async with BleakClient(target_device.address) as client:
        print("Connected:", client.is_connected)
        await asyncio.sleep(1)

        print("\nDiscovering services and subscribing to notifications...")
        await subscribe_notifications(client)

        print("\nListening for notifications. Press Ctrl+C to stop.")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping notifications...")
            notify_chars = [
                c for s in client.services
                for c in s.characteristics
                if ("notify" in c.properties or "indicate" in c.properties)
                and c.uuid not in PROBLEMATIC_UUIDS
            ]
            for char in notify_chars:
                if client.is_connected:
                    await client.stop_notify(char.uuid)
            print(f"Notifications logged to {LOG_FILE}")

if __name__ == "__main__":
    asyncio.run(main())
