"""
Embed the OpenCaster core in your own program: wands, casting, effects and
events in-process, with everything the API can't do (duels, steering).

This one is a "spell combo" toy:
  - every spell is printed with who cast it;
  - Lumos then Nox within 5 s on the same wand plays a rainbow macro on it;
  - Wingardium Leviosa turns that wand into a pointer: its aim (degrees
    right/up) is printed until its next cast.

    python embedded_core.py            # real wands (auto-connects, like the GUI)
    python embedded_core.py --fake     # self-test with two fake wands

Rules that matter here:
  - core.run() owns an asyncio loop; event handlers run ON that loop, so they
    may call core commands directly.  From any other thread use
    loop.call_soon_threadsafe(core.some_command, ...).
  - Handlers must be quick: never block or sleep in them.
  - Each wand plays one effect at a time; a new one replaces the old.
"""

import argparse
import asyncio
import sys
import time

from fake_wands import repo_root

sys.path.insert(0, str(repo_root()))
from opencaster.core import OpenCaster                 # noqa: E402

RAINBOW = [{"command": "changeled", "group": g, "color": c, "duration": 0.15}
           for c in ("FF0000", "FF8000", "FFFF00", "00FF00", "0000FF", "8000FF") for g in range(4)] \
    + [{"command": "delay", "duration": 0.2}, {"command": "clearleds"}]


class ComboApp:
    def __init__(self, core: OpenCaster, log=print):
        self.core, self.log = core, log
        self.last: dict = {}                         # wand -> (spell, time)
        self.pointing: set = set()
        core.events.on("spell", self.on_spell)
        core.events.on("aim", self.on_aim)
        core.events.on("window_open", self.on_window_open)

    def on_spell(self, s: dict):
        wand, name = s["wand"], s["name"]
        self.log(f"{s['wand_label']}: {name}")
        prev = self.last.get(wand)
        if name == "Nox" and prev and prev[0] == "Lumos" and time.monotonic() - prev[1] < 5:
            self.log("  combo! Lumos -> Nox")
            self.core.play_effect(wand, macro=RAINBOW)
        if name == "Wingardium Leviosa":
            self.pointing.add(wand)
            self.core.set_aim(wand, True, "Wingardium Leviosa")   # aim events; the wand glows gold
        self.last[wand] = (name, time.monotonic())

    def on_window_open(self, wand, _target):
        self.pointing.discard(wand)                  # the core ends the aim on a new cast

    def on_aim(self, wand, right: float, up: float):
        if wand in self.pointing:
            self.log(f"  {self.core.wand_label(wand)} points {right:+.0f} deg right, {up:+.0f} deg up")


async def run_real():
    core = OpenCaster()
    ComboApp(core)
    core.events.on("ready", lambda info: print(f"ready: {core.wand_label(info.address)}"))
    core.events.on("status", lambda text: print(f"[status] {text}"))
    print("Connecting wands... cast away (Ctrl+C to stop)")
    await core.run()


async def self_test():
    import fake_wands
    rig = fake_wands.install(2)
    core = fake_wands.temp_core(rig)
    lines = []
    ComboApp(core, lines.append)
    task = asyncio.create_task(core.run())
    await rig.ready(core)
    a, b = rig.addresses
    await rig.cast(a, "Lumos")
    await rig.cast(b, "Incendio")
    await rig.cast(a, "Nox")
    await asyncio.sleep(0.3)
    assert "  combo! Lumos -> Nox" in lines, lines
    assert any(c == (0x80, 0x00, 0xFF) for _g, c, _ms in rig.lights(a)), "no rainbow on wand A"
    await rig.cast(b, "Wingardium Leviosa")
    await rig.turn(b, right_deg=20)
    pointed = [line for line in lines if "points" in line]
    assert pointed and "+20 deg right" in pointed[-1], pointed[-3:]
    await rig.cast(b, "Aguamenti")                  # a new cast lets go of the pointer
    n = len(lines)
    await rig.turn(b, right_deg=10)
    assert not any("points" in line for line in lines[n:]), lines[n:]
    core.stop()
    await asyncio.wait_for(task, 5)
    print("\n".join(line for line in lines if "points" not in line))
    print(f"  ...and {len(pointed)} aim lines, ending: {pointed[-1].strip()}")
    print("embedded_core self-test OK")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fake", action="store_true", help="self-test with fake wands")
    args = ap.parse_args()
    try:
        asyncio.run(self_test() if args.fake else run_real())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
