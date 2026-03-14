import struct

# Re-examine the snoop focusing on conn 0x042 (the wand connection)
# during the known spell cast period (pkts 5600-6300)
# Specifically: what notifications come FROM the wand that are longer than 2 bytes?

with open(r'C:\Users\Hailfire\OneDrive\Documents\OpenCaster\Bluetooth Capture\HP Bluetooth log.btsnoop', 'rb') as f:
    f.read(16)
    pkt_num = 0
    while True:
        rec_hdr = f.read(24)
        if len(rec_hdr) < 24: break
        orig_len, incl_len, flags, drops, ts_sec, ts_usec = struct.unpack('>IIIIii', rec_hdr)
        payload = f.read(incl_len)
        pkt_num += 1
        if pkt_num < 5600 or pkt_num > 6300: continue
        if len(payload) < 10: continue

        handle_flags = struct.unpack_from('<H', payload, 0)[0]
        conn_h = handle_flags & 0x0FFF
        pb = (handle_flags >> 12) & 0x3
        if pb != 2: continue
        l2_cid = struct.unpack_from('<H', payload, 6)[0]
        if l2_cid != 0x0004: continue
        att = payload[8:]
        if not att: continue

        opcode = att[0]
        src = 'HOST' if flags == 0 else 'WAND'

        # Show ALL notifications (0x1b) longer than 2 bytes value
        if opcode == 0x1b and len(att) > 5:
            att_handle = struct.unpack_from('<H', att, 1)[0]
            val = att[3:]
            print(f'Pkt {pkt_num:5d} [{src}] conn=0x{conn_h:03x} NOTIFY h=0x{att_handle:04x} len={len(val):3d}: {val[:20].hex()}')
