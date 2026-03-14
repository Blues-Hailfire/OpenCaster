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

# Focus on the wand connection window - all SEND packets around 2300-2700
# ACL handle for wand appears to be 0x0042 based on 42 20 prefix
print("=== All SENDS around wand connection ===")
for i, (flags, data) in enumerate(packets[2290:2660], start=2290):
    direction = "SEND" if (flags & 1) == 0 else "RECV"
    if direction == "SEND":
        print(f"[{i:05d}] SEND ({len(data):3d}b): {data.hex()}")

print()
# Now decode the IMU notification packets
# Pattern: 42 20 1b 00 eb 00 04 00 1b 16 00 2c ...
# ACL header: handle(2) len(2) | L2CAP: len(2) CID(2) | ATT opcode(1) handle(2) | data
print("=== IMU Notification decode (handle 0x161b = ATT notify) ===")
for i, (flags, data) in enumerate(packets[2590:2830], start=2590):
    if flags & 1 and data[:2] == b'\x42\x20' and len(data) > 10:
        # Parse ACL
        acl_handle = struct.unpack_from("<H", data, 0)[0] & 0x0FFF
        acl_len = struct.unpack_from("<H", data, 2)[0]
        l2cap_len = struct.unpack_from("<H", data, 4)[0]
        cid = struct.unpack_from("<H", data, 6)[0]
        if cid == 0x0004:  # ATT
            att_op = data[8]
            if att_op == 0x1b and len(data) >= 11:  # ATT Handle Value Notification
                att_handle = struct.unpack_from("<H", data, 9)[0]
                payload = data[11:]
                print(f"[{i:05d}] ATT Notify handle=0x{att_handle:04x} payload({len(payload)}b): {payload.hex()}")
                # Try decode as IMU: x(2) y(2) z(2) 
                if len(payload) >= 6:
                    x, y, z = struct.unpack_from("<hhh", payload, 0)
                    print(f"         -> X={x} Y={y} Z={z}")
