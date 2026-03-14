import struct

# Show ALL ATT traffic on conn 0x042 between pkts 2300-2600
with open(r'C:\Users\Hailfire\OneDrive\Documents\OpenCaster\Bluetooth Capture\HP Bluetooth log.btsnoop', 'rb') as f:
    f.read(16)
    pkt_num = 0
    while True:
        rec_hdr = f.read(24)
        if len(rec_hdr) < 24: break
        orig_len, incl_len, flags, drops, ts_sec, ts_usec = struct.unpack('>IIIIii', rec_hdr)
        payload = f.read(incl_len)
        pkt_num += 1
        if pkt_num > 2620: break
        if pkt_num < 2290: continue
        if len(payload) < 10: continue

        handle_flags = struct.unpack_from('<H', payload, 0)[0]
        conn_h = handle_flags & 0x0FFF
        pb = (handle_flags >> 12) & 0x3
        if pb != 2: continue
        l2_cid = struct.unpack_from('<H', payload, 6)[0]
        if l2_cid != 0x0004: continue
        att = payload[8:]
        if not att: continue
        src = 'HOST' if flags == 0 else 'WAND'
        opcode = att[0]

        # Decode key opcodes
        desc = ''
        if opcode == 0x08:  # READ_BY_TYPE_REQ
            start = struct.unpack_from('<H', att, 1)[0]
            end   = struct.unpack_from('<H', att, 3)[0]
            desc = f'READ_BY_TYPE_REQ 0x{start:04x}-0x{end:04x}'
        elif opcode == 0x09:  # READ_BY_TYPE_RSP
            item_len = att[1]
            item = att[2:2+item_len]
            if len(item) >= 5:
                dh = struct.unpack_from('<H', item, 0)[0]
                pr = item[2]
                vh = struct.unpack_from('<H', item, 3)[0]
                desc = f'READ_BY_TYPE_RSP decl=0x{dh:04x} props=0x{pr:02x} val=0x{vh:04x}'
        elif opcode == 0x01:  # ERROR
            desc = f'ERROR req=0x{att[1]:02x} hdl=0x{struct.unpack_from("<H", att, 2)[0]:04x} err=0x{att[4]:02x}'
        elif opcode == 0x0a:  # READ_REQ
            desc = f'READ_REQ hdl=0x{struct.unpack_from("<H", att, 1)[0]:04x}'
        elif opcode == 0x0b:  # READ_RSP
            desc = f'READ_RSP val={att[1:5].hex()}'
        elif opcode == 0x10:  # READ_BY_GROUP_TYPE_REQ
            desc = f'READ_BY_GROUP_TYPE_REQ'
        elif opcode == 0x11:  # READ_BY_GROUP_TYPE_RSP
            desc = f'READ_BY_GROUP_TYPE_RSP'
        elif opcode == 0x04:  # FIND_BY_TYPE_REQ
            desc = f'FIND_BY_TYPE_REQ'
        elif opcode == 0x05:  # FIND_INFO_RSP
            fmt = att[1]
            item_len = 4 if fmt == 1 else 18
            h = struct.unpack_from('<H', att[2:], 0)[0]
            desc = f'FIND_INFO_RSP first_handle=0x{h:04x}'
        elif opcode == 0x06:  # FIND_BY_TYPE_VALUE_REQ
            desc = f'FIND_BY_TYPE_VALUE_REQ'
        elif opcode == 0x1b:  # NOTIFY
            hdl = struct.unpack_from('<H', att, 1)[0]
            desc = f'NOTIFY hdl=0x{hdl:04x}'
        else:
            desc = f'opcode=0x{opcode:02x}'

        print(f'Pkt {pkt_num:4d} [{src}] conn=0x{conn_h:03x} {desc}  raw={att[:8].hex()}')
