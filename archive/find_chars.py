import struct

# Service 0x0013-0x0016 uuid=9fa480e0-4967-4542-9390-d343dc5d04ae
# We need the characteristic UUID inside it that maps to handle 0x0016
# Look for READ_BY_TYPE_RSP (0x07) responses which list characteristic declarations
# Format: opcode(1) + item_len(1) + [decl_handle(2) + properties(1) + value_handle(2) + uuid(2or16)]

with open(r'C:\Users\Hailfire\OneDrive\Documents\OpenCaster\Bluetooth Capture\HP Bluetooth log.btsnoop', 'rb') as f:
    f.read(16)
    pkt_num = 0

    while True:
        rec_hdr = f.read(24)
        if len(rec_hdr) < 24:
            break
        orig_len, incl_len, flags, drops, ts_sec, ts_usec = struct.unpack('>IIIIii', rec_hdr)
        payload = f.read(incl_len)
        pkt_num += 1
        if pkt_num > 3000:
            break
        if len(payload) < 12:
            continue

        handle_flags = struct.unpack_from('<H', payload, 0)[0]
        pb = (handle_flags >> 12) & 0x3
        if pb != 2:
            continue
        l2_cid = struct.unpack_from('<H', payload, 6)[0]
        if l2_cid != 0x0004:
            continue
        att = payload[8:]
        if len(att) < 4:
            continue

        opcode = att[0]

        # READ_BY_TYPE_RSP = 0x07 (characteristic declarations)
        if opcode == 0x07:
            item_len = att[1]
            items = att[2:]
            i = 0
            while i + item_len <= len(items):
                item = items[i:i+item_len]
                decl_handle = struct.unpack_from('<H', item, 0)[0]
                props = item[2]
                val_handle = struct.unpack_from('<H', item, 3)[0]
                uuid_bytes = item[5:]
                if len(uuid_bytes) == 2:
                    uuid_val = struct.unpack_from('<H', uuid_bytes)[0]
                    uuid = f'0x{uuid_val:04x}'
                elif len(uuid_bytes) >= 16:
                    r = uuid_bytes[:16][::-1].hex()
                    uuid = f'{r[0:8]}-{r[8:12]}-{r[12:16]}-{r[16:20]}-{r[20:]}'
                else:
                    uuid = uuid_bytes.hex()
                print(f'Pkt {pkt_num}: decl=0x{decl_handle:04x} props=0x{props:02x} val=0x{val_handle:04x} uuid={uuid}')
                i += item_len

        # FIND_INFO_RSP = 0x05 (handle -> UUID mapping)
        if opcode == 0x05:
            fmt = att[1]
            items = att[2:]
            item_len = 4 if fmt == 1 else 18
            i = 0
            while i + item_len <= len(items):
                item = items[i:i+item_len]
                h = struct.unpack_from('<H', item, 0)[0]
                uuid_bytes = item[2:]
                if fmt == 1:
                    uuid_val = struct.unpack_from('<H', uuid_bytes)[0]
                    uuid = f'0x{uuid_val:04x}'
                else:
                    r = uuid_bytes[:16][::-1].hex()
                    uuid = f'{r[0:8]}-{r[8:12]}-{r[12:16]}-{r[16:20]}-{r[20:]}'
                print(f'Pkt {pkt_num} FIND_INFO: handle=0x{h:04x} uuid={uuid}')
                i += item_len
