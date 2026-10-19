"""
opencaster.elements — Spell elements for the clash duel (pure data)
====================================================================
Battle spells belong to one of five elements, which beat each other in a
balanced cycle (each beats two and loses to two), plus protection, which
blocks anything.  Utility spells (Lumos, Alohomora, Silencio …) have no
element and can't be used in a clash.

    Fire        beats Binding, Locomotive      loses to Water, Explosive
    Explosive   beats Fire, Water              loses to Binding, Locomotive
    Binding     beats Locomotive, Explosive    loses to Fire, Water
    Locomotive  beats Water, Explosive         loses to Fire, Binding
    Water/Ice   beats Fire, Binding            loses to Locomotive, Explosive
    Protection  draws with everything

Spells are grouped by what the original spellbook says they do.
"""

from typing import Optional

from .casting.shapes import spell_key

FIRE, EXPLOSIVE, BINDING, LOCOMOTIVE, WATER, PROTECTION = (
    "fire", "explosive", "binding", "locomotive", "water", "protection")
ATTACKS = (FIRE, EXPLOSIVE, BINDING, LOCOMOTIVE, WATER)
ELEMENTS = ATTACKS + (PROTECTION,)

NAMES = {FIRE: "Fire", EXPLOSIVE: "Explosive", BINDING: "Binding", LOCOMOTIVE: "Locomotive",
         WATER: "Water/Ice", PROTECTION: "Protection"}

# winner → {loser: verb}; "Aguamenti douses Incendio"
BEATS = {
    FIRE:       {BINDING: "burns through", LOCOMOTIVE: "scorches"},
    EXPLOSIVE:  {FIRE: "blasts out", WATER: "blasts apart"},
    BINDING:    {LOCOMOTIVE: "pins down", EXPLOSIVE: "smothers"},
    LOCOMOTIVE: {WATER: "sweeps aside", EXPLOSIVE: "deflects"},
    WATER:      {FIRE: "douses", BINDING: "washes away"},
}

SPELLS = {
    FIRE:       ("Incendio", "Flagrate", "Verdimillious"),
    EXPLOSIVE:  ("Bombarda", "Confringo", "Expulso", "Reducto", "Finestra"),
    BINDING:    ("Incarcerous", "Brachiabindo", "Petrificus Totalus", "Fulgari", "Immobulus",
                 "Impedimenta", "Colloshoo", "Stupefy"),
    LOCOMOTIVE: ("Wingardium Leviosa", "Accio", "Ascendio", "Flipendo", "Expelliarmus",
                 "Arania Exumai", "Piertotum Locomotor", "Ventus", "The Force Spell"),
    WATER:      ("Aguamenti", "Glacius", "Meteolojinx"),
    PROTECTION: ("Protego", "Salvio Hexia", "Expecto Patronum", "Finite"),
}

_BY_KEY = {spell_key(s): e for e, names in SPELLS.items() for s in names}


def element_of(spell: Optional[str]) -> Optional[str]:
    """The spell's element, or None for a utility spell."""
    return _BY_KEY.get(spell_key(spell)) if spell else None


def battle_spells() -> list:
    return [s for names in SPELLS.values() for s in names]


def beats(a: str, b: str) -> bool:
    return b in BEATS.get(a, {})


def clash(a: Optional[str], b: Optional[str]) -> tuple:
    """Resolve two picks (spell names, None = didn't cast).

    Returns (winner, line): winner is 0 or 1 for the side that wins, None for
    a draw or a void round (neither cast); line explains it."""
    ea, eb = element_of(a), element_of(b)
    if a is None and b is None:
        return None, "Neither wizard cast a spell"
    if a is None or b is None:
        side, spell, element = (1, b, eb) if a is None else (0, a, ea)
        if element == PROTECTION:
            return None, f"{spell} stands ready – but no spell came"
        return side, f"{spell} strikes unanswered"
    if PROTECTION in (ea, eb):
        if ea == eb:
            return None, f"{a} and {b} – two shields, no harm done"
        shield, attack = (a, b) if ea == PROTECTION else (b, a)
        return None, f"{shield} blocks {attack}"
    if ea == eb:
        return None, f"{a} meets {b} – evenly matched"
    if beats(ea, eb):
        return 0, f"{a} {BEATS[ea][eb]} {b}"
    return 1, f"{b} {BEATS[eb][ea]} {a}"
