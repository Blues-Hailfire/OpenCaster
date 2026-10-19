"""
opencaster.core — Wires wands to spell assessment, effects, duels and the API
==============================================================================
OpenCaster owns one WandManager (opencaster.wand) and one CastSession
(opencaster.casting) per connected wand, and connects them:

    wand pads / IMU  →  that wand's CastSession  →  cast result  →  effects
    wand firmware spell broadcast                →  treated like a recognised cast

Wands cast independently; a Duel (opencaster.duel) can pit two of them
against each other.  Everything runs on a single asyncio loop.  Observers
subscribe to `core.events` (an Emitter); handlers run on the loop thread, so
a GUI must hop threads itself (see opencaster.gui.bridge).  Command methods
must also be called on the loop thread (call_soon_threadsafe from elsewhere).

Events — the wand manager's scan/found/status/connecting/connected/ready/
disconnected are forwarded as-is; per-wand events carry the wand address
first:
    "pads" "window_open" "trail" "tap" "timeout" "cast" "blocked"
    "label_needed" "labelled" "calibrating" "calibration"
                (address, payload)       from that wand's CastSession
    "battery"   (address, percent)
    "imu"       (address, first sample of the batch)
    "motion"    (address, motion dict or None)
    "wand_info" (info dict)              colour/nickname changed
    "log"       (DeviceInfo, notification)
    "spell"     (dict)                   a spell was cast successfully
    "duel"      (snapshot dict)          see opencaster.duel
    "settings"  (settings dict)
    "library"   ((templates, spellbook))
"""

import asyncio
import logging
from typing import Optional

from . import paths
from .casting import CastLog, CastSession, SpellLibrary, SpellMatcher, WandProfiles, spell_key
from .duel import Duel
from .settings import HOUSES, Settings, normalise_color, rgb
from .spellbook import DIFFICULTY, MASTERY_CASTS, Progress, Spellbook
from .wand import Battery, DeviceInfo, Emitter, WandManager, effects, protocol as p

log = logging.getLogger(__name__)

POOLS = ("cast", "all") + DIFFICULTY      # duel spell pools


class OpenCaster:
    def __init__(self, spells_dir=paths.SPELLS_DIR, media_dir=paths.MEDIA_DIR,
                 casts_file=paths.CASTS_FILE, profiles_file=paths.PROFILES_FILE,
                 progress_file=paths.PROGRESS_FILE, settings_file=paths.SETTINGS_FILE,
                 boxes: bool = True, use_api: bool = True):
        self.events = Emitter()
        self.settings = Settings(settings_file)
        self.library = SpellLibrary(spells_dir)
        self.spellbook = Spellbook(media_dir, self.settings.house_color)
        self.profiles = WandProfiles(profiles_file)
        self.progress = Progress(progress_file)
        self.cast_log = CastLog(casts_file)
        self.matcher = SpellMatcher()
        self.sessions: dict = {}            # address → CastSession
        self.wands: dict = {}               # address → DeviceInfo, connected
        self.ready: set = set()
        self.battery: dict = {}
        self.target: Optional[str] = None   # practice spell for every wand
        self.label_casts = False
        self.duel: Optional[Duel] = None
        self.manager = WandManager(auto=self.profiles.auto_connect(), boxes=boxes,
                                   welcome=lambda info: effects.welcome(self.wand_rgb(info.address)))
        self.manager.events.on("*", self._on_wand)
        self.use_api = use_api
        self.api = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    async def run(self):
        self._loop = asyncio.get_running_loop()
        if self.use_api and self.settings.api.get("enabled"):
            from .api.server import ApiServer
            self.api = ApiServer(self, **self.settings.api)
            await self.api.start()
        try:
            await self.manager.run()
        finally:
            if self.duel:
                self.duel.cancel()
            if self.api:
                await self.api.close()

    @property
    def variables(self) -> dict:
        return {"house_color": self.settings.house_color}

    # ── wands ─────────────────────────────────────────────────────────────────

    def wand_color(self, address: str) -> str:
        own = self.profiles.get(address, "color")
        try:
            return normalise_color(own) if own else self.settings.default_color
        except ValueError:
            return self.settings.default_color

    def wand_rgb(self, address: str) -> tuple:
        return rgb(self.wand_color(address))

    def wand_label(self, address: str) -> str:
        info = self.wands.get(address)
        return self.profiles.get(address, "nickname") or (info.name if info else address)

    def wand_info(self, address: str) -> dict:
        info = self.wands.get(address)
        return {"address": address, "name": info.name if info else address,
                "nickname": self.profiles.get(address, "nickname") or "",
                "label": self.wand_label(address), "color": self.wand_color(address),
                "own_color": bool(self.profiles.get(address, "color")),
                "connected": address in self.wands, "ready": address in self.ready,
                "wanted": self.manager.is_wanted(address),
                "battery": self.battery.get(address)}

    def wand_list(self) -> list:
        return [self.wand_info(a) for a in self.wands]

    def resolve(self, wand: Optional[str]) -> list:
        """'all'/None → every connected wand; else match address, name or
        nickname (case-insensitive).  Raises KeyError if nothing matches."""
        if wand in (None, "", "all", "*"):
            return list(self.wands)
        w = str(wand).lower()
        hits = [a for a, i in self.wands.items()
                if w in (a.lower(), i.name.lower(), self.wand_label(a).lower())]
        if not hits:
            raise KeyError(f"no connected wand {wand!r}")
        return hits

    def _session(self, address: str) -> CastSession:
        s = self.sessions.get(address)
        if s is None:
            s = CastSession(self.library, self.matcher, cast_log=self.cast_log,
                            on_event=lambda n, pl=None, a=address: self._on_session(a, n, pl))
            s.label_casts = self.label_casts and not self._duelling
            s.set_target(None if self._duelling else self.target)
            self.sessions[address] = s
        return s

    @property
    def _duelling(self) -> bool:
        return bool(self.duel and self.duel.active)

    # ── commands (loop thread) ────────────────────────────────────────────────

    def stop(self):
        self.manager.stop()

    def scan(self):
        self.manager.request_scan()

    def connect(self, address: str):
        self.manager.connect(address)

    def disconnect(self, address: str):
        self.profiles.set(address, "auto_connect", None)
        self.manager.disconnect(address)

    def set_target(self, name: Optional[str]):
        t = self.library.get(name) if name else None
        self.target = t.name if t else None
        if not self._duelling:
            for s in self.sessions.values():
                s.set_target(self.target)

    def set_label_casts(self, on: bool):
        self.label_casts = bool(on)
        if not self._duelling:
            for s in self.sessions.values():
                s.set_label_casts(self.label_casts)

    def label(self, address: str, label: Optional[str]):
        if address in self.sessions:
            self.sessions[address].label(label)

    def toggle_override(self, address: str, pad: int):
        if address in self.sessions:
            self.sessions[address].toggle_override(pad)

    def start_calibration(self, address: str):
        if address in self.sessions:
            self.sessions[address].start_calibration()

    def finish_calibration(self, address: str, save: bool):
        s = self.sessions.get(address)
        motion = s.end_calibration() if s else None
        if save and motion and address in self.wands:
            self.profiles.save_motion(address, self.wands[address].name, motion)
            s.set_motion(motion)
            self.events.emit("motion", address, motion)

    def reload(self):
        self.library.reload()
        self.spellbook.house_color = self.settings.house_color
        self.spellbook.reload()
        self.set_target(self.target)
        self.events.emit("library", (self.library.templates, self.spellbook))

    def preview(self, name: str, address: Optional[str] = None):
        """Play a spell's wand and box effects without casting it."""
        for a in ([address] if address else list(self.wands)):
            self._play_spell_effects(name, a)

    # settings -------------------------------------------------------------------

    def set_default_color(self, color: str):
        self.settings.default_color = color
        self.events.emit("settings", self.settings.snapshot())
        for a in self.wands:
            if not self.profiles.get(a, "color"):
                self._show_color(a)
                self.events.emit("wand_info", self.wand_info(a))

    def set_wand_color(self, address: str, color: Optional[str]):
        self.profiles.set(address, "color", normalise_color(color) if color else None,
                          self.wands[address].name if address in self.wands else "")
        self._show_color(address)
        self.events.emit("wand_info", self.wand_info(address))

    def set_nickname(self, address: str, nickname: str):
        self.profiles.set(address, "nickname", nickname.strip() or None,
                          self.wands[address].name if address in self.wands else "")
        self.events.emit("wand_info", self.wand_info(address))

    def set_house(self, house: str):
        self.settings.house = house if house in HOUSES else ""
        self.events.emit("settings", self.settings.snapshot())
        self.spellbook.house_color = self.settings.house_color
        self.spellbook.reload()                  # Colovaria's colours change
        self.events.emit("library", (self.library.templates, self.spellbook))

    def set_patronus(self, name: str):
        self.settings.patronus = name if name in self.spellbook.media.patronuses else "random"
        self.events.emit("settings", self.settings.snapshot())

    def _show_color(self, address: str):
        if address in self.wands:
            self.manager.play(effects.light(self.wand_rgb(address), 250, 1200), address)

    # direct control (API) ---------------------------------------------------------

    def light(self, wand, color: str, fade_ms: int = 300, hold_ms: int = 0, groups=None):
        for a in self.resolve(wand):
            self.manager.play(effects.light(rgb(color), fade_ms, hold_ms,
                                            groups if groups is not None else range(4)), a)

    def vibrate(self, wand, duration_ms: int):
        for a in self.resolve(wand):
            self.manager.play(effects.vibrate(duration_ms), a)

    def clear(self, wand=None):
        for a in self.resolve(wand):
            self.manager.play(effects.clear(), a)

    def play_effect(self, wand, name: Optional[str] = None, spell: Optional[str] = None,
                    macro: Optional[list] = None):
        targets = self.resolve(wand)
        for a in targets:
            if spell:
                self._play_spell_effects(spell, a)
            elif macro is not None:
                self.manager.play_macro(macro, self.variables, a)
            elif name in ("welcome", "success", "glow", "breathe", "countdown", "go", "duel_won"):
                fn = effects.BUILTIN[name]
                self.manager.play(fn(*self.wand_rgb(a)) if name == "glow" else fn(self.wand_rgb(a)), a)
            elif name in effects.BUILTIN:
                self.manager.play(effects.BUILTIN[name](), a)
            else:
                raise KeyError(f"unknown effect {name!r}")

    # duel ---------------------------------------------------------------------------

    def duel_pool(self, pool: str = "cast") -> list:
        names = [t.name for t in self.library.templates]
        if pool == "all":
            return names
        if pool in DIFFICULTY:
            return [n for n in names
                    if (i := self.spellbook.get(n)) and i.difficulty_name == pool]
        good = {k for k, v in self.progress.counts.items() if v > 0}
        for r in self.cast_log.load():
            if r.get("accepted") and r.get("predicted") and r.get("label") \
                    and spell_key(r["predicted"]) == spell_key(r["label"]):
                good.add(spell_key(r["label"]))
        return [n for n in names if spell_key(n) in good]

    def duel_pools(self) -> dict:
        return {k: len(self.duel_pool(k)) for k in POOLS}

    def start_duel(self, players: list, pool: str = "cast"):
        players = [a for a in players if a in self.wands]
        if len(set(players)) != 2:
            self.events.emit("status", "A duel needs two connected wands")
            return
        spells = self.duel_pool(pool)
        if len(spells) < 3:
            spells = self.duel_pool("all")
        if self.duel and self.duel.active:
            self.duel.cancel()
        for s in self.sessions.values():
            s.set_label_casts(False)
            s.set_target(None)
        self.duel = Duel(players, spells, self._on_duel, self._loop.call_later,
                         intro_s=5.0 if self.spellbook.media.duel_intro else 2.0)
        self.duel.start()

    def cancel_duel(self):
        if self.duel:
            self.duel.cancel()

    def skip_round(self):
        if self.duel:
            self.duel.skip()

    def _on_duel(self, snap: dict):
        players, phase = snap["players"], snap["phase"]
        live = [a for a in players if a in self.wands]
        if phase == "countdown":
            for a in live:
                self.sessions[a].set_target(None)
                self.manager.play(effects.countdown_tick(self.wand_rgb(a)), a)
        elif phase == "racing":
            for a in live:
                self.sessions[a].set_target(snap["spell"])
                self.manager.play(effects.go(self.wand_rgb(a)), a)
        elif phase == "result":
            for a in live:
                self.sessions[a].set_target(None)
                if snap["round_winner"] and a != snap["round_winner"]:
                    self.manager.play(effects.round_lost(), a)
        elif phase in ("finished", "cancelled"):
            for a in live:
                if phase == "finished" and a == snap["winner"]:
                    self.manager.play(effects.duel_won(self.wand_rgb(a)), a)
                elif phase == "finished":
                    self.manager.play(effects.round_lost(), a)
            for s in self.sessions.values():      # practice spell / labelling as now set
                s.set_target(self.target)
                s.set_label_casts(self.label_casts)
        self.events.emit("duel", dict(snap, player_info=[self.wand_info(a) for a in players]))

    # ── wand → sessions ───────────────────────────────────────────────────────

    def _on_wand(self, name: str, *args):
        if name == "notify":
            info, ev = args
            if info.kind != "wand":
                if not isinstance(ev, (p.Challenge, p.Pong)):
                    self.events.emit("log", info, ev)
                return
            a = info.address
            if isinstance(ev, p.ImuBatch):
                if a in self.sessions:
                    self.sessions[a].feed_imu(ev.samples)
                self.events.emit("imu", a, ev.samples[0])
            elif isinstance(ev, p.Buttons):
                if a in self.sessions:
                    self.sessions[a].feed_buttons(ev.mask)
            elif isinstance(ev, p.SpellCast):
                self.events.emit("log", info, ev)
                self._spell_cast(ev.name, "wand", a)
            elif isinstance(ev, Battery):
                self.battery[a] = ev.percent
                self.events.emit("battery", a, ev.percent)
            elif not isinstance(ev, (p.Challenge, p.Pong)):
                self.events.emit("log", info, ev)
            return

        info = args[0] if args else None
        if isinstance(info, DeviceInfo) and info.kind == "wand":
            a = info.address
            if name == "connected":
                self.wands[a] = info
                self.profiles.set_last_used(a, info.name)
                self.profiles.set(a, "auto_connect", True)
                motion = self.profiles.motion(a)
                s = self._session(a)
                s.wand = a
                s.set_motion(motion)
                self.events.emit(name, *args)
                self.events.emit("wand_info", self.wand_info(a))
                self.events.emit("motion", a, motion)
                return
            if name == "connecting":
                self.events.emit(name, *args)
                self.events.emit("wand_info", dict(self.wand_info(a), name=info.name,
                                                   label=self.profiles.get(a, "nickname") or info.name))
                return
            if name == "ready":
                self.ready.add(a)
            if name == "disconnected":
                self.wands.pop(a, None)
                self.ready.discard(a)
                self.battery.pop(a, None)
                if a in self.sessions:
                    self.sessions[a].reset()
                if self._duelling and a in self.duel.players:
                    self.events.emit("status", f"{self.wand_label(a)} disconnected - duel cancelled")
                    self.duel.cancel()
            self.events.emit(name, *args)
            self.events.emit("wand_info", dict(self.wand_info(a), name=info.name,
                                               label=self.profiles.get(a, "nickname") or info.name))
            return
        self.events.emit(name, *args)

    # ── sessions → effects ────────────────────────────────────────────────────

    def _on_session(self, address: str, name: str, payload=None):
        if name == "window_open":
            self.manager.play(effects.breathe(self.wand_rgb(address)), address)
            if self.duel:
                self.duel.window_opened(address)
        elif name in ("tap", "calibrating"):
            self.manager.play(effects.clear(), address)
        elif name == "cast":
            if self._duelling and address in self.duel.players and payload.accepted:
                phase = self.duel.phase
                if not self.duel.cast(address, payload.accepted, payload.spell):
                    # Recognised, but it doesn't win the round: no celebration, no mastery.
                    payload = payload.rejected(
                        "round already over" if phase == "result" else
                        "too early - wait for “Cast!”" if phase in ("intro", "countdown")
                        or self.duel.racing and payload.spell == self.duel.spell
                        else f"not {self.duel.spell}")
            if not payload.accepted:
                if not (self.duel and self.duel.phase in ("result", "finished")):
                    self.manager.play(effects.fail(), address)
        self.events.emit(name, address, payload)
        if name == "cast" and payload.accepted:
            self._spell_cast(payload.spell, "cast", address)

    def _play_spell_effects(self, name: str, address: str):
        info = self.spellbook.get(name)
        macro = info.wand_macro() if info else None
        if macro:
            self.manager.play_macro(macro, self.variables, address)
        else:
            self.manager.play(effects.success(self.wand_rgb(address)), address)
        box = info.box_macro() if info else None
        if box:
            self.manager.play_boxes_macro(box, self.variables)

    def _spell_cast(self, name: str, source: str, address: str):
        self._play_spell_effects(name, address)
        template = self.library.get(name)
        display = template.name if template else name
        count = self.progress.record(display)
        patronus = None
        if spell_key(display) == "expectopatronum":
            patronus = self.spellbook.media.patronus(self.settings.patronus)
        self.events.emit("spell", {
            "name": display, "info": self.spellbook.get(display), "source": source,
            "count": count, "mastered_now": count == MASTERY_CASTS, "wand": address,
            "wand_label": self.wand_label(address), "patronus_video": patronus})
