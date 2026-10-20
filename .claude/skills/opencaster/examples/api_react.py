"""
React to spells from ANY program, over OpenCaster's local API (stdlib only).

OpenCaster (the GUI or `python -m opencaster`) must be running; it owns the
wands.  This program listens to the event stream and answers each spell by
flashing every wand in that spell's colour; a missed cast gets a short buzz.

    python api_react.py                    # against the running OpenCaster (127.0.0.1:8765)
    python api_react.py --url http://127.0.0.1:8765 --token SECRET
    python api_react.py --fake             # self-test: fake wands, a private core, no hardware

The API can light, buzz, play effects and stream events.  It can't start
duels or steer: embed the core for that (see embedded_core.py).
"""

import argparse
import sys
import threading
import time

from fake_wands import repo_root

sys.path.insert(0, str(repo_root()))
from opencaster.api.client import OpenCasterClient, OpenCasterError   # noqa: E402


def react(client: OpenCasterClient, limit=None, log=print):
    """Handle events until `limit` spells (None: forever)."""
    seen = 0
    for event in client.events():
        if event["type"] == "spell":
            colour = (event.get("colors") or ["#FFFFFF"])[0]
            log(f"{event['wand']['label']} cast {event['spell']} (x{event['count']}) -> flash {colour}")
            client.light(colour, hold_ms=600)
            seen += 1
            if limit and seen >= limit:
                return
        elif event["type"] == "cast" and not event["accepted"]:
            log(f"{event['wand']['label']} missed: {event['message']}")
            client.vibrate(120, wand=event["wand"]["address"])


def self_test():
    """A private core with fake wands and the API on a spare port."""
    import asyncio
    import socket
    import fake_wands

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    rig = fake_wands.install(1)
    core = fake_wands.temp_core(rig, api_port=port)
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    task = asyncio.run_coroutine_threadsafe(core.run(), loop)
    asyncio.run_coroutine_threadsafe(rig.ready(core), loop).result(20)

    client = OpenCasterClient(f"http://127.0.0.1:{port}")
    for _ in range(100):                       # wait for the API to answer
        try:
            client.status()
            break
        except OpenCasterError:
            time.sleep(0.05)
    lines = []
    listener = threading.Thread(target=react, args=(client, 2, lines.append), daemon=True)
    listener.start()
    time.sleep(0.5)                            # the event stream is connected
    wand = rig.addresses[0]
    for spell in ("Lumos", "Aguamenti"):
        asyncio.run_coroutine_threadsafe(rig.cast(wand, spell), loop).result(10)
    listener.join(10)
    time.sleep(0.3)                            # the last flash reaches the wand
    loop.call_soon_threadsafe(core.stop)       # core commands run on its loop thread
    task.result(10)
    print("\n".join(lines))
    assert len(lines) == 2 and "Lumos" in lines[0] and "Aguamenti" in lines[1], lines
    flash = (0x90, 0x00, 0xB8)                 # Aguamenti's colour, faded in over the API's 300 ms
    assert any(c == flash and ms == 300 for _g, c, ms in rig.lights(wand)), "the flash never reached the wand"
    print("api_react self-test OK")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--token", default="")
    ap.add_argument("--fake", action="store_true", help="self-test with fake wands")
    args = ap.parse_args()
    if args.fake:
        return self_test()
    client = OpenCasterClient(args.url, args.token)
    try:
        print("connected:", ", ".join(w["label"] for w in client.wands()) or "no wands yet")
        react(client)
    except OpenCasterError as e:
        sys.exit(str(e))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
