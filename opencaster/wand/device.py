"""
opencaster.wand.device — One BLE link to a wand (MCW) or box (MCB)
===================================================================
Event-driven: bleak delivers notifications and disconnects as callbacks on
the asyncio loop; nothing here polls.  Keepalive challenges are answered
inside the notify handler, before any listener sees them, so a busy
consumer can never make the wand drop the link.

All methods must be called on the asyncio loop thread.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Callable, Optional

from bleak import BleakClient

from . import protocol as p
from .effects import Effect, macro_effect, welcome

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeviceInfo:
    name: str
    address: str

    @property
    def kind(self) -> str:
        return "box" if self.name.startswith(p.BOX_PREFIX) else "wand"


@dataclass(frozen=True)
class Battery:
    """Battery level notification (separate characteristic)."""
    percent: int


# on_notify(device, event) — event is a protocol.Notification or Battery
NotifyHandler = Callable[["Device", object], None]


class Device:
    CONNECT_TIMEOUT = 20.0

    def __init__(self, info: DeviceInfo, on_notify: NotifyHandler, ble_device=None):
        self.info = info
        self.ble_device = ble_device        # BLEDevice from a scan: connects without re-scanning
        self._on_notify = on_notify
        self.client: Optional[BleakClient] = None
        self._lost = asyncio.Event()
        self._effect: Optional[asyncio.Task] = None
        self._tasks: set = set()        # fire-and-forget writes (pongs)

    # ── link ──────────────────────────────────────────────────────────────────

    async def connect(self):
        """Connect and subscribe to notifications."""
        loop = asyncio.get_running_loop()
        self._lost.clear()
        self.client = BleakClient(
            self.ble_device or self.info.address, timeout=self.CONNECT_TIMEOUT,
            disconnected_callback=lambda _c: loop.call_soon_threadsafe(self._lost.set))
        await self.client.connect()
        await self.client.start_notify(p.NOTIFY_UUID, self._on_raw)

    @property
    def connected(self) -> bool:
        return bool(self.client and self.client.is_connected)

    @property
    def mtu(self) -> int:
        return getattr(self.client, "mtu_size", None) or 23

    async def wait_lost(self):
        await self._lost.wait()

    async def close(self):
        """Stop effects and disconnect; safe to call on a dead link."""
        if self._effect:
            self._effect.cancel()
        for t in tuple(self._tasks):
            t.cancel()
        if self.client is None:
            return
        try:
            await self.client.disconnect()
        except Exception as e:
            log.debug("%s: disconnect failed: %s", self.info.name, e)

    # ── writes and effects ────────────────────────────────────────────────────

    async def write(self, data: bytes):
        await self.client.write_gatt_char(p.WRITE_UUID, data, response=False)

    def send(self, data: bytes):
        """Fire-and-forget write; failures (mid-disconnect) are ignored."""
        self._spawn(self._safe_write(data))

    def play(self, effect: Effect):
        """Play an effect, replacing whatever effect is running."""
        if self._effect and not self._effect.done():
            self._effect.cancel()
        if self.connected:
            self._effect = asyncio.create_task(self._run(effect))

    def play_macro(self, macro: list, variables: Optional[dict] = None):
        """Play an original-app (spellbook.json) macro."""
        self.play(macro_effect(macro, self.mtu, variables))

    async def play_and_wait(self, effect: Effect):
        """Play an effect and wait for it.  If a newer effect replaces it
        (e.g. the cast glow during the connect animation), just return."""
        self.play(effect)
        task = self._effect
        if task is None:
            return
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current and current.cancelling():
                raise                       # we are being cancelled ourselves

    async def _run(self, effect: Effect):
        try:
            for data, wait in effect:
                await self.write(data)
                if wait:
                    await asyncio.sleep(wait)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.debug("%s: effect aborted: %s", self.info.name, e)

    async def _safe_write(self, data: bytes):
        try:
            await self.write(data)
        except Exception:
            pass

    def _spawn(self, coro):
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    # ── notifications ─────────────────────────────────────────────────────────

    def _on_raw(self, _char, data: bytearray):
        event = p.parse_notification(bytes(data))
        if isinstance(event, (p.Challenge, p.Pong)):
            # 0x02 is answered too, as the original OpenCaster did on hardware.
            self.send(p.PONG)
        self._on_notify(self, event)


class Wand(Device):
    """A wand link: haptic init, connect animation, IMU stream, battery."""
    welcome_effect: Optional[Effect] = None     # connect animation (default: welcome())

    async def initialise(self):
        """Run after connect(): the wand is fully usable once this returns."""
        await asyncio.sleep(0.3)                    # settle before init writes
        for cmd in p.HW_INIT:
            await self.write(cmd)
            await asyncio.sleep(p.HW_INIT_GAP_S)
        await asyncio.sleep(0.1)
        await self.play_and_wait(self.welcome_effect or welcome())
        await self.write(p.IMU_STOP)                # reset any stale stream
        await asyncio.sleep(0.1)
        await self.write(p.IMU_START)
        try:
            await self.client.start_notify(
                p.BATTERY_UUID, lambda _c, d: self._on_notify(self, Battery(d[0])))
            level = await self.client.read_gatt_char(p.BATTERY_UUID)
            self._on_notify(self, Battery(level[0]))
        except Exception as e:
            log.debug("%s: battery unavailable: %s", self.info.name, e)

    async def close(self):
        if self.connected:
            await self._safe_write(p.IMU_STOP)
        await super().close()
