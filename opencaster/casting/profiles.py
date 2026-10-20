"""
opencaster.casting.profiles — Per-wand motion calibration
==========================================================
wand_profiles.json, keyed by upper-case MAC address:

    {"E0:62:...": {"name": "MCW-7DFE", "last_seen": "...", "last_connected": "...",
                   "motion": {"tip_axis": [x, y, z], "gyro_bias": [x, y, z],
                              "params": {"flip_x": false}, ...}}}

Unknown keys (e.g. legacy "calibration"/"tuning" blocks) are preserved.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


class WandProfiles:
    def __init__(self, path):
        self.path = Path(path)
        self._data: dict = {}
        if self.path.is_file():
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception as e:
                log.warning("cannot read %s: %s", self.path, e)

    def _save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def _entry(self, address: str, name: str = "") -> dict:
        e = self._data.setdefault(address.upper(), {})
        e["name"] = name or e.get("name") or address.upper()
        e["last_seen"] = _now()
        return e

    def motion(self, address: str) -> Optional[dict]:
        """The tracker block {tip_axis, gyro_bias, params, ...} or None."""
        return self._data.get(address.upper(), {}).get("motion")

    def save_motion(self, address: str, name: str, motion: dict):
        self._entry(address, name)["motion"] = motion
        self._save()

    def get(self, address: str, key: str, default=None):
        return self._data.get(address.upper(), {}).get(key, default)

    def set(self, address: str, key: str, value, name: str = ""):
        """Store any per-wand value (colour, nickname, ...); None removes it."""
        entry = self._entry(address, name)
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value
        self._save()

    def auto_connect(self) -> list:
        """Wands to connect whenever they're found: those flagged
        auto_connect, else the most recently used one."""
        flagged = [a for a, e in self._data.items() if e.get("auto_connect")]
        last = self.last_used()
        return flagged or ([last] if last else [])

    def last_used(self) -> Optional[str]:
        """Address of the most recently connected wand, or None."""
        best = max(self._data.items(), key=lambda kv: kv[1].get("last_connected", ""),
                   default=None)
        return best[0] if best and best[1].get("last_connected") else None

    def set_last_used(self, address: str, name: str = ""):
        self._entry(address, name)["last_connected"] = _now()
        self._save()
