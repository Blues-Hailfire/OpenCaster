"""
buzz_control.py — MCW Wand Haptic Control
==========================================
Usage:
  python buzz_control.py --buzz
  python buzz_control.py --intensity 200
  python buzz_control.py --demo
"""

import asyncio
import argparse
from bleak import BleakClient
from wand import (
    WRITE_UUID, find_wand, hw_init, hw_write, buzz_frame,
    cmd_changeled, cmd_delay,
)


async def do_buzz(client: BleakClient, intensity: int = 100,
                  color: tuple = (0, 0, 0), duration_ms: int = 300) -> None:
    r, g, b = color
    led_cmds = b""
    if any(color):
        for grp in range(4):
            led_cmds += cmd_changeled(grp, r, g, b, duration_ms)
        led_cmds += cmd_delay(duration_ms)
        for grp in range(4):
            led_cmds += cmd_changeled(grp, 0, 0, 0, 300)
    frame = buzz_frame(intensity, led_cmds)
    await hw_write(client, bytes([0x60]))
    await hw_write(client, frame)
    await asyncio.sleep(duration_ms / 1000 + 0.2)
    await hw_write(client, bytes([0x40]))


async def main(args):
    wand = await find_wand()
    async with BleakClient(wand, timeout=20.0) as client:
        await asyncio.sleep(2.0)
        await hw_init(client)

        if args.demo:
            for intensity in [50, 100, 200]:
                print(f"  intensity={intensity}")
                await do_buzz(client, intensity=intensity)
                await asyncio.sleep(1.5)
            await do_buzz(client, intensity=100, color=(255, 0, 0), duration_ms=400)
            await asyncio.sleep(1.0)
            await do_buzz(client, intensity=150, color=(0, 0, 255), duration_ms=400)
        elif args.buzz:
            await do_buzz(client, intensity=args.intensity)
        else:
            print("  Use --buzz or --demo")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="MCW Wand Haptic Control")
    p.add_argument("--buzz",      action="store_true")
    p.add_argument("--intensity", type=int, default=100, help="0-200 (default 100)")
    p.add_argument("--demo",      action="store_true")
    asyncio.run(main(p.parse_args()))
