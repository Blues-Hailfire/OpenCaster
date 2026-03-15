"""
Re-examine btsnoop: find service boundaries to determine which service
owns handles 0x0011-0x0017.
"""
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

# Decode all Read By Group Type responses (service discovery) and
# Read By Type responses (characteristic discovery) for the wand connection
print("=== Service discovery (ATT_READ_BY_GROUP_TYPE_RSP = 0x11) ===")
for i, (flags, data) in enumerate(packets[2290:2700], start=2290):
    if len(data) < 9 or data[:1] != b'\x42':
        continue
    try:
        cid = struct.unpack_from("<H", data, 6)[0]
        if cid != 0x0004:
            continue
        att_op = data[8]
        payload = data[9:]
        if att_op == 0x11:  # READ_BY_GROUP_TYPE_RSP (services)
            item_len = payload[0]
            items = payload[1:]
            while len(items) >= item_len:
                chunk = items[:item_len]
                start = struct.unpack_from("<H", chunk, 0)[0]
                end   = struct.unpack_from("<H", chunk, 2)[0]
                uuid  = chunk[4:].hex()
                print(f"  [pkt {i}] Service start=0x{start:04x} end=0x{end:04x} uuid={uuid}")
                items = items[item_len:]
        elif att_op == 0x09:  # READ_BY_TYPE_RSP (characteristics)
            item_len = payload[0]
            items = payload[1:]
            while len(items) >= item_len:
                chunk = items[:item_len]
                decl_handle = struct.unpack_from("<H", chunk, 0)[0]
                props       = chunk[2]
                value_handle= struct.unpack_from("<H", chunk, 3)[0]
                uuid        = chunk[5:].hex()
                print(f"  [pkt {i}] Char decl=0x{decl_handle:04x} props=0x{props:02x} "
                      f"value=0x{value_handle:04x} uuid={uuid}")
                items = items[item_len:]
    except Exception:
        pass
