# OpenCaster
A reverse engineering project for the Warner Bros Magic Caster Wand.

## Hardware

| Device | Name prefix | Chipset | Source |
|--------|-------------|---------|--------|
| Wand   | `MCW-###`   | Nordic nRF52832 | [Nordic news](https://www.nordicsemi.com/Nordic-news/2022/10/Interactive-smart-wand-from-Warner-Bros-Home-Entertainment-uses-nRF52832-SoC) |
| Box    | `MCB-###`   | Nordic nRF52810 | Same source |

---

## BLE Services & Characteristics

| UUID | Type | Purpose |
|------|------|---------|
| `57420001-587e-48a0-974c-544d6163c577` | Service | Custom wand service |
| `57420002-587e-48a0-974c-544d6163c577` | Write (handle `0x0014`) | Send commands to wand |
| `57420003-587e-48a0-974c-544d6163c577` | Notify | Receive events from wand |
| `00002a19-0000-1000-8000-00805f9b34fb` | Notify/Read | Battery level |
| `8ec90003-f315-4f60-9fb8-838830daea50` | Indicate/Write | Nordic DFU (firmware update) |

---

## LED Control Protocol

All LED commands are written to handle `0x0014` (characteristic `57420002`).
Use `write_gatt_char(..., response=False)` — the characteristic supports write-without-response.

### Frame format
Every write starts with `0x68`, followed by one or more commands concatenated:

```
0x68  [cmd1]  [cmd2]  ...
```

### Command opcodes

| Opcode | Name | Payload | Total bytes |
|--------|------|---------|-------------|
| `0x22` | changeled | `[group:1] [r:1] [g:1] [b:1] [duration_ms:2 LE]` | 7 |
| `0x10` | delay | `[duration_ms:2 LE]` | 3 |
| `0x16` | setloops | `[count:1]` | 2 |
| `0x80` | loop marker | none | 1 |

- **group**: 0–3 (individual LEDs). All 4 must be set separately for full wand coverage.
- **duration_ms**: milliseconds as little-endian uint16.
- **r/g/b**: 0–255 each.

### Example — set all groups red for 800ms
```
68  22 00 ff 00 00 20 03
    22 01 ff 00 00 20 03
    22 02 ff 00 00 20 03
    22 03 ff 00 00 20 03
```

### Example — clear all LEDs (500ms fade)
```
68  22 00 00 00 00 f4 01
    22 01 00 00 00 f4 01
    22 02 00 00 00 f4 01
    22 03 00 00 00 f4 01
```

---

## Notification Events (wand → host)

Received on characteristic `57420003`.

### Type A — status/IMU event (2 bytes)

| Hex | Label |
|-----|-------|
| `1000` | Idle / Ready |
| `1001` | Button / Motion trigger |
| `1002` | Action Ack / End |
| `1003` | Event 3 |
| `1006` | Event 6 |
| `1008` | IMU motion burst start |
| `1009` | IMU motion sample |
| `100a` | IMU axis A |
| `100b` | Gesture window open |
| `100c` | Gesture alt C |
| `100d` | Gesture alt D |
| `100e` | Orientation change |
| `100f` | Gesture window close |

### Type B — heartbeat (3 bytes)
```
01 40 01   — periodic keepalive, fires every ~2s
```

### Type C — spell name (variable)
```
24 00 00 [length:1] [utf-8 spell name]
```
Example: `2400000750726f7465676f` → `Protego`

Gesture recognition runs **on the wand firmware** (nRF52832).
Spell names are transmitted directly over BLE — the box is not required for decoding.

---

## Known Spells (observed)
| Spell | Notes |
|-------|-------|
| Protego | Shield charm |
| Serpensortia | Snake conjuration |

---

## Haptic Control Protocol

Haptic buzz is embedded inside the `0x68` LED frame using opcode `0x50`:

```
0x68  0x50  [intensity_lo]  [intensity_hi]  [optional LED commands...]
```

- Intensity is a uint16 LE — `100` (`0x6400`) = normal, `200` (`0xc800`) = strong
- `0x60` arms/executes the frame, `0x40` stops it
- A one-time init sequence must be sent after connecting (see `buzz_control.py`)

### Init sequence (once per connection)
```
00 → 08 → 09 → 0e02 → 0e04 → 0e08 → 0e09 → 0e01
→ dd00 dd04 dd01 dd05 dd02 dd06 dd03 dd07
→ dc0007 dc040a dc0107 dc050a dc0207 dc060a dc0307 dc070a
→ dd00 dd04 dd01 dd05 dd02 dd06 dd03 dd07
```

### Example — buzz only
```
60          (arm/execute)
68 50 64 00 (buzz frame, intensity=100)
40          (stop)
```

### Example — buzz + red LED flash
```
60
68 50 64 00  22 00 ff 00 00 e8 03
             22 01 ff 00 00 e8 03
             22 02 ff 00 00 e8 03
             22 03 ff 00 00 e8 03
40
```

---

## Tools

| File | Purpose |
|------|---------|
| `Bluetooth Info Test.py` | Main research tool — listen, dual, spell_capture, state_probe, command modes |
| `led_control.py` | LED color control — `--color`, `--clear`, `--demo` |
| `buzz_control.py` | Haptic buzz control — `--buzz`, `--intensity`, `--demo` |
| `scan_devices.py` | Quick BLE scanner to confirm wand/box are advertising |
| `led_probe.py` / `led_probe2.py` | Historical opcode fuzzing (superseded) |

---

## Source References
- Nordic nRF52832: https://www.nordicsemi.com/Products/nRF52832
- Nordic nRF52810: https://www.nordicsemi.com/Products/nRF52810
- APK: `Harry Potter Magic Caster Wand_3.9.4_APKPure.xapk`
- BT snoop log: `Bluetooth Capture/HP Bluetooth log.btsnoop` (captured from official Android app)
