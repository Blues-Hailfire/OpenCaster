"""
opencaster.duel — Wizard's duel rules (pure logic)
===================================================
Three modes.  Quick-draw and clash are two-player, first to three round wins
(best of five); the Duelling Club takes two to five players and has no
rounds: one rally that runs until somebody slips up.

  Duel       quick-draw: both players get the same spell each round;
             whoever casts it first wins the round.
  ClashDuel  each player has CLASH_WINDOW_S to cast any battle spell; the
             spells' elements decide the round (see opencaster.elements).
  ClubDuel   Duelling Club: turn by turn, each spell must be answered with
             one that beats it, or blocked with a shield.

Quick-draw:

    intro → countdown (3, 2, 1) → racing ("Cast!") → result → countdown …
                                                           ↘ finished

  - A cast counts only if its gesture window opened after "Cast!" (no
    drawing during the countdown).
  - A round nobody wins within ROUND_TIMEOUT_S, or one that is skipped, is
    void: no point, next spell.  At most MAX_ROUNDS rounds are played; after
    that the higher score wins (or it's a draw).
  - Spells are drawn at random from the pool without repeats until the pool
    runs out.

Clash: picks stay hidden until both players have locked one in or time is
up.  A gesture started inside the window may finish up to CLASH_GRACE_S
late.  Casting nothing loses to any attack; protection and same-element
picks draw; draws score nothing, so a clash allows up to CLASH_MAX_ROUNDS.

Duelling Club: the first seat has CLUB_ATTACK_S to cast an attack.  The
next player has CLUB_COUNTER_S to answer with a spell that beats it – which
the player after them must then answer – or with a shield, after which they
have CLUB_ATTACK_S to attack.  "Next" is the next seat ("in_order") or
anyone but the caster ("random").  The rally has no limit: the first player
who doesn't answer in time, or answers with a spell that doesn't beat the
attack (a shield is no attack), slips up and the duel ends.  It goes to the
player whose spell went unanswered (the latest move by anyone else); if the
opening attack fails, the other player wins a two-player duel and a bigger
one has no winner.  A gesture that isn't recognised may be cast again while
time remains.  There's one "round"; after the result comes "finished".

No clock or timers of its own: `schedule(delay, fn)` must return a handle
with .cancel() (asyncio's loop.call_later fits) and `clock()` returns
seconds.  Every change is reported as on_change(snapshot dict).
"""

import random
import time
from typing import Callable, Optional

from .elements import BEATS, PROTECTION, battle_spells, beats, clash, element_of

WINS_NEEDED     = 3
MAX_ROUNDS      = 9
COUNTDOWN       = 3          # beats
BEAT_S          = 1.0
ROUND_TIMEOUT_S = 30.0
RESULT_S        = 7.5        # a burst, then a 5 s payoff video

CLASH_WINDOW_S   = 3.0       # time to cast after "Cast!"
CLASH_GRACE_S    = 2.0       # a gesture started in time may finish this much later
CLASH_MAX_ROUNDS = 15

CLUB_ATTACK_S  = 3.0         # opening the rally, or attacking after a block
CLUB_COUNTER_S = 5.0         # answering an attack
CLUB_MAX_PLAYERS = 5
CLUB_ORDERS = ("in_order", "random")


class Duel:
    mode = "race"
    max_rounds = MAX_ROUNDS
    wins_needed = WINS_NEEDED
    min_players = max_players = 2

    def __init__(self, players: list, spells: list, on_change: Callable[[dict], None],
                 schedule: Callable, clock: Callable[[], float] = time.monotonic,
                 rng: Optional[random.Random] = None, intro_s: float = 2.0):
        if not self.min_players <= len(players) <= self.max_players or len(set(players)) != len(players):
            raise ValueError("a duel needs two different wands" if self.max_players == 2 else
                             f"a duel needs {self.min_players} to {self.max_players} different wands")
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
        return {"mode": self.mode, "phase": self.phase, "round": self.round, "spell": self.spell,
                "count": self.count, "players": list(self.players),
                "scores": dict(self.scores), "round_winner": self.round_winner,
                "winner": self.winner, "message": self.message,
                "wins_needed": self.wins_needed, "history": list(self.history)}

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
        if self.round >= self.max_rounds:
            return self._finish()
        self.round += 1
        self.round_winner = None
        self._new_round()
        self.count = COUNTDOWN
        self.phase = "countdown"
        self.message = f"Round {self.round}"
        self._publish()
        self._after(BEAT_S, self._beat)

    def _new_round(self):
        self.spell = self._draw_spell()

    def _beat(self):
        self.count -= 1
        if self.count > 0:
            self._publish()
            self._after(BEAT_S, self._beat)
            return
        self._go()

    def _go(self):
        self.phase = "racing"
        self._go_at = self.clock()
        self.message = "Cast!"
        self._publish()
        self._after(ROUND_TIMEOUT_S, lambda: self._end_round(None, "Time's up"))

    def _end_round(self, winner: Optional[str], message: str):
        self.round_winner = winner
        self.history.append(self._record(winner))
        self.phase = "result"
        self.message = message
        self._publish()
        self._after(RESULT_S, self._finish if self._decided(winner) else self._next_round)

    def _decided(self, winner: Optional[str]) -> bool:
        """Does this round end the duel?"""
        return bool(winner) and self.scores[winner] >= self.wins_needed

    def _finish(self):
        top = max(self.scores.values())
        leaders = [p for p in self.players if self.scores[p] == top]
        self.winner = leaders[0] if len(leaders) == 1 else None      # a tie is a draw
        self.phase = "finished"
        self.message = "Draw" if self.winner is None else "Victory"
        self._cancel_timer()
        self._publish()

    def _record(self, winner: Optional[str]) -> tuple:
        return self.round, self.spell, winner


class ClashDuel(Duel):
    """Each round both players cast any battle spell within CLASH_WINDOW_S of
    "Cast!"; elements decide who wins.  The phase during the window is still
    "racing"."""
    mode = "clash"
    max_rounds = CLASH_MAX_ROUNDS

    def __init__(self, players: list, on_change: Callable[[dict], None], schedule: Callable,
                 clock: Callable[[], float] = time.monotonic,
                 rng: Optional[random.Random] = None, intro_s: float = 2.0):
        super().__init__(players, battle_spells(), on_change, schedule, clock, rng, intro_s)
        self.picks: dict = {}            # player → locked-in spell (hidden until the result)
        self.line = ""                   # "Aguamenti douses Incendio"
        self.overtime = False            # window over, waiting for a gesture in progress
        self._drawing: set = set()       # players drawing a gesture that started in time
        self._deadline = 0.0

    def skip(self):
        pass                             # rounds are short; nothing to skip

    # ── inputs ────────────────────────────────────────────────────────────────

    def window_opened(self, player: str):
        super().window_opened(player)
        if player in self.players and self.racing and player not in self.picks \
                and self.clock() <= self._deadline:
            self._drawing.add(player)

    def window_closed(self, player: str):
        """A gesture ended without a recognised spell (tap, no match)."""
        self._drawing.discard(player)
        self._maybe_done()

    def cast(self, player: str, accepted: bool, spell: Optional[str]) -> str:
        """Report a recognised cast.  Returns "" if it locked in the player's
        spell for this round, else why it doesn't count."""
        if player not in self.players:
            return "not in this duel"
        self._drawing.discard(player)
        note = self._check(player, accepted, spell)
        if not note:
            self.picks[player] = spell
            self._publish()
        self._maybe_done()
        return note

    def _check(self, player: str, accepted: bool, spell: Optional[str]) -> str:
        if self.phase in ("intro", "countdown"):
            return "too early - wait for “Cast!”"
        if self.phase != "racing":
            return "the round is over"
        if player in self.picks:
            return "spell already chosen"
        opened = self._opened.get(player, -1.0)
        if opened < self._go_at:
            return "too early - wait for “Cast!”"
        if opened > self._deadline:
            return "too late"
        if not (accepted and spell):
            return "no spell recognised"
        if element_of(spell) is None:
            return f"{spell} has no power in a duel"
        return ""

    # ── flow ──────────────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        s = super().snapshot()
        shown = self.phase in ("result", "finished")
        s.update(window_s=CLASH_WINDOW_S, overtime=self.overtime,
                 locked=[p for p in self.players if p in self.picks],
                 picks=dict(self.picks) if shown else {},
                 elements={p: element_of(sp) for p, sp in self.picks.items()} if shown else {},
                 line=self.line if shown else "")
        return s

    def _new_round(self):
        self.spell = None
        self.picks, self.line, self.overtime = {}, "", False
        self._drawing = set()

    def _go(self):
        self.phase = "racing"
        self._go_at = self.clock()
        self._deadline = self._go_at + CLASH_WINDOW_S
        self.message = "Cast!"
        self._publish()
        self._after(CLASH_WINDOW_S, self._time_up)

    def _time_up(self):
        if not self.racing:
            return
        if self._drawing:
            self.overtime = True
            self.message = "Finishing…"
            self._publish()
            self._after(CLASH_GRACE_S, self._resolve)
        else:
            self._resolve()

    def _maybe_done(self):
        """Resolve once every player has a spell, or in overtime once nobody
        is still drawing.  Deferred, so the caller's cast is reported first."""
        if self.racing and (len(self.picks) == len(self.players)
                            or self.overtime and not self._drawing):
            self._after(0.0, self._resolve)

    def _resolve(self):
        if not self.racing:
            return
        a, b = self.players
        side, self.line = clash(self.picks.get(a), self.picks.get(b))
        winner = self.players[side] if side is not None else None
        if winner:
            self.scores[winner] += 1
        self.overtime = False
        self._end_round(winner, self.line)

    def _record(self, winner: Optional[str]) -> tuple:
        return self.round, dict(self.picks), winner


class ClubDuel(Duel):
    """Duelling Club: one rally on the clash elements, for two to five
    players in seat order, until somebody slips up.  The phase stays
    "racing" through the rally; every new turn bumps turn_no."""
    mode = "club"
    max_players = CLUB_MAX_PLAYERS
    wins_needed = 1

    def __init__(self, players: list, on_change: Callable[[dict], None], schedule: Callable,
                 clock: Callable[[], float] = time.monotonic,
                 rng: Optional[random.Random] = None, intro_s: float = 2.0,
                 order: str = "in_order"):
        super().__init__(players, battle_spells(), on_change, schedule, clock, rng, intro_s)
        if order not in CLUB_ORDERS:
            raise ValueError(f"order must be one of {CLUB_ORDERS}")
        self.order = order
        self.turn: Optional[str] = None  # whose turn it is
        self.turn_kind = ""              # "attack" or "counter"
        self.turn_no = 0
        self.incoming: Optional[str] = None   # the spell to answer (counter turns)
        self.chain: list = []            # this round's good moves, oldest first
        self.line = ""                   # why the round ended
        self.loser: Optional[str] = None
        self.overtime = False
        self._drawing = False            # the player whose turn it is started a gesture in time
        self._turn_at = 0.0
        self._deadline = 0.0

    def skip(self):
        pass

    @property
    def window_s(self) -> float:
        return CLUB_ATTACK_S if self.turn_kind == "attack" else CLUB_COUNTER_S

    def _next(self, player: str) -> str:
        """Who answers `player`'s spell: the next seat, or anyone else at random."""
        if self.order == "random":
            return self.rng.choice([p for p in self.players if p != player])
        return self.players[(self.players.index(player) + 1) % len(self.players)]

    # ── inputs ────────────────────────────────────────────────────────────────

    def window_opened(self, player: str):
        super().window_opened(player)
        if self.racing and player == self.turn and self.clock() <= self._deadline:
            self._drawing = True

    def window_closed(self, player: str):
        """A gesture ended without a recognised spell (tap, no match)."""
        if player == self.turn:
            self._drawing = False
            self._maybe_out()

    def cast(self, player: str, accepted: bool, spell: Optional[str]) -> tuple:
        """Report a recognised cast.  Returns (counted, note).  counted: it
        was the player's move – a good one if note is "", else a wrong spell
        that loses the round (note says why).  Not counted: note says why it
        was ignored, and the player may cast again while time remains."""
        if player not in self.players:
            return False, "not in this duel"
        if player == self.turn:
            self._drawing = False
        note = self._check(player, accepted, spell)
        if note:
            self._maybe_out()
            return False, note
        element = element_of(spell)
        wrong = self._judge(spell, element)
        if wrong:
            self._after(0.0, lambda: self._lose(player, wrong))
            return True, wrong
        if self.turn_kind == "counter" and element == PROTECTION:
            move, verb, nxt = "block", "blocks", (player, "attack", None)
        elif self.turn_kind == "counter":
            move, verb = "counter", BEATS[element][element_of(self.incoming)]
            nxt = (self._next(player), "counter", spell)
        else:
            move, verb, nxt = "attack", "", (self._next(player), "counter", spell)
        self.chain.append({"player": player, "spell": spell, "element": element, "move": move,
                           "verb": verb, "against": self.incoming})
        self._after(0.0, lambda: self._start_turn(*nxt))      # the cast is reported first
        return True, ""

    def _check(self, player: str, accepted: bool, spell: Optional[str]) -> str:
        if self.phase in ("intro", "countdown"):
            return "too early - wait for “Cast!”"
        if self.phase != "racing":
            return "the round is over"
        if player != self.turn:
            return "not your turn"
        opened = self._opened.get(player, -1.0)
        if opened < self._turn_at:
            return "too early - wait for your turn"
        if opened > self._deadline:
            return "too late"
        if not (accepted and spell):
            return "no spell recognised"
        if element_of(spell) is None:
            return f"{spell} has no power in a duel"
        return ""

    def _judge(self, spell: str, element: str) -> str:
        """Why the move loses the round, or "" for a good move."""
        if self.turn_kind == "attack":
            return f"{spell} is a shield, not an attack" if element == PROTECTION else ""
        if element == PROTECTION:
            return ""
        incoming = element_of(self.incoming)
        if beats(element, incoming):
            return ""
        if element == incoming:
            return f"{spell} can't beat {self.incoming} – the same element"
        return f"{self.incoming} {BEATS[incoming][element]} {spell}"

    # ── flow ──────────────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        s = super().snapshot()
        s.update(order=self.order, turn=self.turn, turn_kind=self.turn_kind, turn_no=self.turn_no,
                 window_s=self.window_s, incoming=self.incoming,
                 incoming_element=element_of(self.incoming), chain=[dict(c) for c in self.chain],
                 line=self.line, loser=self.loser, overtime=self.overtime,
                 starter=self.players[(self.round - 1) % len(self.players)] if self.round else None)
        return s

    def _new_round(self):
        self.spell = None
        self.turn, self.turn_kind, self.incoming = None, "", None
        self.chain, self.line, self.loser = [], "", None
        self.overtime, self._drawing = False, False

    def _go(self):
        self.phase = "racing"
        self.message = "Cast!"
        self._start_turn(self.players[(self.round - 1) % len(self.players)], "attack", None)

    def _start_turn(self, player: str, kind: str, incoming: Optional[str]):
        if not self.racing:
            return
        self.turn, self.turn_kind, self.incoming = player, kind, incoming
        self.turn_no += 1
        self._turn_at = self.clock()
        self._deadline = self._turn_at + self.window_s
        self._drawing, self.overtime = False, False
        self._publish()
        self._after(self.window_s, self._time_up)

    def _time_up(self):
        if not self.racing:
            return
        if self._drawing:
            self.overtime = True
            self.message = "Finishing…"
            self._publish()
            self._after(CLASH_GRACE_S, self._timed_out)
        else:
            self._timed_out()

    def _maybe_out(self):
        """In overtime, the gesture that was still going has ended without a move."""
        if self.racing and self.overtime and not self._drawing:
            self._after(0.0, self._timed_out)

    def _timed_out(self):
        if self.racing:
            self._lose(self.turn, f"no answer to {self.incoming}" if self.turn_kind == "counter"
                       else "no attack in time")

    def _lose(self, player: str, line: str):
        if not self.racing:
            return
        # The player whose spell went unanswered: the latest move by anyone else.
        winner = next((c["player"] for c in reversed(self.chain) if c["player"] != player), None)
        if winner is None and len(self.players) == 2:          # the opener failed
            winner = next(p for p in self.players if p != player)
        if winner:
            self.scores[winner] += 1
        self.loser, self.line, self.overtime = player, line, False
        self._end_round(winner, line)

    def _decided(self, winner: Optional[str]) -> bool:
        return True                      # one rally decides the duel

    def _record(self, winner: Optional[str]) -> tuple:
        return self.round, [c["spell"] for c in self.chain], winner


def _same(a: str, b: str) -> bool:
    norm = lambda s: "".join(ch for ch in s.lower() if ch.isalnum())
    return norm(a) == norm(b)
