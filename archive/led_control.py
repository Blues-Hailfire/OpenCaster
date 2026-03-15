"""
led_control.py — MCW Wand LED Control
======================================
Groups 0-3 map to individual LEDs (g0=handle, g3=tip).

Usage:
  python led_control.py --color ff0000
  python led_control.py --color 0000ff --group 2
  python led_control.py --clear
  python led_control.py --cascade ff0000
  python led_control.py --half top --color ff0000
  python led_control.py --demo
"""

import asyncio
import argparse
from bleak import BleakClient
from wand import (
    WRITE_UUID, find_wand,
    cmd_changeled, cmd_delay, build_frame,
    set_all_groups, set_group, clear_all, hex_to_rgb,
)


async def arm_and_send(client: BleakClient, frame: bytes, label: str = "") -> None:
    if label:
        print(f"  {label}")
    await client.write_gatt_char(WRITE_UUID, bytes([0x60]), response=False)
    await client.write_gatt_char(WRITE_UUID, frame, response=False)
    await asyncio.sleep(0.2)


async def run_cascade(client: BleakClient, r: int, g: int, b: int, step_ms: int = 150) -> None:
    """Cascade g3→g2→g1→g0 (tip to handle). From snoop log [7391]."""
    frame = build_frame(
        cmd_changeled(3, r, g, b, step_ms), cmd_delay(step_ms),
        cmd_changeled(2, r, g, b, step_ms), cmd_delay(step_ms),
        cmd_changeled(1, r, g, b, step_ms), cmd_delay(step_ms),
        cmd_changeled(0, r, g, b, step_ms), cmd_delay(step_ms * 2),
        cmd_changeled(3, 0, 0, 0, 400), cmd_changeled(2, 0, 0, 0, 400),
        cmd_changeled(1, 0, 0, 0, 400), cmd_changeled(0, 0, 0, 0, 400),
    )
    await arm_and_send(client, frame, f"cascade #{r:02x}{g:02x}{b:02x}")
    await asyncio.sleep((step_ms * 6 + 800) / 1000)


async def run_half(client: BleakClient, half: str, r: int, g: int, b: int) -> None:
    """Light only top (g2+g3) or bottom (g0+g1) half."""
    groups = [2, 3] if half == "top" else [0, 1]
    frame = build_frame(*[cmd_changeled(g, r, g, b, 800) for g in groups])
    await arm_and_send(client, frame, f"{half} half #{r:02x}{g:02x}{b:02x}")
    await asyncio.sleep(1.5)
    await arm_and_send(client, clear_all(), "clear")


async def run_demo(client: BleakClient) -> None:
    print("\nRunning LED demo\n")
    colors = [
        ("ff0000","red"), ("00ff00","green"), ("0000ff","blue"),
        ("ff00ff","magenta"), ("00ffff","cyan"), ("ffffff","white"),
        ("ff8800","orange"), ("ff53c1","pink"), ("e2008d","purple"),
    ]
    for hex_color, name in colors:
        r, g, b = hex_to_rgb(hex_color)
        await arm_and_send(client, set_all_groups(r, g, b, 800), name)
        await asyncio.sleep(0.9)

    await run_cascade(client, 255, 0, 0)
    await run_half(client, "top", 0, 0, 255)
    await run_half(client, "bottom", 255, 128, 0)

    # Sequential clear from snoop log [16027]
    frame = build_frame(
        cmd_changeled(0, 0, 0, 0, 350), cmd_delay(150),
        cmd_changeled(1, 0, 0, 0, 250), cmd_delay(200),
        cmd_changeled(2, 0, 0, 0, 250), cmd_delay(150),
        cmd_changeled(3, 0, 0, 0, 250),
    )
    await arm_and_send(client, frame, "sequential clear")
    await asyncio.sleep(1.2)
    print("Done.")


async def main(args):
    wand = await find_wand()
    async with BleakClient(wand, timeout=20.0) as client:
        await asyncio.sleep(2.0)
        if args.demo:
            await run_demo(client)
        elif args.cascade:
            r, g, b = hex_to_rgb(args.cascade)
            await run_cascade(client, r, g, b)
        elif args.half:
            r, g, b = hex_to_rgb(args.color or "ffffff")
            await run_half(client, args.half, r, g, b)
        elif args.clear:
            await arm_and_send(client, clear_all(), "clear")
        elif args.color:
            r, g, b = hex_to_rgb(args.color)
            if args.group is None:
                await arm_and_send(client, set_all_groups(r, g, b, args.duration), f"all #{args.color}")
            else:
                await arm_and_send(client, set_group(args.group, r, g, b, args.duration), f"group {args.group} #{args.color}")
            await asyncio.sleep(2.0)
        else:
            print("  Use --color, --clear, --cascade, --half, or --demo")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="MCW Wand LED Control")
    p.add_argument("--color",    default=None,  help="Hex color e.g. ff0000")
    p.add_argument("--group",    type=int,      default=None, help="Single group 0-3")
    p.add_argument("--duration", type=int,      default=1000, help="Duration ms")
    p.add_argument("--clear",    action="store_true")
    p.add_argument("--demo",     action="store_true")
    p.add_argument("--cascade",  default=None,  help="Hex color for tip→handle cascade")
    p.add_argument("--half",     default=None,  choices=["top","bottom"])
    asyncio.run(main(p.parse_args()))
