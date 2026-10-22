"""Settings dialog (default colour, house, Patronus, media) and the per-wand dialog."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QVBoxLayout)

from .. import media_pack
from ..settings import HOUSES
from . import media_download
from . import theme as T
from .media import VideoPanel
from .widgets import ColorSwatch, section

DEFAULT_BLUE = "#0000FF"


def _chip_icon(color: str) -> QIcon:
    pm = QPixmap(14, 14)
    pm.fill(QColor(color))
    return QIcon(pm)


class SettingsDialog(QDialog):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.bridge = state.bridge
        self.setWindowTitle("Settings")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 20, 26, 20)
        lay.setSpacing(12)
        head = QLabel("✦  Settings")
        head.setFont(T.font(17, serif=True))
        head.setStyleSheet(f"color: {T.GOLD};")
        lay.addWidget(head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)
        cfg = state.config

        # default colour
        grid.addWidget(QLabel("Default wand colour"), 0, 0)
        row = QHBoxLayout()
        self.color = ColorSwatch(cfg.get("default_color", DEFAULT_BLUE), title="Default wand colour")
        self.color.picked.connect(lambda c: self.bridge.call("set_default_color", c))
        reset = QPushButton("Reset to blue")
        reset.setObjectName("Ghost")
        reset.clicked.connect(self._reset_color)
        row.addWidget(self.color)
        row.addWidget(reset)
        row.addStretch()
        grid.addLayout(row, 0, 1)
        hint = QLabel("Used for the cast glow and connect animation of wands without their "
                      "own colour.\nClick a wand at the top of the window to give it one.")
        hint.setObjectName("Dim")
        grid.addWidget(hint, 1, 1)

        # house
        grid.addWidget(QLabel("Hogwarts house"), 2, 0)
        self.house = QComboBox()
        self.house.addItem("No house", "")
        for name, colour in HOUSES.items():
            self.house.addItem(_chip_icon(colour), name, name)
        self.house.setCurrentIndex(max(0, self.house.findData(cfg.get("house", ""))))
        self.house.currentIndexChanged.connect(self._house_changed)
        grid.addWidget(self.house, 2, 1)

        # patronus
        grid.addWidget(QLabel("Patronus"), 3, 0)
        prow = QHBoxLayout()
        self.patronus = QComboBox()
        self.patronus.setMaxVisibleItems(20)
        self.patronus.addItem("Random", "random")
        for name in state.media.patronuses:
            self.patronus.addItem(name, name)
        self.patronus.setCurrentIndex(max(0, self.patronus.findData(cfg.get("patronus", "random"))))
        self.patronus.currentIndexChanged.connect(
            lambda _i: self.bridge.call("set_patronus", self.patronus.currentData()))
        self.preview_btn = QPushButton("Preview")
        self.preview_btn.clicked.connect(self._preview_patronus)
        prow.addWidget(self.patronus, 1)
        prow.addWidget(self.preview_btn)
        grid.addLayout(prow, 3, 1)
        if not state.media.patronuses:
            self.patronus.setEnabled(False)
            self.preview_btn.setEnabled(False)
            self.patronus.setToolTip("Add the media pack (media/) for Patronus videos")
        lay.addLayout(grid)
        self.video = VideoPanel()
        self.video.setMinimumHeight(220)
        self.video.hide()
        self.video.finished.connect(self.video.hide)
        lay.addWidget(self.video)

        lay.addWidget(section("Media"))
        for key, text, default in (
                ("sound", "Casting sounds", True),
                ("video", "Spell videos after a successful cast", True),
                ("mishaps", "Mishap videos after a failed cast", True),
                ("cast_loop", "Ambient wand sound while casting", True),
                ("wand_awake", "Sound when a wand connects", True)):
            box = QCheckBox(text)
            box.setChecked(state.flag(key, default))
            box.toggled.connect(lambda on, k=key: state.set_flag(k, on))
            lay.addWidget(box)
        if media_download.missing(state):
            get = QPushButton(f"Download the media pack ({media_pack.SIZE / 1e6:.0f} MB)…")
            get.setToolTip("Each spell's casting sounds and video, plus Patronus and mishap videos")
            get.clicked.connect(self._download_media)
            lay.addWidget(get, 0, Qt.AlignLeft)

        lay.addWidget(section("Control API"))
        api = cfg.get("api", {})
        url = f"http://{api.get('host', '127.0.0.1')}:{api.get('port', 8765)}/api"
        api_text = QLabel(
            (f"Other programs can light and buzz the wands and hear about casts at "
             f"<span style='color:{T.GOLD}'>{url}</span>"
             if api.get("enabled", True) else "The control API is off.")
            + "<br><span style='color:%s'>Configure it in settings.json (see README → "
              "Control API).</span>" % T.TEXT_FAINT)
        api_text.setTextFormat(Qt.RichText)
        api_text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        api_text.setWordWrap(True)
        lay.addWidget(api_text)

        close = QPushButton("Done")
        close.setObjectName("Primary")
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, Qt.AlignRight)

    def _reset_color(self):
        self.color.set_color(DEFAULT_BLUE)
        self.bridge.call("set_default_color", DEFAULT_BLUE)

    def _house_changed(self, _i):
        house = self.house.currentData()
        self.bridge.call("set_house", house)
        if house and self.state.flag("sound", True):
            self.state.sound().play(self.state.media.houses.get(house))

    def _preview_patronus(self):
        path = self.state.media.patronus(self.patronus.currentData())
        if path:
            self.video.show()
            self.video.play(path)

    def _download_media(self):
        self.accept()
        media_download.download(self.parentWidget(), self.state)

    def done(self, r):
        self.video.stop()
        super().done(r)


class WandDialog(QDialog):
    """One wand: nickname, colour, calibration, disconnect."""

    def __init__(self, state, address: str, open_calibration, parent=None):
        super().__init__(parent)
        self.state, self.address = state, address
        self.bridge = state.bridge
        info = state.wands.get(address, {})
        self.setWindowTitle(info.get("label", address))
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)
        head = QLabel(info.get("label", address))
        head.setFont(T.font(17, serif=True))
        head.setStyleSheet(f"color: {QColor(info.get('color', T.GOLD)).lighter(150).name()};")
        sub = QLabel(f"{info.get('name', '')}   ·   {address}"
                     + (f"   ·   battery {info['battery']}%" if info.get("battery") is not None else ""))
        sub.setObjectName("Dim")
        lay.addWidget(head)
        lay.addWidget(sub)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)
        grid.addWidget(QLabel("Nickname"), 0, 0)
        self.nick = QLineEdit(info.get("nickname", ""))
        self.nick.setPlaceholderText(info.get("name", "e.g. Harry"))
        grid.addWidget(self.nick, 0, 1)
        grid.addWidget(QLabel("Colour"), 1, 0)
        crow = QHBoxLayout()
        self.color = ColorSwatch(info.get("color", DEFAULT_BLUE), title="Wand colour")
        self.color.picked.connect(lambda c: self.bridge.call("set_wand_color", address, c))
        default = QPushButton("Use default colour")
        default.setObjectName("Ghost")
        default.clicked.connect(self._use_default)
        crow.addWidget(self.color)
        crow.addWidget(default)
        crow.addStretch()
        grid.addLayout(crow, 1, 1)
        lay.addLayout(grid)

        buttons = QHBoxLayout()
        cal = QPushButton("Calibrate…")
        cal.clicked.connect(lambda: (self.accept(), open_calibration(address)))
        disc = QPushButton("Disconnect")
        disc.setObjectName("Danger")
        disc.setStyleSheet(f"color: {T.RED};")
        disc.clicked.connect(self._disconnect)
        done = QPushButton("Done")
        done.setObjectName("Primary")
        done.clicked.connect(self.accept)
        buttons.addWidget(cal)
        buttons.addWidget(disc)
        buttons.addStretch()
        buttons.addWidget(done)
        lay.addLayout(buttons)

    def _use_default(self):
        self.color.set_color(self.state.config.get("default_color", DEFAULT_BLUE))
        self.bridge.call("set_wand_color", self.address, None)

    def _disconnect(self):
        self.bridge.call("disconnect", self.address)
        self.reject()

    def accept(self):
        nick = self.nick.text().strip()
        if nick != self.state.wands.get(self.address, {}).get("nickname", ""):
            self.bridge.call("set_nickname", self.address, nick)
        super().accept()
