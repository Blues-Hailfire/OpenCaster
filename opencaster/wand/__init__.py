"""
opencaster.wand — Connection and communication with Magic Caster wands/boxes
=============================================================================
Self-contained: depends only on bleak.  Knows nothing about spells or GUIs.

    from opencaster.wand import WandManager, protocol, effects

    manager = WandManager(preferred="E0:62:21:56:7D:FE")
    manager.events.on("notify", lambda info, ev: print(info.name, ev))
    await manager.run()

Headless:  python -m opencaster.wand --help
"""

from . import effects, protocol
from .device import Battery, Device, DeviceInfo, Wand
from .events import Emitter
from .manager import WandManager

__all__ = ["WandManager", "Device", "Wand", "DeviceInfo", "Battery",
           "Emitter", "protocol", "effects"]
