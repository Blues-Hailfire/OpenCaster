# Extending OpenCaster itself

How the existing features are built, so new ones fit in.  Read the
named files before changing them; match their style (short comments,
docstrings that say why, no new dependencies).

## A new game or duel mode

Follow `opencaster/duel.py` (and `examples/spell_echo.py`, a small copy of
the pattern):

1. **Pure-logic engine** in `opencaster/<name>.py`: no Qt, no asyncio, no
   wand I/O.  Constructor takes `on_change(snapshot)`, `schedule(delay, fn)
   → handle.cancel()`, `clock()`, `rng`.  Inputs are method calls
   (`window_opened(player)`, `cast(player, accepted, spell)` …) that return
   whether/why a cast counted.  Every state change calls
   `on_change(self.snapshot())`; the snapshot is a JSON-able dict (it goes
   to the GUI and the API).  Defer follow-on transitions with
   `schedule(0, …)` so the caller's cast is reported before the next state.
2. **Unit tests with a fake clock** (`examples/test_spell_echo.py`'s
   `FakeClock`): every phase, timeouts, cancel, edge cases.  No real waiting.
3. **Core wiring** in `opencaster/core.py`: a `start_…` command builds the
   engine with `self._loop.call_later`; a `_on_…(snap)` handler plays wand
   cues on the players' live wands (`effects.go`, `round_lost`, `duel_won`
   …) and emits an event.  Route casts in `_on_session` (see how
   `_turn_based` sends clash/club casts to the engine and rejects others
   with a note via `payload.rejected(note)`).  Restrict matching with
   `session.allowed = frozenset(spell keys)` while it runs; restore in
   `_sync_sessions`.  Wand cues go only to `a in self.wands` (the NPC has none).
4. **GUI**: a page or a mode in `gui/duel_page.py`, fed by `_ev_<event>` in
   `gui/app.py`.  Pages that want every spell call `set_free_cast(True)`
   while shown (see `_show_page`).
5. **Headless**: a flag in `opencaster/__main__.py` and printing in its `on_…` handler.
6. **Docs**: README section + the `duel` snapshot fields under "Control API".

The NPC (`opencaster/npc.py`) shows how a computer player joins any mode:
the core plays its moves with timers through the same `_on_session` path as
a wand (window_open → trail events → cast), so engines never special-case it.

## A new page / scene in the GUI
- Scenes are `QWidget`s painted with `QPainter`; animate with
  `widgets.Animator` (a 60 fps timer that runs only while something moves –
  return False from your step when idle; stop it in `hideEvent`).
- Keep rules in a pure model (like `opencaster/environment.py`'s `Pumpkin`,
  whose `cast(spell)` returns `Outcome(spell, text, fx cues, blocked)`), and
  the drawing in the scene (`gui/pumpkin.py` plays the cues).
- Art style of the original app: flat 2D silhouettes, one hue per scene
  (the spell's effect as the bright accent), stipple dust, film grain.
  `gui/pumpkin.py` grades grey-level art through a one-hue gradient map.
- Long work never on the Qt thread; core calls go through `bridge.call`.
- Screenshot to check: `win.grab().save(...)` after `app.processEvents()`,
  with prefs redirected to a temp QSettings (see the pattern in
  `examples/` – never touch the user's real prefs/progress).

## A new spell
- One SVG in `spells/`, a single `<path>` in a 200×200 viewBox, drawn in
  casting order (direction matters).  File name = spell name (matching the
  spellbook entry picks up its effects).  `tools/spell_editor.py` draws one.
- Every new template can be confused with others: run
  `python -m opencaster.casting evaluate` before and after.
- Give it an element in `opencaster/elements.py` if it should duel, and a
  handler `_<spellkey>` in `opencaster/environment.py` (the test requires
  every spell to have one).

## A new wand effect
- Add a function to `opencaster/wand/effects.py` built from proven
  commands (`_prefixed`, `p.all_groups`, `p.changeled`, `_buzz_pulse`,
  waits), register it in `BUILTIN` if the API should offer it, and list it
  in the API's effect help (`opencaster/api/__main__.py`) and the README.

## Testing without hardware
- `examples/fake_wands.py`: fake BLE devices under the real manager, core,
  sessions and effects; `rig.cast(address, "Lumos")` draws the real
  template with synthesised gyro data (all 52 spells recognise).  Inspect
  what was sent with `rig.writes()` / `rig.lights()`.
- Inject straight into the core when the casting pipeline isn't the point:
  `core._on_session(address, "window_open")` then
  `core._on_session(address, "cast", CastResult(trail, "ok", (Match(spell, spell_key(spell), 0.1, 0.3, True),), None))`.
- Keep every test's files in a temp folder (`fake_wands.temp_core`).
- Print ASCII or `sys.stdout.reconfigure(encoding="utf-8")` – Windows
  consoles (cp1252) crash on ✦ ✓ ♪.
- Stay Python 3.11-compatible (no nested same-quote f-strings).
- Nothing here proves the feel on a real wand: say so when reporting.
