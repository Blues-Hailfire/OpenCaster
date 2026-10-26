# Architecture

[← OpenCaster](../README.md) · [Documentation](README.md)

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
  and scan results as callbacks on one asyncio loop; nothing polls (bar
  passive mode's scan every 20 s, which is off unless you turn it on).
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

## Project files

| Path | Purpose |
|------|---------|
| `OpenCaster_GUI.py` | Starts the GUI |
| `setup.bat` / `setup.ps1`, `setup.sh` | One-step setup: Python check, private environment, packages, shortcuts / launcher |
| `packaging/` | Windows release: PyInstaller spec, `build.ps1`, the zip's README and third-party notices |
| `.github/workflows/release.yml` | Builds and publishes the Windows release on a version tag |
| `opencaster/wand/` | **Wand link** (bleak only): `protocol.py` UUIDs, opcodes, parsing, frame builders · `effects.py` built-in animations and spellbook macro encoding · `device.py` one BLE link · `manager.py` scanning, auto-connect, passive mode, reconnect, boxes · `__main__.py` headless CLI |
| `opencaster/casting/` | **Spell assessment** (numpy/scipy only): `tracker.py` gyro gesture tracker · `shapes.py` SVG templates · `matcher.py` DTW recogniser and thresholds · `session.py` casting state machine · `calibration.py` motion calibration logic · `castlog.py` labelled casts · `profiles.py` per-wand calibration · `__main__.py` evaluate / replay CLI |
| `opencaster/recognition/` | **Recognition testing and training** (offline; never loaded by the app): `synth.py` synthetic casts and near-misses, per-spell threshold fitting · `gpu.py` bulk DTW scoring on the GPU (OpenCL, optional) · `__main__.py` synth CLI |
| `opencaster/spellbook.py` | Original spell data, cast colours, sounds, videos; mastery progress |
| `opencaster/media_pack.py` | Downloads, checks and unpacks the media pack into `media/` |
| `opencaster/settings.py` | Default colour, house, Patronus, passive mode, API settings (`settings.json`) |
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
| `wand_profiles.json` | Per-wand calibration, colour, nickname, display mode and auto-connect |
| `media/` | `spellbook.json` (the spell manifest) and `Logo/` are tracked; the media pack (sounds, videos) is gitignored – downloaded by setup or the app |
| `Bluetooth Capture/` | Original btsnoop capture of the official app |
