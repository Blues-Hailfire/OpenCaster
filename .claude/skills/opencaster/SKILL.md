---
name: opencaster
description: Write programs for the Magic Caster wand with OpenCaster - react to spells, light and buzz wands, read the touch pads and motion (IMU), recognise gestures, add spells, and build games, duel modes or GUI pages on opencaster.wand, opencaster.casting, opencaster.core and the local HTTP/SSE API. Use whenever code touches the wand, the OpenCaster modules or its API, and to test wand programs without hardware.
---

# Programming the Magic Caster wand with OpenCaster

OpenCaster (this repo) talks to Magic Caster wands over Bluetooth, recognises
spells from the wand's gyro, and plays the original app's light/haptic
effects.  Its layers can be used separately.  Module docstrings are good –
read the one for whatever you touch.

## 1. Pick the layer

| You want to… | Use | Start from |
|--------------|-----|------------|
| React to spells / light or buzz wands **from another program or language** (OpenCaster GUI or `python -m opencaster` running) | local API: HTTP + SSE on 127.0.0.1:8765 | `examples/api_react.py` |
| A Python program with casting, effects, events, **duels, steering (aim)** | embed `opencaster.core.OpenCaster` | `examples/embedded_core.py` |
| The wand as a plain controller: pads, motion, lights – no spells | `opencaster.wand.WandManager` | `examples/wand_only.py` |
| Recognition only: trails, templates, offline data, new spells | `opencaster.casting` | `examples/recognise_offline.py` |
| A new game | pure-logic engine + core events | `examples/spell_echo.py`, `examples/test_spell_echo.py` |
| Change OpenCaster itself (new mode, page, spell, effect) | the package | [reference/extending.md](reference/extending.md) |

Only one program can own the wands (Bluetooth): if OpenCaster is running,
talk to it through the API instead of starting a second core.

## 2. Rules that bite

- **One asyncio loop owns everything.**  Core and manager commands must run
  on its thread; from another thread use `loop.call_soon_threadsafe(core.cmd, …)`
  (the GUI's `bridge.call` does this).  Event handlers run *on* that loop,
  synchronously: keep them short, never block or sleep.
- **One effect per wand at a time** – a new one cancels the running one
  (cast glow → payoff relies on this).  Concatenate effects to sequence them.
- **Casting** = hold all four pads (mask 0x0F), draw, release.  Template
  direction matters.  Each new spell can hurt accuracy: run
  `python -m opencaster.casting evaluate` before and after.
- **Wire format**: durations are little-endian u16 ms, max 32767; LED
  groups 0 (tip) … 3 (handle); macro JSON durations are seconds.
- **IMU** streams continuously (220 Hz, 19 samples/packet, ~12 packets/s),
  samples `(ax, ay, az, gx, gy, gz)` in g and rad/s.  For "where is the wand
  pointing" use `core.set_aim` / `GestureTracker`, not raw gyro maths.
- **The API can't** start duels, steer, or label casts – embed the core.
  It binds to 127.0.0.1, refuses web-page origins unless allowed, and may
  require `Authorization: Bearer <token>`.
- **Players**: wand addresses, or `"npc"` for the computer opponent
  (`opencaster.npc`); NPC spells never count towards mastery.
- **Data**: never write the user's `progress.json`, `settings.json`,
  `wand_profiles.json` or `casts/` from tests – use temp files.  `media/`
  is optional, local and not redistributable: don't copy, bundle or commit it.
- Windows consoles are cp1252: print ASCII or reconfigure stdout to UTF-8.
  Keep code Python 3.11-compatible.

## 3. Test without a wand

`examples/fake_wands.py` fakes the Bluetooth layer under the real manager,
core, sessions and effects:

```python
import fake_wands                       # sits next to the examples; finds the repo itself
rig = fake_wands.install(2)             # before the core/manager runs
core = fake_wands.temp_core(rig)        # temp files; api_port=… to start the API
task = asyncio.create_task(core.run())
await rig.ready(core)
await rig.cast(rig.addresses[0], "Lumos")    # pads + a real gyro gesture + release
rig.lights(rig.addresses[0])                 # [(group, (r, g, b), ms), …] sent to the wand
```

Also `rig.press(a, mask)`, `rig.stream(a, samples)`, `rig.turn(a, right_deg,
up_deg)`, `rig.firmware_spell(a, name)`.  Every example has a self-test:

```bash
python .claude/skills/opencaster/examples/embedded_core.py --fake
```

(From outside the repo, set `OPENCASTER_ROOT` to the checkout.)  Passing
fakes don't prove the feel on a real wand – say what still needs hardware.

## 4. Reference

- [reference/modules.md](reference/modules.md) – every layer's public API, commands, CLIs
- [reference/events.md](reference/events.md) – manager, session, core and API events with payloads
- [reference/hardware.md](reference/hardware.md) – BLE protocol, pads, IMU, LEDs, timing
- [reference/extending.md](reference/extending.md) – how modes, pages, spells and effects are built and tested
- README.md in the repo root, and the user-facing docs in `docs/`;
  `docs/protocol.md` and `docs/spells.md` ("How recognition works") have the full tables.
