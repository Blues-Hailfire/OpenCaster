# Events

Everything is event-driven.  `Emitter` (`opencaster.wand.events`): `on(name,
fn)`, `off(name, fn)`, `emit(name, *args)`; a handler on `"*"` gets `(name,
*args)` for every event.  **Handlers run synchronously on the emitting
thread** – for the manager and core that's the asyncio loop thread – so keep
them short and never block.

## WandManager.events

| Event | Args | When |
|-------|------|------|
| `scan` | `active: bool` | a scan starts / ends |
| `found` | `DeviceInfo` | a wand or box advertises for the first time |
| `connecting` / `connected` | `DeviceInfo` | link coming up / up (not yet initialised) |
| `ready` | `DeviceInfo` | initialised (haptics, IMU streaming): usable |
| `disconnected` | `DeviceInfo` | link lost or dropped (the manager reconnects wanted wands) |
| `notify` | `DeviceInfo, event` | every notification: `Buttons`, `ImuBatch`, `SpellCast`, `Battery`, … |
| `status` | `text` | human-readable status |

The IMU streams continuously from `ready` until disconnect: ~11.6 `ImuBatch`
packets a second, 19 samples each (220 Hz).

## CastSession on_event(name, payload)

| Event | Payload | When |
|-------|---------|------|
| `pads` | effective pad mask | pads change |
| `window_open` | practice target or None | all four pads held: a cast begins |
| `trail` | N×2 array (degrees) | the trail grew (during a cast) |
| `cast` | `CastResult` | pads released after ≥0.5 s: the cast, accepted or not |
| `tap` | seconds held | released too soon (no cast) |
| `timeout` | – | held over 8 s |
| `blocked` | – | labelling is on and the last cast isn't labelled |
| `label_needed` / `labelled` | record / (label, total, record) | cast labelling |
| `calibrating` / `calibration` | – / state dict | motion calibration |

## OpenCaster.events (the core)

The manager's `scan found status connecting connected ready disconnected` are
forwarded as-is (`DeviceInfo` first).  Per-wand session events carry the
wand address first: `pads window_open trail tap timeout cast blocked
label_needed labelled calibrating calibration` → `(address, payload)`.

| Event | Args | Notes |
|-------|------|-------|
| `spell` | dict | a spell was cast successfully – see below |
| `cast` | `address, CastResult` | every cast, accepted or not (in duels, rejected with a reason) |
| `window_open` | `address, target` | a cast begins (all four pads) |
| `battery` | `address, percent` | |
| `imu` | `address, first sample of the batch` | ~11.6/s per wand |
| `aim` | `address, right_deg, up_deg` | after `set_aim(address, True)`; until that wand's next cast |
| `motion` | `address, profile or None` | calibration loaded |
| `wand_info` | info dict | colour / nickname / connection changed |
| `log` | `DeviceInfo, notification` | raw notifications worth logging |
| `duel` | snapshot dict + `player_info`, `npc_level` | every duel change – see opencaster/duel.py |
| `settings` | settings dict | |
| `library` | `(templates, spellbook)` | spells reloaded |

`spell` dict: `name`, `info` (`SpellInfo` or None), `source` (`"cast"` or
`"wand"` = the wand's own firmware), `count` (times cast, for mastery),
`mastered_now`, `wand` (address, or `"npc"`), `wand_label`,
`patronus_video`.

Wand info dict: `address`, `name`, `nickname`, `label`, `color`,
`own_color`, `display_mode`, `connected`, `ready`, `wanted`, `battery` (the NPC's adds
`npc: True`, `level`).

## API Server-Sent Events (JSON `data:` lines)

`{"type": ...}` with:
- `spell`: `spell`, `wand` (info dict), `source`, `count`, `mastered_now`, `colors` (["#RRGGBB", …])
- `cast`: `wand`, `accepted`, `spell`, `message`, `gate`, `target`, `best` ({spell, score} or null)
- `casting` (a cast window opened): `wand`, `target`
- `tap`, `pads` (`pads`: 4 bools), `battery` (`percent`)
- `wand_connected`, `wand_ready`, `wand_disconnected`, `wand_info`: `wand`
- `duel`: `duel` (the snapshot) · `settings` · `status` (`text`)
- `imu` and `trail` only with `?include=imu,trail`

Not exposed over the API: `aim`, `label_*`, `calibration`, `motion`, `log`.
