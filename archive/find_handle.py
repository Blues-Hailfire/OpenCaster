import struct

# Handle 0x0016 streams IMU - find its UUID via FIND_INFO_RSP (opcode 0x05)
# which maps handle->UUID directly

with open(r'C:\Users\Hailfire\OneDrive\Documents\OpenCaster\Bluetooth Capture\HP Bluetooth log.btsnoop', 'rb') as f:
    f.read(16)
    pkt_num = 0
    
    while True:
        rec_hdr = f.read(24)
        if len(rec_hdr) < 24: break
        orig_len, incl_len, flags, drops, ts_sec, ts_usec = struct.unpack('>IIIIii', rec_hdr)
        payload = f.read(incl_len)
        pkt_num += 1
        if pkt_num > 3000: break
        
        if len(payload) < 10: continue
        handle_flags = struct.unpack_from('<H', payload, 0)[0]
        pb = (handle_flags >> 12) & 0x3
        if pb != 2: continue
        l2_cid = struct.unpack_from('<H', payload, 6)[0]
        if l2_cid != 0x0004: continue
        att = payload[8:]
        if len(att) < 3: continue
        
        opcode = att[0]
        # FIND_INFO_RSP = 0x05: format(1) + [handle(2)+uuid(2or16)]...
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
                    uuid = f'0x{struct.unpack_from("<H", uuid_bytes)[0]:04x}'
                else:
                    r = uuid_bytes[::-1].hex()
                    uuid = f'{r[0:8]}-{r[8:12]}-{r[12:16]}-{r[16:20]}-{r[20:]}'
                if 0x0013 <= h <= 0x0018:
                    print(f'Pkt {pkt_num}: handle=0x{h:04x} uuid={uuid}')
                i += item_len

        # Also check READ_BY_GROUP_TYPE_RSP = 0x11 for service ranges
        if opcode == 0x11:
            item_len = att[1]
            items = att[2:]
            i = 0
            while i + item_len <= len(items):
                item = items[i:i+item_len]
                start = struct.unpack_from('<H', item, 0)[0]
                end   = struct.unpack_from('<H', item, 2)[0]
                uuid_bytes = item[4:]
                if len(uuid_bytes) == 2:
                    uuid = f'0x{struct.unpack_from("<H", uuid_bytes)[0]:04x}'
                else:
                    r = uuid_bytes[::-1].hex()
                    uuid = f'{r[0:8]}-{r[8:12]}-{r[12:16]}-{r[16:20]}-{r[20:]}'
                print(f'Pkt {pkt_num} SERVICE: 0x{start:04x}-0x{end:04x} uuid={uuid}')
                i += item_len
