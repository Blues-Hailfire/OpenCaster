import struct

# Find where the CCCD at 0x0017 got written to enable handle 0x0016 notifications
# Also check what was written to 0x0013 (write char) right before IMU streaming started

with open(r'C:\Users\Hailfire\OneDrive\Documents\OpenCaster\Bluetooth Capture\HP Bluetooth log.btsnoop', 'rb') as f:
    f.read(16)
    pkt_num = 0
    while True:
        rec_hdr = f.read(24)
        if len(rec_hdr) < 24: break
        orig_len, incl_len, flags, drops, ts_sec, ts_usec = struct.unpack('>IIIIii', rec_hdr)
        payload = f.read(incl_len)
        pkt_num += 1
        if pkt_num > 6000: break
        if len(payload) < 10: continue

        handle_flags = struct.unpack_from('<H', payload, 0)[0]
        conn_h = handle_flags & 0x0FFF
        pb = (handle_flags >> 12) & 0x3
        if pb != 2 or conn_h != 0x042: continue
        l2_cid = struct.unpack_from('<H', payload, 6)[0]
        if l2_cid != 0x0004: continue
        att = payload[8:]
        if not att: continue

        opcode = att[0]
        src = 'HOST' if flags == 0 else 'WAND'

        # Show writes from host (0x12 = write req, 0x52 = write cmd)
        if opcode in (0x12, 0x52) and flags == 0:
            hdl = struct.unpack_from('<H', att, 1)[0]
            val = att[3:].hex()
            print(f'Pkt {pkt_num:5d} [HOST->WAND] WRITE h=0x{hdl:04x} val={val}')

        # Show write responses
        if opcode == 0x13 and flags == 1:
            print(f'Pkt {pkt_num:5d} [WAND->HOST] WRITE_RSP')

        # Show first notify on 0x0016
        if opcode == 0x1b and flags == 1:
            hdl = struct.unpack_from('<H', att, 1)[0]
            if hdl == 0x0016:
                val = att[3:].hex()
                print(f'Pkt {pkt_num:5d} [WAND->HOST] NOTIFY h=0x{hdl:04x} val={val[:24]}  <-- FIRST IMU')
                break
