"""
opencaster.spellbook — Original Magic Caster spell data and media
==================================================================
Reads the recovered spellbook (media/spellbook.json) and media pack, both
gitignored and supplied by the user:

    media/spellbook.json                  names, pronunciation, lore, colours,
                                          wand/box light + haptic macros
    media/**/sfx_<spell>_cast_NN.mp3      casting sounds (one picked at random)
    media/**/<spell>_video_payoff.mp4     spell payoff videos

Spells are matched by spell_key() (lower-case letters/digits), so the
template spells/Wingardium Leviosa.svg picks up the "Wingardium Leviosa"
entry, wingardium_leviosa_video_payoff.mp4 and sfx_wingardium_leviosa_*.mp3.
Each sound goes to the longest spell name inside its file name, so Lumos
doesn't collect Lumos Maxima's sounds.
"""

import colorsys
import html
import json
import logging
import os
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

DIFFICULTY = ("Beginner", "Intermediate", "Expert")
MASTERY_CASTS = 10      # "Successfully cast 10 times to master this spell"


def spell_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def cast_colors(macros, house_color: str = "D4AF37", limit: int = 3) -> tuple:
    """The colours a spell lights the wand with, most prominent first.

    Each changeled colour is weighted by duration x brightness; near-black
    fade phases are dropped and colours of nearly the same hue are merged
    (FF000D and FF002B are one red).  Returns '#RRGGBB' strings.
    """
    weights: dict = {}
    for macro in macros:
        for c in macro:
            if c.get("command") != "changeled":
                continue
            hexc = str(c.get("color", "")).strip().lstrip("#")
            if hexc.startswith("$"):
                hexc = house_color.lstrip("#")
            if not re.fullmatch(r"[0-9a-fA-F]{6}", hexc):
                continue
            r, g, b = (int(hexc[i:i + 2], 16) / 255 for i in (0, 2, 4))
            v = max(r, g, b)
            if v < 0.3:                      # near-black: a fade-out phase
                continue
            w = max(float(c.get("duration") or 0), 0.05) * v * v
            weights[hexc.upper()] = weights.get(hexc.upper(), 0.0) + w
    clusters: list = []                      # [colour, hue, saturation, weight]
    for hexc, w in sorted(weights.items(), key=lambda kv: -kv[1]):
        r, g, b = (int(hexc[i:i + 2], 16) / 255 for i in (0, 2, 4))
        h, s, _ = colorsys.rgb_to_hsv(r, g, b)
        for cl in clusters:
            near_hue = min(abs(h - cl[1]), 1 - abs(h - cl[1])) < 0.05
            if (s < 0.3 and cl[2] < 0.3) or (s >= 0.3 and cl[2] >= 0.3 and near_hue):
                cl[3] += w
                break
        else:
            clusters.append([hexc, h, s, w])
    clusters.sort(key=lambda cl: -cl[3])
    return tuple(f"#{cl[0]}" for cl in clusters[:limit])


@dataclass(frozen=True)
class SpellInfo:
    name: str
    key: str
    incantation: str = ""          # e.g. "The Spider-banishing Charm"
    pronunciation: str = ""
    subtitle: str = ""             # "The Spider-Banishing Charm"
    description: str = ""
    notable_uses: str = ""
    spell_type: str = ""           # Charm, Jinx, Hex, Curse, Spell
    difficulty: int = 0
    color: str = "#1b1430"         # spellbook background colour (dark)
    colors: tuple = ()             # wand light colours when cast, most prominent first
    wand_macros: tuple = ()
    box_macros: tuple = ()
    sounds: tuple = field(default=(), compare=False)
    video: Optional[Path] = None

    @property
    def difficulty_name(self) -> str:
        return DIFFICULTY[min(max(self.difficulty, 0), len(DIFFICULTY) - 1)]

    def wand_macro(self) -> Optional[list]:
        return random.choice(self.wand_macros) if self.wand_macros else None

    def box_macro(self) -> Optional[list]:
        return random.choice(self.box_macros) if self.box_macros else None

    def sound(self) -> Optional[Path]:
        return random.choice(self.sounds) if self.sounds else None


# Patronus video file names run words together; these read better split.
_PATRONUS_NAMES = {
    "blackmamba": "Black Mamba", "blackswan": "Black Swan", "brownbear": "Brown Bear",
    "brownhare": "Brown Hare", "calicocat": "Calico Cat", "capuchinmonkey": "Capuchin Monkey",
    "chowdog": "Chow Dog", "fieldmouse": "Field Mouse",
    "firedwellingsalamander": "Fire-Dwelling Salamander", "foxterrier": "Fox Terrier",
    "greysquirrel": "Grey Squirrel", "irishwolfhound": "Irish Wolfhound",
    "kingcobra": "King Cobra", "littleowl": "Little Owl", "mongreldog": "Mongrel Dog",
    "polarbear": "Polar Bear", "snowyowl": "Snowy Owl", "stbernarddog": "St Bernard",
    "westhighlandterrier": "West Highland Terrier", "wildboar": "Wild Boar",
    "wildcat": "Wildcat", "wingedhorse": "Winged Horse",
}


def patronus_name(stem: str) -> str:
    """'sfx_patronus_snowyowl' → 'Snowy Owl'."""
    raw = stem.lower().replace("sfx_patronus_", "")
    return _PATRONUS_NAMES.get(raw, raw.replace("_", " ").title())


@dataclass
class Media:
    """Media not tied to one spell (all optional: missing files stay None/empty)."""
    wand_awake: Optional[Path] = None       # sfx_wandawake_long.mp3: wand connected
    cast_loop: Optional[Path] = None        # sfx_wandmovement_generalloop.mp3: while casting
    mastery_video: Optional[Path] = None    # payoff_maxlevel.mp4: spell mastered / duel won
    duel_intro: Optional[Path] = None       # tutorial_end_transition.mp4
    mishaps: tuple = ()                     # spellcasting_mishap_N.mp4: failed casts
    houses: dict = field(default_factory=dict)      # house → ui_choose_house_*.mp3
    patronuses: dict = field(default_factory=dict)  # display name → sfx_patronus_*.mp4

    def mishap(self) -> Optional[Path]:
        return random.choice(self.mishaps) if self.mishaps else None

    def patronus(self, choice: str = "random") -> Optional[Path]:
        if choice in self.patronuses:
            return self.patronuses[choice]
        return random.choice(list(self.patronuses.values())) if self.patronuses else None


class Spellbook:
    def __init__(self, media_dir, house_color: str = "#D4AF37"):
        self.media_dir = Path(media_dir)
        self.house_color = house_color
        self._spells: dict = {}
        self._mp3s: list = []
        self._videos: dict = {}
        self.media = Media()
        self.reload()

    def _index_media(self, files: list):
        m = Media()
        for path in files:
            low = path.name.lower()
            if low == "sfx_wandawake_long.mp3":
                m.wand_awake = path
            elif low == "sfx_wandmovement_generalloop.mp3":
                m.cast_loop = path
            elif low == "payoff_maxlevel.mp4":
                m.mastery_video = path
            elif low == "tutorial_end_transition.mp4":
                m.duel_intro = path
            elif low.startswith("spellcasting_mishap_") and low.endswith(".mp4"):
                m.mishaps += (path,)
            elif low.startswith("ui_choose_house_") and low.endswith(".mp3"):
                house = low[len("ui_choose_house_"):-4]
                house = {"gryffidor": "gryffindor"}.get(house, house)   # sic in the pack
                m.houses[house.title()] = path
            elif low.startswith("sfx_patronus_") and low.endswith(".mp4"):
                m.patronuses[patronus_name(path.stem)] = path
        m.mishaps = tuple(sorted(m.mishaps))
        m.patronuses = dict(sorted(m.patronuses.items()))
        self.media = m

    def reload(self):
        entries = []
        book = self.media_dir / "spellbook.json"
        if book.is_file():
            try:
                entries = json.loads(book.read_text(encoding="utf-8")).get("spells", [])
            except Exception as e:
                log.warning("cannot read %s: %s", book, e)

        mp3s, videos, every = [], {}, []
        if self.media_dir.is_dir():
            for root, _dirs, files in os.walk(self.media_dir):
                for f in files:
                    low = f.lower()
                    every.append(Path(root) / f)
                    if low.endswith(".mp3"):
                        mp3s.append(Path(root) / f)
                    elif low.endswith("_video_payoff.mp4"):
                        videos[spell_key(f[:-len("_video_payoff.mp4")])] = Path(root) / f
        self._mp3s = mp3s
        self._index_media(every)

        keys = [spell_key(s["spell_name"]) for s in entries]
        sounds: dict = {}
        for mp3 in mp3s:
            fname = spell_key(mp3.stem)
            hits = [k for k in keys if k in fname]
            if hits:
                sounds.setdefault(max(hits, key=len), []).append(mp3)

        spells = {}
        for s, key in zip(entries, keys):
            subtitle, _, desc = html.unescape(s.get("description") or "").partition(" | ")
            if not desc:
                subtitle, desc = "", subtitle
            color = (s.get("spell_background_color") or "").strip().lstrip("#")
            spells[key] = SpellInfo(
                name=s["spell_name"], key=key,
                incantation=s.get("incantation_name") or "",
                pronunciation=s.get("pronunciation") or "",
                subtitle=subtitle.strip(), description=desc.strip(),
                notable_uses=html.unescape(s.get("notable_uses") or "").strip(),
                spell_type=s.get("spell_type") or "",
                difficulty=int(s.get("difficulty") or 0),
                color=f"#{color}" if re.fullmatch(r"[0-9a-fA-F]{6}", color) else SpellInfo.color,
                colors=cast_colors((s.get("config_wand") or {}).get("macros_payoff") or (),
                                   self.house_color),
                wand_macros=tuple((s.get("config_wand") or {}).get("macros_payoff") or ()),
                box_macros=tuple((s.get("config_wandbox") or {}).get("macros_payoff") or ()),
                sounds=tuple(sorted(sounds.get(key, ()))),
                video=videos.get(key))
        self._spells = spells
        self._videos = videos
        log.info("spellbook: %d spells, %d sounds, %d videos", len(spells), len(mp3s), len(videos))

    def get(self, name: str) -> Optional[SpellInfo]:
        """Spellbook entry for a spell, or a bare entry with any matching
        media if the spellbook doesn't list it (None if nothing at all)."""
        key = spell_key(name or "")
        if key in self._spells:
            return self._spells[key]
        sounds = tuple(sorted(p for p in self._mp3s if key and key in spell_key(p.name)))
        video = self._videos.get(key)
        return SpellInfo(name=name, key=key, sounds=sounds, video=video) \
            if (sounds or video) else None

    @property
    def spells(self) -> list:
        return list(self._spells.values())

    def __len__(self):
        return len(self._spells)


class Progress:
    """Successful casts per spell (spell mastery), kept in progress.json."""

    def __init__(self, path):
        self.path = Path(path)
        self.counts: dict = {}
        if self.path.is_file():
            try:
                self.counts = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception as e:
                log.warning("cannot read %s: %s", self.path, e)

    def count(self, name: str) -> int:
        return int(self.counts.get(spell_key(name), 0))

    def record(self, name: str) -> int:
        key = spell_key(name)
        self.counts[key] = self.counts.get(key, 0) + 1
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.counts, indent=1, sort_keys=True), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as e:
            log.warning("cannot save %s: %s", self.path, e)
        return self.counts[key]
