import struct

with open(r"C:\Users\Hailfire\OneDrive\Documents\OpenCaster\Bluetooth Capture\HP Bluetooth log.btsnoop", "rb") as f:
    f.read(16)
    packets = []
    while True:
        rec_hdr = f.read(24)
        if len(rec_hdr) < 24:
            break
        orig_len, inc_len, flags, drops, ts_hi, ts_lo = struct.unpack(">IIIIII", rec_hdr)
        data = f.read(inc_len)
        packets.append((flags, data))

print(f"Total packets: {len(packets)}")

# Search for the custom UUID bytes (57420002 and 57420003) in little-endian
uuid_write = bytes.fromhex("02004257")  # 57420002 LE prefix
uuid_notify = bytes.fromhex("03004257")  # 57420003 LE prefix
imu_keywords = [b"\x00\x16", b"\x16\x00"]  # handle 0x0016

print("\n--- Packets containing custom UUID 574200xx ---")
for i, (flags, data) in enumerate(packets):
    direction = "SEND" if (flags & 1) == 0 else "RECV"
    if uuid_write in data or uuid_notify in data:
        print(f"[{i:05d}] {direction} ({len(data):3d}b): {data.hex()}")

print("\n--- Searching for handle 0x0016 (IMU) in ATT layer ---")
# ATT handle 0x0016 = bytes 16 00
for i, (flags, data) in enumerate(packets):
    direction = "SEND" if (flags & 1) == 0 else "RECV"
    # Look for handle 0x0016 in context of ATT reads/writes/notifications
    if b"\x16\x00" in data[3:] or b"\x00\x16" in data[3:]:
        print(f"[{i:05d}] {direction} ({len(data):3d}b): {data.hex()}")
