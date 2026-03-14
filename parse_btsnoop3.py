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

# Packets [02593]-[02820] show IMU data at handle 0x161b (ACL handle)
# Let's look at connection setup around packet 2313 where handle 0x0016 first appears
# Packet 2313: RECV 42201a001600040011141200170077c563614d544c97a0487e5801004257
# This is ACL data - let's look at GATT layer around the wand connection

# Focus: find all WRITE commands sent to the wand after connection (around pkt 2396+)
print("=== GATT Writes to wand (ACL connection 0x0042) ===")
for i, (flags, data) in enumerate(packets[2300:2700], start=2300):
    direction = "SEND" if (flags & 1) == 0 else "RECV"
    # ACL packets to/from wand have handle bytes 42 20 or 42 40
    if data[:2] in [b'\x42\x20', b'\x42\x40']:
        print(f"[{i:05d}] {direction} ({len(data):3d}b): {data.hex()}")
