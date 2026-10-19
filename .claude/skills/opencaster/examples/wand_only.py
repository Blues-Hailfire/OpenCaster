"""
Use the wand as a plain Bluetooth controller: opencaster.wand only (needs
bleak; no spell recognition, no numpy).

  - prints every touch-pad change;
  - all four pads held: the wand glows in a colour picked by how it's tilted
    (tip up = green, level = blue, tip down = red), and buzzes once;
  - pads released: the light fades;
  - prints the IMU packet rate every few seconds.

    python wand_only.py                         # first wand found
    python wand_only.py --address AA:BB:...     # a particular wand
    python wand_only.py --fake                  # self-test with a fake wand

The manager reconnects by itself; everything runs on its asyncio loop.
"""

import argparse
import asyncio
import sys
import time

from fake_wands import repo_root

sys.path.insert(0, str(repo_root()))
from opencaster.wand import WandManager, effects, protocol as p      # noqa: E402


class Controller:
    def __init__(self, manager: WandManager, log=print):
        self.m, self.log = manager, log
        self.tilt: dict = {}                 # address -> accel along the tip (+y), in g
        self.packets, self.since = 0, time.monotonic()
        manager.events.on("notify", self.on_notify)
        manager.events.on("ready", lambda info: log(f"ready: {info.name}"))

    def on_notify(self, info, ev):
        if info.kind != "wand":
            return
        if isinstance(ev, p.ImuBatch):
            self.tilt[info.address] = ev.samples[-1][1]          # ay: + when the tip points up
            self.packets += 1
            if time.monotonic() - self.since > 3:
                self.log(f"IMU: {self.packets / (time.monotonic() - self.since):.1f} packets/s")
                self.packets, self.since = 0, time.monotonic()
        elif isinstance(ev, p.Buttons):
            self.log(f"{info.name}: {p.describe(ev)}")
            if ev.mask == 0x0F:
                ay = self.tilt.get(info.address, 0.0)
                colour = (0, 255, 60) if ay > 0.5 else (255, 30, 0) if ay < -0.5 else (0, 80, 255)
                self.m.play(effects.glow(*colour, fade_ms=200) + effects.vibrate(150), info.address)
            elif ev.mask == 0:
                self.m.play(effects.clear(), info.address)
        elif isinstance(ev, p.SpellCast):
            self.log(f"{info.name}: the wand's firmware recognised {ev.name}")


async def run_real(address):
    m = WandManager(auto=[address] if address else (), boxes=False)
    Controller(m)
    m.events.on("status", lambda text: print(f"[status] {text}"))
    print("Scanning for wands... (Ctrl+C to stop)")
    await m.run()


async def self_test():
    import fake_wands
    rig = fake_wands.install(1)
    m = WandManager(auto=rig.addresses, boxes=False)
    m.SCAN_S = 0.05
    lines = []
    Controller(m, lines.append)
    task = asyncio.create_task(m.run())
    await rig.ready(m)
    a = rig.addresses[0]
    await rig.stream(a, [(0.0, 0.9, 0.4, 0.0, 0.0, 0.0)] * 40)     # tip up
    rig.press(a, 0x0F)
    await asyncio.sleep(0.4)
    assert any(c == (0, 255, 60) for _g, c, _ms in rig.lights(a)), "tip up should glow green"
    assert any(w[:2] == bytes([0x68, 0x50]) for w in rig.writes(a)), "no buzz"
    rig.press(a, 0x00)
    await asyncio.sleep(0.1)
    assert rig.lights(a)[-1][1] == (0, 0, 0), "didn't fade out"
    m.stop()
    await asyncio.wait_for(task, 5)
    print("\n".join(lines))
    print("wand_only self-test OK")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--address", help="connect this wand (default: the first found)")
    ap.add_argument("--fake", action="store_true", help="self-test with a fake wand")
    args = ap.parse_args()
    try:
        asyncio.run(self_test() if args.fake else run_real(args.address))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
