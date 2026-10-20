"""
OpenCaster main window.  The core (wands + casting) runs on a background
asyncio thread; its events arrive here as queued Qt signals and are routed
to the pages.  Nothing in the GUI polls.
"""

import ctypes
import logging
import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QByteArray, QPointF, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QHBoxLayout, QLabel,
                               QMainWindow, QPushButton, QStackedWidget, QVBoxLayout)

from ..core import OpenCaster
from ..npc import NPC
from ..wand import protocol
from . import theme as T
from .bridge import CoreBridge
from .calibration import CalibrationDialog
from .cast_page import CastPage
from .duel_page import DuelPage
from .environment_page import EnvironmentPage
from .settings_dialog import SettingsDialog, WandDialog
from .spellbook_page import SpellbookPage
from .state import AppState
from .widgets import Backdrop, ConnectionPill, draw_star

# Per-wand session events: (address, payload)
WAND_EVENTS = {"pads", "window_open", "trail", "tap", "timeout", "cast", "blocked",
               "label_needed", "labelled", "calibrating", "calibration"}
CAST, SPELLBOOK, DUEL, ENVIRONMENT = 0, 1, 2, 3
SUPPORT_URL = "https://www.buymeacoffee.com/hailfire"
ASSETS = Path(__file__).parent / "assets"


def _svg_pixmap(name: str, size: int, dpr: float = 1.0, recolor=()) -> Optional[QPixmap]:
    """Render assets/<name> square; recolor: (old, new) colour swaps in the SVG."""
    path = ASSETS / name
    if not path.is_file():
        return None
    svg = path.read_text(encoding="utf-8")
    for old, new in recolor:
        svg = svg.replace(old, new)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pm = QPixmap(round(size * dpr), round(size * dpr))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def logo_pixmap(size: int, dpr: float = 1.0) -> QPixmap:
    """The header mark: the logo in its dark-background colours (white ring,
    gold star), so the navy ring doesn't vanish into the header."""
    pm = _svg_pixmap("opencaster-logo-1c.svg", size, dpr,
                     (("#17142A", "#FFFFFF"), ("#6B4EFF", "#FFC94A")))
    if pm is None:
        pm = QPixmap(round(size * dpr), round(size * dpr))
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        draw_star(p, QPointF(pm.width() / 2, pm.height() / 2), pm.width() * 0.4)
        p.end()
        pm.setDevicePixelRatio(dpr)
    return pm


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pm = _svg_pixmap("opencaster-icon-1c-dark.svg", size)
        if pm is not None:
            icon.addPixmap(pm)
    if not icon.isNull():
        return icon
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#1d1038"))
    p.drawRoundedRect(0, 0, 64, 64, 14, 14)
    draw_star(p, QPointF(32, 33), 22)
    p.end()
    return QIcon(pm)


def dark_title_bar(win):
    """Ask Windows 10/11 for a dark title bar (no-op elsewhere)."""
    if sys.platform != "win32":
        return
    try:
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(int(win.winId()), 20, ctypes.byref(value),
                                                   ctypes.sizeof(value))
    except Exception:
        pass


class MainWindow(QMainWindow):
    def __init__(self, bridge: CoreBridge):
        super().__init__()
        self.bridge = bridge
        self.state = AppState(bridge)
        self._boxes: set = set()
        self._pills: dict = {}
        self._found: dict = {}          # address → name of wands seen by scans
        self._calibration = None
        self._scanning = False
        self.setWindowTitle("OpenCaster")
        self.setWindowIcon(app_icon())
        self.resize(1400, 860)
        self.setMinimumSize(1100, 700)     # widened to fit the header (_fit_header)

        back = Backdrop()
        self.setCentralWidget(back)
        root = QVBoxLayout(back)
        root.setContentsMargins(24, 14, 24, 10)
        root.setSpacing(14)
        self.header = self._build_header()
        root.addLayout(self.header)
        self.pages = QStackedWidget()
        self.cast_page = CastPage(self.state, self.open_calibration)
        self.book_page = SpellbookPage(self.state, self.practise)
        self.duel_page = DuelPage(self.state)
        self.env_page = EnvironmentPage(self.state)
        for page in (self.cast_page, self.book_page, self.duel_page, self.env_page):
            self.pages.addWidget(page)
        root.addWidget(self.pages, 1)
        self.status = QLabel("Starting…")
        self.status.setObjectName("Dim")
        self.status.setFont(T.font(9))
        root.addWidget(self.status)

        geometry = self.state.prefs.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        self.state.wands_changed.connect(self._refresh_pills)
        bridge.event.connect(self._on_event)
        dark_title_bar(self)
        self._refresh_pills()

    def _build_header(self) -> QHBoxLayout:
        h = QHBoxLayout()
        h.setSpacing(8)
        mark = QLabel()
        mark.setPixmap(logo_pixmap(34, self.devicePixelRatioF()))
        h.addWidget(mark)
        logo = QLabel("OpenCaster")
        logo.setFont(T.font(21, serif=True))
        logo.setStyleSheet(f"color: {T.GOLD};")
        h.addWidget(logo)
        h.addSpacing(10)
        coffee = QPushButton("☕ Buy me a coffee")
        coffee.setToolTip(SUPPORT_URL)
        coffee.setCursor(Qt.PointingHandCursor)
        coffee.setStyleSheet("QPushButton { background: #FFDD00; color: #000000; border: 1px solid #000000;"
                             " border-radius: 8px; padding: 5px 14px; font-size: 11pt; font-weight: 600; }"
                             " QPushButton:hover { background: #FFE843; }")
        coffee.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(SUPPORT_URL)))
        h.addWidget(coffee)
        h.addSpacing(14)
        self.nav = QButtonGroup(self)
        for i, text in enumerate(("Cast", "Spellbook", "Duel", "Environment")):
            b = QPushButton(text)
            b.setObjectName("Nav")
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.setCursor(Qt.PointingHandCursor)
            self.nav.addButton(b, i)
            h.addWidget(b)
        self.nav.idClicked.connect(self._show_page)
        h.addStretch()
        self.pills = QHBoxLayout()
        self.pills.setSpacing(6)
        self.placeholder_pill = ConnectionPill()
        self.pills.addWidget(self.placeholder_pill)
        h.addLayout(self.pills)
        self.box_label = QLabel("")
        self.box_label.setObjectName("Dim")
        h.addWidget(self.box_label)
        self.wands = QComboBox()
        self.wands.setMinimumWidth(130)
        self.wands.setPlaceholderText("Found wands")
        self.wands.setToolTip("Wands in range that aren't connected")
        h.addWidget(self.wands)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setObjectName("Primary")
        self.connect_btn.setToolTip("Connect this wand too (several wands can be connected)")
        self.connect_btn.clicked.connect(self._connect_selected)
        h.addWidget(self.connect_btn)
        self.scan_btn = QPushButton("Scan")
        self.scan_btn.clicked.connect(lambda: self.bridge.call("scan"))
        h.addWidget(self.scan_btn)
        gear = QPushButton("⚙")
        gear.setToolTip("Settings: default colour, house, Patronus, media, API")
        gear.setFixedWidth(40)
        gear.clicked.connect(lambda: SettingsDialog(self.state, self).exec())
        h.addWidget(gear)
        return h

    # ── actions ───────────────────────────────────────────────────────────────

    def started(self):
        self.cast_page.start()

    def practise(self, name: str):
        self.cast_page.practise(name)
        self._show_page(CAST)

    def _show_page(self, i: int):
        self.nav.button(i).setChecked(True)
        was = self.pages.currentIndex()
        self.pages.setCurrentIndex(i)
        if (was == ENVIRONMENT) != (i == ENVIRONMENT):     # the jack-o'-lantern takes any spell
            self.bridge.call("set_free_cast", i == ENVIRONMENT)

    def _on_page(self, i: int) -> bool:
        return self.pages.currentIndex() == i

    def _connect_selected(self):
        address = self.wands.currentData()
        if address:
            self.bridge.call("connect", address)
        else:
            self._set_status("Scan for wands first")

    def open_calibration(self, address=None):
        if not address or not self.state.wands.get(address, {}).get("connected"):
            self._set_status("Connect a wand before calibrating")
            return
        self._calibration = CalibrationDialog(self.bridge, address, self.state.wand_label(address), self)
        self._calibration.finished.connect(lambda _r: setattr(self, "_calibration", None))
        self._calibration.open()

    def _open_wand(self, address: str):
        WandDialog(self.state, address, self.open_calibration, self).exec()

    def _set_status(self, text: str, log: bool = True):
        self.status.setText(text)
        if log:
            self.cast_page.add_log(text)

    def _refresh_pills(self):
        shown = {a for a, w in self.state.wands.items() if w.get("connected") or w.get("wanted")}
        for a in list(self._pills):
            if a not in shown:
                self._pills.pop(a).deleteLater()
        for a in shown:
            if a not in self._pills:
                pill = ConnectionPill(a)
                pill.clicked.connect(self._open_wand)
                self.pills.addWidget(pill)
                self._pills[a] = pill
            self._pills[a].set_wand(self.state.wands[a], compact=len(shown) > 2)
        self.placeholder_pill.setVisible(not shown)
        QTimer.singleShot(0, self._fit_header)      # once the pills' new sizes are in
        if not shown:
            self.placeholder_pill.set_state("scanning" if self._scanning else "none")
        self._refresh_found()
        title = ", ".join(self.state.wand_label(a) for a in self.state.connected_wands())
        self.setWindowTitle("OpenCaster" + (f" — {title}" if title else ""))

    def _fit_header(self):
        """Keep the window at least as wide as the header needs, so wand
        pills are never squeezed unreadable."""
        self.header.invalidate()
        m = self.centralWidget().layout().contentsMargins()
        need = max(1100, self.header.minimumSize().width() + m.left() + m.right())
        screen = self.screen().availableGeometry().width() if self.screen() else need
        self.setMinimumWidth(min(need, screen))

    def _refresh_found(self):
        current = self.wands.currentData()
        self.wands.blockSignals(True)
        self.wands.clear()
        for a, name in self._found.items():
            w = self.state.wands.get(a, {})
            if not (w.get("connected") or w.get("wanted")):
                self.wands.addItem(name, a)
                self.wands.setItemData(self.wands.count() - 1, a, Qt.ToolTipRole)
        i = self.wands.findData(current)
        self.wands.setCurrentIndex(i if i >= 0 else 0 if self.wands.count() else -1)
        self.wands.blockSignals(False)
        self.connect_btn.setEnabled(self.wands.count() > 0)

    # ── core events ───────────────────────────────────────────────────────────

    def _on_event(self, name: str, args: tuple):
        handler = getattr(self, f"_ev_{name}", None)
        if handler:
            handler(*args)
        elif name in WAND_EVENTS:
            self.cast_page.wand_event(name, *args)

    def _ev_scan(self, active: bool):
        self._scanning = active
        self.scan_btn.setEnabled(not active)
        self.scan_btn.setText("Scanning…" if active else "Scan")
        self._refresh_pills()

    def _ev_found(self, info):
        if info.kind == "wand":
            self._found[info.address] = info.name
            self._refresh_found()
        self.cast_page.add_log(f"found {info.name} ({info.address})")

    def _ev_status(self, text: str):
        self._set_status(text)

    def _ev_connecting(self, info):
        if info.kind == "wand":
            self._set_status(f"Connecting to {info.name}…")

    def _ev_connected(self, info):
        if info.kind == "box":
            self._boxes.add(info.address)
            self.box_label.setText(f"▣ {len(self._boxes)} box" + ("es" if len(self._boxes) > 1 else ""))
            self._set_status(f"Box connected: {info.name}")
            return
        self.cast_page.stage(info.address)
        self._set_status(f"Connected to {info.name} - initialising…")

    def _ev_ready(self, info):
        self._set_status(f"{self.state.wand_label(info.address)} ready - hold all four pads and cast")
        if self.state.flag("sound", True) and self.state.flag("wand_awake", True):
            self.state.sound(info.address).play(self.state.media.wand_awake)

    def _ev_disconnected(self, info):
        if info.kind == "box":
            self._boxes.discard(info.address)
            self.box_label.setText(f"▣ {len(self._boxes)} box" if self._boxes else "")
            self._set_status(f"Box disconnected: {info.name}")
            return
        self.state.cast_loop(info.address, False)
        self._set_status(f"{self.state.wand_label(info.address)} disconnected")
        if self._calibration and self._calibration.address == info.address:
            self._calibration.reject()

    def _ev_wand_info(self, info: dict):
        self.state.update_wand(info["address"], **info)
        if not info.get("connected") and not info.get("wanted"):
            self.cast_page.remove_stage(info["address"])

    def _ev_motion(self, address, motion):
        name = self.state.wand_label(address)
        self._set_status(f"{name}: motion calibration loaded" if motion else
                         f"{name}: not calibrated yet - Calibrate for best accuracy")

    def _ev_battery(self, address, pct: int):
        self.state.update_wand(address, battery=pct)

    def _ev_imu(self, address, sample):
        self.cast_page.on_imu(address, sample)

    def _ev_log(self, info, event):
        self.cast_page.add_log(f"{info.name}: {protocol.describe(event)}")

    def _ev_window_open(self, address, target):
        if address == NPC:                      # the computer opponent lives on the duel page
            self.duel_page.on_window_open(address, target)
            return
        if self.state.duelling:
            self.duel_page.on_window_open(address, target)
        elif self._on_page(SPELLBOOK):
            self._show_page(CAST)
        elif self._on_page(ENVIRONMENT):
            self.env_page.on_window_open(address)
        self.cast_page.wand_event("window_open", address, target)

    def _ev_trail(self, address, trail):
        if address == NPC:
            self.duel_page.on_trail(address, trail)
            return
        self.cast_page.wand_event("trail", address, trail)
        if self.state.duelling:
            self.duel_page.on_trail(address, trail)

    def _ev_cast(self, address, result):
        if address == NPC:
            self.duel_page.on_cast(address, result)
            return
        self.cast_page.wand_event("cast", address, result)
        if self.state.duelling:
            self.duel_page.on_cast(address, result)
        elif self._on_page(ENVIRONMENT):
            self.env_page.on_cast(address, result)

    def _ev_aim(self, address, right, up):
        if self._on_page(ENVIRONMENT):
            self.env_page.on_aim(address, right, up)

    def _ev_spell(self, s: dict):
        if s["wand"] == NPC:                    # its spell is heard, and counts for nothing
            if self.state.flag("sound", True) and s["info"]:
                self.state.sound(NPC).play(s["info"].sound())
            self.cast_page.add_log(f"✦ {s['name']}  ({s['wand_label']})", T.VIOLET)
            return
        # Payoff videos only where they can be seen: the cast page, outside a duel.
        self.cast_page.on_spell(s, media=not self.state.duelling and self._on_page(CAST))
        if self._on_page(ENVIRONMENT) and not self.state.duelling:
            self.env_page.on_spell(s)
        self.state.set_count(s["name"], s["count"])
        self.cast_page.add_log(f"✦ {s['name']}  ({s['wand_label']})"
                               + ("  - wand firmware" if s["source"] == "wand" else ""), T.VIOLET)

    def _ev_labelled(self, address, payload):
        self._set_status(self.cast_page.wand_event("labelled", address, payload), log=False)

    def _ev_calibration(self, address, state: dict):
        if self._calibration and self._calibration.address == address:
            self._calibration.show_state(state)

    def _ev_duel(self, snap: dict):
        was_active = self.state.duelling
        self.state.duel = snap
        if self.state.duelling and not was_active:
            self._show_page(DUEL)
        self.duel_page.on_duel(snap)
        if snap["phase"] in ("finished", "cancelled"):
            self.duel_page._refresh_setup()

    def _ev_settings(self, cfg: dict):
        self.state.config = cfg
        self.state.config_changed.emit()

    def _ev_library(self, payload):
        templates, spellbook = payload
        self.state.set_library(templates, spellbook)
        with_fx = sum(1 for t in templates if (i := spellbook.get(t.name)) and i.wand_macros)
        with_snd = sum(1 for t in templates if (i := spellbook.get(t.name)) and i.sounds)
        self._set_status(f"Spells loaded: {len(templates)} - {with_fx} with wand effects, "
                         f"{with_snd} with sounds")

    def closeEvent(self, e):
        self.state.prefs.setValue("geometry", self.saveGeometry())
        for st in self.cast_page.stages.values():
            st.stop_video()
        self.book_page.video.stop()
        self.duel_page._stop_video()
        self.bridge.stop()
        super().closeEvent(e)


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if sys.platform == "win32":     # own taskbar icon instead of python.exe's
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OpenCaster.GUI")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("OpenCaster")
    app.setFont(T.font(10))
    app.setStyleSheet(T.STYLESHEET)
    bridge = CoreBridge(OpenCaster())
    win = MainWindow(bridge)
    win.show()
    bridge.start()
    win.started()
    return app.exec()
