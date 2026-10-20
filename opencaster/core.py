"""
opencaster.core — Wires wands to spell assessment, effects, duels and the API
==============================================================================
OpenCaster owns one WandManager (opencaster.wand) and one CastSession
(opencaster.casting) per connected wand, and connects them:

    wand pads / IMU  →  that wand's CastSession  →  cast result  →  effects
    wand firmware spell broadcast                →  treated like a recognised cast

Wands cast independently; a duel (opencaster.duel: quick-draw, clash or
Duelling Club) can pit them against each other, or against the NPC
(opencaster.npc), a computer opponent the core plays with timers through
the same path as a wand's casts.  A duel, or a GUI
page that wants every spell (set_free_cast), suspends the practice spell and
cast labelling.

Everything runs on a single asyncio loop.  Observers subscribe to
`core.events` (an Emitter); handlers run on the loop thread, so
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
    "aim"       (address, right, up)     degrees the wand has turned since set_aim(on),
                                         ~12 times a second, until its next cast
    "duel"      (snapshot dict)          see opencaster.duel
    "settings"  (settings dict)
    "library"   ((templates, spellbook))
"""

import asyncio
import logging
from typing import Optional

from . import npc as N
from . import paths
from .casting import (CastLog, CastResult, CastSession, GestureTracker, Match, SpellLibrary, SpellMatcher,
                      WandProfiles, spell_key)
from .duel import CLUB_MAX_PLAYERS, CLUB_ORDERS, ClashDuel, ClubDuel, Duel
from .elements import battle_spells
from .settings import HOUSES, Settings, normalise_color, rgb
from .spellbook import DIFFICULTY, MASTERY_CASTS, Progress, Spellbook
from .wand import Battery, DeviceInfo, Emitter, WandManager, effects, protocol as p

log = logging.getLogger(__name__)

POOLS = ("cast", "all") + DIFFICULTY      # quick-draw spell pools
MODES = ("race", "clash", "club")         # duel modes
BATTLE_KEYS = frozenset(spell_key(n) for n in battle_spells())


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
        self.free_cast = False              # practice spell / labelling suspended
        self.duel: Optional[Duel] = None
        self._duel_phase: Optional[str] = None
        self._duel_turn: Optional[int] = None
        self.npc: Optional[N.Npc] = None    # the computer opponent, while it has a seat
        self._npc_on = None                 # the round or turn its current move is for
        self._npc_token = 0
        self._npc_timers: list = []
        self._aim: dict = {}                # address → {tracker, glow, lit}: wands steering
        self._payoff_until: dict = {}       # address → loop time its spell light ends
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
        if address == N.NPC:
            return N.COLOR
        own = self.profiles.get(address, "color")
        try:
            return normalise_color(own) if own else self.settings.default_color
        except ValueError:
            return self.settings.default_color

    def wand_rgb(self, address: str) -> tuple:
        return rgb(self.wand_color(address))

    def wand_label(self, address: str) -> str:
        if address == N.NPC:
            return N.NAME
        info = self.wands.get(address)
        return self.profiles.get(address, "nickname") or (info.name if info else address)

    def wand_info(self, address: str) -> dict:
        if address == N.NPC:
            return {"address": N.NPC, "name": N.NAME, "nickname": "", "label": N.NAME,
                    "color": N.COLOR, "own_color": False, "connected": True, "ready": True,
                    "wanted": False, "battery": None, "npc": True,
                    "level": self.npc.level if self.npc else None}
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
            s.label_casts = self.label_casts and not self._suspended
            s.set_target(None if self._suspended else self.target)
            self.sessions[address] = s
        return s

    @property
    def _duelling(self) -> bool:
        return bool(self.duel and self.duel.active)

    @property
    def _suspended(self) -> bool:
        return self._duelling or self.free_cast

    def _sync_sessions(self):
        """Apply the practice spell and labelling to every session, unless a
        duel (which sets targets itself) or free casting suspends them."""
        for s in self.sessions.values():
            s.set_label_casts(self.label_casts and not self._suspended)
            if not self._duelling:
                s.set_target(None if self.free_cast else self.target)
                s.allowed = None

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
        self._sync_sessions()

    def set_label_casts(self, on: bool):
        self.label_casts = bool(on)
        self._sync_sessions()

    def set_aim(self, address: str, on: bool, spell: Optional[str] = None):
        """Report where a wand points ("aim" events) – the GUI steers a
        levitating jack-o'-lantern with it.  The wand glows in `spell`'s
        colour once that spell's own light has played, until the hold ends:
        set_aim(off), or the wand's next cast (all four pads again)."""
        self._aim_end(address, clear=True)
        if not (on and address in self.wands):
            return
        tracker = GestureTracker.from_profile(self.profiles.motion(address))
        tracker.begin()
        info = self.spellbook.get(spell) if spell else None
        colour = rgb(info.colors[0]) if info and info.colors else self.wand_rgb(address)
        wait = max(0.0, self._payoff_until.get(address, 0.0) - self._loop.time())
        self._aim[address] = {"tracker": tracker, "lit": False,
                              "glow": self._loop.call_later(wait, lambda: self._aim_glow(address, colour))}

    def _aim_glow(self, address: str, colour: tuple):
        aim = self._aim.get(address)
        if aim:
            aim["lit"] = True
            self.manager.play(effects.glow(*colour, fade_ms=600), address)

    def _aim_feed(self, address: str, samples):
        tracker = self._aim[address]["tracker"]
        tracker.feed_many(samples)
        self.events.emit("aim", address, *tracker.position())

    def _aim_end(self, address: str, clear: bool):
        """Stop steering with a wand; clear its glow if it's showing (a new
        cast's own light replaces it anyway)."""
        aim = self._aim.pop(address, None)
        if aim:
            aim["glow"].cancel()
            if clear and aim["lit"]:
                self.manager.play(effects.clear(), address)

    def set_free_cast(self, on: bool):
        """Accept any spell from every wand, without labelling (the GUI's
        environment page); the practice settings come back when it ends."""
        self.free_cast = bool(on)
        self._sync_sessions()

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
            self.manager.play(effects.color_preview(self.wand_rgb(address)), address)

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
            elif name in ("welcome", "success", "glow", "breathe", "countdown", "go", "locked_in",
                          "duel_won"):
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

    def start_duel(self, players: list, pool: str = "cast", mode: str = "race",
                   order: str = "in_order", npc_level: str = "medium"):
        """mode "race": quick-draw on spells from `pool`; "clash": any battle
        spell, elements decide; "club": Duelling Club turns on the same
        elements, 2-5 players in seat order, the next to answer chosen by
        `order` ("in_order" or "random").  Quick-draw and clash take two.
        A player may be npc.NPC, the computer opponent, at `npc_level`."""
        players = list(dict.fromkeys(a for a in players if a in self.wands or a == N.NPC))   # seat order
        most = CLUB_MAX_PLAYERS if mode == "club" else 2
        if not 2 <= len(players) <= most or players == [N.NPC]:
            self.events.emit("status", "A duel needs two players: connected wands or the NPC" if most == 2
                             else f"The Duelling Club needs 2 to {most} players: connected wands or the NPC")
            return
        if self.duel and self.duel.active:
            self.duel.cancel()
        for s in self.sessions.values():
            s.set_label_casts(False)
            s.set_target(None)
        intro_s = 5.0 if self.spellbook.media.duel_intro else 2.0
        self._npc_cancel()
        self._npc_on = None
        self.npc = N.Npc(npc_level, {t.name for t in self.library.templates}) if N.NPC in players else None
        if mode in ("clash", "club"):
            for a in players:
                if a in self.sessions:
                    self.sessions[a].allowed = BATTLE_KEYS
            if mode == "clash":
                self.duel = ClashDuel(players, self._on_duel, self._loop.call_later, intro_s=intro_s)
            else:
                self.duel = ClubDuel(players, self._on_duel, self._loop.call_later, intro_s=intro_s,
                                     order=order if order in CLUB_ORDERS else "in_order")
        else:
            spells = self.duel_pool(pool)
            if len(spells) < 3:
                spells = self.duel_pool("all")
            self.duel = Duel(players, spells, self._on_duel, self._loop.call_later, intro_s=intro_s)
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
        new_phase = phase != self._duel_phase      # clash re-publishes "racing" on lock-in
        self._duel_phase = phase
        clash = snap["mode"] == "clash"
        if phase == "countdown":
            self._duel_turn = None
            for a in live:
                self.sessions[a].set_target(None)
                self.manager.play(effects.countdown_tick(self.wand_rgb(a)), a)
        elif phase == "racing" and snap["mode"] == "club":
            if snap["turn_no"] != self._duel_turn:  # your turn: a flash on that wand only
                self._duel_turn = snap["turn_no"]
                if snap["turn"] in live:
                    self.manager.play(effects.go(self.wand_rgb(snap["turn"])), snap["turn"])
        elif phase == "racing" and new_phase:
            for a in live:
                self.sessions[a].set_target(None if clash else snap["spell"])
                self.manager.play(effects.go(self.wand_rgb(a)), a)
        elif phase == "result":
            winner = snap["round_winner"]
            for a in live:
                self.sessions[a].set_target(None)
                # the Duelling Club's loser is the one who failed (there may be no winner)
                lost = a == snap["loser"] if snap["mode"] == "club" else bool(winner) and a != winner
                if clash and snap["picks"].get(a):       # the reveal: both spells go off
                    self._spell_cast(snap["picks"][a], "cast", a, play=not lost)
                if lost:
                    self.manager.play(effects.round_lost(), a)
                elif clash and not snap["picks"].get(a):
                    self.manager.play(effects.clear(), a)
        elif phase in ("finished", "cancelled"):
            for a in live:
                if phase == "finished" and a == snap["winner"]:
                    self.manager.play(effects.duel_won(self.wand_rgb(a)), a)
                elif phase == "finished" and snap["mode"] != "club":   # the club's loser has faded
                    self.manager.play(effects.round_lost(), a)
            self._sync_sessions()             # practice spell / labelling as now set
        self._npc_follow(snap)
        self.events.emit("duel", dict(snap, player_info=[self.wand_info(a) for a in players],
                                      npc_level=self.npc.level if self.npc and N.NPC in players else None))

    # NPC ----------------------------------------------------------------------------

    def _npc_follow(self, snap: dict):
        """Every duel snapshot: start the NPC's move when it's due, or drop it."""
        if not self.npc or N.NPC not in snap["players"]:
            return
        phase, mode = snap["phase"], snap["mode"]
        if phase != "racing":
            self._npc_cancel()
            if phase == "result" and mode == "clash":
                for a, spell in snap.get("picks", {}).items():
                    if a != N.NPC:
                        self.npc.observe(spell)
            return
        if mode == "club":
            if snap["turn"] != N.NPC or self._npc_on == ("turn", snap["turn_no"]):
                return
            self._npc_on = ("turn", snap["turn_no"])
            move = self.npc.counter(snap["incoming"]) if snap["turn_kind"] == "counter" else self.npc.attack()
        else:
            if self._npc_on == ("round", snap["round"]):     # a clash re-publishes on lock-in
                return
            self._npc_on = ("round", snap["round"])
            move = self.npc.race(snap["spell"]) if mode == "race" else self.npc.clash()
        self._npc_cancel()
        self._npc_play(move, self._npc_on)

    def _npc_due(self, on) -> bool:
        """Is the move for `on` (a round or turn) still the NPC's to make?"""
        d = self.duel
        if not (d and d.racing and self.npc and N.NPC in d.players):
            return False
        if d.mode == "club":
            return d.turn == N.NPC and on == ("turn", d.turn_no)
        return on == ("round", d.round) and not (d.mode == "clash" and N.NPC in d.picks)

    def _npc_play(self, move: N.Move, on):
        """React, then draw the gesture (live trail events), then cast – as a
        wand would, through _on_session."""
        def start():
            if not self._npc_due(on):
                return
            self._on_session(N.NPC, "window_open", None)
            trail = N.gesture(getattr(self.library.get(move.spell), "outline", None), self.npc.rng)
            steps = max(2, int(move.draw / 0.08))
            for i in range(1, steps):
                self._npc_later(move.draw * i / steps,
                                lambda n=max(2, len(trail) * i // steps): self._on_session(N.NPC, "trail", trail[:n]))
            self._npc_later(move.draw, lambda: finish(trail))

        def finish(trail):
            if not self._npc_due(on):
                return
            key = spell_key(move.spell)
            match = Match(move.spell, key, 0.55 if move.fumble else 0.12, 0.3, not move.fumble)
            self._on_session(N.NPC, "cast", CastResult(trail, "ok", (match,), None))
            if move.fumble and self._npc_due(on):            # not recognised: cast again
                self._npc_play(self.npc.retry(move), on)

        self._npc_later(move.react, start)

    def _npc_later(self, delay: float, fn):
        token = self._npc_token

        def run():
            if token == self._npc_token:
                fn()
        self._npc_timers = [h for h in self._npc_timers if not h.cancelled()]
        self._npc_timers.append(self._loop.call_later(delay, run))

    def _npc_cancel(self):
        self._npc_token += 1
        for h in self._npc_timers:
            h.cancel()
        self._npc_timers.clear()

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
                if a in self._aim:
                    self._aim_feed(a, ev.samples)
                self.events.emit("imu", a, ev.samples[0])
            elif isinstance(ev, p.Buttons):
                if a in self.sessions:
                    self.sessions[a].feed_buttons(ev.mask)
            elif isinstance(ev, p.SpellCast):
                self.events.emit("log", info, ev)
                if not (self._duelling and a in self.duel.players):   # duels count only our casts
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
                self._aim_end(a, clear=False)
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
            self._aim_end(address, clear=False)   # a new cast lets go of what it was steering
            self.manager.play(effects.breathe(self.wand_rgb(address)), address)
            if self.duel:
                self.duel.window_opened(address)
        elif name in ("tap", "calibrating"):
            self.manager.play(effects.clear(), address)
            if self._turn_based(address):
                self.duel.window_closed(address)
        elif name == "cast":
            held = False                          # a clash pick, revealed with the result
            if self._turn_based(address) and self.duel.mode == "club":
                if payload.accepted:
                    _counted, note = self.duel.cast(address, True, payload.spell)
                    if note:                      # ignored, or a wrong spell that loses
                        payload = payload.rejected(note)
                else:
                    self.duel.window_closed(address)
            elif self._turn_based(address):
                if payload.accepted:
                    note = self.duel.cast(address, True, payload.spell)
                    if note:
                        payload = payload.rejected(note)
                    else:
                        held = True
                        self.manager.play(effects.locked_in(self.wand_rgb(address)), address)
                else:
                    self.duel.window_closed(address)
            elif self._duelling and address in self.duel.players and payload.accepted:
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
            if payload.accepted and not held:
                self._spell_cast(payload.spell, "cast", address)
            return
        self.events.emit(name, address, payload)

    def _turn_based(self, address: str) -> bool:
        """A clash or Duelling Club player: their gesture windows matter to the duel."""
        return self._duelling and self.duel.mode in ("clash", "club") and address in self.duel.players

    def _play_spell_effects(self, name: str, address: str):
        info = self.spellbook.get(name)
        macro = info.wand_macro() if info else None
        if macro:
            self.manager.play_macro(macro, self.variables, address)
            steps = effects.macro_to_frames(macro, 512, self.variables)
        else:
            steps = effects.success(self.wand_rgb(address))
            self.manager.play(steps, address)
        if self._loop:      # when its last step (usually a fade out) starts: a steering glow takes over
            self._payoff_until[address] = self._loop.time() + sum(w for _f, w in steps) + 0.05
        box = info.box_macro() if info else None
        if box:
            self.manager.play_boxes_macro(box, self.variables)

    def _spell_cast(self, name: str, source: str, address: str, play: bool = True):
        if play:
            self._play_spell_effects(name, address)
        template = self.library.get(name)
        display = template.name if template else name
        # the NPC's spells don't count towards your mastery
        count = self.progress.count(display) if address == N.NPC else self.progress.record(display)
        patronus = None
        if spell_key(display) == "expectopatronum":
            patronus = self.spellbook.media.patronus(self.settings.patronus)
        self.events.emit("spell", {
            "name": display, "info": self.spellbook.get(display), "source": source,
            "count": count, "mastered_now": count == MASTERY_CASTS and address != N.NPC, "wand": address,
            "wand_label": self.wand_label(address), "patronus_video": patronus})
