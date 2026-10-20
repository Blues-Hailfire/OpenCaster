"""
opencaster.environment — The enchanted jack-o'-lantern (pure logic)
===================================================================
State for the GUI's Environment page: a carved pumpkin with a candle inside
that every spell acts on.  cast(spell) changes the state and returns an
Outcome (a line of text plus one-shot animation cues); the GUI draws the
state and plays the cues.  No Qt, no timers: timed states (moods,
Immobulus, weather) carry an expiry from `clock`, cleared by expire().

Spells interact the way they do in the clash duel (opencaster.elements):
water douses the candle, fire burns bindings and melts ice, blasts smash, a
shield blocks the next battle spell, bindings stop the pumpkin being moved.

Wingardium Leviosa floats it only while a wand holds the charm: let_go()
drops it (or, frozen by Immobulus, once that wears off).
"""

import random
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .casting.shapes import spell_key
from .elements import ATTACKS, LOCOMOTIVE, element_of

# What's inside: FIRE is the lit candle, EMPTY a dark pumpkin
EMPTY, WATER, ICE, FIRE, FLOWERS = "empty", "water", "ice", "fire", "flowers"
UPRIGHT, LEVITATING, FALLEN, GONE, VANISHED = "upright", "levitating", "fallen", "gone", "vanished"

MOOD_S = 6.0          # dizzy, giggling, cheerful, silly, alive, stunned
SLEEP_S = 12.0
HELD_S = 8.0          # Immobulus, Impedimenta
WEATHER_S = 7.0
COLOURS = ("#C0392B", "#2E86DE", "#27AE60", "#8E44AD", "#E67E22", "#16A085")
SHIELD_NAMES = {"protego": "Protego", "salvio": "Salvio Hexia", "patronus": "The Patronus"}
BINDING_NAMES = {"ropes": "the ropes", "cords": "the cords", "cuffs": "the glowing cuffs"}
# spells that act on the night around it, so they work with no pumpkin in view
ROOM = {"lumos", "nox", "meteolojinx", "apparevestigium", "accio", "finite"}


@dataclass(frozen=True)
class Outcome:
    spell: str
    text: str
    fx: tuple = ()            # animation cues, e.g. ("splash", "steam")
    blocked: bool = False     # a shield or a binding stopped it


@dataclass
class Pumpkin:
    contents: str = FIRE                # a fresh jack-o'-lantern has its candle lit
    fire_color: str = "orange"          # orange | green (Verdimillious)
    pose: str = UPRIGHT
    broken: bool = False
    stone: bool = False
    frost: bool = False
    soot: float = 0.0                   # 0..1
    tint: Optional[str] = None          # Colovaria '#RRGGBB'; None = pumpkin orange
    rune: bool = False                  # Flagrate's fiery mark
    vines: bool = False
    bound: str = ""                     # "" | ropes | cords | cuffs
    stuck: bool = False                 # Colloshoo
    sealed: bool = False                # Colloportus: the lid
    shield: str = ""                    # "" | protego | salvio | patronus
    light: str = "normal"               # normal | lit | dark
    music: str = ""                     # "" | singing | humming
    mood: str = ""                      # "" | asleep | dizzy | giggling | cheerful | silly | alive | stunned
    mood_until: float = 0.0
    held: str = ""                      # "" | frozen | slowed
    held_until: float = 0.0
    weather: str = ""                   # "" | rain | snow
    weather_until: float = 0.0
    history: list = field(default_factory=list)     # recent spells, newest last

    def __post_init__(self):
        self.clock: Callable[[], float] = time.monotonic
        self.house_color: Optional[str] = None
        self.rng = random.Random()
        self.drop_when_free = False         # let go while frozen in mid-air

    # ── public ────────────────────────────────────────────────────────────────

    @property
    def present(self) -> bool:
        return self.pose not in (GONE, VANISHED)

    @property
    def movable(self) -> str:
        """'' if the pumpkin can be moved, else what holds it."""
        if self.bound:
            return BINDING_NAMES[self.bound]
        if self.stuck:
            return "the Stickfast Jinx"
        if self.held == "frozen":
            return "Immobulus"
        return ""

    def reset(self):
        clock, house, rng = self.clock, self.house_color, self.rng
        self.__init__()
        self.clock, self.house_color, self.rng = clock, house, rng

    def expire(self) -> bool:
        """Clear timed states that have run out; True if anything changed."""
        now, changed = self.clock(), False
        if self.mood and now >= self.mood_until:
            self.mood, changed = "", True
        if self.held and now >= self.held_until:
            self.held, changed = "", True
            if self.drop_when_free and self.pose == LEVITATING:
                self.pose = UPRIGHT                 # nothing holds it up any more
            self.drop_when_free = False
        if self.weather and now >= self.weather_until:
            self.weather, changed = "", True
        return changed

    def next_expiry(self) -> Optional[float]:
        times = [t for on, t in ((self.mood, self.mood_until), (self.held, self.held_until),
                                 (self.weather, self.weather_until)) if on]
        return min(times) if times else None

    def let_go(self) -> Optional[Outcome]:
        """The wand holding Wingardium Leviosa lets go: the pumpkin drops –
        unless Immobulus has it frozen in mid-air, then it drops when that
        wears off.  None if nothing happens now."""
        if self.pose != LEVITATING:
            return None
        if self.held == "frozen":
            self.drop_when_free = True
            return None
        self.pose = UPRIGHT
        return Outcome("Wingardium Leviosa", "the charm ends and the pumpkin drops to the ground",
                       ("drop",))

    def cast(self, spell: str) -> Outcome:
        self.expire()
        key = spell_key(spell)
        self.history = (self.history + [spell])[-6:]
        woke = self.mood == "asleep" and key != "thesleepingcharm"
        if woke:
            self.mood = ""
        out = self._cast(spell, key)
        if woke:
            out = Outcome(out.spell, out.text + " – and wakes it up", out.fx + ("wake",), out.blocked)
        return out

    # ── rules ─────────────────────────────────────────────────────────────────

    def _cast(self, spell: str, key: str) -> Outcome:
        element = element_of(spell)
        if not self.present and key not in ROOM:
            how = "vanished.  Accio or Finite" if self.pose == VANISHED else "flown off.  Accio"
            return Outcome(spell, f"{spell} finds nothing – the jack-o'-lantern has {how} brings it back",
                           ("fizzle",), blocked=True)
        if self.shield and element in ATTACKS and self.present:
            shield, self.shield = self.shield, ""
            return Outcome(spell, f"{SHIELD_NAMES[shield]} blocks {spell}", ("block",), blocked=True)
        if self.broken and key not in {"reparo", "evanesco", "finite", "scourgify"} | ROOM \
                and element != "explosive":
            return Outcome(spell, f"{spell} fizzles over the smashed pumpkin – Reparo would mend it",
                           ("fizzle",), blocked=True)
        if element == LOCOMOTIVE and key not in ("araniaexumai", "ventus") and self.present \
                and self.movable:
            return Outcome(spell, f"{spell} strains, but {self.movable} hold it fast",
                           ("strain",), blocked=True)
        handler = getattr(self, f"_{key}", None)
        if handler:
            text, fx = handler(spell)
        else:
            text, fx = f"{spell} sparkles over the pumpkin", ("sparkle",)
        return Outcome(spell, text, tuple(fx))

    def _timed(self, attr: str, value: str, seconds: float):
        setattr(self, attr, value)
        setattr(self, f"{attr}_until", self.clock() + seconds)

    def _spill(self) -> str:
        """Tipped over or flung: the contents go."""
        lost, self.contents = self.contents, EMPTY
        return {WATER: " and the water gushes out", FIRE: " and the candle gutters out",
                ICE: " and the ice slides out", FLOWERS: " and the flowers tumble out"}.get(lost, "")

    def _knock_over(self, spell: str, verb: str, fx: str) -> tuple:
        if self.pose == FALLEN:
            return f"{spell} rolls the fallen pumpkin", (fx,)
        self.pose = FALLEN
        if self.mood == "alive":
            self.mood = ""
        return f"{spell} {verb}{self._spill()}", (fx, "spill")

    # fire ----------------------------------------------------------------------------

    def _incendio(self, spell):
        if self.bound in ("ropes", "cords"):
            what = BINDING_NAMES[self.bound]
            self.bound, self.soot = "", min(1.0, self.soot + 0.3)
            return f"{spell} burns away {what}", ("flare", "smoke")
        if self.sealed:
            self.soot = min(1.0, self.soot + 0.2)
            return f"{spell}'s flames lick the sealed lid", ("flare",)
        if self.pose == FALLEN:
            self.soot = min(1.0, self.soot + 0.2)
            return f"{spell} scorches the fallen pumpkin", ("flare", "smoke")
        self.frost = False
        if self.contents == WATER:
            self.contents = EMPTY
            return f"{spell} boils the water away", ("flare", "steam")
        if self.contents == ICE:
            self.contents = WATER
            return f"{spell} melts the ice", ("flare", "steam")
        burnt = "flowers" if self.contents == FLOWERS else "vines" if self.vines else ""
        lit = self.contents == FIRE
        self.vines = False
        self.contents, self.fire_color = FIRE, "orange"
        self.soot = min(1.0, self.soot + 0.15)
        if burnt:
            return f"{spell} sets the {burnt} ablaze", ("flare",)
        return (f"{spell} makes the candle blaze" if lit else f"{spell} lights the candle"), ("flare",)

    def _flagrate(self, spell):
        self.rune = True
        return f"{spell} draws a fiery sigil on the pumpkin", ("rune",)

    def _verdimillious(self, spell):
        if self.contents == FIRE:
            self.fire_color = "green"
            return f"{spell} turns the candle flame green", ("sparks",)
        return f"{spell} sends green sparks fountaining from the pumpkin", ("sparks",)

    # explosive -----------------------------------------------------------------------

    def _blast(self, spell, verb="smashes the pumpkin to pieces", fiery=False):
        if self.broken:
            return f"{spell} scatters the pieces", ("blast",)
        self.broken = True
        self.bound, self.stuck, self.sealed, self.vines, self.rune = "", False, False, False, False
        self.contents = EMPTY
        self.soot = min(1.0, self.soot + (0.5 if fiery else 0.3))
        if self.pose == LEVITATING:
            self.pose = UPRIGHT
        if self.mood in ("alive", "silly", "cheerful", "giggling"):
            self.mood = ""
        return f"{spell} {verb}", ("blast", "shatter") + (("flare",) if fiery else ())

    def _bombarda(self, spell):
        return self._blast(spell)

    def _confringo(self, spell):
        return self._blast(spell, "bursts the pumpkin in a ball of flame", fiery=True)

    def _expulso(self, spell):
        return self._blast(spell, "blows the pumpkin apart")

    def _reducto(self, spell):
        return self._blast(spell, "blasts the pumpkin to pulp")

    def _finestra(self, spell):
        return self._blast(spell, "cracks the pumpkin into chunks")

    # water ---------------------------------------------------------------------------

    def _aguamenti(self, spell):
        self.soot = max(0.0, self.soot - 0.25)
        if self.sealed:
            return f"{spell}'s water runs off the sealed lid", ("splash",)
        if self.pose == FALLEN:
            return f"{spell} soaks the fallen pumpkin", ("splash",)
        if self.contents == FIRE:
            self.contents = WATER
            return f"{spell} douses the candle and fills the pumpkin", ("splash", "steam")
        if self.contents == FLOWERS:
            return f"{spell} waters the flowers – they bloom", ("splash", "bloom")
        if self.contents == ICE:
            return f"{spell} pours over the ice", ("splash",)
        self.contents = WATER
        return f"{spell} fills the pumpkin with water", ("splash",)

    def _glacius(self, spell):
        self.frost = True
        if self.contents == WATER:
            self.contents = ICE
            return f"{spell} freezes the water solid", ("frost",)
        if self.contents == FIRE:
            self.contents = EMPTY
            return f"{spell} snuffs out the candle in a crust of frost", ("frost", "steam")
        if self.contents == FLOWERS:
            return f"{spell} frosts the flowers", ("frost",)
        return f"{spell} frosts the pumpkin with icicles", ("frost",)

    def _meteolojinx(self, spell):
        snow = self.frost or self.contents == ICE
        self._timed("weather", "snow" if snow else "rain", WEATHER_S)
        if not snow and self.present and self.pose != FALLEN and not (self.sealed or self.broken):
            if self.contents == FIRE:
                self.contents = WATER
                return f"{spell} brews a rain cloud that douses the candle", ("cloud", "steam")
            if self.contents == EMPTY:
                self.contents = WATER
                return f"{spell} brews a rain cloud that fills the pumpkin", ("cloud",)
            if self.contents == FLOWERS:
                return f"{spell} brews a rain cloud that waters the flowers", ("cloud", "bloom")
        return f"{spell} brews a little {'snow' if snow else 'rain'} cloud", ("cloud",)

    # binding -------------------------------------------------------------------------

    def _bind(self, spell, how, text):
        self.bound = how
        if self.pose == LEVITATING:
            self.pose = UPRIGHT
        if self.mood in ("alive", "silly", "dizzy", "giggling"):
            self.mood = ""
        return f"{spell} {text}", ("bind",)

    def _incarcerous(self, spell):
        return self._bind(spell, "ropes", "wraps the pumpkin in ropes")

    def _brachiabindo(self, spell):
        return self._bind(spell, "cords", "binds the pumpkin with cords")

    def _fulgari(self, spell):
        return self._bind(spell, "cuffs", "snaps glowing cuffs around the pumpkin")

    def _petrificustotalus(self, spell):
        self.stone = True
        if self.pose == LEVITATING:
            self.pose = UPRIGHT
            text = f"{spell} turns the pumpkin to stone – it drops with a thud"
        else:
            text = f"{spell} turns the pumpkin to stone"
        if self.mood not in ("", "asleep"):
            self.mood = ""
        return text, ("petrify",)

    def _immobulus(self, spell):
        self._timed("held", "frozen", HELD_S)
        return f"{spell} freezes the pumpkin in place", ("freeze",)

    def _impedimenta(self, spell):
        self._timed("held", "slowed", HELD_S)
        return f"{spell} slows everything around the pumpkin to a crawl", ("slow",)

    def _colloshoo(self, spell):
        self.stuck = True
        if self.pose == LEVITATING:
            self.pose = UPRIGHT
            return f"{spell} pulls the pumpkin down and glues it to the ground", ("goo",)
        return f"{spell} glues the pumpkin to the ground", ("goo",)

    def _stupefy(self, spell):
        if self.movable:
            return f"{spell} hits the pumpkin – it shudders but {self.movable} hold it", ("zap",)
        text, fx = self._knock_over(spell, "stuns the pumpkin – it keels over", "zap")
        self._timed("mood", "stunned", MOOD_S)
        return text, fx

    # locomotive ----------------------------------------------------------------------

    def _wingardiumleviosa(self, spell):
        if self.pose == LEVITATING:
            return f"{spell} lifts the pumpkin a little higher", ("lift",)
        righted = self.pose == FALLEN
        self.pose = LEVITATING
        return (f"{spell} rights the pumpkin and floats it in the air" if righted
                else f"{spell} floats the pumpkin into the air"), ("lift",)

    def _accio(self, spell):
        if not self.present:
            self.pose, self.broken = UPRIGHT, False
            return f"{spell} summons the jack-o'-lantern back", ("summon",)
        if self.broken:
            return f"{spell} gathers up the pieces", ("summon",)
        was = self.pose
        self.pose = UPRIGHT
        return (f"{spell} pulls the pumpkin upright" if was == FALLEN
                else f"{spell} pulls the pumpkin towards you"), ("summon",)

    def _ascendio(self, spell):
        self.pose = UPRIGHT
        return f"{spell} launches the pumpkin high into the air", ("launch",)

    def _flipendo(self, spell):
        return self._knock_over(spell, "knocks the pumpkin over", "knock")

    def _theforcespell(self, spell):
        return self._knock_over(spell, "slams into the pumpkin and topples it", "shock")

    def _expelliarmus(self, spell):
        self.pose = GONE
        self.mood, self.held, self.shield = "", "", ""
        self._spill()
        return f"{spell} sends the pumpkin spinning away", ("fling",)

    def _araniaexumai(self, spell):
        return f"{spell} blasts the spiders away from the pumpkin", ("spiders",)

    def _piertotumlocomotor(self, spell):
        if self.pose == FALLEN:
            self.pose = UPRIGHT
        self._timed("mood", "alive", MOOD_S)
        return f"{spell} brings the {'stone ' if self.stone else ''}jack-o'-lantern to life – it hops about", \
            ("hop",)

    def _ventus(self, spell):
        if self.contents == FIRE:
            self.contents = EMPTY
            return f"{spell} blows the candle out", ("gust", "smoke")
        if self.contents == FLOWERS or self.vines:
            return f"{spell} sends petals whirling", ("gust", "petals")
        return f"{spell} whirls autumn leaves around the pumpkin", ("gust",)

    # protection ----------------------------------------------------------------------

    def _protego(self, spell):
        self.shield = "protego"
        return f"{spell} raises a shield around the pumpkin", ("shield",)

    def _salviohexia(self, spell):
        self.shield = "salvio"
        return f"{spell} rings the pumpkin with protective runes", ("shield",)

    def _expectopatronum(self, spell):
        self.shield = "patronus"
        return f"{spell} – a silvery guardian circles the pumpkin", ("patronus",)

    def _finite(self, spell):
        if self.pose == GONE:
            return f"{spell} – the pumpkin has flown off; Accio brings it back", ("fizzle",)
        ended = []
        if self.shield:
            ended.append("shield")
        if self.bound or self.stuck or self.held or self.stone:
            ended.append("bindings")
        if self.mood or self.music or self.weather or self.tint or self.rune or self.sealed:
            ended.append("charms")
        if self.pose == LEVITATING:
            ended.append("levitation")
        self.shield, self.bound, self.stuck, self.held, self.stone = "", "", False, "", False
        self.drop_when_free = False
        self.mood, self.music, self.weather, self.tint, self.rune, self.sealed = "", "", "", None, False, False
        if self.pose == LEVITATING:
            self.pose = UPRIGHT
        if self.pose == VANISHED:
            self.pose = UPRIGHT
            return f"{spell} undoes the vanishing – the jack-o'-lantern reappears", ("finite", "summon")
        if not ended:
            return f"{spell} – there's nothing to undo", ("finite",)
        return f"{spell} ends every spell on the pumpkin", ("finite",)

    # utility -------------------------------------------------------------------------

    def _lumos(self, spell):
        self.light = "lit"
        return f"{spell} lights up the pumpkin patch", ("light",)

    def _nox(self, spell):
        if self.light == "lit":
            self.light = "normal"
            return f"{spell} puts out the light", ("dark",)
        self.light = "dark"
        if self.contents == FIRE and self.present and not self.broken:
            return f"{spell} plunges the night into darkness – only the jack-o'-lantern glows", ("dark",)
        return f"{spell} plunges the night into darkness", ("dark",)

    def _alohomora(self, spell):
        if self.sealed:
            self.sealed = False
            return f"{spell} unlocks the lid", ("unseal",)
        return f"{spell} – nothing here is locked", ("sparkle",)

    def _aberto(self, spell):
        if self.sealed:
            self.sealed = False
            return f"{spell} opens the sealed lid", ("unseal",)
        return f"{spell} – the lid isn't sealed", ("sparkle",)

    def _colloportus(self, spell):
        self.sealed = True
        if self.contents == FIRE:
            self.contents = EMPTY
            return f"{spell} seals the lid and smothers the candle", ("seal", "smoke")
        return f"{spell} seals the lid shut", ("seal",)

    def _apparevestigium(self, spell):
        return f"{spell} reveals traces of the magic cast here", ("traces",)

    def _cantis(self, spell):
        self.music = "singing"
        return f"{spell} – the jack-o'-lantern bursts into song", ("notes",)

    def _quietus(self, spell):
        if self.music:
            self.music = "humming"
            return f"{spell} quietens the pumpkin to a hum", ("hush",)
        return f"{spell} – the pumpkin was quiet already", ("hush",)

    def _silencio(self, spell):
        if self.music:
            self.music = ""
            return f"{spell} silences the pumpkin", ("hush",)
        return f"{spell} – the pumpkin was silent already", ("hush",)

    def _colovaria(self, spell):
        house = self.house_color.upper() if self.house_color else None
        options = ([house] if house else []) + [c for c in COLOURS if c != house]
        current = options.index(self.tint) if self.tint in options else -1
        self.tint = options[(current + 1) % len(options)]
        return f"{spell} changes the pumpkin's colour", ("recolour",)

    def _confundo(self, spell):
        self._timed("mood", "dizzy", MOOD_S)
        return f"{spell} leaves the pumpkin dizzy", ("dizzy",)

    def _rictusempra(self, spell):
        self._timed("mood", "giggling", MOOD_S)
        return f"{spell} – the pumpkin shakes with giggles", ("giggle",)

    def _riddikulus(self, spell):
        self._timed("mood", "silly", MOOD_S)
        return f"{spell} turns the pumpkin wobbly as jelly, in a party hat", ("silly",)

    def _thecheeringcharm(self, spell):
        self._timed("mood", "cheerful", MOOD_S)
        return f"{spell} fills the pumpkin with good cheer", ("cheer",)

    def _thesleepingcharm(self, spell):
        self._timed("mood", "asleep", SLEEP_S)
        return f"{spell} sends the pumpkin to sleep", ("sleep",)

    def _evanesco(self, spell):
        if self.contents != EMPTY:
            what = {WATER: "water", ICE: "ice", FIRE: "candle flame", FLOWERS: "flowers"}[self.contents]
            self.contents = EMPTY
            return f"{spell} vanishes the {what}", ("poof",)
        self.pose, self.broken = VANISHED, False
        self.mood, self.held, self.shield = "", "", ""
        return f"{spell} vanishes the jack-o'-lantern itself", ("poof",)

    def _herbivicus(self, spell):
        self.vines = True
        if self.contents == FLOWERS:
            return f"{spell} – vines curl up the pumpkin and the flowers bloom", ("grow", "bloom")
        return f"{spell} – pumpkin vines curl up around it and burst into bloom", ("grow",)

    def _orchideous(self, spell):
        if self.sealed:
            return f"{spell}'s bouquet bounces off the sealed lid", ("petals",)
        if self.pose == FALLEN:
            return f"{spell} scatters flowers around the fallen pumpkin", ("petals",)
        if self.contents == FIRE:
            return f"{spell}'s bouquet goes up in the candle flame", ("flare",)
        self.contents = FLOWERS
        return f"{spell} – a bouquet bursts out of the pumpkin", ("bloom",)

    def _reparo(self, spell):
        if self.broken:
            self.broken = False
            return f"{spell} mends the pumpkin", ("mend",)
        return f"{spell} smooths out every bruise", ("sparkle",)

    def _scourgify(self, spell):
        if self.soot or self.rune or self.stuck:
            self.soot, self.rune, self.stuck = 0.0, False, False
            return f"{spell} scrubs the pumpkin clean", ("bubbles",)
        return f"{spell} – it's already spotless", ("bubbles",)
