import struct

TARGET_UUID = "57420003"
IMU_HANDLES = []

with open(r"C:\Users\Hailfire\OneDrive\Documents\OpenCaster\Bluetooth Capture\HP Bluetooth log.btsnoop", "rb") as f:
    magic = f.read(8)
    version, datalink = struct.unpack(">II", f.read(8))
    print(f"btsnoop version={version} datalink={datalink}")

    packets = []
    while True:
        rec_hdr = f.read(24)
        if len(rec_hdr) < 24:
            break
        orig_len, inc_len, flags, drops, ts_hi, ts_lo = struct.unpack(">IIIIII", rec_hdr)
        data = f.read(inc_len)
        packets.append((flags, data))

print(f"Total packets: {len(packets)}")

# Print first 40 packets as hex to understand structure
for i, (flags, data) in enumerate(packets[:40]):
    direction = "SEND" if (flags & 1) == 0 else "RECV"
    print(f"[{i:04d}] {direction} ({len(data):3d} bytes): {data.hex()}")
