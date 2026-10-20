"""
opencaster.gui.bridge — Runs the core on a background asyncio thread
=====================================================================
Bluetooth (bleak/WinRT) stays off the Qt thread.  Core events cross into Qt
as one queued signal, event(name, args), so the GUI never polls; GUI
commands go the other way with call(), which schedules the core method on
the asyncio loop.
"""

import asyncio
import logging
import threading

from PySide6.QtCore import QObject, Signal

from ..core import OpenCaster

log = logging.getLogger(__name__)


class CoreBridge(QObject):
    event = Signal(str, object)          # (name, args tuple), delivered on the Qt thread

    def __init__(self, core: OpenCaster):
        super().__init__()
        self.core = core
        self.loop = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, name="opencaster-core", daemon=True)
        core.events.on("*", self._forward)

    def start(self):
        self._thread.start()
        self._ready.wait(5)

    def stop(self, timeout: float = 4.0):
        self.call("stop")
        self._thread.join(timeout)

    def call(self, method: str, *args):
        """Run core.<method>(*args) on the core's loop (thread-safe)."""
        if self.loop and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(getattr(self.core, method), *args)

    def _forward(self, name: str, *args):
        self.event.emit(name, args)      # Qt queues this onto the GUI thread

    def _run(self):
        try:
            asyncio.run(self._main())
        except Exception:
            log.exception("core loop crashed")

    async def _main(self):
        self.loop = asyncio.get_running_loop()
        self._ready.set()
        await self.core.run()
