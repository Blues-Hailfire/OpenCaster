"""
opencaster.npc — A computer opponent for duels (pure logic)
============================================================
The NPC takes a seat in any duel mode under the player id NPC.  For each
move it decides what to cast and how long that takes – a pause to react,
then a gesture drawn over a second or two – at one of three skill levels:

    easy    slow; fumbles one gesture in four; answers right two times in three
    medium  quicker; fumbles one in eight; answers right four times in five
    hard    quick and sure; in a clash it learns your favourite element

A fumbled gesture isn't recognised, so it casts again while time allows.
The core plays the moves with timers and feeds them to the duel exactly
like a wand's casts (OpenCaster._npc_*); this module has no clock and no I/O.
"""

import random
from collections import Counter
from dataclasses import dataclass
from typing import Optional

import numpy as np

from . import elements as E

NPC = "npc"                      # the NPC's player id in duels
NAME = "NPC"
COLOR = "#B8C2D6"                # silver
LEVELS = ("easy", "medium", "hard")


@dataclass(frozen=True)
class Skill:
    react: tuple                 # seconds before a gesture starts (min, max)
    draw: tuple                  # seconds a gesture takes (min, max)
    fumble: float                # chance a gesture isn't recognised
    right: float                 # Duelling Club: chance an answer beats the attack
    shield: float                # Duelling Club: chance it blocks instead
    read: float                  # clash: chance it counters your most-cast element


SKILLS = {
    "easy":   Skill((0.9, 1.8), (2.0, 3.0), 0.25, 0.65, 0.15, 0.0),
    "medium": Skill((0.5, 1.1), (1.4, 2.3), 0.12, 0.8, 0.15, 0.3),
    "hard":   Skill((0.25, 0.6), (0.9, 1.6), 0.05, 0.94, 0.12, 0.6),
}


@dataclass(frozen=True)
class Move:
    react: float                 # wait before the gesture starts
    draw: float                  # how long the gesture takes
    spell: str                   # the spell it means to cast
    fumble: bool = False         # the gesture won't be recognised


class Npc:
    def __init__(self, level: str = "medium", known=None, rng: Optional[random.Random] = None):
        """known: the spells it may cast in clash and club moves (those with
        a gesture shape); None for all."""
        self.level = level if level in LEVELS else "medium"
        self.skill = SKILLS[self.level]
        self.rng = rng or random.Random()
        ok = (lambda s: True) if known is None else (lambda s: s in known)
        self.spells = {e: [s for s in E.SPELLS[e] if ok(s)] or list(E.SPELLS[e]) for e in E.ELEMENTS}
        self.seen: Counter = Counter()        # opponents' clash elements

    # ── moves ─────────────────────────────────────────────────────────────────

    def race(self, spell: str) -> Move:
        """Quick-draw: cast the round's spell."""
        return self._move(spell)

    def clash(self) -> Move:
        """Clash: any battle spell; a sharp NPC counters your favourite element."""
        element = None
        if self.seen and self.rng.random() < self.skill.read:
            favourite = self.seen.most_common(1)[0][0]
            options = [e for e in E.ATTACKS if E.beats(e, favourite)]
            element = self.rng.choice(options) if options else None
        if element is None:
            element = E.PROTECTION if self.rng.random() < 0.1 else self.rng.choice(E.ATTACKS)
        return self._move(self._spell(element))

    def attack(self) -> Move:
        """Duelling Club: open the rally, or attack after a block."""
        return self._move(self._spell(self.rng.choice(E.ATTACKS)))

    def counter(self, incoming: str) -> Move:
        """Duelling Club: answer an attack – usually with a spell that beats
        it, sometimes a shield, sometimes a mistake."""
        against = E.element_of(incoming)
        if self.rng.random() < self.skill.shield:
            element = E.PROTECTION
        else:
            right = self.rng.random() < self.skill.right
            element = self.rng.choice([e for e in E.ATTACKS if E.beats(e, against) == right])
        return self._move(self._spell(element))

    def retry(self, move: Move) -> Move:
        """Cast again after a fumble, quicker this time."""
        return Move(self.rng.uniform(0.1, 0.3), self.rng.uniform(*self.skill.draw), move.spell,
                    self.rng.random() < self.skill.fumble)

    def observe(self, spell: Optional[str]):
        """An opponent's clash pick, for reading their habits."""
        element = E.element_of(spell)
        if element:
            self.seen[element] += 1

    def _spell(self, element: str) -> str:
        return self.rng.choice(self.spells[element])

    def _move(self, spell: str) -> Move:
        s = self.skill
        return Move(self.rng.uniform(*s.react), self.rng.uniform(*s.draw), spell,
                    self.rng.random() < s.fumble)


def gesture(outline: Optional[np.ndarray], rng: random.Random, size: float = 32.0) -> np.ndarray:
    """A hand-drawn-looking trail (degrees, y up) along a spell's outline, or
    a loop if there is none."""
    if outline is None or len(outline) < 2:
        t = np.linspace(0, 2 * np.pi, 60)
        outline = np.stack([np.cos(t) * 0.8, np.sin(t) * 0.8], 1)
    pts = np.asarray(outline, float)
    step = max(1, len(pts) // 90)
    pts = np.vstack([pts[::step], pts[-1:]]) * size
    gen = np.random.default_rng(rng.randrange(1 << 30))
    wobble = np.cumsum(gen.normal(0.0, 0.35, pts.shape), axis=0)
    wobble -= np.linspace(0, 1, len(pts))[:, None] * wobble[-1]        # ends where it should
    return pts + wobble
