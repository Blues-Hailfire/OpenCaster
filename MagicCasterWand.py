import asyncio
from bleak import BleakClient
from wand import WRITE_UUID, NOTIFY_UUID, find_wand

# Packets to send on connect (write to WRITE_UUID, not notify char)
PACKETS = ["021002", "02100a", "02100b"]

# Map known status codes to human-readable labels
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

    # Spell name: prefix byte 0x24, format 24 00 00 <len> <utf-8>
    if data[0] == 0x24:
        try:
            text = data[4:].decode("utf-8")
            print(f"[notify] Spell: \"{text}\"")
        except Exception as e:
            print(f"[notify] Spell decode error: {e} — raw: {hex_str}")
        return

    # Heartbeat: 01 40 01
    if hex_str == "014001":
        print("[notify] Heartbeat")
        return

    # Type A status event: exactly 2 bytes starting with 0x10
    if data[0] == 0x10 and len(data) == 2:
        status = STATUS_CODES.get(hex_str, f"Unknown (0x{hex_str})")
        print(f"[notify] Status: {status}  ({hex_str})")
        return

    # Fallback
    print(f"[notify] Raw: {hex_str}")


async def main():
    wand = await find_wand()

    async with BleakClient(wand, timeout=20.0) as client:
        print(f"Connected to {wand.name}")
        await asyncio.sleep(2.0)

        await client.start_notify(NOTIFY_UUID, lambda _s, d: parse_notification(d))

        # Send packets to the write characteristic (not the notify one)
        for pkt in PACKETS:
            print(f"Sending: {pkt}")
            await client.write_gatt_char(WRITE_UUID, bytes.fromhex(pkt), response=False)
            await asyncio.sleep(0.05)

        print("Listening for notifications... (30 s)")
        await asyncio.sleep(30)
        await client.stop_notify(NOTIFY_UUID)
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
