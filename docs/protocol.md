# Protocol reference

[← OpenCaster](../README.md) · [Documentation](README.md)

## Hardware

| Device | Name prefix | Chipset |
|--------|-------------|---------|
| Wand   | `MCW-###`   | Nordic nRF52832 |
| Box    | `MCB-###`   | Nordic nRF52810 |

The wand works standalone; the box is optional.

## BLE services

| UUID | Type | Purpose |
|------|------|---------|
| `57420001-…c577` | Service | Custom wand service |
| `57420002-…c577` | Write (handle `0x0014`) | Commands to the wand (write-without-response) |
| `57420003-…c577` | Notify (handle `0x0015`) | Events from the wand |
| `00002a19-…34fb` | Notify / Read | Battery level |
| `8ec90003-…ea50` | Indicate / Write | Nordic DFU (firmware update) |

## Lights and haptics

Effects are sent as frames: `0x68` followed by commands.  OpenCaster writes
`0x60` before each frame, as observed from the app; `0x40` clears the LEDs.

| Opcode | Command | Payload | Bytes |
|--------|---------|---------|-------|
| `0x22` | changeled | `[group][r][g][b][duration_ms: u16 LE]` | 7 |
| `0x10` | delay | `[duration_ms: u16 LE]` | 3 |
| `0x50` | buzz | `[duration_ms: u16 LE]` | 3 |

- **Groups:** 0–3, tip to handle.  `changeled` fades over its duration and
  doesn't block, so consecutive `changeled`s run together; `delay` waits.
- **Buzz:** the official app sends a duration in ms (capped at 32767).  Older
  OpenCaster animations treat it as intensity and stop the motor with `0x40`.
- **Loops:** the app's `setloops N … loop` blocks are expanded in software,
  because the on-wand loop opcode is unconfirmed.
- **Frame size:** long effects are split at command boundaries to fit the BLE
  MTU.

Example — all groups red for 800 ms:

```
68  22 00 ff 00 00 20 03
    22 01 ff 00 00 20 03
    22 02 ff 00 00 20 03
    22 03 ff 00 00 20 03
```

Haptics need this init sequence once per connection (`protocol.HW_INIT`):

```
00  08  09  0e02  0e04  0e08  0e09  0e01
dd00 dd04 dd01 dd05 dd02 dd06 dd03 dd07
dc0007 dc040a dc0107 dc050a dc0207 dc060a dc0307 dc070a
dd00 dd04 dd01 dd05 dd02 dd06 dd03 dd07
```

## Notifications (wand → host, on `57420003`)

| First byte | Meaning | Format |
|------------|---------|--------|
| `0x01` | Keepalive challenge | Reply by writing `0x01`, or the wand disconnects (OpenCaster also answers `0x02`) |
| `0x10` | Touch sensors | `10 [mask]`: bit 0–3 = sensors 1–4 (`0x0F` = all held) |
| `0x24` | Spell recognised by the wand's firmware | `24 00 00 [len] [utf-8 name]`, e.g. `2400000750726f7465676f` → `Protego` |
| `0x2C` | IMU samples | See below |
| `0x08`, `0x09`, `0x0E`, `0xDD` | Replies to the init sequence | Wand address, paired box address, product info (serial, SKU), pad thresholds |

A firmware spell broadcast is handled like one of OpenCaster's own matches and
plays that spell's effects.

## IMU stream

Enable with two writes to `57420002`: `0x31` (reset), then `0x30 0x00 0x80`
(start).  Packets arrive as opcode `0x2C`:

```
[0x2C][seq: u16 LE][count]  then count × 12 bytes:
[gx: i16][gy: i16][gz: i16][ax: i16][ay: i16][az: i16]
```

Measured on hardware:

- **220 Hz**, 19 samples per packet (~11.6 packets/s).  All samples in a packet
  share one arrival time, so the pipeline uses a fixed dt = 1/220 s.
- Accel 2048 counts/g (±16 g).  Gyro 0.0625 °/s per count (±2000 °/s); fast
  flicks can clip it.
- Gyro bias ≈1 °/s, drifting slowly.  Still-noise 0.1–0.7 °/s.
- The tip is sensor **+y** (both rest poses read ≈0 g on y, and swing
  centripetal force lands on y) on every wand, so it isn't calibrated.

## References

- Nordic announcement: <https://www.nordicsemi.com/Nordic-news/2022/10/Interactive-smart-wand-from-Warner-Bros-Home-Entertainment-uses-nRF52832-SoC>
- Nordic nRF52832: <https://www.nordicsemi.com/Products/nRF52832>
- Nordic nRF52810: <https://www.nordicsemi.com/Products/nRF52810>
- APK: `Harry Potter Magic Caster Wand_3.9.4_APKPure.xapk`
- BT snoop log: `Bluetooth Capture/HP Bluetooth log.btsnoop`
