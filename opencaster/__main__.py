"""
Headless OpenCaster: connect, cast, see results in the terminal.

    python -m opencaster                 auto-connect the wands used last time (or the first found)
    python -m opencaster --target Lumos  practise one spell
    python -m opencaster --duel          duel as soon as two wands are ready
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
        phase = d["phase"]
        names = {i["address"]: i["label"] for i in d["player_info"]}
        score = " - ".join(str(d["scores"][a]) for a in d["players"])
        if phase == "countdown":
            _print(f"[duel] round {d['round']}: {d['spell']} ... {d['count']}")
        elif phase == "racing":
            _print(f"[duel] CAST {d['spell'].upper()}!")
        elif phase == "result":
            w = d["round_winner"]
            _print(f"[duel] {names[w] + ' wins the round' if w else d['message']}   ({score})")
        elif phase == "finished":
            w = d["winner"]
            _print(f"[duel] {names[w] + ' is victorious!' if w else 'a draw'}   ({score})")
        elif phase in ("intro", "cancelled"):
            _print(f"[duel] {d['message']}")

    def maybe_duel(_info):
        if args.duel and len(core.ready) >= 2 and not (core.duel and core.duel.active):
            core.start_duel(sorted(core.ready)[:2], args.duel)

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
