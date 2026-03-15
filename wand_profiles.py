"""
wand_profiles.py — Per-wand calibration storage
================================================
Stores calibration data keyed by wand MAC address in wand_profiles.json.
Each profile contains the calibration result plus the wand's friendly name
and the timestamp of last calibration.

Usage:
    from wand_profiles import WandProfiles
    profiles = WandProfiles()
    profiles.save("E0:62:21:56:7D:FE", "MCW-7DFE", cal_data)
    cal = profiles.load("E0:62:21:56:7D:FE")   # None if unknown
    known = profiles.is_known("E0:62:21:56:7D:FE")
"""

import json
import os
from typing import Optional

PROFILES_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "wand_profiles.json")


class WandProfiles:
    def __init__(self):
        self._data: dict = self._load_file()

    def _load_file(self) -> dict:
        if os.path.isfile(PROFILES_FILE):
            try:
                with open(PROFILES_FILE, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"  [profiles] Failed to load: {e}")
        return {}

    def _save_file(self):
        with open(PROFILES_FILE, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    def is_known(self, address: str) -> bool:
        return address.upper() in self._data

    def load(self, address: str) -> Optional[dict]:
        """Return the calibration dict for this wand, or None if unknown."""
        return self._data.get(address.upper(), {}).get("calibration")

    def save(self, address: str, name: str, calibration: dict):
        """Save or update the calibration for a wand."""
        import time
        self._data[address.upper()] = {
            "name":        name,
            "last_seen":   time.strftime("%Y-%m-%dT%H:%M:%S"),
            "calibration": calibration,
        }
        self._save_file()
        print(f"  [profiles] Saved calibration for {name} ({address})")

    def all_wands(self) -> list[dict]:
        """Return list of {address, name, last_seen} for all known wands."""
        return [
            {"address": addr, "name": v["name"], "last_seen": v["last_seen"]}
            for addr, v in self._data.items()
        ]

    def last_used(self) -> Optional[dict]:
        """Return {address, name} for the most recently connected wand, or None."""
        import time as _time
        best_addr = None
        best_ts   = ""
        for addr, v in self._data.items():
            if v.get("last_connected", "") > best_ts:
                best_ts   = v["last_connected"]
                best_addr = addr
        if best_addr is None:
            return None
        return {"address": best_addr, "name": self._data[best_addr]["name"]}

    def set_last_used(self, address: str, name: str = ""):
        """Stamp the last-connected timestamp for this wand.

        Always writes the timestamp regardless of whether the wand has a
        calibration profile yet — this is what drives auto-connect on the
        next launch.  If the wand is brand new (no calibration saved) a
        minimal stub entry is created so last_used() can find it.
        """
        import time as _time
        key = address.upper()
        if key not in self._data:
            # First time seeing this wand — create a stub so auto-connect works
            # even before calibration is completed.
            self._data[key] = {
                "name":      name or key,
                "last_seen": _time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
        self._data[key]["last_connected"] = _time.strftime("%Y-%m-%dT%H:%M:%S")
        # Keep friendly name up to date if supplied
        if name:
            self._data[key]["name"] = name
        self._save_file()
