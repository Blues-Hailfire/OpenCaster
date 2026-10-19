"""
Headless wand tool.

    python -m opencaster.wand scan                       list nearby wands and boxes
    python -m opencaster.wand monitor [--imu]            connect and print every event
    python -m opencaster.wand record capture.csv         save raw IMU + pad state to CSV
    python -m opencaster.wand effect success             play a built-in effect (see effect --help)
    python -m opencaster.wand effect "#ff8800"           or a solid colour

Add --address AA:BB:... to pick a wand (default: first found).
"""

import argparse
import asyncio
import csv
import sys
import time

from . import effects, protocol as p
from .device import Battery
from .manager import WandManager


def _print(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def _manager(args, **kw) -> WandManager:
    m = WandManager(auto=[args.address] if args.address else (),
                    boxes=getattr(args, "boxes", False), **kw)
    for name in ("status", "connecting", "connected", "ready", "disconnected"):
        m.events.on(name, lambda x, n=name: _print(f"[{n}]", x))
    return m


async def cmd_scan(args):
    m = WandManager(auto_connect=False)
    m.events.on("found", lambda i: _print(f"{i.kind:4}  {i.name:10}  {i.address}"))
    found = await m.scan(args.time)
    if not found:
        _print("nothing found")


async def cmd_monitor(args):
    m = _manager(args)
    rate = {"pkts": 0, "t": time.monotonic()}

    def on_notify(info, ev):
        if isinstance(ev, p.ImuBatch):
            rate["pkts"] += 1
            if args.imu:
                ax, ay, az, gx, gy, gz = ev.samples[0]
                _print(f"{info.name} imu #{ev.seq:5d} x{len(ev.samples)} "
                       f"a=({ax:+.2f} {ay:+.2f} {az:+.2f}) g=({gx:+.2f} {gy:+.2f} {gz:+.2f})")
            elif time.monotonic() - rate["t"] >= 5:
                dt = time.monotonic() - rate["t"]
                _print(f"{info.name} IMU {rate['pkts'] / dt:.1f} packets/s")
                rate.update(pkts=0, t=time.monotonic())
        elif isinstance(ev, (p.Challenge, p.Pong)):
            if args.verbose:
                _print(f"{info.name} keepalive (answered)")
        elif isinstance(ev, Battery):
            _print(f"{info.name} battery {ev.percent}%")
        else:
            _print(info.name, p.describe(ev)
                   + ("  ALL HELD" if isinstance(ev, p.Buttons) and ev.all_held else ""))

    m.events.on("notify", on_notify)
    await _run_for(m, args.seconds)


async def cmd_record(args):
    m = _manager(args)
    f = open(args.file, "w", newline="")
    w = csv.writer(f)
    w.writerow(["t", "seq", "buttons", "ax", "ay", "az", "gx", "gy", "gz"])
    state = {"mask": 0, "n": 0}
    dt = 1.0 / p.IMU_SAMPLE_RATE_HZ

    def on_notify(_info, ev):
        if isinstance(ev, p.Buttons):
            state["mask"] = ev.mask
            _print(p.describe(ev))
        elif isinstance(ev, p.ImuBatch):
            for s in ev.samples:
                w.writerow([f"{state['n'] * dt:.5f}", ev.seq, state["mask"]]
                           + [f"{v:.6f}" for v in s])
                state["n"] += 1

    m.events.on("notify", on_notify)
    m.events.on("ready", lambda _i: _print(f"recording to {args.file} - Ctrl+C to stop"))
    try:
        await _run_for(m, args.seconds)
    finally:
        f.close()
        _print(f"{state['n']} samples written")


async def cmd_effect(args):
    m = _manager(args)
    if args.name.startswith("#"):
        effect = effects.solid(args.name)
    else:
        effect = effects.BUILTIN[args.name]()

    async def play(info):
        await m.wands[info.address].play_and_wait(effect)
        await asyncio.sleep(1.0)
        m.stop()

    m.events.on("ready", lambda i: asyncio.ensure_future(play(i)))
    await m.run()


async def _run_for(m: WandManager, seconds):
    task = asyncio.create_task(m.run())
    try:
        await asyncio.wait_for(asyncio.shield(task), seconds)
    except asyncio.TimeoutError:
        pass
    finally:
        m.stop()
        await task


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="python -m opencaster.wand", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="list nearby wands and boxes")
    s.add_argument("--time", type=float, default=6.0, help="scan seconds")

    for name, fn_help in (("monitor", "print every event"), ("record", "save IMU to CSV"),
                          ("effect", "play an effect")):
        s = sub.add_parser(name, help=fn_help)
        s.add_argument("--address", help="wand MAC address")
        if name == "monitor":
            s.add_argument("--imu", action="store_true", help="print every IMU packet")
            s.add_argument("--boxes", action="store_true", help="also connect boxes")
            s.add_argument("-v", "--verbose", action="store_true", help="show keepalives")
        if name == "record":
            s.add_argument("file")
        if name == "effect":
            s.add_argument("name", help="welcome, success, fail, glow, breathe, clear, countdown, go, round_lost, duel_won, or #RRGGBB")
        if name != "effect":
            s.add_argument("--seconds", type=float, help="stop after this long")

    args = ap.parse_args(argv)
    try:
        asyncio.run(globals()[f"cmd_{args.cmd}"](args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
