"""
opencaster.duel — Wizard's duel rules (pure logic)
===================================================
Two players get the same spell each round; whoever casts it first wins the
round.  First to three round wins takes the duel (best of five).

    intro → countdown (3, 2, 1) → racing ("Cast!") → result → countdown …
                                                           ↘ finished

  - A cast counts only if its gesture window opened after "Cast!" (no
    drawing during the countdown).
  - A round nobody wins within ROUND_TIMEOUT_S, or one that is skipped, is
    void: no point, next spell.  At most MAX_ROUNDS rounds are played; after
    that the higher score wins (or it's a draw).
  - Spells are drawn at random from the pool without repeats until the pool
    runs out.

No clock or timers of its own: `schedule(delay, fn)` must return a handle
with .cancel() (asyncio's loop.call_later fits) and `clock()` returns
seconds.  Every change is reported as on_change(snapshot dict).
"""

import random
import time
from typing import Callable, Optional

WINS_NEEDED     = 3
MAX_ROUNDS      = 9
COUNTDOWN       = 3          # beats
BEAT_S          = 1.0
ROUND_TIMEOUT_S = 30.0
RESULT_S        = 7.5        # a burst, then a 5 s payoff video


class Duel:
    def __init__(self, players: list, spells: list, on_change: Callable[[dict], None],
                 schedule: Callable, clock: Callable[[], float] = time.monotonic,
                 rng: Optional[random.Random] = None, intro_s: float = 2.0):
        if len(players) != 2 or players[0] == players[1]:
            raise ValueError("a duel needs two different wands")
        if not spells:
            raise ValueError("the spell pool is empty")
        self.players = list(players)
        self.pool = list(spells)
        self.on_change = on_change
        self.schedule = schedule
        self.clock = clock
        self.rng = rng or random.Random()
        self.intro_s = intro_s
        self.phase = "idle"
        self.round = 0
        self.spell: Optional[str] = None
        self.count = 0
        self.scores = {p: 0 for p in self.players}
        self.round_winner: Optional[str] = None
        self.winner: Optional[str] = None
        self.message = ""
        self.history: list = []          # (round, spell, winner or None)
        self._deck: list = []
        self._go_at = 0.0
        self._opened: dict = {}
        self._timer = None

    # ── control ───────────────────────────────────────────────────────────────

    def start(self):
        self.phase = "intro"
        self.message = "The duel begins"
        self._publish()
        self._after(self.intro_s, self._next_round)

    def cancel(self):
        if self.phase in ("finished", "cancelled"):
            return
        self._cancel_timer()
        self.phase = "cancelled"
        self.message = "Duel cancelled"
        self._publish()

    def skip(self):
        """Void the current round (e.g. a spell that won't recognise)."""
        if self.phase in ("countdown", "racing"):
            self._end_round(None, "Round skipped")

    @property
    def active(self) -> bool:
        return self.phase in ("intro", "countdown", "racing", "result")

    @property
    def racing(self) -> bool:
        return self.phase == "racing"

    # ── inputs ────────────────────────────────────────────────────────────────

    def window_opened(self, player: str):
        self._opened[player] = self.clock()

    def cast(self, player: str, accepted: bool, spell: Optional[str]) -> bool:
        """Report a finished cast; returns True if it won the round."""
        if self.phase != "racing" or player not in self.players:
            return False
        if self._opened.get(player, -1.0) < self._go_at:
            return False                         # started drawing before "Cast!"
        if not (accepted and spell and _same(spell, self.spell)):
            return False
        self.scores[player] += 1
        self._end_round(player, "")
        return True

    # ── flow ──────────────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        return {"phase": self.phase, "round": self.round, "spell": self.spell,
                "count": self.count, "players": list(self.players),
                "scores": dict(self.scores), "round_winner": self.round_winner,
                "winner": self.winner, "message": self.message,
                "wins_needed": WINS_NEEDED, "history": list(self.history)}

    def _publish(self):
        self.on_change(self.snapshot())

    def _after(self, delay: float, fn):
        self._cancel_timer()
        self._timer = self.schedule(delay, fn)

    def _cancel_timer(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _draw_spell(self) -> str:
        if not self._deck:
            self._deck = list(self.pool)
            self.rng.shuffle(self._deck)
            if len(self._deck) > 1 and _same(self._deck[-1], self.spell or ""):
                self._deck.insert(0, self._deck.pop())      # no immediate repeat
        return self._deck.pop()

    def _next_round(self):
        if self.round >= MAX_ROUNDS:
            return self._finish()
        self.round += 1
        self.spell = self._draw_spell()
        self.round_winner = None
        self.count = COUNTDOWN
        self.phase = "countdown"
        self.message = f"Round {self.round}"
        self._publish()
        self._after(BEAT_S, self._beat)

    def _beat(self):
        self.count -= 1
        if self.count > 0:
            self._publish()
            self._after(BEAT_S, self._beat)
            return
        self.phase = "racing"
        self._go_at = self.clock()
        self.message = "Cast!"
        self._publish()
        self._after(ROUND_TIMEOUT_S, lambda: self._end_round(None, "Time's up"))

    def _end_round(self, winner: Optional[str], message: str):
        self.round_winner = winner
        self.history.append((self.round, self.spell, winner))
        self.phase = "result"
        self.message = message
        self._publish()
        if winner and self.scores[winner] >= WINS_NEEDED:
            self._after(RESULT_S, self._finish)
        else:
            self._after(RESULT_S, self._next_round)

    def _finish(self):
        a, b = self.players
        self.winner = a if self.scores[a] > self.scores[b] else \
            b if self.scores[b] > self.scores[a] else None
        self.phase = "finished"
        self.message = "Draw" if self.winner is None else "Victory"
        self._cancel_timer()
        self._publish()


def _same(a: str, b: str) -> bool:
    norm = lambda s: "".join(ch for ch in s.lower() if ch.isalnum())
    return norm(a) == norm(b)
