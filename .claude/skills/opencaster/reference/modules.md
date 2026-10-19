# OpenCaster modules – public API

The repo root holds `opencaster/` (the package), `spells/` (52 SVG gesture
templates), `casts/casts.jsonl` (labelled casts), `tools/` (spell authoring),
`OpenCaster_GUI.py`.  `media/` is optional local data from the original app
(spellbook.json, sounds, videos) – **gitignored, not redistributable**; code
must work without it.  Requirements: Python 3.11+, `bleak`, `numpy`, `scipy`,
`PySide6` (GUI only).  `opencaster.paths` anchors every data file to the repo
root (`ROOT`, `SPELLS_DIR`, `MEDIA_DIR`, `CASTS_FILE`, `PROFILES_FILE`,
`PROGRESS_FILE`, `SETTINGS_FILE`).

Layers, lowest first; each depends only on those above it in this list.

## opencaster.wand – Bluetooth (bleak only)

```python
from opencaster.wand import WandManager, effects, protocol as p, DeviceInfo, Battery, Emitter
```

**WandManager**`(auto=(), auto_connect=True, boxes=True, welcome=None)`
- `await run()` – supervise until `stop()`: scan, connect wanted wands,
  reconnect, keep each linked.  `auto`: addresses to connect when found
  (empty: the first wand found).  `welcome(info) -> Effect` per connect.
- `stop()`, `connect(address)`, `disconnect(address)`, `request_scan()`,
  `is_wanted(address)`.
- `play(effect, address=None)` – None = every wand.  `play_macro(macro,
  variables=None, address=None)`, `play_boxes_macro(macro, variables=None)`.
- `found` {address: DeviceInfo}, `wands` {address: Wand} (linked now).
- `events`: an `Emitter` – see events.md.  Class attrs `SCAN_S` etc.
- `DeviceInfo(name, address)`, `.kind` is `"wand"` (name `MCW-…`) or `"box"` (`MCB-…`).

**protocol** – notification types from `parse_notification(bytes)`:
`Buttons(mask)` (bit 0..3 = pads 1..4 tip→handle; `.pressed` tuple),
`ImuBatch(seq, samples)` (samples: `(ax, ay, az, gx, gy, gz)` in g and
rad/s), `SpellCast(name)` (the wand's own firmware recognised a spell),
`Challenge`/`Pong` (keepalive, answered for you), `FirmwareVersion`,
`CalibrationDone(kind)`, `Unknown(opcode, raw)`.  `describe(ev)` → short
text.  Frame builders: `frame(*cmds)`, `changeled(group, r, g, b, ms)`,
`all_groups(r, g, b, ms, groups=range(4))`, `buzz(ms)`; constants
`IMU_START`, `IMU_STOP`, `LIGHTS_OFF`, `EFFECT_PREFIX`, UUIDs.

**effects** – an `Effect` is a tuple of `(bytes, wait_seconds)` steps.
Built-ins (`effects.BUILTIN` by name): `welcome(rgb)`, `success(rgb)`,
`fail()`, `glow(r, g, b, fade_ms)` (stays on), `breathe(rgb, seconds,
period)`, `clear()`, `countdown_tick(rgb)`, `go(rgb)`, `locked_in(rgb)`,
`round_lost()`, `duel_won(rgb)`.  Direct: `light(rgb, fade_ms=300,
hold_ms=0, groups=range(4))` (hold 0 = stays on), `vibrate(ms)`,
`solid("#RRGGBB")`.  Macros (the original app's format):
`macro_effect(macro, mtu, variables)`, `macro_to_frames(...)`,
`expand_loops(...)`.  Effects concatenate: `effects.glow(...) + effects.vibrate(150)`.

Macro commands (list of dicts, durations in **seconds**):
`{"command": "changeled", "group": 0-3, "color": "RRGGBB" or "$house_color", "duration": s}`
(a fade, doesn't block) · `{"command": "delay", "duration": s}` ·
`{"command": "buzz", "duration": s}` · `{"command": "clearleds"}` ·
`{"command": "setloops", "loops": n}` … `{"command": "loop"}`.

CLI: `python -m opencaster.wand scan | monitor [--imu] | record x.csv | effect NAME|#RRGGBB [--address A]`.

## opencaster.casting – spell recognition (numpy + scipy only)

```python
from opencaster.casting import (SpellLibrary, SpellMatcher, CastSession, CastResult, assess,
                                GestureTracker, CastLog, WandProfiles, spell_key)
```

- `SpellLibrary(spells_dir)` – `.templates`, `.get(name)` (case/space-insensitive),
  `.names()`, `.reload()`.  `SpellTemplate`: `name`, `key`, `points` (64×2,
  y up, centred, max |coord| 1), `outline` (full path, same frame).
- `spell_key("Wingardium Leviosa") == "wingardiumleviosa"` – compare names with it.
- `SpellMatcher()` – `.rank(trail, templates)` → `[Match]` best first;
  `Match(spell, key, score, threshold, success, margin)`.  Lower score = closer.
- `assess(trail, library, matcher, target=None, allowed=None) -> CastResult` –
  gates (≥20 points, ≥15° across) then ranks.  `allowed`: frozenset of keys.
- `CastResult`: `trail` (N×2 degrees, x right, y up), `gate`, `ranked`,
  `target`, `note`; `.accepted`, `.spell` (None unless accepted), `.best`,
  `.message()`, `.rejected(note)`.
- `CastSession(library, matcher=None, on_event=fn(name, payload), cast_log=None, clock=time.monotonic)`
  – the live state machine for one wand: `feed_buttons(mask)` (all four
  pads = 0x0F opens the window; release closes it), `feed_imu(samples)`,
  `set_target(name)`, `allowed` (attribute), `set_motion(profile)`,
  `set_label_casts(on)`, `label(name)`, `reset()`.  Events: see events.md.
- `GestureTracker` – IMU → trail.  `.from_profile(motion)`, `begin()`,
  `feed(*sample)` / `feed_many(samples)`, `end() -> trail`, `position()`
  (current tip offset from begin, degrees).  Feed every sample, always.
- `run_pipeline(samples, pre_samples=None, motion=None)` (in `.tracker`) –
  offline: samples → (trail, stats).
- `WandProfiles(path)` – per-wand JSON: `motion(address)`, `get/set(address, key)`, `auto_connect()`.

CLI: `python -m opencaster.casting list | evaluate [--misses] | replay capture.csv`.

## opencaster.core – everything wired together

```python
from opencaster.core import OpenCaster
core = OpenCaster(spells_dir=..., media_dir=..., casts_file=..., profiles_file=...,
                  progress_file=..., settings_file=..., boxes=True, use_api=True)
await core.run()            # owns the asyncio loop until core.stop()
```

One `CastSession` per connected wand; recognised spells play their wand
macro (or `success` in the wand's colour), count towards mastery
(`progress.json`) and emit `"spell"`.  **All commands run on the core's
loop thread.**

| Command | Does |
|---------|------|
| `stop()`, `scan()`, `connect(a)`, `disconnect(a)` | links |
| `light(wand, "#RRGGBB", fade_ms, hold_ms, groups)`, `vibrate(wand, ms)`, `clear(wand)` | direct control; `wand`: "all", address, name or nickname (`resolve`) |
| `play_effect(wand, name=…\|spell=…\|macro=[…])` | a built-in, a spell's payoff, or a macro |
| `set_target(name)` | practise one spell (others are rejected) |
| `set_free_cast(on)` | accept any spell, no labelling (what game pages use) |
| `set_aim(address, on, spell=None)` | `"aim"` events while on; wand glows in `spell`'s colour after its payoff; ends at that wand's next cast |
| `start_duel(players, pool, mode, order, npc_level)` | `mode`: "race", "clash", "club"; `players`: addresses and/or `"npc"` |
| `cancel_duel()`, `skip_round()` | |
| `set_wand_color(a, "#RRGGBB"\|None)`, `set_nickname(a, s)`, `set_default_color`, `set_house`, `set_patronus` | settings (persisted) |
| `wand_info(a)`, `wand_list()`, `wand_label(a)`, `wand_color(a)` | queries |

Attributes: `wands` {address: DeviceInfo}, `ready` set, `sessions`,
`library`, `spellbook`, `progress`, `settings`, `duel`, `npc`, `events`.

Headless runner: `python -m opencaster [--target Lumos] [--duel [POOL] | --clash | --club [N] [--random-order]] [--npc [LEVEL]]`.

## opencaster.api – control from other programs

HTTP + JSON + Server-Sent Events on `127.0.0.1:8765` (settings.json `api`:
`enabled`, `host`, `port`, `token`, `allow_origins`).  Requests with an
Origin header are refused unless allowed (web pages can't drive wands);
with a token set, send `Authorization: Bearer <token>`.

| Request | Body |
|---------|------|
| `GET /api/status` · `/api/wands` · `/api/spells` | – |
| `GET /api/events[?include=imu,trail]` | SSE stream |
| `POST /api/light` | `{"wand": "all", "color": "#FF8800", "fade_ms": 300, "hold_ms": 0, "groups": [0,1,2,3]}` |
| `POST /api/vibrate` | `{"wand": "all", "duration_ms": 200}` |
| `POST /api/clear` | `{"wand": "all"}` |
| `POST /api/effect` | `{"name": "success"}` or `{"spell": "Lumos"}` or `{"macro": [...]}` |

`opencaster/api/client.py` – `OpenCasterClient(base, token)` – is stdlib
only; copy it into any project: `.status() .wands() .spells() .light()
.vibrate() .clear() .effect() .events()`.  CLI: `python -m opencaster.api
status | light COLOR [--hold MS] | vibrate MS | effect NAME | spell NAME | listen`.
**The API can't start duels, steer, or read raw pads** – embed the core for those.

## Game logic (pure, no Qt, no I/O)

- `opencaster.elements` – `FIRE, EXPLOSIVE, BINDING, LOCOMOTIVE, WATER, PROTECTION`;
  `element_of(spell)`, `beats(a, b)`, `clash(spell_a, spell_b) -> (winner 0/1/None, line)`,
  `battle_spells()`, `SPELLS`, `BEATS` (verbs), `NAMES`.
- `opencaster.duel` – `Duel` (quick-draw), `ClashDuel`, `ClubDuel`; constructor
  `(players, [spells,] on_change, schedule, clock, rng, intro_s)`; inputs
  `window_opened(p)`, `window_closed(p)`, `cast(p, accepted, spell)`; `snapshot()`.
- `opencaster.npc` – `NPC = "npc"`, `Npc(level, known, rng)` → `Move(react, draw, spell, fumble)`
  via `.race(spell) .clash() .attack() .counter(incoming) .retry(move)`; `gesture(outline, rng)`.
- `opencaster.environment` – `Pumpkin` (the jack-o'-lantern): `cast(spell) -> Outcome(spell, text, fx, blocked)`,
  `let_go()`, `expire()`, `next_expiry()`, state fields (`contents`, `pose`, …).
- `opencaster.spellbook` – `Spellbook(media_dir)`: `.get(name) -> SpellInfo`
  (`colors`, `wand_macro()`, `sound()`, `video`, `pronunciation`, `difficulty`…);
  `Progress(path)`: `.count(name)`, `.record(name)`.  Without `media/` these are empty.
- `opencaster.settings` – `Settings(path)`, `HOUSES`, `rgb("#RRGGBB")`, `normalise_color`.

## opencaster.gui – PySide6

`OpenCaster_GUI.py` → `gui.app.MainWindow(CoreBridge(core))`.  The bridge
runs the core on a background thread; core events arrive on the Qt thread
as `MainWindow._on_event(name, args)` → `_ev_<name>(*args)` methods; GUI
commands go back with `bridge.call("method", *args)`.  Pages: `CastPage`,
`SpellbookPage`, `DuelPage`, `EnvironmentPage` (+ `PumpkinScene`).  Shared
`AppState` (`state.wands`, `state.wand_label(a)`, `state.info(spell)`,
`state.template(spell)`, `state.flag(...)`, `state.prefs` QSettings).
