"""
A wand game built the way OpenCaster's duels are: "Spell Echo".

Each round shows a sequence of spells, one more than the last; cast them
back in order, each within CAST_S.  A wrong spell or a timeout ends the game.

The engine (EchoGame) is pure logic, like opencaster/duel.py:
  - no clock or timers of its own: `schedule(delay, fn)` returns a handle with
    .cancel() (asyncio's loop.call_later fits) and `clock()` returns seconds;
  - every change is published as on_change(snapshot dict);
  - inputs are plain method calls (cast), so it's testable with a fake
    clock (test_spell_echo.py) and drivable by anything: the core's "spell"
    events, the API's event stream, a GUI.

    python spell_echo.py           # play with your wand (embeds the core)
    python spell_echo.py --fake    # watch a fake wand play three rounds
"""

import argparse
import asyncio
import random
import sys
import time
from typing import Callable, Optional

SHOW_S = 1.6          # each spell of the sequence is shown this long
CAST_S = 8.0          # time to cast each spell back
RESULT_S = 2.0        # pause after a round
START_LENGTH = 1
EASY = ("Lumos", "Nox", "Incendio", "Aguamenti", "Accio", "Protego", "Ventus", "Reparo")


class EchoGame:
    """idle → showing → casting → result → showing … → finished"""

    def __init__(self, on_change: Callable[[dict], None], schedule: Callable,
                 clock: Callable[[], float] = time.monotonic, rng: Optional[random.Random] = None,
                 spells=EASY):
        self.on_change, self.schedule, self.clock = on_change, schedule, clock
        self.rng = rng or random.Random()
        self.spells = list(spells)
        self.phase = "idle"
        self.sequence: list = []
        self.shown = 0                      # how many of the sequence are on show
        self.done = 0                       # how many cast back correctly this round
        self.score = 0                      # rounds completed
        self.message = ""
        self.deadline = 0.0
        self._timer = None

    # -- control ---------------------------------------------------------------

    def start(self):
        self.sequence = [self.rng.choice(self.spells) for _ in range(START_LENGTH)]
        self.score = 0
        self._show()

    def cancel(self):
        self._cancel_timer()
        self.phase, self.message = "finished", "Cancelled"
        self._publish()

    @property
    def active(self) -> bool:
        return self.phase in ("showing", "casting", "result")

    # -- input -------------------------------------------------------------------

    def cast(self, spell: str) -> str:
        """A recognised spell.  Returns "" if it was the right one, else why not."""
        if self.phase != "casting":
            return "wait for your turn" if self.phase == "showing" else "the game isn't running"
        want = self.sequence[self.done]
        if spell != want:
            self._end(f"{spell} – the spell was {want}")
            return f"not {want}"
        self.done += 1
        if self.done == len(self.sequence):
            self.score += 1
            self.phase, self.message = "result", f"Round {self.score} done!"
            self._publish()
            self._after(RESULT_S, self._next_round)
        else:
            self._expect()
        return ""

    # -- flow --------------------------------------------------------------------

    def snapshot(self) -> dict:
        return {"phase": self.phase, "sequence": list(self.sequence[:self.shown])
                if self.phase == "showing" else list(self.sequence), "shown": self.shown,
                "done": self.done, "next": self.sequence[self.done] if self.phase == "casting" else None,
                "score": self.score, "message": self.message,
                "seconds_left": max(0.0, self.deadline - self.clock()) if self.phase == "casting" else None}

    def _publish(self):
        self.on_change(self.snapshot())

    def _after(self, delay: float, fn):
        self._cancel_timer()
        self._timer = self.schedule(delay, fn)

    def _cancel_timer(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _show(self):
        self.phase, self.shown, self.done = "showing", 0, 0
        self.message = f"Watch: {len(self.sequence)} spell{'s' if len(self.sequence) > 1 else ''}"
        self._show_next()

    def _show_next(self):
        if self.shown == len(self.sequence):
            self.phase, self.message = "casting", "Your turn: cast them back in order"
            self._expect()
            return
        self.shown += 1
        self._publish()
        self._after(SHOW_S, self._show_next)

    def _expect(self):
        self.deadline = self.clock() + CAST_S
        self._publish()
        self._after(CAST_S, lambda: self._end(f"Too slow – the spell was {self.sequence[self.done]}"))

    def _next_round(self):
        self.sequence.append(self.rng.choice(self.spells))
        self._show()

    def _end(self, why: str):
        self._cancel_timer()
        self.phase, self.message = "finished", f"Game over: {why}.  Score {self.score}"
        self._publish()


# -- wiring it to the wand: the core's events in, wand effects out ---------------

def wire(core, game_factory, log=print) -> dict:
    """Connect an EchoGame to an OpenCaster core.  Returns a dict holding the
    game, so the caller can start it once a wand is ready."""
    state: dict = {"game": None, "wand": None}

    def on_change(snap):
        log(f"[{snap['phase']}] {snap['message']}"
            + (f"  showing: {' > '.join(snap['sequence'])}" if snap["phase"] == "showing" else "")
            + (f"  next: {snap['next']}" if snap["next"] else ""))
        wand = state["wand"]
        if wand and snap["phase"] == "result":
            core.play_effect(wand, name="success")
        elif wand and snap["phase"] == "finished":
            core.play_effect(wand, name="round_lost")

    def on_spell(s):
        game = state["game"]
        if game and game.active:
            state["wand"] = s["wand"]
            note = game.cast(s["name"])
            if note:
                log(f"  ({note})")

    state["game"] = game_factory(on_change)
    core.events.on("spell", on_spell)
    core.set_free_cast(True)                 # no practice spell or labelling getting in the way
    return state


async def run(fake: bool):
    loop = asyncio.get_running_loop()
    if fake:
        import fake_wands
        rig = fake_wands.install(1)
        core = fake_wands.temp_core(rig)
    else:
        from fake_wands import repo_root
        sys.path.insert(0, str(repo_root()))
        from opencaster.core import OpenCaster
        core, rig = OpenCaster(), None
    task = asyncio.create_task(core.run())
    lines = []
    state = wire(core, lambda on_change: EchoGame(on_change, loop.call_later, rng=random.Random(3)),
                 (lambda s: (print(s), lines.append(s))) if fake else print)
    if fake:
        await rig.ready(core)
    else:
        print("Waiting for a wand... (Ctrl+C to stop)")
        while not core.ready:
            await asyncio.sleep(0.2)
    game = state["game"]
    game.start()
    if not fake:
        while game.phase != "finished":
            await asyncio.sleep(0.2)
    else:
        wand = rig.addresses[0]
        while game.score < 3:                          # a fake player with a perfect memory
            while game.phase != "casting":
                await asyncio.sleep(0.05)
            await rig.cast(wand, game.snapshot()["next"])
            await asyncio.sleep(0.1)
        while game.phase != "casting":
            await asyncio.sleep(0.05)
        wrong = next(s for s in EASY if s != game.snapshot()["next"])
        await rig.cast(wand, wrong)                    # ... until it slips
        await asyncio.sleep(0.2)
        assert game.phase == "finished" and game.score == 3, game.snapshot()
        assert any("Game over" in s for s in lines)
        print("spell_echo self-test OK")
    core.stop()
    await asyncio.wait_for(task, 5)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fake", action="store_true", help="a fake wand plays")
    args = ap.parse_args()
    try:
        asyncio.run(run(args.fake))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
