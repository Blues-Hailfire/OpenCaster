"""GUI-side snapshot of spells, wands and settings, kept current from core events."""

from pathlib import Path
from typing import Optional

import numpy as np
from PySide6.QtCore import QObject, QRect, QSettings, Signal
from PySide6.QtGui import QImage

from ..casting import CastSizes, spell_key
from ..casting.session import MIN_GESTURE_DEG
from ..paths import ICONS_DIR
from ..spellbook import MASTERY_CASTS
from .media import SoundPlayer


def _on_raspberry_pi() -> bool:
    try:
        return "Raspberry Pi" in Path("/proc/device-tree/model").read_text(errors="replace")
    except OSError:
        return False


# A Pi decodes video in software, so cast and duel videos start off there
# (Settings -> Media turns them back on; the spellbook's play button still works).
OFF_ON_PI = {"video", "mishaps"} if _on_raspberry_pi() else set()


def load_icon(path) -> Optional[QImage]:
    """An icon PNG cropped to its visible stroke, so every icon fills its
    card the same way."""
    img = QImage(str(path))
    if img.isNull():
        return None
    img = img.convertToFormat(QImage.Format_ARGB32)
    w, h = img.width(), img.height()
    rows = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine())
    alpha = rows[:, :w * 4].reshape(h, w, 4)[..., 3]
    ys, xs = np.nonzero(alpha > 24)
    if not len(xs):
        return img
    pad = 6
    x0, y0 = max(0, xs.min() - pad), max(0, ys.min() - pad)
    x1, y1 = min(w, xs.max() + pad + 1), min(h, ys.max() + pad + 1)
    return img.copy(QRect(int(x0), int(y0), int(x1 - x0), int(y1 - y0)))


class AppState(QObject):
    library_changed = Signal()
    progress_changed = Signal(str)          # spell name
    wands_changed = Signal()
    config_changed = Signal()               # core settings (default colour, house, patronus)

    def __init__(self, bridge):
        super().__init__()
        core = bridge.core
        self.bridge = bridge
        self.prefs = QSettings("OpenCaster", "OpenCaster")   # GUI-only preferences
        self.config = core.settings.snapshot()               # core settings
        self.sizes = CastSizes(core.cast_log.load(), MIN_GESTURE_DEG)
        self.progress = dict(core.progress.counts)
        self.wands: dict = {}               # address → wand info dict (connected or known)
        self.duel: Optional[dict] = None    # latest duel snapshot
        self._sounds: dict = {}
        self._loops: dict = {}
        self.templates: list = []
        self._by_key: dict = {}
        self.spellbook = None
        self._icon_files: dict = {}
        self._icons: dict = {}
        self.set_library(core.library.templates, core.spellbook)

    # ── spells ────────────────────────────────────────────────────────────────

    def set_library(self, templates, spellbook):
        self.templates = sorted(templates, key=lambda t: t.name.lower())
        self._by_key = {t.key: t for t in self.templates}
        self.spellbook = spellbook
        self._icon_files = ({spell_key(p.stem): p for p in ICONS_DIR.glob("*.png")}
                            if ICONS_DIR.is_dir() else {})
        self._icons = {}
        self.library_changed.emit()

    @property
    def media(self):
        return self.spellbook.media

    def template(self, name: Optional[str]):
        return self._by_key.get(spell_key(name)) if name else None

    def icon(self, name: Optional[str]) -> Optional[QImage]:
        """The spell's original gesture PNG (cropped), or None."""
        key = spell_key(name or "")
        if key not in self._icons:
            path = self._icon_files.get(key)
            self._icons[key] = load_icon(path) if path else None
        return self._icons[key]

    def info(self, name: str):
        return self.spellbook.get(name) if self.spellbook and name else None

    def color(self, name: str):
        """Card palette: the colours the spell lights the wand with, or its
        dark spellbook background colour when it has none (Nox)."""
        info = self.info(name)
        if info is None:
            return "#2a1f4a"
        return info.colors or info.color

    def count(self, name: str) -> int:
        return int(self.progress.get(spell_key(name), 0))

    def mastered(self, name: str) -> bool:
        return self.count(name) >= MASTERY_CASTS

    def set_count(self, name: str, count: int):
        self.progress[spell_key(name)] = count
        self.progress_changed.emit(name)

    # ── wands ─────────────────────────────────────────────────────────────────

    def update_wand(self, address: str, /, **fields):
        w = self.wands.setdefault(address, {"address": address, "name": address, "label": address,
                                            "color": self.config.get("default_color", "#0000FF"),
                                            "connected": False, "ready": False, "battery": None})
        w.update(fields)
        self.wands_changed.emit()

    def wand_label(self, address: str) -> str:
        return self.wands.get(address, {}).get("label") or address

    def wand_color(self, address: str) -> str:
        return self.wands.get(address, {}).get("color") or self.config.get("default_color", "#0000FF")

    def connected_wands(self) -> list:
        return [a for a, w in self.wands.items() if w.get("connected")]

    @property
    def duelling(self) -> bool:
        return bool(self.duel and self.duel["phase"] in ("intro", "countdown", "racing", "result"))

    # ── audio ─────────────────────────────────────────────────────────────────

    def sound(self, key: str = "ui") -> SoundPlayer:
        """One player per wand (and one for the UI), so two wands casting at
        once don't cut each other's sounds off."""
        if key not in self._sounds:
            self._sounds[key] = SoundPlayer()
        return self._sounds[key]

    def cast_loop(self, address: str, on: bool):
        """The ambient wand-movement loop while a wand's cast window is open."""
        if on and self.flag("cast_loop", True) and self.flag("sound", True) and self.media.cast_loop:
            if address not in self._loops:
                self._loops[address] = SoundPlayer(volume=0.35, loop=True)
            self._loops[address].play(self.media.cast_loop)
        elif address in self._loops:
            self._loops[address].stop()

    # ── preferences ───────────────────────────────────────────────────────────

    def flag(self, key: str, default: bool) -> bool:
        return self.prefs.value(key, default and key not in OFF_ON_PI, type=bool)

    def set_flag(self, key: str, value: bool):
        self.prefs.setValue(key, value)
