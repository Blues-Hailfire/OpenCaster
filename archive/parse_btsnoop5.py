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

# Key GATT sends around IMU enable - decode ATT layer
print("=== Decoded ATT layer for wand SENDS (ACL 0x0042) ===")
ATT_OPCODES = {
    0x02: "ATT_ERROR_RSP",
    0x04: "ATT_FIND_INFO_REQ",
    0x05: "ATT_FIND_INFO_RSP",
    0x08: "ATT_READ_BY_TYPE_REQ",
    0x09: "ATT_READ_BY_TYPE_RSP",
    0x0a: "ATT_READ_REQ",
    0x0b: "ATT_READ_RSP",
    0x0c: "ATT_READ_BLOB_REQ",
    0x10: "ATT_READ_BY_GROUP_TYPE_REQ",
    0x11: "ATT_READ_BY_GROUP_TYPE_RSP",
    0x12: "ATT_WRITE_REQ",
    0x13: "ATT_WRITE_RSP",
    0x1b: "ATT_HANDLE_VALUE_NTF",
    0x52: "ATT_WRITE_CMD",
}

for i, (flags, data) in enumerate(packets[2290:2660], start=2290):
    direction = "SEND" if (flags & 1) == 0 else "RECV"
    # Only short, meaningful GATT packets (not DFU bulk)
    if len(data) > 50:
        continue
    # ACL wand packets start with 42 00 or 42 20
    if data[:1] != b'\x42':
        continue
    # Parse ACL header
    if len(data) < 9:
        continue
    try:
        l2cap_len = struct.unpack_from("<H", data, 4)[0]
        cid = struct.unpack_from("<H", data, 6)[0]
        if cid != 0x0004:  # ATT
            continue
        att_op = data[8]
        op_name = ATT_OPCODES.get(att_op, f"0x{att_op:02x}")
        payload = data[9:]
        
        if att_op in (0x12, 0x52) and len(payload) >= 2:  # Write req/cmd
            handle = struct.unpack_from("<H", payload, 0)[0]
            value = payload[2:]
            print(f"[{i:05d}] {direction} {op_name} handle=0x{handle:04x} value={value.hex()}")
        elif att_op == 0x0a and len(payload) >= 2:  # Read req
            handle = struct.unpack_from("<H", payload, 0)[0]
            print(f"[{i:05d}] {direction} {op_name} handle=0x{handle:04x}")
        elif att_op == 0x08 and len(payload) >= 4:  # Read by type
            start = struct.unpack_from("<H", payload, 0)[0]
            end = struct.unpack_from("<H", payload, 2)[0]
            uuid = payload[4:]
            print(f"[{i:05d}] {direction} {op_name} start=0x{start:04x} end=0x{end:04x} uuid={uuid.hex()}")
        elif att_op == 0x10 and len(payload) >= 4:  # Read by group type
            start = struct.unpack_from("<H", payload, 0)[0]
            end = struct.unpack_from("<H", payload, 2)[0]
            uuid = payload[4:]
            print(f"[{i:05d}] {direction} {op_name} start=0x{start:04x} end=0x{end:04x} uuid={uuid.hex()}")
        elif att_op == 0x04 and len(payload) >= 4:  # Find info
            start = struct.unpack_from("<H", payload, 0)[0]
            end = struct.unpack_from("<H", payload, 2)[0]
            print(f"[{i:05d}] {direction} {op_name} start=0x{start:04x} end=0x{end:04x}")
        else:
            print(f"[{i:05d}] {direction} {op_name} raw={payload.hex()}")
    except Exception as e:
        print(f"[{i:05d}] parse error: {e} data={data.hex()}")
