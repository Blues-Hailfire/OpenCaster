"""
opencaster.wand.events — Minimal synchronous event emitter
===========================================================
Handlers run in the emitting thread (for the wand package that is always
the asyncio loop thread).  A handler registered for "*" receives
(name, *args) for every event, which is how bridges and loggers listen.
"""

import logging

log = logging.getLogger(__name__)


class Emitter:
    def __init__(self):
        self._handlers: dict = {}

    def on(self, name: str, handler):
        self._handlers.setdefault(name, []).append(handler)
        return handler

    def off(self, name: str, handler):
        try:
            self._handlers.get(name, []).remove(handler)
        except ValueError:
            pass

    def emit(self, name: str, *args):
        for h in tuple(self._handlers.get(name, ())):
            self._call(h, name, args)
        for h in tuple(self._handlers.get("*", ())):
            self._call(h, name, (name,) + args)

    @staticmethod
    def _call(handler, name, args):
        # One faulty listener must not break a BLE callback or the others.
        try:
            handler(*args)
        except Exception:
            log.exception("handler for %r failed", name)
