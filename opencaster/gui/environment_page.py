"""
Environment page: every spell cast from any wand acts on an enchanted
jack-o'-lantern (opencaster.environment for the rules, .pumpkin for the
drawing).
While this page is open the core casts freely: no practice spell and no
cast labelling.
"""

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
                               QVBoxLayout, QWidget)

from ..casting import spell_key
from ..environment import LEVITATING, Outcome
from ..settings import HOUSES
from . import theme as T
from .pumpkin import PumpkinScene
from .widgets import card

TRY = ("Nox – only the candle glows",
       "Aguamenti, then Glacius, then Incendio",
       "Incarcerous, then Incendio",
       "Bombarda, then Reparo",
       "Protego, then Bombarda",
       "Wingardium Leviosa – then steer it with your wand",
       "Ventus, Orchideous, Herbivicus",
       "Cantis, then Silencio")


class EnvironmentPage(QWidget):
    HISTORY_MAX = 40

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self._steer = None               # the wand steering the floating pumpkin
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(16)
        self.scene = PumpkinScene()
        lay.addWidget(self.scene, 1)

        side = QVBoxLayout()
        side.setSpacing(14)
        intro, il = card("Environment")
        title = QLabel("The Jack-o'-Lantern")
        title.setFont(T.font(19, serif=True))
        title.setStyleSheet(f"color: {T.GOLD};")
        text = QLabel("Every spell you cast acts on the jack-o'-lantern: douse its candle, fill "
                      "it, freeze it, set it ablaze, knock it over, smash it, mend it.  Spells "
                      "play off each other – water douses fire, fire burns through bindings, a "
                      "shield blocks the next battle spell.")
        text.setObjectName("Dim")
        text.setWordWrap(True)
        note = QLabel("Any wand can cast here.  The practice spell and cast labelling are paused "
                      "while this page is open.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {T.TEXT_FAINT};")
        note.setFont(T.font(9))
        for w in (title, text, note):
            il.addWidget(w)
        side.addWidget(intro)

        log, ll = card("What happened")
        self.history = QListWidget()
        self.history.setWordWrap(True)
        self.history.setFocusPolicy(Qt.NoFocus)
        ll.addWidget(self.history, 1)
        side.addWidget(log, 1)

        ideas, tl = card("Try")
        tips = QLabel("\n".join(f"·  {t}" for t in TRY))
        tips.setObjectName("Dim")
        tips.setWordWrap(True)
        tl.addWidget(tips)
        reset = QPushButton("Reset the jack-o'-lantern")
        reset.clicked.connect(self.reset)
        tl.addWidget(reset)
        side.addWidget(ideas)

        holder = QWidget()
        holder.setLayout(side)
        holder.setFixedWidth(310)
        lay.addWidget(holder)

    # ── actions ───────────────────────────────────────────────────────────────

    def reset(self):
        self._stop_steer(drop=False)
        self.scene.reset()
        self.scene.say("A fresh jack-o'-lantern", "cast any spell at it")
        self._log("Reset", "a fresh jack-o'-lantern", T.TEXT_DIM)

    def _log(self, spell: str, text: str, colour: str):
        item = QListWidgetItem(f"{datetime.now().strftime('%H:%M')}   ✦ {spell}\n{text}")
        item.setForeground(QColor(colour))
        self.history.insertItem(0, item)
        while self.history.count() > self.HISTORY_MAX:
            self.history.takeItem(self.history.count() - 1)

    # ── core events (only while the page is shown) ────────────────────────────

    def on_spell(self, s: dict):
        model = self.scene.model
        model.house_color = HOUSES.get(self.state.config.get("house", ""))
        before = {"contents": model.contents, "pose": model.pose}
        out = model.cast(s["name"])
        if spell_key(out.spell) == "wingardiumleviosa" and model.pose == LEVITATING and not out.blocked \
                and s["wand"] in self.state.connected_wands():
            self._start_steer(s["wand"])
            out = Outcome(out.spell, out.text + " – move your wand to steer it", out.fx, out.blocked)
        elif self._steer and (model.pose != LEVITATING or model.movable):
            self._stop_steer()             # knocked down, bound or glued; frozen, it hangs there for now
        self.scene.apply(out, before)
        who = f"   ({s['wand_label']})" if len(self.state.connected_wands()) > 1 else ""
        self._log(out.spell + who, out.text, T.TEXT_FAINT if out.blocked else T.VIOLET)

    def on_aim(self, address: str, right: float, up: float):
        if address == self._steer:
            self.scene.steer_to(right, up)

    def _start_steer(self, address: str):
        """Wingardium Leviosa: the casting wand steers the floating pumpkin."""
        if self._steer and self._steer != address:
            self.state.bridge.call("set_aim", self._steer, False)
        self._steer = address
        self.state.bridge.call("set_aim", address, True, "Wingardium Leviosa")    # the wand glows meanwhile
        info = self.state.info("Wingardium Leviosa")              # and so does the pumpkin, to match
        self.scene.start_steer(info.colors[0] if info and info.colors else self.state.wand_color(address))

    def _stop_steer(self, drop: bool = True):
        """The wand lets go of the charm: the pumpkin drops (Immobulus keeps
        it hanging in the air until that wears off)."""
        steering, self._steer = self._steer, None
        if steering:
            self.state.bridge.call("set_aim", steering, False)
        self.scene.stop_steer()
        out = self.scene.model.let_go() if steering and drop else None
        if out:
            self.scene.apply(out, {"contents": self.scene.model.contents, "pose": LEVITATING})
            self._log(out.spell, out.text, T.TEXT_DIM)

    def hideEvent(self, e):
        self._stop_steer()
        super().hideEvent(e)

    def on_window_open(self, address: str):
        if address == self._steer:            # a new cast lets go of the charm: it drops
            self._stop_steer()
        self.scene.say(f"{self.state.wand_label(address)} is casting…")

    def on_cast(self, address: str, r):
        if not r.accepted:
            self.scene.say(f"✗  {r.message()}", f"{self.state.wand_label(address)}'s spell fizzles")
            self.scene.fizzle()
