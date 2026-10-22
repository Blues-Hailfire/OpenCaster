# OpenCaster

<a href="https://www.buymeacoffee.com/hailfire"><img src="https://img.buymeacoffee.com/button-api/?text=Buy%20me%20a%20coffee&emoji=&slug=hailfire&button_colour=FFDD00&font_colour=000000&font_family=Cookie&outline_colour=000000&coffee_colour=ffffff" alt="Buy me a coffee" height="42"></a>

## 🎃 Happy Halloween – the first release!

Hi everyone, happy Halloween!  This is the first release of this project,
and there's a lot of cool stuff to unpack here.  For starters, it's a
toolkit to build your own stuff with the Magic Caster wand: OpenCaster is
broken down into [separate modules](#architecture) so other applications
can use and reuse parts of it.  Not to mention a
[Claude skills package](.claude/skills/opencaster/SKILL.md) to make life
easy.  It's my hope we'll add support for things like TVs and smart home
devices, but if you beat me to it, there's an [API](#control-api) – go wild!

Some of the coolest features include the return of [duelling](#wizards-duel)!
Duel your friends!  Or an NPC if you need people, I'm sorry.  There are
three duel modes, with Duelling Club supporting up to 5 players.  (Yes, you
can connect more than one wand.)  The Spellbook is back!  (Media coming
soon – we have it, we just have to finalize it.)  I've also added a fun
[environment mode](#environment-the-enchanted-jack-o-lantern): cast spells
and blow up some pumpkins!  I highly recommend giving Wingardium Leviosa a
go.

What I could really use from all of you is to download the application and
cast some spells!  Then put in a pull request with the training data you've
gathered ([here's how](#contributing)) – the more I get, the better
detection will be.

Lastly, I love contributions, and not just money: feel free to bolt some
stuff on, make a pull request, and we can build a better application
together!

---

An unofficial, open-source reimplementation of the Warner Bros. Magic Caster
Wand experience.  OpenCaster talks to the wand directly over Bluetooth LE: it
tracks your gesture with the wand's gyro, recognises it against 52 spell
shapes, and plays that spell's original light, haptic, sound and video
effects (on the wand, and on a Magic Caster box if one is nearby).  Several
wands can cast at once, wizards can duel (a quick-draw race or a clash of
spell elements for two, or a Duelling Club rally for up to five), an
enchanted jack-o'-lantern on screen reacts to every spell, and other
programs can drive the wands through a local API.

## Credits

- **Spell data and audio/visual media:** credit to **uuyyyuu** and
  [uuyyyuu/magic-caster-spellbook](https://github.com/uuyyyuu/magic-caster-spellbook),
  which recovered and preserved the original Magic Caster app's spell
  definitions (`spellbook.json`: wand and box lighting/haptic effects) and its
  `zz_spell_assets` media pack (casting sounds, spell videos), which OpenCaster
  plays when you cast.  These files belong to their original owners.  The
  spell manifest, `media/spellbook.json`, is included in this repository;
  the media pack is **not committed** and stays in your local `media/`
  folder.
- **Spell gesture SVGs:** all 52 templates in `spells/` were traced from the
  gesture diagrams by **eigger** in
  [eigger/hass-magic-caster-wand](https://github.com/eigger/hass-magic-caster-wand/tree/master/docs/gestures)
  (MIT licence); each traced SVG names its source image.  The spell icons in
  `spells/icons/` are those original PNGs, unmodified (licence alongside).

Magic Caster is a Warner Bros. product.  OpenCaster is an unofficial project
and is not affiliated with or endorsed by Warner Bros.

---

## Contents

- [Quick start](#quick-start)
- [Using the GUI](#using-the-gui)
- [Wizard's duel](#wizards-duel)
- [Environment: the enchanted jack-o'-lantern](#environment-the-enchanted-jack-o-lantern)
- [Running headless](#running-headless)
- [Control API](#control-api)
- [Spells](#spells)
- [Spell effects and media](#spell-effects-and-media)
- [Architecture](#architecture)
- [How recognition works](#how-recognition-works)
- [Protocol reference](#protocol-reference)
- [Project files](#project-files)
- [Contributing](#contributing)
- [References](#references)

---

## Quick start

**Windows, no Python needed:** download `OpenCaster-<version>-windows.zip`
from [Releases](https://github.com/Blues-Hailfire/OpenCaster/releases),
unzip it and run **OpenCaster.exe** (the zip's README.txt has the details;
SmartScreen may ask you to click *More info → Run anyway*, as the build
isn't code-signed).

**Windows, from source:** double-click **`setup.bat`**.  It finds (or
offers to install) Python, installs everything OpenCaster needs into
`%LOCALAPPDATA%\OpenCaster`, and adds **OpenCaster** to your Desktop and
Start Menu.  Run it again any time to update.  If the app doesn't start,
use the **OpenCaster (troubleshoot)** shortcut to see the error.

**macOS / Linux:** `bash setup.sh` does the same and creates an
`opencaster` launcher (plus an app-menu entry on Linux).

**By hand:**

```bash
pip install -r requirements.txt
python OpenCaster_GUI.py
```

1. **Effects:** `media/spellbook.json` (included) gives every spell its own
   wand light and haptics.  For sounds and videos, add the media pack's
   files to `media/` (sounds in `media/sounds/`, videos anywhere under
   `media/`); without them the spellbook shows shapes only.
2. **Launch:** the app scans for wands and boxes and connects automatically.
3. **Calibrate (optional):** press **Calibrate** once per wand to measure its gyro bias.
4. **Cast:** hold all four touch pads, draw the spell, release.

Requires Python 3.11+.  Sounds and videos play through Qt Multimedia, so
they work on every platform PySide6 supports.

---

## Using the GUI

Four pages: **Cast**, **Spellbook**, **Duel** and **Environment**.  The header shows a pill
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

- **Start:** hold all four touch pads.  The wand's body breathes in its
  colour while the gesture window is open (the tip stays dark until a spell
  succeeds), the trail is drawn live with sparkles
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
*Not a spell*, or *Discard*.  Starting a calibration discards a cast still
waiting for its label.  Hovering a spell previews its shape on the
trail.  While practising, the question is just "Was that Lumos?".  Labelled
trails go to `casts/casts.jsonl` for tuning (see
[Tuning recognition](#tuning-recognition)).

### Spellbook

A card for every spell template, coloured with the light colours the spell
plays on the wand and showing its original gesture icon (`spells/icons/`,
falling back to the SVG shape).  The small icon in each card's top left is
the spell's duelling type (Fire, Explosive, Binding, Locomotive, Water/Ice or
Protection, as on the duel wheel); utility spells, which take no part in
clashes or the Duelling Club, have none.  Hovering a card names the type and
what it beats.  Open one for its pronunciation, lore and
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
connected.  Three self-advancing steps, about 20 s:

1. Lay the wand flat → gyro bias and noise
2. Swipe up → confirms tracking reads up
3. Swipe right → confirms it reads right

The tip axis and left/right sign are the same on every wand, so the swipes
only confirm them: one that reads the wrong way (or too small or crooked)
is asked for again.  The result is saved as a `motion` block for that wand
in `wand_profiles.json` (keyed by MAC address) and loaded on every connect.
Without it, defaults are used (tip +y, bias learned on the fly), so
calibrating is optional.  A tip more than 25° off +y, saved by an older
calibration with the wand held wrong, is ignored at load: only its gyro
bias is used.

**Diagnostics** shows match scores, the live IMU samples and an event log.

---

## Wizard's duel

Connect the wands, open **Duel**, pick a mode and the wizards, and **Begin
the duel**.  Quick-draw and Clash are for two wizards, best of five (first
to three round wins); the Duelling Club is one rally for two to five.  Each
wand pulses in its colour through the 3-2-1 countdown and flashes on
**Cast!**; a gesture started during the countdown never counts.

### The NPC opponent

No one to duel?  Any seat can be the **NPC**, a computer opponent; with a
single wand connected, Wizard 2 is the NPC already.  **NPC skill** sets how
good it is:

| Skill | Reacts in | Draws a gesture in | Fumbles | Duelling Club answers |
|-------|-----------|--------------------|---------|-----------------------|
| Easy | 0.9–1.8 s | 2–3 s | 1 in 4 | right about 2 times in 3 |
| Medium | 0.5–1.1 s | 1.4–2.3 s | 1 in 8 | right 4 times in 5 |
| Hard | 0.25–0.6 s | 0.9–1.6 s | 1 in 20 | right 19 times in 20 |

Its panel draws each spell's shape as it casts.  A fumbled gesture isn't
recognised and it casts again while there's time.  In a clash a Medium or
Hard NPC learns your favourite element and counters it; in the Duelling Club
it sometimes blocks with a shield, and sometimes answers wrong and slips
up.  Its spells sound but never count towards your mastery.  One NPC per
duel; it needs at least one wand to play against.

### Quick-draw

The original app's duelling mode: two wizards, one spell.

- Each round both wizards are shown the same spell; the first to cast it
  wins the round.  The winner's wand plays the spell, the other fades red.
  A different spell doesn't count.
- A round nobody wins in 30 s is void; **Skip spell** voids it by hand;
  after 9 rounds the higher score wins.
- **Spell pools:** *Spells you've cast* (the default: spells you've been
  recognised casting, so rounds don't stall on shapes that won't
  recognise), *All spells*, or one difficulty.

### Clash

Spells as rock-paper-scissors.  After **Cast!** each wizard has **3
seconds** to cast any battle spell (a gesture started in time may finish up
to 2 s late).  Your first recognised battle spell is your pick: your wand
buzzes and glows dimly in your own colour, and your panel only says *Spell
chosen*.  Picks stay hidden until both are in or time is up; then both cards
are revealed, both wands play their spells, and the elements decide:

| Element | Beats | Spells |
|---------|-------|--------|
| Fire | Binding, Locomotive | Incendio, Flagrate, Verdimillious |
| Explosive | Fire, Water/Ice | Bombarda, Confringo, Expulso, Reducto, Finestra |
| Binding | Locomotive, Explosive | Incarcerous, Brachiabindo, Petrificus Totalus, Fulgari, Immobulus, Impedimenta, Colloshoo, Stupefy |
| Locomotive | Water/Ice, Explosive | Wingardium Leviosa, Accio, Ascendio, Flipendo, Expelliarmus, Arania Exumai, Piertotum Locomotor, Ventus, The Force Spell |
| Water/Ice | Fire, Binding | Aguamenti, Glacius, Meteolojinx |
| Protection | – (blocks everything) | Protego, Salvio Hexia, Expecto Patronum, Finite |

- Each element beats two and loses to two.  The same element twice is a
  draw, and a shield draws with anything, even no spell at all.
- An attack beats no spell; if neither wizard casts, the round is void.
  Draws score nothing, so a clash runs up to 15 rounds (then the higher
  score wins).
- Utility spells (Lumos, Nox, Alohomora, Silencio, Reparo …) have no
  element and play no part: while the window is open, gestures are matched
  against the 32 battle spells only.  A cast that isn't recognised doesn't
  use up your pick, so cast again if there's time.
- The table lives in `opencaster/elements.py`.

### Duelling Club

Two to five wizards, the same elements, turn by turn.  Wizard 1 opens with
an attack (**3 seconds**).  The next wizard has **5 seconds** to answer
with a spell that beats it – which the wizard after them must then answer –
or to block it with a shield, and then has 3 seconds to attack.  **Who
answers** sets who's next: *In order* goes round the seats (Wizard 1, 2,
3 …, back to 1); *Random* picks anyone but the caster.

There are no rounds and no limit: the rally goes on until someone answers
too late or with a spell that doesn't beat the attack (a shield doesn't
count as an attack).  The wizard whose spell went unanswered wins.  If the
very first attack fails, the other wizard wins a two-wizard duel, and a
bigger one ends with no winner.

- Wizards 3–5 appear in Duelling Club mode; set any of them to *no one*.
  Seats 1–3 sit down the left of the arena and 4–5 down the right.
- Whose turn it is glows gold; the centre shows the spell to beat, which
  elements beat it, a timer running round the card, and the rally so far.
- A gesture that isn't recognised can be cast again while time remains,
  and one started in time may finish up to 2 s late.  Gestures started
  before your turn don't count.
- Every good move plays its spell on the caster's wand and counts towards
  mastery; only the wand whose turn it is flashes, and only the wizard who
  slips up fades red.  The spell left unanswered plays its video.

The duel opens with the intro video, each round's winning spell plays its
video, and the duel's winner gets confetti, a rainbow on their wand and the
celebration video.  **Rematch** starts again in the same mode.  Labelling
and the practice spell are suspended during a duel and restored afterwards.
Headless: `python -m opencaster --duel` (quick-draw), `--clash`, or `--club [N]`
for a Duelling Club once N wands (2–5) are ready (`--random-order` for random
turns); add `--npc [easy|medium|hard]` to give the last seat to the NPC
(`--npc` on its own is a quick-draw against it with one wand).

---

## Environment: the enchanted jack-o'-lantern

**Environment** shows a jack-o'-lantern in a moonlit pumpkin patch, and
every spell cast from any wand acts on it (the wand, sound and lighting
effects play as usual).  The practice spell and cast labelling pause while
the page is open.

It's drawn the way the original app's art is: flat silhouettes in a single
colour, with the spell's effect as the one bright thing.  The whole night
takes the colour of the last spell (warm for fire, blue for water, green
for growing things, purple to start), and a lit pumpkin glows in its
candle's colour.

A fresh jack-o'-lantern has its candle lit.  Spells change it and play off
each other, the same way the clash elements do:

| Spells | On the jack-o'-lantern |
|--------|------------------------|
| Aguamenti · Glacius · Meteolojinx | douse the candle and fill it with water (it dribbles from the grin) · freeze the water (frost and icicles otherwise) · a rain or snow cloud that douses or fills it |
| Incendio · Verdimillious · Flagrate | light the candle (melts ice, boils water away, burns ropes, vines and flowers) · a green flame and a green-glowing face, or green sparks · a fiery sigil |
| Bombarda · Confringo · Expulso · Reducto · Finestra | smash it; **Reparo** mends it |
| Incarcerous · Brachiabindo · Fulgari | ropes, cords or glowing cuffs: it can't be moved |
| Petrificus Totalus · Immobulus · Impedimenta · Colloshoo · Stupefy | stone · frozen in place (the flame too) · everything slowed · glued to the ground · stunned, it keels over |
| Wingardium Leviosa · Ascendio · Accio | float it, and steer it with your wand · launch it · pull it towards you (or summon it back) |
| Flipendo · The Force Spell · Expelliarmus | knock it over, spilling what's inside · fling it away |
| Piertotum Locomotor · Arania Exumai · Ventus | it grows legs and hops · spiders scatter · a gust that blows the candle out and whirls leaves and petals |
| Protego · Salvio Hexia · Expecto Patronum | a shield, a ring of runes or a silvery guardian that blocks the next battle spell |
| Finite | ends every spell on it: shield, bindings, stone, charms, levitation, vanishing |
| Lumos · Nox | light up the patch · darken the night (the candle and glowing things still shine) |
| Colloportus · Alohomora, Aberto | seal the lid with a lock (smothers the candle) · unseal it |
| Orchideous · Herbivicus | a bouquet bursting out of the top · pumpkin vines that curl up it and bloom |
| Evanesco | vanish what's inside, or the jack-o'-lantern itself |
| Colovaria | change its colour (your house colour first) |
| Scourgify | scrub off soot, sigils and glue |
| Cantis · Quietus · Silencio | it sings · hums · goes quiet |
| Confundo · Rictusempra · Riddikulus · The Cheering Charm · The Sleeping Charm | dizzy · giggling · wobbly, in a party hat · golden cheer · asleep until the next spell |
| Appare Vestigium | reveals the last few spells cast here |

Its carved face changes with its mood: closed eyes asleep, crosses when
dizzy or stunned, a big grin when it's happy, an open mouth when it sings.

**Wingardium Leviosa** ties the floating pumpkin to the wand that cast it:
point the wand up, down, left or right and the pumpkin follows, leaning
into the pull (about 30° of turn takes it to the side of the scene).  When
the spell's own light ends, the wand glows gold instead of fading, the whole
time it holds the pumpkin.  Pressing all four pads to cast again ends the
charm: the glow goes, and the pumpkin drops straight down under gravity –
a bounce, a squash and a puff of dust – and stays where it lands (Accio
pulls it back to the middle).  The charm also ends if the pumpkin is
knocked down, bound or glued, when you leave the page, or on **Reset**.
Frozen by Immobulus, it hangs in mid-air until that wears off, then drops.
Cast Wingardium Leviosa again to pick it back up from where it lies.

**Reset the jack-o'-lantern** starts afresh.  The rules are plain Python in
`opencaster/environment.py`; `opencaster/gui/pumpkin.py` draws them, and
animates only while something moves (a lit candle flickers, so it keeps
moving while the page is open).

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
python -m opencaster [--target Lumos] [--duel | --clash | --club [N] [--random-order]] [--npc [LEVEL]]
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
| `POST /api/effect` | `{"name": "success"}` (success, fail, welcome, glow, breathe, clear, countdown, go, locked_in, round_lost, duel_won), `{"spell": "Lumos"}`, or `{"macro": [...]}` in the spellbook's command format |

`wand` is `"all"` (the default), an address, a wand name (`MCW-F108`) or a
nickname.  Each wand plays one effect at a time, so an API effect replaces
whatever was playing (including the cast glow).

Events: `spell` (wand, spell, colours, mastery count), `cast` (accepted or
not, best match), `casting`, `tap`, `pads`, `wand_connected`, `wand_ready`,
`wand_disconnected`, `wand_info`, `battery`, `duel`, `settings`, `status`.
`duel` snapshots carry `mode` (`race`, `clash` or `club`); the NPC plays as
the player `"npc"` (its `player_info` has `"npc": true` and its `level`, and
the snapshot `npc_level`).  A clash adds
`window_s`, `locked` (who has picked), and after each round `picks`,
`elements` and `line` ("Aguamenti douses Incendio").  Duelling Club adds
`order` (`in_order` or `random`), `turn`, `turn_kind` (`attack` or
`counter`), `turn_no`, `window_s`, `incoming` (the spell to answer), `chain`
(the rally's moves), and once somebody slips up `loser` and `line`; it has a
single round, so `result` is followed by `finished`.

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

Labelled casts are few per spell, so `opencaster.recognition` also tests
against synthetic ones: casts generated from the templates with a hand's
tilt, stretch, wobble and rounded corners, plus near-misses that must be
rejected (half a spell, a spell drawn backwards, two spells blended, random
scribbles).  It fits a threshold per spell and shows the trade-off at several
false-accept weights, on held-out synthetic casts and on your real ones:

```bash
python -m opencaster.recognition synth --per 500 --save synth.npz   # generate, score, fit
python -m opencaster.recognition synth --load synth.npz --fa-weight 2
```

Scoring runs on the GPU through OpenCL when `pyopencl` is installed
(`pip install pyopencl`; any AMD, NVIDIA or Intel GPU driver includes
OpenCL), and on every CPU core otherwise (`--cpu` forces it).  500 per spell
is about 78,000 trails: about 16 s on a Radeon RX 9070 XT and about 18 min
on a 16-core CPU.

---

## Spell effects and media

`opencaster/spellbook.py` reads the original app's data from `media/`.
`spellbook.json` and OpenCaster's logo (`media/Logo/`) are tracked; the rest
of `media/` is gitignored.  Everything is optional; missing files are simply
skipped.

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
| `breathe` | Cast window open: a bloom, then a slow breath in the wand's colour (body only) |
| `success` | Spell without its own macro: buzz, colour wave tip → handle, white flash |
| `fail` | Failed cast: a faint red wash on the body, no buzz |
| `countdown`, `go`, `round_lost`, `duel_won` | Duel cues (body only) |
| `locked_in` | Clash pick made: one buzz and a dim glow in the wand's own colour, giving nothing away |

**The tip only glows for a successful cast** (the spell's own light, the
Wingardium steering glow, a clash pick) and for the connect animation.
Every other cue lights the body (groups 1–3) and fades the tip out, so a
spell's leftover glow never sits on the tip through the next cast window.
The API's direct `light`/`glow` commands are exempt.

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
                          │  opencaster.duel + .elements (rules)   opencaster.api (HTTP + SSE)
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
- The tip is sensor **+y** (both rest poses read ≈0 g on y, and swing
  centripetal force lands on y) on every wand, so it isn't calibrated.

---

## Project files

| Path | Purpose |
|------|---------|
| `OpenCaster_GUI.py` | Starts the GUI |
| `setup.bat` / `setup.ps1`, `setup.sh` | One-step setup: Python check, private environment, packages, shortcuts / launcher |
| `packaging/` | Windows release: PyInstaller spec, `build.ps1`, the zip's README and third-party notices |
| `.github/workflows/release.yml` | Builds and publishes the Windows release on a version tag |
| `opencaster/wand/` | **Wand link** (bleak only): `protocol.py` UUIDs, opcodes, parsing, frame builders · `effects.py` built-in animations and spellbook macro encoding · `device.py` one BLE link · `manager.py` scanning, auto-connect, reconnect, boxes · `__main__.py` headless CLI |
| `opencaster/casting/` | **Spell assessment** (numpy/scipy only): `tracker.py` gyro gesture tracker · `shapes.py` SVG templates · `matcher.py` DTW recogniser and thresholds · `session.py` casting state machine · `calibration.py` motion calibration logic · `castlog.py` labelled casts · `profiles.py` per-wand calibration · `__main__.py` evaluate / replay CLI |
| `opencaster/recognition/` | **Recognition testing and training** (offline; never loaded by the app): `synth.py` synthetic casts and near-misses, per-spell threshold fitting · `gpu.py` bulk DTW scoring on the GPU (OpenCL, optional) · `__main__.py` synth CLI |
| `opencaster/spellbook.py` | Original spell data, cast colours, sounds, videos; mastery progress |
| `opencaster/settings.py` | Default colour, house, Patronus, API settings (`settings.json`) |
| `opencaster/duel.py` | Duel rules: quick-draw, clash and Duelling Club |
| `opencaster/npc.py` | The NPC opponent: skill levels, what it casts and how long it takes (pure logic; the core plays it) |
| `opencaster/elements.py` | Spell elements and who beats whom (clash duel, jack-o'-lantern shields) |
| `opencaster/environment.py` | The enchanted jack-o'-lantern's rules (pure logic) |
| `opencaster/api/` | Control API: `server.py` (HTTP + SSE), `client.py` (stdlib client), `__main__.py` CLI |
| `opencaster/core.py` | Wires the wands to casting, effects, duels and the API; `python -m opencaster` runs it headless |
| `opencaster/gui/` | PySide6 interface: cast page (a stage per wand), spellbook, duel (quick-draw, clash and Duelling Club; `elements.py` wheel and legend), environment (`pumpkin.py` scene), settings, calibration; `assets/` holds the logo and app icon |
| `tools/` | Spell authoring: `spell_editor.py`, `gesture_png_to_svg.py`, `gesture_waypoints.json` |
| `spells/` | Spell templates (52 SVGs, used for recognition and the trail guide) |
| `spells/icons/` | Original gesture PNGs by eigger (MIT), shown on spell cards |
| `casts/casts.jsonl` | Labelled casts |
| `wand_profiles.json` | Per-wand calibration, colour, nickname and auto-connect |
| `media/` | `spellbook.json` (the spell manifest) and `Logo/` are tracked; the media pack (sounds, videos) is gitignored – supply your own |
| `Bluetooth Capture/` | Original btsnoop capture of the official app |

---

## Contributing

**Share your casts – it's the most useful thing you can do.**  Recognition
gets better with every honestly labelled cast from different people and
wands.

1. Keep **Label casts** on (the default) and cast spells.  After each cast,
   pick the spell you *meant* to cast – even when OpenCaster guessed wrong –
   or **Not a spell** for a fumble.  That's what makes the data useful.
2. Your casts are appended to `casts/casts.jsonl` (in the Windows release,
   the `casts` folder next to OpenCaster.exe).
3. Fork this repository, add your casts to `casts/casts.jsonl`, and open a
   pull request – or attach the file to an issue if pull requests are new
   to you.  Each record holds the gesture trail, the labels and scores, a
   timestamp and your wand's Bluetooth address – nothing else.  Casts also
   keep the wand's raw motion (1 s before the window opens, then the whole
   gesture), so tracker improvements can be re-run on them later
   (`python -m opencaster.casting evaluate --retrack`); that's about
   10–30 KB per cast.

**Code, spells and ideas** are just as welcome: bolt something on and open
a pull request.  [Architecture](#architecture) shows how the pieces fit,
and the Claude skill in `.claude/skills/opencaster/` describes how
features, spells and effects are built and tested without a wand.

### Building the Windows release

`packaging\build.ps1 -Version v1.0.0` makes a one-folder PyInstaller build
(`OpenCaster.exe`, plus `OpenCaster (debug).exe` with a console for error
messages) and zips it, in `%LOCALAPPDATA%\OpenCaster\release` so OneDrive
doesn't sync the build.  `OpenCaster.exe --smoke-test` checks a build
(spells, assets, Bluetooth backend, Qt Multimedia, the window) without
touching Bluetooth.

Pushing a version tag (`git tag v1.0.0 && git push origin v1.0.0`) runs
the same build on GitHub Actions (`.github/workflows/release.yml`), smoke
tests it, and attaches the zip to a GitHub release.  The release ships
`media/spellbook.json` next to the exe but never the media pack; user files
(casts, profiles, progress, settings, `media/`) live next to the exe.

---

## References

- Nordic announcement: <https://www.nordicsemi.com/Nordic-news/2022/10/Interactive-smart-wand-from-Warner-Bros-Home-Entertainment-uses-nRF52832-SoC>
- Nordic nRF52832: <https://www.nordicsemi.com/Products/nRF52832>
- Nordic nRF52810: <https://www.nordicsemi.com/Products/nRF52810>
- APK: `Harry Potter Magic Caster Wand_3.9.4_APKPure.xapk`
- BT snoop log: `Bluetooth Capture/HP Bluetooth log.btsnoop`
