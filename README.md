# OpenCaster
Reverse-engineering and open-source reimplementation of the Warner Bros Magic Caster Wand.

Connects directly to the wand over BLE, decodes its events, drives LEDs and haptics,
and recognises custom spell gestures using a DTW shape-matching pipeline — no box required.

---

## Hardware

| Device | Name prefix | Chipset | Source |
|--------|-------------|---------|--------|
| Wand   | `MCW-###`   | Nordic nRF52832 | [Nordic news](https://www.nordicsemi.com/Nordic-news/2022/10/Interactive-smart-wand-from-Warner-Bros-Home-Entertainment-uses-nRF52832-SoC) |
| Box    | `MCB-###`   | Nordic nRF52810 | Same source |

The wand operates fully standalone — the box is not required for any feature in this project.

---

## Quick Start

```bash
pip install bleak numpy scipy matplotlib
python wand_gui.py
```

On first launch, press **Scan** to find your wand, then **Connect**.
A calibration prompt will appear; run it once for best gesture accuracy.
On subsequent launches the GUI auto-connects to the last used wand.

---

## Repository Layout

```
OpenCaster/
├── wand_gui.py          # Main GUI — live events, gesture trail, spell matching
├── wand.py              # Shared BLE helpers, LED/haptic frame builders
├── spell_matcher.py     # DTW spell recognition engine
├── spell_shapes.py      # SVG template loader and normaliser
├── spell_editor.py      # Mouse-drawn spell shape editor (standalone)
├── wand_calibrator.py   # Guided IMU axis calibration wizard
├── wand_profiles.py     # Per-wand calibration storage (wand_profiles.json)
├── spells/              # SVG spell shape templates (one file per spell)
├── sounds/              # Optional .wav files played on successful cast
├── calibration.json     # Most-recently-saved calibration (auto-generated)
├── wand_profiles.json   # Per-wand calibration store (auto-generated)
├── feedback_log.csv     # User feedback on spell match quality (auto-generated)
├── archive/             # Historical research scripts (superseded)
└── apk_extract/         # Decompiled APK source fragments
```

---

## BLE Services & Characteristics

| UUID | Type | Purpose |
|------|------|---------|
| `57420001-…c577` | Service | Custom wand service |
| `57420002-…c577` | Write (handle `0x0014`) | Send commands to wand |
| `57420003-…c577` | Notify (handle `0x0015`) | Receive events from wand |
| `00002a19-…34fb` | Notify / Read | Battery level |
| `8ec90003-…ea50` | Indicate / Write | Nordic DFU (firmware update) |

All command writes go to `57420002` using **write-without-response**.

---

## LED Control Protocol

### Frame format
Every write begins with `0x68`, followed by one or more commands concatenated:

```
0x68  [cmd1]  [cmd2]  ...
```

### Command opcodes

| Opcode | Name | Payload | Total bytes |
|--------|------|---------|-------------|
| `0x22` | changeled | `[group:1][r:1][g:1][b:1][duration_ms:2 LE]` | 7 |
| `0x10` | delay | `[duration_ms:2 LE]` | 3 |
| `0x16` | setloops | `[count:1]` | 2 |
| `0x80` | loop marker | *(none)* | 1 |

- **group** 0–3 maps tip→handle (group 0 = tip, group 3 = handle).
- **duration_ms** is little-endian uint16; max is 65535 (≈ permanent).

### Example — all groups red for 800 ms
```
68  22 00 ff 00 00 20 03
    22 01 ff 00 00 20 03
    22 02 ff 00 00 20 03
    22 03 ff 00 00 20 03
```

---

## Haptic Protocol

Embed haptic inside the `0x68` LED frame using opcode `0x50`:

```
0x68  0x50  [intensity_lo]  [intensity_hi]  [optional LED commands...]
```

- Intensity is uint16 LE: `100` = normal, `200` = strong.
- `0x60` arms/executes the frame; `0x40` stops it.
- Send the init sequence once per connection (see `hw_init()` in `wand.py`).

### Init sequence (once per connection)
```
00  08  09  0e02  0e04  0e08  0e09  0e01
dd00 dd04 dd01 dd05 dd02 dd06 dd03 dd07
dc0007 dc040a dc0107 dc050a dc0207 dc060a dc0307 dc070a
dd00 dd04 dd01 dd05 dd02 dd06 dd03 dd07
```

---

## Notification Events (wand → host)

Received on `57420003`.

### Type A — status / gesture event (2 bytes)

| Hex | Label |
|-----|-------|
| `1000` | Idle / Ready |
| `1001` | Button / Motion trigger |
| `1002` | Action Ack / End |
| `1008` | Grip detected |
| `1009` | Grip deepening |
| `100a` | Grip fully engaged |
| `100b` | **Gesture window open** |
| `100c` | Gesture alt C |
| `100d` | Gesture alt D |
| `100e` | Orientation change |
| `100f` | **Gesture window close** |

### Type B — heartbeat (3 bytes)
```
01 40 01   — periodic keepalive, ~every 2 s
```

### Type C — spell name broadcast (variable)
```
24 00 00 [length:1] [utf-8 spell name]
```
Example: `2400000750726f7465676f` → `Protego`

The wand runs gesture recognition on-device and broadcasts the matched spell name over BLE.
OpenCaster ignores this broadcast and performs its own shape-matching against custom templates.

---

## IMU & Gesture Pipeline

The wand's nRF52832 streams 6-axis IMU bursts on a hidden GATT handle (`0x0016`)
discoverable only via raw ATT writes — Windows GATT cache does not surface it.
`wand.py::imu_subscribe()` bypasses the cache by writing directly to the CCCD
at handle `0x0017` via the WinRT `GattSession` API.

### Packet format (handle 0x0016, 232 bytes)
```
[0x2c: marker][seq:u16 LE][0x13: 19 samples]
then 19 × 12 bytes:  [ax:i16][ay:i16][az:i16][gx:i16][gy:i16][gz:i16]
```

### Gesture detection flow

```
IMU burst arrives (~30 Hz)
  └─ axis selection (calibrated horizontal/vertical axes)
  └─ velocity-zeroing baseline (first 3 samples subtracted)
  └─ EMA smoothing (α = 0.8)
  └─ dead-zone with hysteresis
       • stop drawing when magnitude < 300 counts
       • resume drawing only when magnitude > 450 counts  (1.5× hysteresis)
  └─ direct accel → position  (no velocity integration)
  └─ trail appended to deque

Gesture window close (100f / 1000)
  └─ trail trimmed (last 5 pts removed — wrist-settle artifact)
  └─ SpellMatcher.match_all() scores all loaded templates
       • normalise → resample → Savitzky-Golay smooth → re-normalise
       • DTW over 8 rotations × forward + reverse (16 candidates)
       • score normalised to [0, 1]; 0 = perfect match
  └─ best match below threshold → spell success animation + sound
  └─ miss → dim red flash, hint line shows top-3 closest matches
```

### Calibration

Run the calibration wizard (**Calibrate** button in the GUI) to capture your
casting style.  The wizard collects IMU samples for up/down/left/right gestures
and computes:
- which raw axis maps to vertical vs horizontal drawing
- dead-zone floor (10% of peak response, minimum 300 counts)
- per-axis scale (normalises a full-force gesture to ±5000 plot units)

Results are saved to `calibration.json` and to a per-wand profile in
`wand_profiles.json` (keyed by MAC address), so each wand remembers its own
calibration across sessions.

---

## Auto-Connect

On launch, `wand_gui.py` reads `wand_profiles.json` for the most recently
connected wand (tracked by `last_connected` timestamp), performs a silent
background BLE scan, and connects automatically if the wand is in range.
No user action is needed on subsequent launches.

A minimal stub entry is written to `wand_profiles.json` on every successful
connection — even before calibration — so auto-connect works from the very
second launch onwards.

---

## Spell Templates

Spell shapes live in `spells/` as plain SVG files.  Each file contains a
single `<path>` drawn in a 200×200 viewBox.  The loader:

1. Parses all path commands (M/L/H/V/C/Q/Z) including cubic and quadratic Béziers.
2. Resamples to 64 evenly-spaced points by arc length.
3. Flips the Y axis (SVG is top-down; wand accelerometer is bottom-up).
4. Normalises to zero-centred unit extent.

### Adding a new spell

**Option A — Spell Editor (recommended)**
```bash
python spell_editor.py
```
Draw with your mouse, adjust RDP simplification and Chaikin smoothing,
then save directly to `spells/`.

**Option B — manual SVG**
Create `spells/MySpell.svg` with a `<path>` in a `200×200` viewBox.
The spell name is the filename (case-insensitive).

### Tuning match thresholds

Edit `PER_SPELL_THRESHOLDS` in `spell_matcher.py` to tighten or loosen
recognition per spell.  Use `feedback_log.csv` (written after every cast
when you click ✓/✗) to see real score distributions.

---

## Known Spells (observed from wand firmware broadcast)

| Spell | Hex |
|-------|-----|
| Protego | `2400000750726f7465676f` |
| Serpensortia | *(observed in live logs)* |

---

## Key Files

| File | Purpose |
|------|---------|
| `wand_gui.py` | Main GUI dashboard — connect, visualise, cast |
| `wand.py` | BLE helpers, LED/haptic frame builders, IMU subscription |
| `spell_matcher.py` | DTW recogniser with rotation search and per-spell thresholds |
| `spell_shapes.py` | SVG → normalised point array loader |
| `spell_editor.py` | Mouse-drawn spell template editor |
| `wand_calibrator.py` | Guided 4-direction IMU axis calibration wizard |
| `wand_profiles.py` | Per-wand calibration + auto-connect profile store |
| `NordicSemiUpdateRecon.py` | BLE recon tool — subscribes to all safe characteristics |
| `analyze_thresholds.py` | Offline analysis of `feedback_log.csv` score distributions |

---

## Source References

- Nordic nRF52832: https://www.nordicsemi.com/Products/nRF52832
- Nordic nRF52810: https://www.nordicsemi.com/Products/nRF52810
- Nordic announcement: https://www.nordicsemi.com/Nordic-news/2022/10/Interactive-smart-wand-from-Warner-Bros-Home-Entertainment-uses-nRF52832-SoC
- APK: `Harry Potter Magic Caster Wand_3.9.4_APKPure.xapk`
- BT snoop log: `Bluetooth Capture/HP Bluetooth log.btsnoop`
