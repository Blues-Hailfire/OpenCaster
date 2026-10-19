"""
Fake Magic Caster wands: test OpenCaster programs without hardware.

    import fake_wands
    rig = fake_wands.install(2)                  # BEFORE OpenCaster / WandManager run
    core = fake_wands.temp_core(rig)             # OpenCaster on temp files, no boxes
    task = asyncio.create_task(core.run())
    await rig.ready(core)
    await rig.cast(rig.addresses[0], "Lumos")    # pads, a real gyro gesture, release
    rig.writes(rig.addresses[0])                 # every byte written to that wand

The fakes sit at the Bleak level: scans "find" the fake wands, and what the
rig sends goes through the real notification parser, CastSession, tracker,
matcher and effects – the whole pipeline a real wand drives.  `cast` draws
the spell's template with synthesised gyro data (all 52 spells recognise).

It depends on OpenCaster internals – it replaces
opencaster.wand.manager.BleakScanner and opencaster.wand.manager.Wand – so
if those move, update install().  ASCII output only (Windows consoles).
"""

import asyncio
import json
import math
import os
import struct
import sys
import tempfile
from pathlib import Path


def repo_root() -> Path:
    """The OpenCaster checkout: $OPENCASTER_ROOT, or the repo this skill sits in."""
    env = os.environ.get("OPENCASTER_ROOT")
    root = Path(env) if env else Path(__file__).resolve().parents[4]
    if not (root / "opencaster" / "__init__.py").exists():
        sys.exit(f"OpenCaster not found at {root} - set OPENCASTER_ROOT to the checkout")
    return root


sys.path.insert(0, str(repo_root()))

import opencaster.wand.manager as _manager            # noqa: E402
from opencaster.casting import SpellLibrary          # noqa: E402
from opencaster.casting.shapes import resample       # noqa: E402
from opencaster.paths import SPELLS_DIR              # noqa: E402
from opencaster.wand import protocol as p            # noqa: E402
from opencaster.wand.device import Battery, Wand     # noqa: E402

RATE = 220.0                       # IMU samples per second, as on the wand
PER_PACKET = 19                    # samples per BLE packet, as on the wand
STILL = (0.0, 0.0, 1.0, 0.0, 0.0, 0.0)   # level, not moving: (ax, ay, az, gx, gy, gz)


class FakeClient:
    """Stands in for bleak's BleakClient on one fake wand."""
    is_connected = True
    mtu_size = 23

    def __init__(self):
        self.writes: list = []
        self._notify = None

    async def write_gatt_char(self, _uuid, data, response=False):
        self.writes.append(bytes(data))

    async def start_notify(self, uuid, callback):
        if uuid == p.NOTIFY_UUID:
            self._notify = callback

    async def read_gatt_char(self, _uuid):
        return bytearray([80])                # battery 80 %

    async def disconnect(self):
        self.is_connected = False

    def push(self, data: bytes):
        """The wand sends a notification."""
        if self._notify:
            self._notify(None, bytearray(data))


class _Dev:
    def __init__(self, address, name):
        self.address, self.name = address, name


class _Adv:
    local_name = None


class Rig:
    def __init__(self, wands: dict, quick: bool):
        self.wands = dict(wands)              # address -> name
        self.quick = quick
        self.clients: dict = {}               # address -> FakeClient (the latest connection)
        self._seq: dict = {}
        self._library = None

    @property
    def addresses(self) -> list:
        return list(self.wands)

    # -- inspecting what the program sent ---------------------------------------

    def writes(self, address: str) -> list:
        return self.clients[address].writes if address in self.clients else []

    def lights(self, address: str) -> list:
        """(group, (r, g, b), ms) for every changeled the wand was sent, in
        order.  Frames are 0x68 + commands: changeled 0x22 (7 bytes), delay
        0x10 and buzz 0x50 (3 bytes)."""
        out = []
        for w in self.writes(address):
            if w[:1] != b"\x68":
                continue
            i = 1
            while i < len(w):
                if w[i] == 0x22 and i + 7 <= len(w):
                    out.append((w[i + 1], tuple(w[i + 2:i + 5]), w[i + 5] | (w[i + 6] << 8)))
                    i += 7
                elif w[i] in (0x10, 0x50) and i + 3 <= len(w):
                    i += 3
                else:
                    break
        return out

    # -- acting as the wand -------------------------------------------------------

    def press(self, address: str, mask: int):
        """Touch pads: bit 0..3 = pads 1..4 (0x0F all held, 0 released)."""
        self.clients[address].push(bytes([p.Resp.BUTTON_PAYLOAD, mask & 0x0F]))

    def imu(self, address: str, samples):
        """Send IMU samples (ax, ay, az in g; gx, gy, gz in rad/s), packed
        like the wand: int16 counts, gyro before accel, 19 per packet."""
        samples = list(samples)
        for i in range(0, len(samples), PER_PACKET):
            chunk = samples[i:i + PER_PACKET]
            seq = self._seq.get(address, 0)
            self._seq[address] = (seq + 1) & 0xFFFF
            body = b"".join(struct.pack("<hhhhhh", *(_count(v, p.IMU_GYRO_SCALE) for v in s[3:]),
                                        *(_count(v, p.IMU_ACCEL_SCALE) for v in s[:3])) for s in chunk)
            self.clients[address].push(bytes([p.Resp.IMU_PAYLOAD, seq & 0xFF, seq >> 8, len(chunk)]) + body)

    async def stream(self, address: str, samples):
        """Send IMU samples in real time (packets ~11.6 a second)."""
        samples = list(samples)
        for i in range(0, len(samples), PER_PACKET):
            self.imu(address, samples[i:i + PER_PACKET])
            await asyncio.sleep(PER_PACKET / RATE)

    async def idle(self, address: str, seconds: float = 0.5):
        await self.stream(address, [STILL] * int(seconds * RATE))

    async def cast(self, address: str, spell: str, size_deg: float = 40.0, seconds: float = 1.4):
        """Hold all four pads, draw `spell`'s shape with the wand, release."""
        if self._library is None:
            self._library = SpellLibrary(SPELLS_DIR)
        template = self._library.get(spell)
        if template is None:
            raise KeyError(f"no spell template {spell!r}")
        self.press(address, 0x0F)
        await self.idle(address, 0.1)
        await self.stream(address, gesture(template.outline, size_deg, seconds))
        await self.idle(address, 0.1)
        self.press(address, 0x00)
        await asyncio.sleep(0.05)

    async def turn(self, address: str, right_deg: float = 0.0, up_deg: float = 0.0, seconds: float = 0.5):
        """Point the wand this many degrees right/up (outside a cast: aiming)."""
        n = max(1, int(seconds * RATE))
        wz, wx = -math.radians(right_deg) / seconds, math.radians(up_deg) / seconds
        await self.stream(address, [(0.0, 0.0, 1.0, wx, 0.0, wz)] * n)

    def firmware_spell(self, address: str, name: str):
        """The wand's own firmware recognised a spell (0x24 broadcast)."""
        raw = name.encode()
        self.clients[address].push(bytes([p.Resp.SPELL_CAST, 0, 0, len(raw)]) + raw)

    async def ready(self, core_or_manager, timeout: float = 15.0):
        """Wait until every fake wand is connected and ready."""
        ready = getattr(core_or_manager, "ready", None)
        manager = getattr(core_or_manager, "manager", core_or_manager)
        for _ in range(int(timeout / 0.02)):
            done = ready >= set(self.wands) if ready is not None else set(manager.wands) >= set(self.wands)
            if done and all(a in self.clients for a in self.wands):
                await asyncio.sleep(0.05)
                return
            await asyncio.sleep(0.02)
        raise TimeoutError(f"fake wands not ready: {sorted(set(self.wands) - set(self.clients))}")


def _count(value: float, scale: float) -> int:
    return max(-32768, min(32767, int(round(value / scale))))


def gesture(outline, size_deg: float = 40.0, seconds: float = 1.4) -> list:
    """IMU samples that move a level wand's tip (+y) along an outline
    (y up, about -1..1), size_deg across, over `seconds`."""
    n = max(2, int(seconds * RATE))
    pts = resample(outline, n + 1) * (size_deg / 2)
    dt = 1.0 / RATE
    return [(0.0, 0.0, 1.0, math.radians(y1 - y0) / dt, 0.0, -math.radians(x1 - x0) / dt)
            for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:])]


def install(wands=1, quick: bool = True) -> Rig:
    """Make scans find fake wands and connect to them.  `wands`: a count, or
    {address: name}.  quick skips the 3 s connect animation and init writes."""
    if isinstance(wands, int):
        wands = {f"AA:00:00:00:00:{i + 1:02X}": f"MCW-{i + 1:04d}" for i in range(wands)}
    rig = Rig(wands, quick)

    class FakeScanner:
        def __init__(self, detection_callback):
            self.cb = detection_callback

        async def __aenter__(self):
            for address, name in rig.wands.items():
                self.cb(_Dev(address, name), _Adv())
            return self

        async def __aexit__(self, *exc):
            pass

    class FakeWand(Wand):
        async def connect(self):
            self._lost.clear()
            self.client = FakeClient()
            await self.client.start_notify(p.NOTIFY_UUID, self._on_raw)
            rig.clients[self.info.address] = self.client

        async def initialise(self):
            if not rig.quick:
                return await super().initialise()
            await self.write(p.IMU_STOP)
            await self.write(p.IMU_START)
            self._on_notify(self, Battery(80))

        async def close(self):
            await super().close()            # rig.clients keeps its writes for inspection

    _manager.BleakScanner = FakeScanner
    _manager.Wand = FakeWand
    return rig


def temp_core(rig: Rig, api_port=None, **kw):
    """An OpenCaster core that auto-connects the rig's wands and keeps its
    files (profiles, progress, casts, settings) in a temp folder, so tests
    never touch your real ones.  api_port: start the control API there."""
    from opencaster.core import OpenCaster
    tmp = Path(tempfile.mkdtemp(prefix="opencaster_test_"))
    (tmp / "profiles.json").write_text(json.dumps(
        {a: {"name": n, "auto_connect": True} for a, n in rig.wands.items()}), encoding="utf-8")
    settings = {"api": {"enabled": api_port is not None, "host": "127.0.0.1", "port": api_port or 8765}}
    (tmp / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    core = OpenCaster(casts_file=tmp / "casts.jsonl", profiles_file=tmp / "profiles.json",
                      progress_file=tmp / "progress.json", settings_file=tmp / "settings.json",
                      boxes=False, use_api=api_port is not None, **kw)
    core.manager.SCAN_S = 0.05
    core.temp_dir = tmp
    return core


async def _self_test():
    """python fake_wands.py: two fake wands, casts through the real pipeline."""
    rig = install(2)
    core = temp_core(rig)
    spells, casts = [], []
    core.events.on("spell", lambda s: spells.append((s["wand"], s["name"])))
    core.events.on("cast", lambda a, r: casts.append((a, r.accepted, r.message())))
    task = asyncio.create_task(core.run())
    await rig.ready(core)
    a, b = rig.addresses
    await rig.cast(a, "Lumos")
    await rig.cast(b, "Incendio")
    rig.firmware_spell(a, "Protego")
    await asyncio.sleep(0.2)
    assert spells == [(a, "Lumos"), (b, "Incendio"), (a, "Protego")], (spells, casts)
    assert any(c == (255, 200, 100) for _g, c, _ms in rig.lights(a)), "no Lumos light on the wand"
    core.stop()
    await asyncio.wait_for(task, 5)
    print("fake wands OK:", ", ".join(f"{n} on {w[-2:]}" for w, n in spells))


if __name__ == "__main__":
    asyncio.run(_self_test())
