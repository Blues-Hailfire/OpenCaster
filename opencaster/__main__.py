"""
Headless OpenCaster: connect, cast, see results in the terminal.

    python -m opencaster                 auto-connect the wands used last time (or the first found)
    python -m opencaster --target Lumos  practise one spell
    python -m opencaster --duel          quick-draw duel as soon as two wands are ready
    python -m opencaster --clash         clash duel (elements) as soon as two wands are ready
    python -m opencaster --club [N]      Duelling Club (turn by turn) once N wands (2-5) are ready
    python -m opencaster --npc [LEVEL]   duel the NPC (computer opponent) in the last seat – with
                                         --duel, --clash or --club, or a quick-draw on its own
    python -m opencaster --cast-seconds S  seconds each player has to cast in a duel (default: the
                                         mode's own – quick-draw 30, clash 3, Duelling Club 5)
    python -m opencaster --no-sound      skip casting sounds

Every connected wand casts independently.  The control API runs here too
(see `python -m opencaster.api --help`).  Casting sounds use Windows MCI
here (the GUI uses Qt Multimedia instead).
"""

import argparse
import asyncio
import ctypes
import logging
import sys
import time

from .core import OpenCaster
from .npc import LEVELS as NPC_LEVELS, NPC
from .wand import DeviceInfo


class MciPlayer:
    """MP3 playback through Windows MCI; silently does nothing elsewhere."""

    def __init__(self, alias: str = "opencaster_sfx"):
        self.alias = alias
        self._send = ctypes.windll.winmm.mciSendStringW if sys.platform == "win32" else None

    def play(self, path) -> bool:
        if self._send is None or path is None:
            return False
        self._send(f"close {self.alias}", None, 0, 0)
        if self._send(f'open "{path}" type mpegvideo alias {self.alias}', None, 0, 0):
            return False
        return self._send(f"play {self.alias}", None, 0, 0) == 0


def _print(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="python -m opencaster", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", help="practise one spell (only it can be accepted)")
    ap.add_argument("--duel", nargs="?", const="cast", metavar="POOL",
                    help="duel when two wands are ready; POOL: cast (default), all, "
                         "Beginner, Intermediate, Expert")
    ap.add_argument("--clash", action="store_true",
                    help="clash duel when two wands are ready: a few seconds to cast any battle "
                         "spell, elements decide the round")
    ap.add_argument("--club", nargs="?", const=2, type=int, metavar="PLAYERS",
                    help="Duelling Club once PLAYERS wands (2-5, default 2) are ready: answer "
                         "each spell with one that beats it, or block and attack, until someone "
                         "slips up")
    ap.add_argument("--npc", nargs="?", const="medium", choices=NPC_LEVELS, metavar="LEVEL",
                    help="duel the NPC, a computer opponent, in the last seat (one wand fewer "
                         "needed; a quick-draw unless --clash or --club); LEVEL: easy, medium "
                         "(default) or hard")
    ap.add_argument("--random-order", action="store_true",
                    help="Duelling Club: the next to answer is anyone but the caster, at random "
                         "(default: the next wand in order)")
    ap.add_argument("--cast-seconds", type=float, metavar="S",
                    help="seconds each player has to cast in a duel: quick-draw (default 30), "
                         "clash (3) or each Duelling Club attack and answer (5)")
    ap.add_argument("--no-sound", action="store_true")
    ap.add_argument("--no-boxes", action="store_true", help="don't connect Magic Caster boxes")
    ap.add_argument("--no-api", action="store_true", help="don't start the control API")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")

    core = OpenCaster(boxes=not args.no_boxes, use_api=not args.no_api)
    core.set_target(args.target)
    players: dict = {}                       # address → MciPlayer (one per wand)

    def sound(address, path):
        if not args.no_sound:
            players.setdefault(address, MciPlayer(f"opencaster_{len(players)}")).play(path)

    who = core.wand_label
    _print(f"{len(core.library)} spells, {len(core.spellbook)} spellbook entries"
           + (f" - practising {core.target}" if core.target else ""))

    ev = core.events
    ev.on("status", lambda t: _print(f"[status] {t}"))
    for name in ("connecting", "connected", "ready", "disconnected"):
        ev.on(name, lambda i, n=name: isinstance(i, DeviceInfo)
              and _print(f"[{n}] {who(i.address) if i.kind == 'wand' else i.name} ({i.address})"))
    ev.on("motion", lambda a, m: _print(f"{who(a)}: " + (
        "motion calibration loaded" if m else "no motion calibration (defaults) - calibrate in the GUI")))
    ev.on("battery", lambda a, pct: _print(f"{who(a)}: battery {pct}%"))
    ev.on("window_open", lambda a, _t: _print(f"{who(a)}: casting..."))
    ev.on("tap", lambda a, held: _print(f"{who(a)}: quick tap ({held:.1f} s) ignored"))
    ev.on("timeout", lambda a, _p: _print(f"{who(a)}: gesture timeout"))
    ev.on("blocked", lambda a, _p: _print(f"{who(a)}: label the last cast first"))

    def on_cast(a, r):
        top = "  ".join(f"{m.spell} {m.score:.3f}" for m in r.ranked[:3])
        if not r.accepted:
            _print(f"{who(a)}: ✗ {r.message()}" + (f"   [{top}]" if top else ""))

    def on_spell(s):
        info = s["info"]
        _print(f"{s['wand_label']}: ✦ {s['name']}"
               + (f"  ({info.pronunciation})" if info and info.pronunciation else "")
               + f"   cast {s['count']}x" + ("  [wand firmware]" if s["source"] == "wand" else "")
               + ("  - MASTERED!" if s["mastered_now"] else ""))
        if info:
            sound(s["wand"], info.sound())

    def on_duel(d):
        phase, clash, club = d["phase"], d["mode"] == "clash", d["mode"] == "club"
        names = {i["address"]: i["label"] for i in d["player_info"]}
        score = " - ".join(str(d["scores"][a]) for a in d["players"])
        if phase == "countdown":
            what = "any battle spell" if clash else f"{names[d['starter']]} attacks first" if club \
                else d["spell"]
            prefix = "" if club else f"round {d['round']}: "
            _print(f"[duel] {prefix}{what} ... {d['count']}")
        elif phase == "racing" and club:
            who, secs = names[d["turn"]], f"{d['window_s']:.0f} s"
            if d["overtime"]:
                _print("[duel] time! finishing the last gesture...")
            elif d["chain"] and d["chain"][-1]["move"] != "attack":
                last = d["chain"][-1]
                _print(f"[duel] {names[last['player']]}: {last['spell']} {last['verb']} {last['against']}")
            if not d["overtime"]:
                _print(f"[duel] {who}: " + (f"beat {d['incoming']} or block it! ({secs})"
                                           if d["turn_kind"] == "counter" else f"attack! ({secs})"))
        elif phase == "racing" and clash:
            if d["overtime"]:
                _print("[duel] time! finishing the last gesture...")
            elif d["locked"]:
                _print(f"[duel] {', '.join(names[a] for a in d['locked'])} ready")
            else:
                _print(f"[duel] CAST! ({d['window_s']:.0f} seconds)")
        elif phase == "racing":
            _print(f"[duel] CAST {d['spell'].upper()}!")
        elif phase == "result":
            w = d["round_winner"]
            if clash:
                picks = "  vs  ".join(f"{names[a]}: {d['picks'].get(a) or '-'}" for a in d["players"])
                _print(f"[duel] {picks}  ->  {d['line']}")
            elif club:
                _print(f"[duel] {names[d['loser']]} slips up: {d['line']}")
                return                                # one rally: the finish says who won
            _print(f"[duel] {names[w] + ' wins the round' if w else d['message']}   ({score})")
        elif phase == "finished" and club:
            w, n = d["winner"], len(d["chain"])
            _print(f"[duel] {names[w] + ' wins the duel!' if w else 'No winner.'}   "
                   f"(a rally of {n} spell{'s' if n != 1 else ''})")
        elif phase == "finished":
            w = d["winner"]
            _print(f"[duel] {names[w] + ' is victorious!' if w else 'a draw'}   ({score})")
        elif phase in ("intro", "cancelled"):
            _print(f"[duel] {d['message']}")

    def maybe_duel(_info):
        wands = min(max(args.club or 2, 2), 5) - (1 if args.npc else 0)
        if (args.duel or args.clash or args.club or args.npc) and len(core.ready) >= wands \
                and not (core.duel and core.duel.active):
            core.start_duel(sorted(core.ready)[:wands] + ([NPC] if args.npc else []), args.duel or "cast",
                            "clash" if args.clash else "club" if args.club else "race",
                            "random" if args.random_order else "in_order", args.npc or "medium",
                            args.cast_seconds)

    ev.on("cast", on_cast)
    ev.on("spell", on_spell)
    ev.on("duel", on_duel)
    ev.on("ready", maybe_duel)
    try:
        asyncio.run(core.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
