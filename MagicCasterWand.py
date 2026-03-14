import asyncio
from bleak import BleakClient
from wand import (
    WRITE_UUID, NOTIFY_UUID, find_wand,
    hw_init, hw_write, buzz_frame,
    set_all_groups, clear_all, hsv_to_rgb, build_frame, cmd_changeled,
)

# Packets to send on connect (write to WRITE_UUID, not notify char)
PACKETS = ["021002", "02100a", "02100b"]

# Map known status codes to human-readable labels
STATUS_CODES = {
    "1000": "Ready / Idle",
    "1001": "Action Started",
    "1002": "Action Ended / Ack",
    "1003": "Unknown Event 3",
    "1006": "Unknown Event 6",
    "1008": "IMU motion burst start",
    "1009": "IMU motion sample",
    "100a": "IMU axis A",
    "100b": "Gesture window open",
    "100c": "Gesture alt C",
    "100d": "Gesture alt D",
    "100e": "Orientation change",
    "100f": "Gesture window close",
}


async def welcome_rainbow(client: BleakClient) -> None:
    """Sweep through rainbow hues, then buzz short + long as acknowledgment."""
    print("  Playing welcome sequence...")

    # Arm the LED controller
    await client.write_gatt_char(WRITE_UUID, bytes([0x60]), response=False)

    # Rainbow sweep: 12 hue steps across the full spectrum
    steps = 12
    step_ms = 80
    for i in range(steps):
        hue = i / steps
        r, g, b = hsv_to_rgb(hue)
        frame = set_all_groups(r, g, b, step_ms)
        await client.write_gatt_char(WRITE_UUID, frame, response=False)
        await asyncio.sleep(step_ms / 1000)

    # Fade out
    await client.write_gatt_char(WRITE_UUID, clear_all(), response=False)
    await asyncio.sleep(0.3)

    # Short buzz (100ms)
    await hw_write(client, bytes([0x60]))
    await hw_write(client, buzz_frame(100))
    await asyncio.sleep(0.15)
    await hw_write(client, bytes([0x40]))
    await asyncio.sleep(0.25)

    # Long buzz (350ms)
    await hw_write(client, bytes([0x60]))
    await hw_write(client, buzz_frame(100))
    await asyncio.sleep(0.4)
    await hw_write(client, bytes([0x40]))

    print("  Welcome sequence done.")


async def on_gesture_window_open(client: BleakClient) -> None:
    """Glow solid blue while the gesture window is open."""
    frame = set_all_groups(0, 0, 255, 2000)
    await client.write_gatt_char(WRITE_UUID, bytes([0x60]), response=False)
    await client.write_gatt_char(WRITE_UUID, frame, response=False)


async def on_gesture_window_close(client: BleakClient) -> None:
    """Clear LEDs when gesture window closes."""
    await client.write_gatt_char(WRITE_UUID, clear_all(), response=False)


def parse_notification(data: bytes) -> str | None:
    """Parse a BLE notification, return the event key string or None."""
    hex_str = data.hex()

    # Spell name: prefix byte 0x24, format 24 00 00 <len> <utf-8>
    if data[0] == 0x24:
        try:
            text = data[4:].decode("utf-8")
            print(f"[notify] Spell: \"{text}\"")
        except Exception as e:
            print(f"[notify] Spell decode error: {e} — raw: {hex_str}")
        return None

    # Heartbeat: 01 40 01
    if hex_str == "014001":
        print("[notify] Heartbeat")
        return None

    # Type A status event: exactly 2 bytes starting with 0x10
    if data[0] == 0x10 and len(data) == 2:
        status = STATUS_CODES.get(hex_str, f"Unknown (0x{hex_str})")
        print(f"[notify] Status: {status}  ({hex_str})")
        return hex_str

    # Fallback
    print(f"[notify] Raw: {hex_str}")
    return None


async def main():
    wand = await find_wand()

    async with BleakClient(wand, timeout=20.0) as client:
        print(f"Connected to {wand.name}")
        await asyncio.sleep(2.0)

        # Run haptic init so buzz works, then play welcome sequence
        await hw_init(client)
        await welcome_rainbow(client)

        # Notification handler — dispatches gesture window events to LED responses
        def notification_handler(_sender, data: bytes):
            event = parse_notification(data)
            if event == "100b":   # Gesture window open → glow blue
                asyncio.ensure_future(on_gesture_window_open(client))
            elif event == "100f": # Gesture window close → clear
                asyncio.ensure_future(on_gesture_window_close(client))

        await client.start_notify(NOTIFY_UUID, notification_handler)

        # Send init packets
        for pkt in PACKETS:
            print(f"Sending: {pkt}")
            await client.write_gatt_char(WRITE_UUID, bytes.fromhex(pkt), response=False)
            await asyncio.sleep(0.05)

        print("Listening for notifications... (press Ctrl+C to stop)")
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping...")

        await client.stop_notify(NOTIFY_UUID)
        print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
