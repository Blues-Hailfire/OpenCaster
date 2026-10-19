"""
opencaster.wand.manager — Find wands and boxes and keep them connected
=======================================================================
WandManager supervises any number of wands and every box it finds:

  - scans with a detection callback (devices are reported as they appear);
  - auto-connects the wands in `auto` (e.g. the ones connected last time)
    whenever a scan finds them; with nothing connected or wanted it falls
    back to the first wand found, rescanning every RESCAN_S while none is
    in range;
  - each wanted wand gets its own supervised link: held until bleak reports
    a disconnect, then reconnected with backoff (WinRT's spurious
    CancelledError counts as a transient failure);
  - connects and scans run one at a time (concurrent WinRT operations tend
    to fail with "operation in progress");
  - a wand you disconnect is not auto-connected again this session;
  - each box gets its own reconnecting link (gives up after 5 failures).

Everything it learns is published on `manager.events` (an Emitter):

    "scan"          (active: bool)
    "found"         (DeviceInfo)
    "status"        (text)
    "connecting"    (DeviceInfo)
    "connected"     (DeviceInfo)              wand or box (see info.kind)
    "ready"         (DeviceInfo)              wand finished its init sequence
    "disconnected"  (DeviceInfo)
    "notify"        (DeviceInfo, event)       protocol.Notification or Battery

Run it with `await manager.run()` on one asyncio loop; every other method
must be called on that loop's thread.
"""

import asyncio
import logging
import time
from typing import Callable, Iterable, Optional

from bleak import BleakScanner

from . import protocol as p
from .device import Device, DeviceInfo, Wand
from .effects import Effect
from .events import Emitter

log = logging.getLogger(__name__)


def _cancelled_by_owner() -> bool:
    """True when the current task itself is being cancelled (shutdown),
    as opposed to WinRT raising CancelledError mid-connect."""
    task = asyncio.current_task()
    return bool(task and task.cancelling())


async def _first(*aws):
    """Wait until the first awaitable finishes; cancel the rest."""
    tasks = [asyncio.ensure_future(a) for a in aws]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        return next(iter(done))
    finally:
        for t in tasks:
            t.cancel()


class WandManager:
    SCAN_S           = 6.0
    RESCAN_S         = 10.0
    PROBE_SCAN_S     = 3.0      # short scan before retrying a wand that failed to connect
    BOX_MAX_FAILURES = 5

    def __init__(self, auto: Iterable[str] = (), auto_connect: bool = True,
                 boxes: bool = True,
                 welcome: Optional[Callable[[DeviceInfo], Effect]] = None):
        self.events = Emitter()
        self.auto = {a.upper() for a in auto}   # connect these whenever found
        self.auto_connect = auto_connect
        self.use_boxes = boxes
        self.welcome = welcome                  # connect animation per wand
        self.found: dict = {}                   # address → DeviceInfo (wands and boxes)
        self.wands: dict = {}                   # address → linked Wand
        self.boxes: dict = {}                   # address → linked box Device
        self._ble: dict = {}                    # address → BLEDevice from the latest scan
        self._seen: dict = {}                   # address → time a scan last saw it
        self._wanted: dict = {}                 # address → (DeviceInfo, drop Event)
        self._wand_tasks: dict = {}
        self._box_tasks: dict = {}
        self._dismissed: set = set()            # disconnected by hand this session
        self._scan_task: Optional[asyncio.Task] = None
        self._radio = asyncio.Lock()            # one connect or scan at a time
        self._wake = asyncio.Event()            # supervisor: re-check now
        self._stop = asyncio.Event()

    # ── public API (loop thread) ──────────────────────────────────────────────

    async def run(self):
        """Supervise until stop(): find wands, keep the wanted ones linked."""
        while not self._stop.is_set():
            if self.auto_connect and not self._wanted:
                await self.scan()
                if not self._wanted:
                    pick = self._first_found()
                    if pick is None:
                        self._status(f"No wand found - scanning again in {self.RESCAN_S:.0f} s")
                        await self._sleep(self.RESCAN_S)
                        continue
                    self.connect(pick.address)
            await self._sleep(None)
        await self._shutdown()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def connect(self, address: str):
        """Keep this wand connected (in addition to any others)."""
        address = self._known_address(address)
        self._dismissed.discard(address.upper())
        if address in self._wanted:
            return
        info = self.found.get(address) or DeviceInfo(address, address)
        drop = asyncio.Event()
        self._wanted[address] = (info, drop)
        self._wand_tasks[address] = asyncio.create_task(self._wand_loop(info, drop))

    def disconnect(self, address: str):
        """Drop this wand and don't auto-connect it again this session."""
        address = self._known_address(address)
        self._dismissed.add(address.upper())
        entry = self._wanted.pop(address, None)
        if entry:
            entry[1].set()
        self._wake.set()

    def is_wanted(self, address: str) -> bool:
        return self._known_address(address) in self._wanted

    def request_scan(self, duration: Optional[float] = None) -> asyncio.Task:
        """Scan in the background (also while wands are connected).  Only one
        scan runs at a time; a request during a scan joins it."""
        if self._scan_task is None or self._scan_task.done():
            self._scan_task = asyncio.create_task(self._scan(duration or self.SCAN_S))
        return self._scan_task

    async def scan(self, duration: Optional[float] = None) -> dict:
        """Scan for MCW/MCB devices; returns everything found so far."""
        return await asyncio.shield(self.request_scan(duration))

    def connect_box(self, info: DeviceInfo):
        if info.address not in self._box_tasks:
            self._box_tasks[info.address] = asyncio.create_task(self._box_loop(info))

    # effects ------------------------------------------------------------------

    def _targets(self, address: Optional[str]) -> list:
        if address is None:
            return list(self.wands.values())
        w = self.wands.get(self._known_address(address))
        return [w] if w else []

    def play(self, effect: Effect, address: Optional[str] = None):
        """Play on one wand, or on every connected wand when address is None."""
        for w in self._targets(address):
            w.play(effect)

    def play_macro(self, macro: list, variables: Optional[dict] = None,
                   address: Optional[str] = None):
        for w in self._targets(address):
            w.play_macro(macro, variables)

    def play_boxes_macro(self, macro: list, variables: Optional[dict] = None):
        for box in tuple(self.boxes.values()):
            box.play_macro(macro, variables)

    # ── internals ─────────────────────────────────────────────────────────────

    def _status(self, text: str):
        self.events.emit("status", text)

    def _known_address(self, address: str) -> str:
        """Match an address case-insensitively against found/wanted ones."""
        for a in (*self._wanted, *self.found):
            if a.upper() == address.upper():
                return a
        return address

    def _first_found(self) -> Optional[DeviceInfo]:
        wands = sorted((i for i in self.found.values() if i.kind == "wand"
                        and i.address.upper() not in self._dismissed), key=lambda i: i.address)
        return wands[0] if wands else None

    async def _sleep(self, seconds: Optional[float]):
        """Sleep, but wake early on connect / disconnect / stop."""
        try:
            await asyncio.wait_for(self._wake.wait(), seconds)
        except asyncio.TimeoutError:
            pass
        self._wake.clear()

    def _dispatch(self, device: Device, event):
        self.events.emit("notify", device.info, event)

    async def _scan(self, duration: float) -> dict:
        early = asyncio.Event()
        new_boxes = []

        def seen(device, adv):
            name = device.name or adv.local_name
            if not name or not name.startswith((p.WAND_PREFIX, p.BOX_PREFIX)):
                return
            info = DeviceInfo(name, device.address)
            self._ble[device.address] = device
            self._seen[device.address] = time.monotonic()
            if device.address not in self.found:
                self.found[device.address] = info
                self.events.emit("found", info)
                if info.kind == "box":
                    new_boxes.append(info)
            # every auto wand seen and nothing else to wait for: stop early
            pending = {a for a in self.auto if a not in {x.upper() for x in self._wanted}}
            if pending and pending <= {a.upper() for a in self.found}:
                early.set()

        async with self._radio:
            self.events.emit("scan", True)
            try:
                async with BleakScanner(detection_callback=seen):
                    try:
                        await asyncio.wait_for(early.wait(), duration)
                    except asyncio.TimeoutError:
                        pass
            except Exception as e:
                self._status(f"Scan failed: {e}")
            finally:
                self.events.emit("scan", False)
        for info in list(self.found.values()):
            if info.kind == "wand" and info.address.upper() in self.auto \
                    and info.address.upper() not in self._dismissed:
                self.connect(info.address)
        if self.use_boxes:
            for info in new_boxes:
                self.connect_box(info)
        return dict(self.found)

    async def _seen_since(self, address: str, since: float) -> bool:
        """Has a scan seen this wand advertising since `since`?  Runs a short
        scan if not.  A failed connect holds the radio for the whole connect
        timeout, so an unreachable wand is only retried once it shows up again."""
        if self._seen.get(address, -1e9) > since:
            return True
        await self.scan(self.PROBE_SCAN_S)
        return self._seen.get(address, -1e9) > since

    async def _wand_loop(self, info: DeviceInfo, drop: asyncio.Event):
        retry, failed_at = 2.0, None
        try:
            while not (self._stop.is_set() or drop.is_set()):
                if failed_at is not None and not await self._seen_since(info.address, failed_at):
                    retry = min(retry * 1.5, 15.0)
                    self._status(f"{info.name}: not in range - looking again in {retry:.0f} s")
                    await _first(asyncio.sleep(retry), drop.wait(), self._stop.wait())
                    continue
                linked = await self._hold(info, drop)
                if self._stop.is_set() or drop.is_set():
                    break
                failed_at = None if linked else time.monotonic()
                retry = 2.0 if linked else min(retry * 1.5, 15.0)
                self._status(f"{info.name}: link lost - reconnecting" if linked
                             else f"{info.name}: retrying in {retry:.0f} s")
                await _first(asyncio.sleep(1.0 if linked else retry), drop.wait(),
                             self._stop.wait())
        finally:
            if self._wand_tasks.get(info.address) is asyncio.current_task():
                del self._wand_tasks[info.address]

    async def _hold(self, info: DeviceInfo, drop: asyncio.Event) -> bool:
        """Connect to a wand and keep it until it drops or is dropped.
        Returns whether the link was established."""
        info = self.found.get(info.address, info)
        wand = Wand(info, self._dispatch, self._ble.get(info.address))
        if self.welcome:
            wand.welcome_effect = self.welcome(info)
        self.events.emit("connecting", info)
        try:
            async with self._radio:
                if drop.is_set() or self._stop.is_set():
                    return False
                await wand.connect()
        except asyncio.CancelledError:
            if _cancelled_by_owner():
                raise
            self._status(f"{info.name}: service discovery interrupted")
            await wand.close()
            return False
        except Exception as e:
            self._status(f"{info.name}: {e}")
            await wand.close()
            return False

        self.wands[info.address] = wand
        self.events.emit("connected", info)

        def ended():
            return wand.wait_lost(), drop.wait(), self._stop.wait()

        try:
            init = asyncio.ensure_future(wand.initialise())
            first = await _first(init, *ended())
            if first is init:
                if init.cancelled():
                    self._status(f"{info.name}: init was interrupted")
                elif init.exception() is None:
                    self.events.emit("ready", info)
                    await _first(*ended())
                else:
                    self._status(f"{info.name}: init failed - {init.exception()}")
        finally:
            self.wands.pop(info.address, None)
            await wand.close()
            self.events.emit("disconnected", info)
        return True

    async def _box_loop(self, info: DeviceInfo):
        retry, failures = 2.0, 0
        while not self._stop.is_set() and failures < self.BOX_MAX_FAILURES:
            box = Device(info, self._dispatch, self._ble.get(info.address))
            try:
                async with self._radio:
                    await box.connect()
                self.boxes[info.address] = box
                self.events.emit("connected", info)
                retry, failures = 2.0, 0
                await _first(box.wait_lost(), self._stop.wait())
            except asyncio.CancelledError:
                if _cancelled_by_owner():
                    raise
                failures += 1
            except Exception as e:
                failures += 1
                self._status(f"{info.name}: {e}")
            finally:
                if self.boxes.pop(info.address, None) is not None:
                    self.events.emit("disconnected", info)
                await box.close()
            if not self._stop.is_set():
                await _first(asyncio.sleep(retry), self._stop.wait())
                retry = min(retry * 1.5, 15.0)
        self._box_tasks.pop(info.address, None)      # a later scan may retry
        if failures >= self.BOX_MAX_FAILURES:
            self._status(f"Gave up connecting to {info.name}")

    async def _shutdown(self):
        tasks = list(self._wand_tasks.values()) + list(self._box_tasks.values())
        if self._scan_task:
            tasks.append(self._scan_task)
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
