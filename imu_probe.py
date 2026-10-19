"""
imu_probe.py — IMU diagnostic logger for OpenCaster
=====================================================
Connects to the wand, streams IMU data for 30 seconds,
and writes a CSV with raw and scaled values so we can
calibrate ACCEL_SCALE and IMU_DEAD_ZONE from real data.

Usage:
    python imu_probe.py

Output: imu_probe_log.csv
"""

import asyncio, csv, struct, time
from bleak import BleakScanner, BleakClient

WRITE_UUID  = "57420002-587e-48a0-974c-544d6163c577"
NOTIFY_UUID = "57420003-587e-48a0-974c-544d6163c577"

IMU_ACCEL_SCALE = 0.00048828125
IMU_GYRO_SCALE  = 0.0010908308

DURATION_S = 30
LOG_FILE   = "imu_probe_log.csv"

samples_collected = []
start_time = None

def decode_imu(data: bytes):
    if not data or data[0] != 0x2C or len(data) < 4:
        return []
    count = data[3]
    if len(data) < 4 + count * 12:
        return []
    out = []
    off = 4
    for _ in range(count):
        gx, gy, gz, ax, ay, az = struct.unpack_from('<hhhhhh', data, off)
        off += 12
        out.append((ax, ay, az, gx, gy, gz))
    return out

def handle_notification(sender, data):
    global start_time
    if not data or data[0] != 0x2C:
        # Still reply to challenge pings so we don't drop
        return
    t = time.time() - start_time
    for ax, ay, az, gx, gy, gz in decode_imu(data):
        # Scaled values
        ax_g = ax * IMU_ACCEL_SCALE
        ay_g = ay * IMU_ACCEL_SCALE
        az_g = az * IMU_ACCEL_SCALE
        mag  = (ax_g**2 + ay_g**2 + az_g**2) ** 0.5
        samples_collected.append({
            't': round(t, 4),
            'ax_raw': ax, 'ay_raw': ay, 'az_raw': az,
            'gx_raw': gx, 'gy_raw': gy, 'gz_raw': gz,
            'ax_g': round(ax_g, 5), 'ay_g': round(ay_g, 5), 'az_g': round(az_g, 5),
            'accel_mag_g': round(mag, 5),
        })

async def pong_loop(client):
    """Reply to CHALLENGE pings to keep connection alive."""
    while True:
        await asyncio.sleep(0.5)

async def main():
    global start_time

    print("Scanning for wand...")
    devices = await BleakScanner.discover(timeout=8)
    wand = next((d for d in devices if d.name and d.name.startswith("MCW")), None)
    if not wand:
        print("No wand found.")
        return
    print(f"Found {wand.name} ({wand.address})")

    async with BleakClient(wand.address, timeout=20) as client:
        print("Connected. Subscribing...")

        # Challenge pong handler
        async def _notify(sender, data):
            if data and data[0] == 0x01:
                try:
                    await client.write_gatt_char(WRITE_UUID, bytes([0x01]), response=False)
                except Exception:
                    pass
            handle_notification(sender, data)

        await client.start_notify(NOTIFY_UUID, _notify)
        await asyncio.sleep(0.3)

        # Start IMU streaming
        await client.write_gatt_char(WRITE_UUID, bytes([0x31]), response=False)
        await asyncio.sleep(0.1)
        await client.write_gatt_char(WRITE_UUID, bytes([0x30, 0x00, 0x80]), response=False)

        start_time = time.time()
        print(f"\nLogging for {DURATION_S}s — wave the wand around now!")
        print("STILL for 5s first, then do casting motions, then hold STILL again.\n")

        await asyncio.sleep(DURATION_S)

        await client.write_gatt_char(WRITE_UUID, bytes([0x31]), response=False)
        await client.stop_notify(NOTIFY_UUID)

    # Write CSV
    if not samples_collected:
        print("No IMU samples captured.")
        return

    with open(LOG_FILE, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=samples_collected[0].keys())
        w.writeheader()
        w.writerows(samples_collected)

    # Print summary stats
    import statistics
    ax_g_vals = [s['ax_g'] for s in samples_collected]
    ay_g_vals = [s['ay_g'] for s in samples_collected]
    az_g_vals = [s['az_g'] for s in samples_collected]
    mag_vals  = [s['accel_mag_g'] for s in samples_collected]
    ax_raw    = [s['ax_raw'] for s in samples_collected]

    print(f"\n=== IMU PROBE RESULTS ({len(samples_collected)} samples) ===")
    print(f"{'':10} {'ax_g':>10} {'ay_g':>10} {'az_g':>10} {'mag_g':>10}")
    for label, vals in [('min', [min(ax_g_vals), min(ay_g_vals), min(az_g_vals), min(mag_vals)]),
                        ('max', [max(ax_g_vals), max(ay_g_vals), max(az_g_vals), max(mag_vals)]),
                        ('mean', [statistics.mean(ax_g_vals), statistics.mean(ay_g_vals),
                                  statistics.mean(az_g_vals), statistics.mean(mag_vals)]),
                        ('stdev', [statistics.stdev(ax_g_vals), statistics.stdev(ay_g_vals),
                                   statistics.stdev(az_g_vals), statistics.stdev(mag_vals)])]:
        print(f"{label:10} {vals[0]:>10.4f} {vals[1]:>10.4f} {vals[2]:>10.4f} {vals[3]:>10.4f}")

    print(f"\nax_raw range: {min(ax_raw)} to {max(ax_raw)}")
    print(f"\nSaved to {LOG_FILE}")

if __name__ == "__main__":
    asyncio.run(main())
