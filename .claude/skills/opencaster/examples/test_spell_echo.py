"""
Unit tests for the Spell Echo engine with a fake clock: no wand, no waiting.
The same pattern tests OpenCaster's own engines (duel.py, environment.py).

    python test_spell_echo.py
"""

import random

import spell_echo as G


class FakeClock:
    """schedule(delay, fn) → handle with .cancel(); advance() runs what's due."""

    def __init__(self):
        self.t = 0.0
        self.jobs: list = []                     # [due, seq, fn, cancelled-flag]
        self._seq = 0

    def schedule(self, delay, fn):
        job = [self.t + delay, self._seq, fn, [False]]
        self._seq += 1
        self.jobs.append(job)

        class Handle:
            def cancel(self_inner):
                job[3][0] = True
        return Handle()

    def advance(self, seconds):
        end = self.t + seconds
        while True:
            due = sorted((j for j in self.jobs if not j[3][0] and j[0] <= end), key=lambda j: (j[0], j[1]))
            if not due:
                break
            job = due[0]
            self.jobs.remove(job)
            self.t = job[0]
            job[2]()
        self.t = end


def game(seed=1):
    clock, snaps = FakeClock(), []
    g = G.EchoGame(snaps.append, clock.schedule, lambda: clock.t, random.Random(seed))
    return g, clock, snaps


def test_show_then_cast_back_and_grow():
    g, clock, snaps = game()
    g.start()
    assert g.phase == "showing" and snaps[-1]["sequence"] == g.sequence[:1]
    assert g.cast("Lumos") == "wait for your turn"
    clock.advance(G.SHOW_S * len(g.sequence))
    assert g.phase == "casting" and snaps[-1]["next"] == g.sequence[0]
    assert g.cast(g.sequence[0]) == ""
    assert g.phase == "result" and g.score == 1
    clock.advance(G.RESULT_S)
    assert g.phase == "showing" and len(g.sequence) == 2       # one more each round
    clock.advance(G.SHOW_S * 2)
    for spell in list(g.sequence):
        assert g.cast(spell) == ""
    assert g.score == 2


def test_wrong_spell_ends_it():
    g, clock, snaps = game()
    g.start()
    clock.advance(G.SHOW_S)
    want = g.sequence[0]
    wrong = next(s for s in G.EASY if s != want)
    assert g.cast(wrong) == f"not {want}"
    assert g.phase == "finished" and "Game over" in snaps[-1]["message"] and not g.active


def test_too_slow_ends_it_and_counts_down():
    g, clock, snaps = game()
    g.start()
    clock.advance(G.SHOW_S)
    clock.advance(G.CAST_S / 2)
    assert abs(g.snapshot()["seconds_left"] - G.CAST_S / 2) < 1e-9
    clock.advance(G.CAST_S / 2)
    assert g.phase == "finished" and "Too slow" in g.message


def test_cancel_stops_the_timers():
    g, clock, snaps = game()
    g.start()
    g.cancel()
    n = len(snaps)
    clock.advance(100)
    assert len(snaps) == n and g.phase == "finished"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    print("spell echo engine OK")
