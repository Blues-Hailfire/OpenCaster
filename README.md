# OpenCaster

An unofficial, open-source reimplementation of the Warner Bros. Magic Caster
Wand experience.  OpenCaster talks to the wand directly over Bluetooth LE: it
tracks your gesture with the wand's gyro, recognises it against 52 spell
shapes, and plays that spell's original light, haptic, sound and video
effects (on the wand, and on a Magic Caster box if one is nearby).  Several
wands can cast at once, two wizards can duel, and other programs can drive
the wands through a local API.

## Credits

- **Spell data and audio/visual media:** credit to **uuyyyuu** and
  [uuyyyuu/magic-caster-spellbook](https://github.com/uuyyyuu/magic-caster-spellbook),
  which recovered and preserved the original Magic Caster app's spell
  definitions (`spellbook.json`: wand and box lighting/haptic effects) and its
  `zz_spell_assets` media pack (casting sounds, spell videos), which OpenCaster
  plays when you cast.  These files belong to their original owners and are
  **not committed** to this repository; they live in the gitignored `media/`
  folder.
- **Spell gesture SVGs:** 45 of the templates in `spells/` were traced from the
  gesture diagrams by **eigger** in
  [eigger/hass-magic-caster-wand](https://github.com/eigger/hass-magic-caster-wand/tree/master/docs/gestures)
  (MIT licence); each traced SVG names its source image.  The spell icons in
  `spells/icons/` are those original PNGs, unmodified (licence alongside).  Alohomora, Bombarda,
  Expelliarmus, Incarcerous, Incendio, Lumos and Nox were drawn for OpenCaster.

Magic Caster is a Warner Bros. product.  OpenCaster is an unofficial project
and is not affiliated with or endorsed by Warner Bros.

---

## Contents

- [Quick start](#quick-start)
- [Using the GUI](#using-the-gui)
- [Wizard's duel](#wizards-duel)
- [Running headless](#running-headless)
- [Control API](#control-api)
- [Spells](#spells)
- [Spell effects and media](#spell-effects-and-media)
- [Architecture](#architecture)
- [How recognition works](#how-recognition-works)
- [Protocol reference](#protocol-reference)
- [Project files](#project-files)
- [References](#references)

---

## Quick start

```bash
pip install -r requirements.txt
python OpenCaster_GUI.py
```

1. **Effects (optional):** put `spellbook.json` and the media pack's files in
   `media/` (sounds in `media/sounds/`, videos anywhere under `media/`).
   Without them casting still works: the wand plays a generic pulse in its
   colour on success and the spellbook shows shapes only.
2. **Launch:** the app scans for wands and boxes and connects automatically.
3. **Calibrate:** press **Calibrate** once per wand for the best accuracy.
4. **Cast:** hold all four touch pads, draw the spell, release.

Requires Python 3.11+.  Sounds and videos play through Qt Multimedia, so
they work on every platform PySide6 supports.

---

## Using the GUI

Three pages: **Cast**, **Spellbook** and **Duel**.  The header shows a pill
for every connected wand (its colour, nickname and battery) and any boxes;
**⚙** opens Settings.

### Connecting (one wand or several)

- **Automatic:** on launch the wands that were connected last time are
  reconnected whenever they're in range; with none of those around, the
  first wand found is connected.  While nothing is found it rescans every
  10 s, and a dropped link is reconnected automatically.
- **More wands:** **Scan**, pick a wand under *Found wands*, **Connect**.
  Every connected wand casts independently, each in its own stage.
- **A wand's settings:** click its pill for its nickname, colour,
  **Calibrate…** and **Disconnect** (a disconnected wand isn't reconnected
  automatically again).
- **Boxes:** every box (`MCB-*`) found is connected too.

### Casting

- **Start:** hold all four touch pads.  The wand breathes in its colour
  while the gesture window is open, the trail is drawn live with sparkles
  at the tip, and a soft wand sound plays.
- **End:** release any pad (or wait 8 s).  The trail is then matched.
- **Quick taps:** releasing within 0.5 s isn't counted as a cast.
- **Result:** a recognised spell bursts in its colours, plays its
  light/haptic effect on the wand (and box), its casting sound and its
  payoff video (Expecto Patronum is followed by your Patronus).  A failed
  cast plays a dim red flash, shows the closest shape dashed over your
  trail, and a short mishap video (not while **Label casts** is on, so the
  trail stays visible while you answer).  Videos start a moment after the
  spell's burst, and a new cast stops them.
- **Pads:** the orbs in each stage's header mirror its touch pads.  Click
  one to force it on, as a workaround for a faulty sensor (gold ring).
- **Mastery:** every successful cast counts towards mastering that spell
  (10 casts, as in the original app), kept in `progress.json`; mastering a
  spell plays the celebration video.

### Practising one spell

**Practise** defaults to **Any spell**.  Pick a spell, or press **Practise
this spell** in the Spellbook, and its shape is drawn as a guide, starting
where your stroke starts, at the size you usually cast it.  Only that spell
can then be cast; a cast that looks more like another spell is rejected with
"not X (closest: Y)".

### Labelling casts

With **Label casts** on (the default), each cast must be labelled before the
next one can start on that wand: one of the closest spells, any other spell,
*Not a spell*, or *Discard*.  Hovering a spell previews its shape on the
trail.  While practising, the question is just "Was that Lumos?".  Labelled
trails go to `casts/casts.jsonl` for tuning (see
[Tuning recognition](#tuning-recognition)).

### Spellbook

A card for every spell template, coloured with the light colours the spell
plays on the wand and showing its original gesture icon (`spells/icons/`,
falling back to the SVG shape).  Open one for its pronunciation, lore and
mastery progress, with buttons to practise it, play its effect on the wands,
play its sound or watch its video.  Expecto Patronum's page has a **Patronus**
picker and Colovaria's a **house** picker.

### Settings (⚙)

| Setting | What it does |
|---------|--------------|
| Default wand colour | The breathing cast glow and connect animation of wands without their own colour (blue until changed).  A wand's own colour is set by clicking its pill. |
| Hogwarts house | Gryffindor, Hufflepuff, Ravenclaw or Slytherin: plays the house's sound and fills Colovaria's house colour |
| Patronus | Random, or any of the 69 Patronuses that have a video; shown after Expecto Patronum (with a preview) |
| Media | Casting sounds, spell videos, mishap videos, ambient casting sound, wand-connect sound |
| Control API | Shows the API address (configured in `settings.json`) |

Core settings live in `settings.json` (shared with the headless runner and
the API); per-wand colour and nickname in `wand_profiles.json`.

### Calibration

Press **Calibrate** (or **Calibrate…** in a wand's settings) while
connected.  Four self-advancing steps, about 30 s:

1. Lay the wand flat → gyro bias and noise
2. Point the tip at the ceiling → tip axis
3. Swipe up → confirms the tip sign (catches a handle-up pose in step 2)
4. Swipe right → confirms the left/right sign

The result is saved as a `motion` block for that wand in `wand_profiles.json`
(keyed by MAC address) and loaded on every connect.  Without it, defaults are
used (tip +y, bias learned on the fly).

**Diagnostics** shows match scores, the live IMU samples and an event log.

---

## Wizard's duel

The original app's duelling mode: two wizards, one spell.  Connect two wands,
open **Duel**, pick the wizards and the spell pool, and **Begin the duel**.

- Each round both wizards are shown the same spell: a 3-2-1 countdown (each
  wand pulses in its colour), then **Cast!**  The first to cast that spell
  wins the round; the winner's wand plays the spell, the other fades red.
- A gesture started during the countdown doesn't count, and neither does a
  different spell.
- First to three round wins takes the duel (best of five).  A round nobody
  wins in 30 s is void; **Skip spell** voids it by hand; after 9 rounds the
  higher score wins.
- **Spell pools:** *Spells you've cast* (the default: spells you've been
  recognised casting, so rounds don't stall on shapes that won't
  recognise), *All spells*, or one difficulty.
- The duel opens with the intro video, each round ends with the winning
  spell's video, and the winner gets confetti, a rainbow on their wand and
  the celebration video.  **Rematch** starts again.

Labelling and the practice spell are suspended during a duel and restored
afterwards.  Headless: `python -m opencaster --duel`.

---

## Running headless

The wand link and spell assessment are separate packages, and each runs
without the GUI:

```bash
# Wand only (opencaster.wand, needs bleak)
python -m opencaster.wand scan                  # list nearby wands and boxes
python -m opencaster.wand monitor               # connect and print every event
python -m opencaster.wand record capture.csv    # raw IMU + pad state to CSV
python -m opencaster.wand effect success        # a built-in effect, or a #RRGGBB colour

# Spell assessment only (opencaster.casting, needs numpy + scipy)
python -m opencaster.casting list               # spell templates
python -m opencaster.casting evaluate           # score the matcher on labelled casts
python -m opencaster.casting replay capture.csv # replay a recorded capture through casting

# Everything together, in the terminal (every connected wand casts)
python -m opencaster [--target Lumos] [--duel]
```

`--address AA:BB:...` picks a wand for the wand commands; `replay --wand
ADDRESS` uses that wand's calibration.

---

## Control API

While OpenCaster runs (GUI or `python -m opencaster`), other programs can
light and buzz the wands and hear about casts, over plain HTTP + JSON at
`http://127.0.0.1:8765/api`.  Events stream as
[Server-Sent Events](https://developer.mozilla.org/docs/Web/API/Server-sent_events).

| Request | Body / notes |
|---------|--------------|
| `GET /api/status` | wands, duel state, settings |
| `GET /api/wands` | connected wands: address, name, nickname, colour, battery |
| `GET /api/spells` | spells: name, cast colours, difficulty, mastery count |
| `GET /api/events` | event stream (`?include=imu,trail` adds raw motion) |
| `POST /api/light` | `{"wand": "all", "color": "#FF8800", "fade_ms": 300, "hold_ms": 0, "groups": [0,1,2,3]}` — `hold_ms` 0 leaves it on; groups run tip (0) to handle (3) |
| `POST /api/vibrate` | `{"wand": "all", "duration_ms": 200}` |
| `POST /api/clear` | `{"wand": "all"}` |
| `POST /api/effect` | `{"name": "success"}` (success, fail, welcome, glow, breathe, clear, countdown, go, round_lost, duel_won), `{"spell": "Lumos"}`, or `{"macro": [...]}` in the spellbook's command format |

`wand` is `"all"` (the default), an address, a wand name (`MCW-F108`) or a
nickname.  Each wand plays one effect at a time, so an API effect replaces
whatever was playing (including the cast glow).

Events: `spell` (wand, spell, colours, mastery count), `cast` (accepted or
not, best match), `casting`, `tap`, `pads`, `wand_connected`, `wand_ready`,
`wand_disconnected`, `wand_info`, `battery`, `duel`, `settings`, `status`.

```bash
curl http://127.0.0.1:8765/api/wands
curl -X POST http://127.0.0.1:8765/api/light -H "Content-Type: application/json" \
     -d '{"color": "#FF8800", "hold_ms": 1500}'
curl -N http://127.0.0.1:8765/api/events
```

```python
from opencaster.api.client import OpenCasterClient   # stdlib only: copy the file anywhere

oc = OpenCasterClient()
oc.vibrate(300, wand="MCW-F108")
for event in oc.events():
    if event["type"] == "spell":
        print(event["wand"]["label"], "cast", event["spell"])
        oc.light("#00FF00", hold_ms=1000)
```

Or from the terminal: `python -m opencaster.api light red --hold 1500`,
`... vibrate 300`, `... spell Lumos`, `... listen`.

**Configuration** (`settings.json` → `"api"`): `enabled` (default true),
`host` (default `127.0.0.1`: this computer only), `port` (8765), `token`
(if set, requests need `Authorization: Bearer <token>` or `?token=`), and
`allow_origins` (web pages allowed to call the API; requests from any other
web origin are refused, and POST bodies must be JSON, so a website can't
drive your wand).

---

## Spells

Each spell is one SVG in `spells/` containing a single `<path>` in a 200×200
viewBox, drawn in casting order: **the path's start is where the gesture
starts**, because recognition takes direction into account.  The spell's name
is the file name.  Name it after the spellbook entry (e.g.
`Wingardium Leviosa.svg`) so it picks up that spell's effects.

**Reload spells** reloads templates and effects without restarting.

### Adding a spell

- **Draw it:** `python tools/spell_editor.py` lets you draw with the mouse,
  smooth the stroke and save straight to `spells/`.
- **Trace a gesture diagram:** `tools/gesture_png_to_svg.py` traces images
  like eigger's (a stroke running from a start dot to an arrowhead).  Guide
  points in `tools/gesture_waypoints.json` fix the drawing order (dot,
  corners, both sides of each crossing, arrow tip); between them the trace
  follows the drawn stroke's centre line.

  ```bash
  python tools/gesture_png_to_svg.py grid  PNG_DIR out/ --only name     # gridded image to read points from
  python tools/gesture_png_to_svg.py trace PNG_DIR out/ --only name --review out/review.png
  ```

Every extra spell is one more shape a cast can be confused with, so check new
ones with `python -m opencaster.casting evaluate`.

### Tuning recognition

```bash
python -m opencaster.casting evaluate                      # accuracy, confusion table, suggested thresholds
python -m opencaster.casting evaluate --misses             # every labelled cast the matcher got wrong
python -m opencaster.casting evaluate --threshold 0.3 --margin 1.2
```

It re-runs every labelled cast in `casts/casts.jsonl` through the current
matcher and prints a `PER_SPELL_THRESHOLDS` block to paste into
`opencaster/casting/matcher.py`.

---

## Spell effects and media

`opencaster/spellbook.py` reads the original app's data from `media/`, which
is gitignored.  Everything is optional; missing files are simply skipped.

| Media | Source | Used for |
|-------|--------|----------|
| Wand lights + haptics | `config_wand.macros_payoff` in `media/spellbook.json` | A recognised spell's effect on the wand, encoded like the app's `MacroFactory` (see [Lights and haptics](#lights-and-haptics)) |
| Box lights | `config_wandbox.macros_payoff` | Sent to every connected box; **not yet verified on hardware** |
| Card colours | the colours in each wand macro | Spellbook cards, duel cards and the cast burst (weighted by duration × brightness) |
| Lore | `pronunciation`, `description`, `notable_uses`, `spell_type`, `difficulty` | The Spellbook |
| Casting sound | `sfx_<spell>_cast_01..05.mp3` | One at random per cast |
| Payoff video | `<spell>_video_payoff.mp4` | After a successful cast; each duel round's winning spell |
| Patronus videos | `sfx_patronus_<animal>.mp4` (69) | After Expecto Patronum; the Patronus picker |
| Mishap videos | `spellcasting_mishap_N.mp4` | After a failed cast |
| Celebration | `payoff_maxlevel.mp4` | Mastering a spell; winning a duel |
| Duel intro | `tutorial_end_transition.mp4` | Opening a duel |
| Wand awake | `sfx_wandawake_long.mp3` | A wand connects |
| Wand movement | `sfx_wandmovement_generalloop.mp3` | Looped while a cast window is open |
| House sounds | `ui_choose_house_*.mp3` | Choosing a house in Settings |

Media is matched to spells by file name, ignoring spaces and punctuation
(`sfx_lumos_cast_01.mp3` → Lumos); each sound goes to the longest spell name
it contains, so Lumos doesn't pick up Lumos Maxima's sounds.  Spells without
a wand macro fall back to a generic pulse in the wand's colour.  Colovaria's
`$house_color` is your house's colour (gold without a house).

### Built-in wand animations (`opencaster/wand/effects.py`)

| Effect | When |
|--------|------|
| `welcome` | Connect: the wand's colour sweeps handle → tip, two buzzes, a glow that fades out |
| `breathe` | Cast window open: a bloom, then a slow breath in the wand's colour |
| `success` | Spell without its own macro: buzz, colour wave tip → handle, white flash |
| `fail` | Failed cast: a faint red wash, no buzz |
| `countdown`, `go`, `round_lost`, `duel_won` | Duel cues |

They use only commands already proven on the wand (`0x60` prefix, `changeled`
fades, host-timed waits, the existing buzz pattern).

---

## Architecture

```
BLE ──▶ opencaster.wand ──notify──▶ opencaster.casting ──cast──▶ effects on wands + boxes
        WandManager: any number     one CastSession per wand:
        of wands + boxes, scan,     window, tracker, matcher,
        reconnect, keepalive        calibration, cast log
                 └────── opencaster.core.OpenCaster wires them ──────┘
                          │  opencaster.duel (rules)   opencaster.api (HTTP + SSE)
                          │ events (one queued Qt signal)
                          ▼
                  opencaster.gui (PySide6)
```

- **Event-driven throughout.**  bleak delivers notifications, disconnects
  and scan results as callbacks on one asyncio loop; nothing polls.
  Keepalive challenges are answered inside the BLE notify handler.  Gesture
  timeouts are checked as IMU batches arrive, so the casting logic needs no
  timers or threads and replays deterministically.  GUI animations run a
  frame timer only while something is moving.
- **Thread model.**  The core runs on its own asyncio thread (bleak/WinRT
  stays off the Qt thread); events reach the GUI as one queued Qt signal,
  and GUI commands are scheduled onto the loop with `call_soon_threadsafe`.
  The API server runs on the same loop.
- **Several wands.**  Each wanted wand has its own supervised link; BLE
  connects and scans run one at a time (concurrent WinRT operations fail).
- **Effects** are step lists played by one task per device; a new effect
  cancels the running one, so the cast glow and a spell's payoff never
  interleave.
- **Matching** scores every template under every tilt in one vectorised DTW
  pass (~35 ms per cast).

---

## How recognition works

### Gesture tracking (`opencaster/casting/tracker.py`)

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
however the wand is held.

### Matching (`opencaster/casting/matcher.py`)

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

Haptics need this init sequence once per connection (`protocol.HW_INIT`):

```
00  08  09  0e02  0e04  0e08  0e09  0e01
dd00 dd04 dd01 dd05 dd02 dd06 dd03 dd07
dc0007 dc040a dc0107 dc050a dc0207 dc060a dc0307 dc070a
dd00 dd04 dd01 dd05 dd02 dd06 dd03 dd07
```

### Notifications (wand → host, on `57420003`)

| First byte | Meaning | Format |
|------------|---------|--------|
| `0x01` | Keepalive challenge | Reply by writing `0x01`, or the wand disconnects (OpenCaster also answers `0x02`) |
| `0x10` | Touch sensors | `10 [mask]`: bit 0–3 = sensors 1–4 (`0x0F` = all held) |
| `0x24` | Spell recognised by the wand's firmware | `24 00 00 [len] [utf-8 name]`, e.g. `2400000750726f7465676f` → `Protego` |
| `0x2C` | IMU samples | See below |
| `0x08`, `0x09`, `0x0E`, `0xDD` | Replies to the init sequence | Wand address, paired box address, product info (serial, SKU), pad thresholds |

A firmware spell broadcast is handled like one of OpenCaster's own matches and
plays that spell's effects.

### IMU stream

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
- The tip defaults to sensor **+y** (both rest poses read ≈0 g on y, and swing
  centripetal force lands on y).  **Calibrate** measures it per wand.

---

## Project files

| Path | Purpose |
|------|---------|
| `OpenCaster_GUI.py` | Starts the GUI |
| `opencaster/wand/` | **Wand link** (bleak only): `protocol.py` UUIDs, opcodes, parsing, frame builders · `effects.py` built-in animations and spellbook macro encoding · `device.py` one BLE link · `manager.py` scanning, auto-connect, reconnect, boxes · `__main__.py` headless CLI |
| `opencaster/casting/` | **Spell assessment** (numpy/scipy only): `tracker.py` gyro gesture tracker · `shapes.py` SVG templates · `matcher.py` DTW recogniser and thresholds · `session.py` casting state machine · `calibration.py` motion calibration logic · `castlog.py` labelled casts · `profiles.py` per-wand calibration · `__main__.py` evaluate / replay CLI |
| `opencaster/spellbook.py` | Original spell data, cast colours, sounds, videos; mastery progress |
| `opencaster/settings.py` | Default colour, house, Patronus, API settings (`settings.json`) |
| `opencaster/duel.py` | Wizard's duel rules |
| `opencaster/api/` | Control API: `server.py` (HTTP + SSE), `client.py` (stdlib client), `__main__.py` CLI |
| `opencaster/core.py` | Wires the wands to casting, effects, duels and the API; `python -m opencaster` runs it headless |
| `opencaster/gui/` | PySide6 interface: cast page (a stage per wand), spellbook, duel, settings, calibration |
| `tools/` | Spell authoring: `spell_editor.py`, `gesture_png_to_svg.py`, `gesture_waypoints.json` |
| `spells/` | Spell templates (52 SVGs, used for recognition and the trail guide) |
| `spells/icons/` | Original gesture PNGs by eigger (MIT), shown on spell cards |
| `casts/casts.jsonl` | Labelled casts |
| `wand_profiles.json` | Per-wand calibration, colour, nickname and auto-connect |
| `media/` | Spellbook and media pack (gitignored, supply your own) |
| `Bluetooth Capture/` | Original btsnoop capture of the official app |

---

## References

- Nordic announcement: <https://www.nordicsemi.com/Nordic-news/2022/10/Interactive-smart-wand-from-Warner-Bros-Home-Entertainment-uses-nRF52832-SoC>
- Nordic nRF52832: <https://www.nordicsemi.com/Products/nRF52832>
- Nordic nRF52810: <https://www.nordicsemi.com/Products/nRF52810>
- APK: `Harry Potter Magic Caster Wand_3.9.4_APKPure.xapk`
- BT snoop log: `Bluetooth Capture/HP Bluetooth log.btsnoop`
