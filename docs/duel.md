# Wizard's duel

[← OpenCaster](../README.md) · [Documentation](README.md)

Connect the wands, open **Duel**, pick a mode and the wizards, and **Begin
the duel**.  Quick-draw and Clash are for two wizards, best of five (first
to three round wins); the Duelling Club is one rally for two to five.  Each
wand pulses in its colour through the 3-2-1 countdown and flashes on
**Cast!**; a gesture started during the countdown never counts.

**Seconds to cast** sets how long each wizard has to cast: in quick-draw
before the round is void (30 s by default), in a clash after **Cast!** (3 s),
and in the Duelling Club for every attack and answer (5 s).  Each mode
remembers its own setting; headless, use `--cast-seconds`.

## The NPC opponent

No one to duel?  Any seat can be the **NPC**, a computer opponent; with a
single wand connected, Wizard 2 is the NPC already.  **NPC skill** sets how
good it is:

| Skill | Reacts in | Draws a gesture in | Fumbles | Duelling Club answers |
|-------|-----------|--------------------|---------|-----------------------|
| Easy | 0.9–1.8 s | 2–3 s | 1 in 4 | right about 2 times in 3 |
| Medium | 0.5–1.1 s | 1.4–2.3 s | 1 in 8 | right 4 times in 5 |
| Hard | 0.25–0.6 s | 0.9–1.6 s | 1 in 20 | right 19 times in 20 |

Its panel draws each spell's shape as it casts.  A fumbled gesture isn't
recognised and it casts again while there's time.  In a clash a Medium or
Hard NPC learns your favourite element and counters it; in the Duelling Club
it sometimes blocks with a shield, and sometimes answers wrong and slips
up.  Its spells sound but never count towards your mastery.  One NPC per
duel; it needs at least one wand to play against.

## Quick-draw

The original app's duelling mode: two wizards, one spell.

- Each round both wizards are shown the same spell; the first to cast it
  wins the round.  The winner's wand plays the spell, the other fades red.
  A different spell doesn't count.
- A round nobody wins within **Seconds to cast** (30 s by default) is void;
  **Skip spell** voids it by hand;
  after 9 rounds the higher score wins.
- **Spell pools:** *Spells you've cast* (the default: spells you've been
  recognised casting, so rounds don't stall on shapes that won't
  recognise), *All spells*, or one difficulty.

## Clash

Spells as rock-paper-scissors.  After **Cast!** each wizard has **3
seconds** (by default; **Seconds to cast**) to cast any battle spell (a
gesture started in time may finish up to 2 s late).  Your first recognised battle spell is your pick: your wand
buzzes and glows dimly in your own colour, and your panel only says *Spell
chosen*.  Picks stay hidden until both are in or time is up; then both cards
are revealed, both wands play their spells, and the elements decide:

| Element | Beats | Spells |
|---------|-------|--------|
| Fire | Binding, Locomotive | Incendio, Flagrate, Verdimillious |
| Explosive | Fire, Water/Ice | Bombarda, Confringo, Expulso, Reducto, Finestra |
| Binding | Locomotive, Explosive | Incarcerous, Brachiabindo, Petrificus Totalus, Fulgari, Immobulus, Impedimenta, Colloshoo, Stupefy |
| Locomotive | Water/Ice, Explosive | Wingardium Leviosa, Accio, Ascendio, Flipendo, Expelliarmus, Arania Exumai, Piertotum Locomotor, Ventus, The Force Spell |
| Water/Ice | Fire, Binding | Aguamenti, Glacius, Meteolojinx |
| Protection | – (blocks everything) | Protego, Salvio Hexia, Expecto Patronum, Finite |

- Each element beats two and loses to two.  The same element twice is a
  draw, and a shield draws with anything, even no spell at all.
- An attack beats no spell; if neither wizard casts, the round is void.
  Draws score nothing, so a clash runs up to 15 rounds (then the higher
  score wins).
- Utility spells (Lumos, Nox, Alohomora, Silencio, Reparo …) have no
  element and play no part: while the window is open, gestures are matched
  against the 32 battle spells only.  A cast that isn't recognised doesn't
  use up your pick, so cast again if there's time.
- The table lives in `opencaster/elements.py`.

## Duelling Club

Two to five wizards, the same elements, turn by turn.  Wizard 1 opens with
an attack.  The next wizard answers with a spell that beats it – which the
wizard after them must then answer – or blocks it with a shield and then
attacks.  Every attack and answer has **5 seconds** (by default; **Seconds
to cast**).  **Who
answers** sets who's next: *In order* goes round the seats (Wizard 1, 2,
3 …, back to 1); *Random* picks anyone but the caster.

There are no rounds and no limit: the rally goes on until someone answers
too late or with a spell that doesn't beat the attack (a shield doesn't
count as an attack).  The wizard whose spell went unanswered wins.  If the
very first attack fails, the other wizard wins a two-wizard duel, and a
bigger one ends with no winner.

- Wizards 3–5 appear in Duelling Club mode; set any of them to *no one*.
  Seats 1–3 sit down the left of the arena and 4–5 down the right.
- Whose turn it is glows gold; the centre shows the spell to beat, which
  elements beat it, a timer running round the card, and the rally so far.
- A gesture that isn't recognised can be cast again while time remains,
  and one started in time may finish up to 2 s late.  Gestures started
  before your turn don't count.
- Every good move plays its spell on the caster's wand and counts towards
  mastery; only the wand whose turn it is flashes, and only the wizard who
  slips up fades red.  The spell left unanswered plays its video.

The duel opens with the intro video, each round's winning spell plays its
video, and the duel's winner gets confetti, a rainbow on their wand and the
celebration video.  **Rematch** starts again in the same mode.  Labelling
and the practice spell are suspended during a duel and restored afterwards.
Headless: `python -m opencaster --duel` (quick-draw), `--clash`, or `--club [N]`
for a Duelling Club once N wands (2–5) are ready (`--random-order` for random
turns); add `--npc [easy|medium|hard]` to give the last seat to the NPC
(`--npc` on its own is a quick-draw against it with one wand).
