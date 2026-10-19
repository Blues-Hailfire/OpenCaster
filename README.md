# OpenCaster

An unofficial, open-source reimplementation of the Warner Bros. Magic Caster
Wand experience.  OpenCaster talks to the wand directly over Bluetooth LE: it
tracks your gesture with the wand's gyro, recognises it against 52 spell
shapes, and plays that spell's original light, haptic and sound effects on
the wand (and on a Magic Caster box, if one is nearby).

## Credits

- **Spell data and audio/visual media:** credit to **uuyyyuu** and
  [uuyyyuu/magic-caster-spellbook](https://github.com/uuyyyuu/magic-caster-spellbook),
  which recovered and preserved the original Magic Caster app's spell
  definitions (`spellbook.json`: wand and box lighting/haptic effects) and its
  `zz_spell_assets` media pack (casting sounds, spell videos).  Audio and
  visual media from this source will be added to OpenCaster soon.  These files
  belong to their original owners and are **not committed** to this
  repository; they live in the gitignored `media/` folder.
- **Spell gesture SVGs:** 45 of the templates in `spells/` were traced from the
  gesture diagrams by **eigger** in
  [eigger/hass-magic-caster-wand](https://github.com/eigger/hass-magic-caster-wand/tree/master/docs/gestures)
  (MIT licence); each traced SVG names its source image.  Alohomora, Bombarda,
  Expelliarmus, Incarcerous, Incendio, Lumos and Nox were drawn for OpenCaster.

Magic Caster is a Warner Bros. product.  OpenCaster is an unofficial project
and is not affiliated with or endorsed by Warner Bros.

---

## Contents

- [Quick start](#quick-start)
- [Using the GUI](#using-the-gui)
- [Spells](#spells)
- [Spell effects](#spell-effects)
- [How recognition works](#how-recognition-works)
- [Protocol reference](#protocol-reference)
- [Project files](#project-files)
- [References](#references)

---

## Quick start

```bash
pip install bleak numpy scipy matplotlib
python wand_gui.py
```

1. **Effects (optional):** put `spellbook.json` and the media pack's files in
   `media/` (sounds in `media/sounds/`).  Without them, casting still works and
   the wand plays a generic gold pulse on success.
2. **Launch:** the GUI scans for wands and boxes and connects automatically.
3. **Calibrate:** press **Calibrate** once per wand for the best accuracy.
4. **Cast:** hold all four touch sensors, draw the spell, release.

Casting sounds use Windows MCI, so audio plays on Windows only; everything
else is plain Python.

---

## Using the GUI

### Connecting

On launch `wand_gui.py` scans for wands (`MCW-*`) and boxes (`MCB-*`):

- **Wand:** the last-used wand if it's in range (from `wand_profiles.json`),
  otherwise the first one found.  If none is found it rescans every 10 s.
- **Boxes:** every box found is connected too, shown as 📦 in the header.
- **Switching:** **Scan** and **Connect** pick a different wand.  One wand is
  used at a time.

### Casting

- **Start:** hold all four touch sensors.  The wand glows blue while the
  gesture window is open.
- **End:** release any sensor (or wait 8 s).  The trail is then matched.
- **Quick taps:** releasing within 0.5 s isn't counted as a cast.  The glow
  just switches off, with no fail flash and no label prompt.
- **Result:** a recognised spell plays its effects; anything else plays a dim
  red flash.  Every cast ends with an animation on the wand.

The trail view opens at the size of a typical cast (the median size of your
labelled casts, 45° until there are some) and only grows if a stroke runs past
it.  After a cast, the matched spell's shape is drawn over your trail as a dashed
outline (purple if accepted, red if not), with a dot and arrow marking where it
starts and which way it goes.

### Practising one spell

The **SPELLS** dropdown above the gesture trail defaults to **Any**.  Pick a
spell and its shape is drawn on the trail as a guide, starting where your
stroke starts, at the size you usually cast it (from your labelled casts of
that spell).  Only that spell can then be cast.  A cast that looks more like
another spell is rejected with "not X (closest: Y)".

### Labelling casts

With **Label casts** ticked (the default), each cast must be labelled before
the next one can start: pick the spell you actually cast, *Not a spell*, or
*Discard*.  Hovering a spell button previews its shape on the trail.  While
practising one spell, the question is just "Was that Lumos?" (for whichever
spell is selected): *Yes*, *Not a spell* or *Discard*.  Labelled
trails are saved to `casts/casts.jsonl` for tuning (see
[Tuning recognition](#tuning-recognition)).  Untick it to cast freely.

### Calibration

Press **Calibrate** while connected.  Four self-advancing steps, about 30 s:

1. Lay the wand flat → gyro bias and noise
2. Point the tip at the ceiling → tip axis
3. Swipe up → confirms the tip sign (catches a handle-up pose in step 2)
4. Swipe right → confirms the left/right sign

The result is saved as a `motion` block for that wand in `wand_profiles.json`
(keyed by MAC address) and loaded on every connect.  Without it, defaults are
used (tip +y, bias learned on the fly).

---

## Spells

Each spell is one SVG in `spells/` containing a single `<path>` in a 200×200
viewBox, drawn in casting order: **the path's start is where the gesture
starts**, because recognition takes direction into account.  The spell's name
is the file name (case-insensitive).  Name it after the spellbook entry (e.g.
`Wingardium Leviosa.svg`) so it picks up that spell's effects.

**↺ Reload Spells** reloads templates and effects without restarting.

### Adding a spell

- **Draw it:** `python spell_editor.py` lets you draw with the mouse, smooth
  the stroke and save straight to `spells/`.
- **Trace a gesture diagram:** `gesture_png_to_svg.py` traces images like
  eigger's (a stroke running from a start dot to an arrowhead).  Guide points
  in `gesture_waypoints.json` fix the drawing order (dot, corners, both sides
  of each crossing, arrow tip); between them the trace follows the drawn
  stroke's centre line.

  ```bash
  python gesture_png_to_svg.py grid  PNG_DIR out/ --only name     # gridded image to read points from
  python gesture_png_to_svg.py trace PNG_DIR out/ --only name --review out/review.png
  ```

Every extra spell is one more shape a cast can be confused with, so check new
ones with `eval_matcher.py`.

### Tuning recognition

```bash
python eval_matcher.py                   # accuracy, confusion table, suggested thresholds
python eval_matcher.py --misses          # every labelled cast the matcher got wrong
python eval_matcher.py --threshold 0.3 --margin 1.2   # try other settings
```

It re-runs every labelled cast in `casts/casts.jsonl` through the current
matcher and prints a `PER_SPELL_THRESHOLDS` block to paste into
`spell_matcher.py`.

---

## Spell effects

`spell_effects.py` plays the original app's effects when a spell is
recognised.  It reads everything from `media/`, which is gitignored:

| Effect | Source | Notes |
|--------|--------|-------|
| Wand lights + haptics | `config_wand.macros_payoff` in `media/spellbook.json` | Encoded like the app's `MacroFactory` (see [Lights and haptics](#lights-and-haptics)) |
| Box lights | `config_wandbox.macros_payoff` | Sent to every connected box; **not yet verified on hardware** |
| Casting sound | 5 MP3s per spell in `media/sounds/` | One is picked at random |
| Videos | `media/*.mp4` | Not used yet |

Sounds are matched to spells by file name, ignoring spaces and punctuation
(`sfx_lumos_cast_01.mp3` → Lumos); each file goes to the longest spell name it
contains, so Lumos doesn't pick up Lumos Maxima's sounds.  Spells without a
wand macro fall back to the generic gold pulse.

---

## How recognition works

### Gesture tracking (`motion.py`)

The trail is the direction the wand tip points, in degrees, from the gyro:

```
every IMU sample
  ├─ not in a gesture: update gyro bias (rolling still-detector)
  │                    and world-up (low-passed accel)
  └─ in a gesture:
       ω = gyro − bias
       up ← up − (ω × up)·dt        world-up carried through the motion by the gyro
       v  = ω × tip                 tip velocity (wrist roll drops out)
       right += v · unit(tip × up)·dt     (degrees)
       up    += v · up·dt
       tip speed < min_rate → ignored;  point appended every min_step degrees
```

Because "up" is real world-up, the trail keeps its orientation: a Λ stays a Λ
however the wand is held.  (An earlier accelerometer pipeline plotted tilt plus
jolt rather than movement; `wand_tuner.py` keeps it as "Accel (legacy)" for
comparison only.)

### Matching (`spell_matcher.py`)

1. **Gates:** trails under 20 points or spanning less than 15° are rejected.
2. **Prepare:** trim 3% of the path from each end, resample to 64 points,
   smooth, and centre/scale by the larger bounding-box side.
3. **Compare:** banded DTW on position **and** stroke direction against every
   template, allowing only ±20° of tilt and no reversal.
4. **Decide:** accept the best spell only if its score is under its threshold
   (default 0.30) **and** the runner-up scores at least 1.25× worse.

---

## Protocol reference

### Hardware

| Device | Name prefix | Chipset |
|--------|-------------|---------|
| Wand   | `MCW-###`   | Nordic nRF52832 |
| Box    | `MCB-###`   | Nordic nRF52810 |

The wand works standalone; the box is optional.

### BLE services

| UUID | Type | Purpose |
|------|------|---------|
| `57420001-…c577` | Service | Custom wand service |
| `57420002-…c577` | Write (handle `0x0014`) | Commands to the wand (write-without-response) |
| `57420003-…c577` | Notify (handle `0x0015`) | Events from the wand |
| `00002a19-…34fb` | Notify / Read | Battery level |
| `8ec90003-…ea50` | Indicate / Write | Nordic DFU (firmware update) |

### Lights and haptics

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

Haptics need this init sequence once per connection (`hw_init()` in `wand.py`):

```
00  08  09  0e02  0e04  0e08  0e09  0e01
dd00 dd04 dd01 dd05 dd02 dd06 dd03 dd07
dc0007 dc040a dc0107 dc050a dc0207 dc060a dc0307 dc070a
dd00 dd04 dd01 dd05 dd02 dd06 dd03 dd07
```

### Notifications (wand → host, on `57420003`)

| First byte | Meaning | Format |
|------------|---------|--------|
| `0x01` | Keepalive challenge | Reply by writing `0x01`, or the wand disconnects |
| `0x10` | Touch sensors | `10 [mask]`: bit 0–3 = sensors 1–4 (`0x0F` = all held) |
| `0x24` | Spell recognised by the wand's firmware | `24 00 00 [len] [utf-8 name]`, e.g. `2400000750726f7465676f` → `Protego` |
| `0x2C` | IMU samples | See below |

A firmware spell broadcast is handled like one of OpenCaster's own matches and
plays that spell's effects.

### IMU stream

Enable with two writes to `57420002`: `0x31` (reset), then `0x30 0x00 0x80`
(start).  Packets arrive as opcode `0x2C`:

```
[0x2C][seq: u16 LE][count]  then count × 12 bytes:
[gx: i16][gy: i16][gz: i16][ax: i16][ay: i16][az: i16]
```

Measured from `imu_probe_log.csv`:

- **220 Hz**, 19 samples per packet (~11.6 packets/s).  All samples in a packet
  share one arrival time, so the pipeline uses a fixed dt = 1/220 s.
- Accel 2048 counts/g (±16 g).  Gyro 0.0625 °/s per count (±2000 °/s); fast
  flicks can clip it.
- Gyro bias ≈1 °/s, drifting slowly.  Still-noise 0.1–0.7 °/s.
- The tip defaults to sensor **+y** (both rest poses read ≈0 g on y, and swing
  centripetal force lands on y).  **Calibrate** measures it per wand.

---

## Project files

| Path | Purpose |
|------|---------|
| `wand_gui.py` | Main app: connect, cast, practise, label |
| `wand.py` | BLE UUIDs, opcodes, LED/haptic frame builders, built-in animations |
| `motion.py` | Gyro gesture tracker (shared by GUI, tuner and replay) |
| `spell_matcher.py` | DTW recogniser and per-spell thresholds |
| `spell_shapes.py` | SVG template loader |
| `spell_effects.py` | Original wand/box macros and casting sounds |
| `cast_log.py` | Labelled-cast storage (`casts/casts.jsonl`) |
| `eval_matcher.py` | Scores the matcher against labelled casts |
| `spell_editor.py` | Mouse-drawn spell template editor |
| `gesture_png_to_svg.py`, `gesture_waypoints.json` | Gesture-diagram tracer and its guide points |
| `wand_calibrator.py` | Guided motion calibration |
| `wand_profiles.py`, `wand_profiles.json` | Per-wand calibration and last-used wand |
| `wand_tuner.py` | Live pipeline tuner; **Save Capture** records raw samples to `captures/` |
| `replay_capture.py` | Replays captures offline with spell scores |
| `imu_probe.py`, `NordicSemiUpdateRecon.py` | BLE/IMU research tools |
| `spells/` | Spell templates (52) |
| `media/` | Spellbook and media pack (gitignored, supply your own) |
| `casts/` | Labelled casts |
| `archive/`, `apk_extract/` | Earlier research scripts and decompiled app fragments |
| `analyze_thresholds.py`, `feedback_log.csv` | Legacy: superseded by `eval_matcher.py` |

---

## References

- Nordic announcement: <https://www.nordicsemi.com/Nordic-news/2022/10/Interactive-smart-wand-from-Warner-Bros-Home-Entertainment-uses-nRF52832-SoC>
- Nordic nRF52832: <https://www.nordicsemi.com/Products/nRF52832>
- Nordic nRF52810: <https://www.nordicsemi.com/Products/nRF52810>
- APK: `Harry Potter Magic Caster Wand_3.9.4_APKPure.xapk`
- BT snoop log: `Bluetooth Capture/HP Bluetooth log.btsnoop`
