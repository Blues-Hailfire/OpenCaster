import struct

with open(r'C:\Users\Hailfire\OneDrive\Documents\OpenCaster\Bluetooth Capture\HP Bluetooth log.btsnoop', 'rb') as f:
    f.read(16)  # file header
    pkt_num = 0
    imu_packets = []

    while True:
        rec_hdr = f.read(24)
        if len(rec_hdr) < 24:
            break
        orig_len, incl_len, flags, drops, ts_sec, ts_usec = struct.unpack('>IIIIii', rec_hdr)
        payload = f.read(incl_len)
        pkt_num += 1

        # flags=1 = device->host (FROM wand). Look for 1008/1009/100a with trailing data.
        if flags == 1 and len(payload) >= 8:
            for i in range(len(payload) - 1):
                if payload[i] == 0x10 and payload[i+1] in (0x08, 0x09, 0x0a):
                    code = payload[i+1]
                    remainder = payload[i+2:]
                    if len(remainder) >= 4:
                        imu_packets.append((pkt_num, code, payload.hex(), remainder))
                    break

print(f'Found {len(imu_packets)} IMU packets with payload data\n')
for pkt_num, code, raw_hex, data in imu_packets[:40]:
    vals = [struct.unpack_from('<h', data, j)[0] for j in range(0, len(data)-1, 2)]
    print(f'Pkt {pkt_num:5d} | 10{code:02x} | len={len(data):2d} | int16s={vals[:6]}  | raw_tail={data[:12].hex()}')
