import asyncio
from bleak import BleakClient, BleakScanner

DEVICE_NAME = "MCW-7DFE"
SERVICE_UUID = "57420003-587e-48a0-974c-544d6163c577"
CHAR_UUID = SERVICE_UUID  # Your characteristic for notifications
PACKETS = ["021002", "02100a", "02100b"]

# Map known status codes to human-readable
STATUS_CODES = {
    "1000": "Ready / Idle",
    "1001": "Action Started",
    "1002": "Action Ended / Ack",
    "1003": "Unknown Event 3",
    "1006": "Unknown Event 6",
    "1008": "Unknown Event 8",
    "1009": "Unknown Event 9",
    "100a": "Unknown Event A",
    "100b": "Unknown Event B",
    "100e": "Unknown Event E",
    "100f": "Unknown Event F",
}

def parse_notification(data: bytes):
    hex_str = data.hex()
    
    # Check for text messages (prefix 24 = likely text)
    if hex_str.startswith("24"):
        # skip the first byte(s) (length/prefix), then decode UTF-8
        try:
            # Assuming format: 24 + 0000 + length + text
            # Find first non-zero after 24
            text_bytes = bytes.fromhex(hex_str[8:])  # adjust if format differs
            text = text_bytes.decode("utf-8")
            print(f"[{CHAR_UUID}] Text: \"{text}\"")
        except Exception as e:
            print(f"[{CHAR_UUID}] Text decode error: {e} - Raw: {hex_str}")
    else:
        # Treat as status/event code
        code = hex_str[-4:]  # last 2 bytes as code
        status = STATUS_CODES.get(code, "Unknown Status")
        print(f"[{CHAR_UUID}] Status: 0x{code} -> {status}")

async def main():
    print("Scanning...")
    device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10.0)
    if not device:
        print("Device not found.")
        return
    
    async with BleakClient(device) as client:
        print(f"Connected to {DEVICE_NAME}")

        def notification_handler(sender, data):
            parse_notification(data)

        await client.start_notify(CHAR_UUID, notification_handler)

        # Send packets
        for pkt in PACKETS:
            print(f"Sending: {pkt}")
            await client.write_gatt_char(CHAR_UUID, bytes.fromhex(pkt))
        
        print("All packets sent. Listening for notifications...")

        # Keep listening for notifications for 30 seconds
        await asyncio.sleep(30)
        await client.stop_notify(CHAR_UUID)
        print("Done.")

if __name__ == "__main__":
    asyncio.run(main())
