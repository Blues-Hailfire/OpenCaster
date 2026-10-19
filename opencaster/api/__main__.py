"""
Control a running OpenCaster (GUI or `python -m opencaster`) from the terminal.

    python -m opencaster.api status
    python -m opencaster.api light "#FF8800" --hold 1500     every wand, 1.5 s
    python -m opencaster.api light red --wand MCW-F108       names: red green blue gold white
    python -m opencaster.api vibrate 300
    python -m opencaster.api effect success
    python -m opencaster.api spell Lumos                     play a spell's wand effect
    python -m opencaster.api clear
    python -m opencaster.api listen                          print events as they happen
"""

import argparse
import json
import sys

from .client import OpenCasterClient, OpenCasterError

NAMED = {"red": "#FF0000", "green": "#00FF00", "blue": "#0000FF", "gold": "#FFB400",
         "white": "#FFFFFF", "purple": "#9000FF", "orange": "#FF6000", "off": "#000000"}


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="python -m opencaster.api", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--token", default="")
    ap.add_argument("--wand", default="all", help="address, name or nickname (default: all)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("status", "wands", "spells", "clear"):
        sub.add_parser(name)
    s = sub.add_parser("light")
    s.add_argument("color")
    s.add_argument("--fade", type=int, default=300, help="fade ms")
    s.add_argument("--hold", type=int, default=0, help="fade out after this many ms (0 = stay on)")
    s.add_argument("--groups", help="e.g. 0,1 (0 = tip … 3 = handle)")
    s = sub.add_parser("vibrate")
    s.add_argument("ms", type=int, nargs="?", default=200)
    s = sub.add_parser("effect")
    s.add_argument("name", help="success, fail, welcome, glow, breathe, clear, countdown, go, "
                                "locked_in, round_lost, duel_won")
    s = sub.add_parser("spell")
    s.add_argument("name")
    s = sub.add_parser("listen")
    s.add_argument("--include", default="", help="imu,trail")
    args = ap.parse_args(argv)

    oc = OpenCasterClient(args.url, args.token)
    try:
        if args.cmd in ("status", "wands", "spells"):
            print(json.dumps(getattr(oc, args.cmd)(), indent=2))
        elif args.cmd == "light":
            groups = [int(g) for g in args.groups.split(",")] if args.groups else None
            print(oc.light(NAMED.get(args.color.lower(), args.color), args.wand,
                           args.fade, args.hold, groups))
        elif args.cmd == "vibrate":
            print(oc.vibrate(args.ms, args.wand))
        elif args.cmd == "clear":
            print(oc.clear(args.wand))
        elif args.cmd == "effect":
            print(oc.effect(name=args.name, wand=args.wand))
        elif args.cmd == "spell":
            print(oc.effect(spell=args.name, wand=args.wand))
        elif args.cmd == "listen":
            include = [x for x in args.include.split(",") if x]
            for ev in oc.events(include):
                print(json.dumps(ev), flush=True)
    except OpenCasterError as e:
        sys.exit(f"error: {e}")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
