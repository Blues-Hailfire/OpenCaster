"""
opencaster.settings — App settings shared by the GUI, headless runner and API
==============================================================================
Kept in settings.json (gitignored, per user).  Per-wand settings (colour,
nickname, calibration) live in wand_profiles.json instead.

    default_color   colour of the cast glow and the connect animation
                    for wands without their own colour ("#0000FF")
    house           Hogwarts house: fills Colovaria's house colour
    patronus        Patronus shown after Expecto Patronum ("random" or a name)
    passive_mode    keep scanning and connect every wand in range (off)
    api             local control API: enabled, host, port, token, allow_origins
"""

import copy
import json
import logging
import os
import re
from pathlib import Path

log = logging.getLogger(__name__)

# Bright, LED-friendly house colours (Colovaria's "$house_color").
HOUSES = {
    "Gryffindor": "#D41010",
    "Hufflepuff": "#FFC000",
    "Ravenclaw":  "#1E50FF",
    "Slytherin":  "#00A040",
}
NO_HOUSE_COLOR = "#D4AF37"          # gold until a house is chosen

DEFAULTS = {
    "default_color": "#0000FF",
    "house": "",
    "patronus": "random",
    "passive_mode": False,
    "api": {"enabled": True, "host": "127.0.0.1", "port": 8765, "token": "",
            "allow_origins": []},
}

_HEX = re.compile(r"#?[0-9a-fA-F]{6}")


def normalise_color(value: str) -> str:
    """'ff8800' / '#FF8800' → '#FF8800'; raises ValueError otherwise."""
    value = str(value).strip()
    if not _HEX.fullmatch(value):
        raise ValueError(f"not a #RRGGBB colour: {value!r}")
    return "#" + value.lstrip("#").upper()


def rgb(color: str) -> tuple:
    h = normalise_color(color)[1:]
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


class Settings:
    def __init__(self, path):
        self.path = Path(path)
        self.data = copy.deepcopy(DEFAULTS)
        if self.path.is_file():
            try:
                stored = json.loads(self.path.read_text(encoding="utf-8"))
                for k, v in stored.items():
                    if isinstance(v, dict) and isinstance(self.data.get(k), dict):
                        self.data[k].update(v)
                    else:
                        self.data[k] = v
            except Exception as e:
                log.warning("cannot read %s: %s", self.path, e)

    def save(self):
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as e:
            log.warning("cannot save %s: %s", self.path, e)

    def snapshot(self) -> dict:
        return copy.deepcopy(self.data)

    # ── typed accessors ───────────────────────────────────────────────────────

    @property
    def default_color(self) -> str:
        try:
            return normalise_color(self.data.get("default_color", DEFAULTS["default_color"]))
        except ValueError:
            return DEFAULTS["default_color"]

    @default_color.setter
    def default_color(self, value: str):
        self.data["default_color"] = normalise_color(value)
        self.save()

    @property
    def house(self) -> str:
        h = self.data.get("house", "")
        return h if h in HOUSES else ""

    @house.setter
    def house(self, value: str):
        self.data["house"] = value if value in HOUSES else ""
        self.save()

    @property
    def house_color(self) -> str:
        return HOUSES.get(self.house, NO_HOUSE_COLOR)

    @property
    def patronus(self) -> str:
        return self.data.get("patronus") or "random"

    @patronus.setter
    def patronus(self, value: str):
        self.data["patronus"] = value or "random"
        self.save()

    @property
    def passive_mode(self) -> bool:
        return self.data.get("passive_mode") is True

    @passive_mode.setter
    def passive_mode(self, value: bool):
        self.data["passive_mode"] = bool(value)
        self.save()

    @property
    def api(self) -> dict:
        return dict(self.data.get("api", DEFAULTS["api"]))
