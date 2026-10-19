"""
Duel page: set up a wizard's duel between two wands and watch it play out.

Both wizards get the same spell each round; the first to cast it wins the
round, best of five.  The rules live in opencaster.duel (run by the core);
this page renders its snapshots: countdown, live trails, round results, the
duel intro / payoff / victory videos and a confetti finish.
"""

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QStackedLayout, QStackedWidget, QVBoxLayout, QWidget)

from . import theme as T
from .media import VideoPanel
from .trail import TrailCanvas
from .widgets import Animator, ColorSwatch, Particles, card, paint_spell_art

POOL_NAMES = {"cast": "Spells you've cast", "all": "All spells", "Beginner": "Beginner spells",
              "Intermediate": "Intermediate spells", "Expert": "Expert spells"}


class ArenaCenter(QWidget):
    """The round's spell card with the countdown, banners and particles."""

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.spell = None
        self.big = ""                    # "3", "2", "1", "Cast!"
        self.big_color = T.GOLD
        self.banner, self.banner_color = "", T.TEXT
        self.sub = ""
        self._pop = 1.0                  # countdown pop animation 0 → 1
        self._anim = None
        self.fx = Particles()
        self.animator = Animator(self)
        self.setMinimumSize(300, 360)

    def set_spell(self, name):
        self.spell = name
        self.update()

    def set_big(self, text: str, color: str = T.GOLD):
        self.big, self.big_color = text, color
        if self._anim:
            self._anim.stop()
        self._anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=450)
        self._anim.setEasingCurve(QEasingCurve.OutBack)
        self._anim.valueChanged.connect(lambda v: (setattr(self, "_pop", float(v)), self.update()))
        self._anim.start()

    def set_banner(self, text: str, color: str = T.TEXT, sub: str = ""):
        self.banner, self.banner_color, self.sub = text, color, sub
        self.update()

    def burst(self, colors):
        self.fx.burst(self.width() / 2, self.height() * 0.42, list(colors) + ["#FFFFFF"],
                      n=110, speed=self.width() * 0.7)
        self.animator.kick()

    def confetti(self, colors):
        self.fx.confetti(self.width(), list(colors), n=180)
        self.animator.kick()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.fx.step(self.animator.dt(self.fx.active))
        r = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        card_w = min(r.width() * 0.8, r.height() * 0.62)
        card_r = QRectF(r.center().x() - card_w / 2, r.top() + 10, card_w, card_w * 1.25)
        if self.spell:
            t = self.state.template(self.spell)
            info = self.state.info(self.spell)
            glyph = card_r.adjusted(card_w * 0.12, card_w * 0.1, -card_w * 0.12, -card_w * 0.42)
            paint_spell_art(p, card_r, self.state.color(self.spell), t.outline if t else None,
                            self.spell, 20, glyph, 3.4, T.qcolor("#ffffff", 0.12),
                            self.state.icon(self.spell))
            p.setPen(QColor("#FFFFFF"))
            p.setFont(T.font(max(16.0, card_w / 11), serif=True))
            p.drawText(QRectF(card_r.left(), card_r.bottom() - card_w * 0.38, card_r.width(),
                              card_w * 0.2), Qt.AlignCenter | Qt.TextWordWrap, self.spell)
            if info and info.pronunciation:
                p.setPen(T.qcolor("#FFFFFF", 0.75))
                p.setFont(T.font(max(9.0, card_w / 28), italic=True))
                p.drawText(QRectF(card_r.left(), card_r.bottom() - card_w * 0.18, card_r.width(),
                                  card_w * 0.12), Qt.AlignCenter, info.pronunciation)
        if self.big:
            k = self._pop
            size = max(30.0, card_w / 3.2) * (0.6 + 0.4 * k)
            p.setFont(T.font(size, serif=True, bold=True))
            col = T.qcolor(self.big_color, min(1.0, 0.3 + k))
            rect = QRectF(r.left(), card_r.top() + card_r.height() * 0.18, r.width(), size * 1.6)
            p.setPen(QPen(T.qcolor("#000000", 0.55)))
            p.drawText(rect.translated(2, 3), Qt.AlignCenter, self.big)
            p.setPen(col)
            p.drawText(rect, Qt.AlignCenter, self.big)
        if self.banner:
            p.setPen(QColor(self.banner_color))
            p.setFont(T.font(20, serif=True))
            p.drawText(QRectF(r.left(), card_r.bottom() + 8, r.width(), 36), Qt.AlignCenter,
                       self.banner)
        if self.sub:
            p.setPen(T.qcolor(T.TEXT_DIM))
            p.setFont(T.font(10, italic=True))
            p.drawText(QRectF(r.left(), card_r.bottom() + 42, r.width(), 22), Qt.AlignCenter, self.sub)
        if self.fx.active:
            self.fx.paint(p)
            self.animator.kick()


class Pips(QWidget):
    """●●○ round wins."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.wins, self.needed, self.color = 0, 3, T.GOLD
        self.setFixedSize(90, 22)

    def set_state(self, wins: int, needed: int, color: str):
        self.wins, self.needed, self.color = wins, needed, color
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        for i in range(self.needed):
            c = QPointF(11 + i * 26, 11)
            if i < self.wins:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(self.color))
            else:
                p.setPen(QPen(T.qcolor("#FFFFFF", 0.3), 1.5))
                p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, 8, 8)


class PlayerPanel(QFrame):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.address = None
        self.setObjectName("Stage")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        head = QHBoxLayout()
        self.bar = QFrame()
        self.bar.setFixedSize(5, 34)
        self.name = QLabel("")
        self.name.setFont(T.font(17, serif=True))
        self.pips = Pips()
        head.addWidget(self.bar)
        head.addWidget(self.name)
        head.addStretch()
        head.addWidget(self.pips)
        lay.addLayout(head)
        self.canvas = TrailCanvas(state.sizes.typical)
        self.canvas.hint = ""
        lay.addWidget(self.canvas, 1)

    def set_player(self, info: dict, wins: int, needed: int):
        self.address = info["address"]
        color = info.get("color", T.GOLD)
        self.bar.setStyleSheet(f"background: {color}; border-radius: 2px;")
        self.name.setText(info.get("label", self.address))
        self.pips.set_state(wins, needed, color)
        self.canvas.set_accent(color)


class DuelPage(QWidget):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.bridge = state.bridge
        self.snap = None
        self._last_phase = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.pages = QStackedWidget()
        root.addWidget(self.pages)
        self.pages.addWidget(self._build_setup())
        self.pages.addWidget(self._build_arena())
        state.wands_changed.connect(self._refresh_setup)
        state.library_changed.connect(self._refresh_pools)
        self._refresh_setup()

    # ── setup ─────────────────────────────────────────────────────────────────

    def _build_setup(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        kicker = QLabel("MAGIC CASTER")
        kicker.setObjectName("Section")
        title = QLabel("Wizard's Duel")
        title.setFont(T.font(30, serif=True))
        rules = QLabel("Two wizards, one spell.  Each round both of you are shown the same spell: "
                       "the first to cast it wins the round.  Best of five.\n"
                       "Wait for “Cast!” – a gesture started during the countdown doesn't count.")
        rules.setObjectName("Dim")
        rules.setWordWrap(True)
        for x in (kicker, title, rules):
            outer.addWidget(x)
        outer.addSpacing(16)

        box, bl = card(margins=(24, 20, 24, 20), spacing=14)
        box.setMaximumWidth(720)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)
        self.player_boxes, self.swatches = [], []
        for i in range(2):
            lbl = QLabel(f"Wizard {i + 1}")
            lbl.setFont(T.font(12, serif=True))
            combo = QComboBox()
            combo.setMinimumWidth(240)
            combo.currentIndexChanged.connect(lambda _i, k=i: self._player_changed(k))
            sw = ColorSwatch(title="Wand colour")
            sw.setToolTip("This wand's colour (cast glow, connect animation, duel colour)")
            sw.picked.connect(lambda c, k=i: self._colour_picked(k, c))
            grid.addWidget(lbl, i, 0)
            grid.addWidget(combo, i, 1)
            grid.addWidget(sw, i, 2)
            self.player_boxes.append(combo)
            self.swatches.append(sw)
        pool_lbl = QLabel("Spells")
        pool_lbl.setFont(T.font(12, serif=True))
        self.pool = QComboBox()
        grid.addWidget(pool_lbl, 2, 0)
        grid.addWidget(self.pool, 2, 1, 1, 2)
        bl.addLayout(grid)
        row = QHBoxLayout()
        self.setup_note = QLabel("")
        self.setup_note.setObjectName("Dim")
        self.begin = QPushButton("Begin the duel")
        self.begin.setObjectName("Primary")
        self.begin.clicked.connect(self._begin)
        row.addWidget(self.setup_note, 1)
        row.addWidget(self.begin)
        bl.addLayout(row)
        outer.addWidget(box)
        outer.addStretch()
        self._refresh_pools()
        return w

    def _refresh_pools(self):
        if not hasattr(self, "pool"):
            return
        current = self.pool.currentData()
        counts = self.bridge.core.duel_pools()      # read-only: progress + cast log
        self.pool.blockSignals(True)
        self.pool.clear()
        for key, n in counts.items():
            if n:
                self.pool.addItem(f"{POOL_NAMES.get(key, key)}  ({n})", key)
        i = self.pool.findData(current or ("cast" if counts.get("cast", 0) >= 3 else "all"))
        self.pool.setCurrentIndex(max(0, i))
        self.pool.blockSignals(False)

    def _refresh_setup(self):
        wands = self.state.connected_wands()
        taken = []
        for i, combo in enumerate(self.player_boxes):
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            for a in wands:
                combo.addItem(self.state.wand_label(a), a)
            free = [a for a in wands if a not in taken]
            pick = current if current in free else (free[0] if free else None)
            if pick:
                combo.setCurrentIndex(combo.findData(pick))
                taken.append(pick)
            combo.blockSignals(False)
            self._player_changed(i)
        a, b = (c.currentData() for c in self.player_boxes)
        ok = bool(a and b and a != b) and not self.state.duelling
        self.begin.setEnabled(ok)
        self.setup_note.setText(
            "" if ok else "Connect two wands to duel (Scan, pick a wand, Connect)."
            if len(wands) < 2 else "Pick two different wands.")

    def _player_changed(self, i: int):
        a = self.player_boxes[i].currentData()
        if a:
            self.swatches[i].set_color(self.state.wand_color(a))
        if hasattr(self, "begin"):
            x, y = (c.currentData() for c in self.player_boxes)
            self.begin.setEnabled(bool(x and y and x != y))

    def _colour_picked(self, i: int, color: str):
        a = self.player_boxes[i].currentData()
        if a:
            self.bridge.call("set_wand_color", a, color)

    def _begin(self):
        players = [c.currentData() for c in self.player_boxes]
        self.bridge.call("start_duel", players, self.pool.currentData() or "all")

    # ── arena ─────────────────────────────────────────────────────────────────

    def _build_arena(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        top = QHBoxLayout()
        self.round_label = QLabel("")
        self.round_label.setFont(T.font(14, serif=True))
        self.round_label.setStyleSheet(f"color: {T.GOLD};")
        top.addWidget(self.round_label)
        top.addStretch()
        self.skip_btn = QPushButton("Skip spell")
        self.skip_btn.setToolTip("Void this round and draw another spell")
        self.skip_btn.clicked.connect(lambda: self.bridge.call("skip_round"))
        self.cancel_btn = QPushButton("End duel")
        self.cancel_btn.clicked.connect(lambda: self.bridge.call("cancel_duel"))
        self.rematch_btn = QPushButton("Rematch")
        self.rematch_btn.setObjectName("Primary")
        self.rematch_btn.clicked.connect(self._rematch)
        self.back_btn = QPushButton("Back")
        self.back_btn.clicked.connect(lambda: self.pages.setCurrentIndex(0))
        for b in (self.skip_btn, self.cancel_btn, self.rematch_btn, self.back_btn):
            top.addWidget(b)
        lay.addLayout(top)

        row = QHBoxLayout()
        row.setSpacing(14)
        self.left = PlayerPanel(self.state)
        self.right = PlayerPanel(self.state)
        centre = QWidget()
        centre.setMinimumWidth(340)
        self.centre_stack = QStackedLayout(centre)
        self.centre = ArenaCenter(self.state)
        self.video = VideoPanel()
        self.video.finished.connect(self._video_done)
        self._then = None                    # run once the current video ends (or is skipped)
        self._later = QTimer(self)           # round videos wait for the result to show
        self._later.setSingleShot(True)
        self._later.timeout.connect(lambda: self._play(*self._later_paths))
        self._later_paths: tuple = ()
        self.centre_stack.addWidget(self.centre)
        self.centre_stack.addWidget(self.video)
        row.addWidget(self.left, 3)
        row.addWidget(centre, 3)
        row.addWidget(self.right, 3)
        lay.addLayout(row, 1)
        return w

    def _panel(self, address):
        return self.left if self.left.address == address else \
            self.right if self.right.address == address else None

    def _play(self, *paths, then=None) -> bool:
        """Play videos in the centre; `then` runs when they end (or right away
        if video is off or the files are missing)."""
        if self.state.flag("video", True) and any(paths):
            self._then = then
            self.centre_stack.setCurrentWidget(self.video)
            self.video.play(*paths)
            return True
        if then:
            then()
        return False

    def _play_later(self, *paths, delay_ms: int = 1200):
        self._later_paths = paths
        self._later.start(delay_ms)

    def _stop_video(self):
        self._later.stop()
        self._then = None
        self.video.stop()

    def _video_done(self):
        self.centre_stack.setCurrentWidget(self.centre)
        then, self._then = self._then, None
        if then:
            then()

    def _rematch(self):
        if self.snap:
            self.bridge.call("start_duel", self.snap["players"], self.pool.currentData() or "all")

    # ── core events ───────────────────────────────────────────────────────────

    def on_duel(self, snap: dict):
        self.snap = snap
        phase = snap["phase"]
        infos = snap.get("player_info") or []
        if phase == "cancelled":
            self._stop_video()
            self.pages.setCurrentIndex(0)
            self._refresh_setup()
            self.setup_note.setText(snap.get("message", ""))
            return
        self.pages.setCurrentIndex(1)
        for panel, info in zip((self.left, self.right), infos):
            panel.set_player(info, snap["scores"].get(info["address"], 0), snap["wins_needed"])
        live = phase in ("intro", "countdown", "racing", "result")
        self.skip_btn.setVisible(phase in ("countdown", "racing"))
        self.cancel_btn.setVisible(live)
        self.rematch_btn.setVisible(phase == "finished")
        self.back_btn.setVisible(phase == "finished")
        label = lambda a: next((i["label"] for i in infos if i["address"] == a), a)
        colour = lambda a: next((i["color"] for i in infos if i["address"] == a), T.GOLD)
        text_colour = lambda a: QColor(colour(a)).lighter(165).name()   # readable on the dark
        new_phase = phase != self._last_phase
        self._last_phase = phase

        if phase == "intro":
            self.round_label.setText("The duel begins")
            self.centre.set_spell(None)
            self.centre.set_big("")
            self.centre.set_banner(f"{label(snap['players'][0])}  vs  {label(snap['players'][1])}",
                                   T.GOLD, "Wands at the ready…")
            if new_phase:
                self._play(self.state.media.duel_intro)
        elif phase == "countdown":
            self._stop_video()
            self.round_label.setText(f"Round {snap['round']}")
            self.centre.set_spell(snap["spell"])
            self.centre.set_big(str(snap["count"]), T.GOLD)
            self.centre.set_banner("Get ready…", T.TEXT_DIM, "")
            if new_phase:
                for panel in (self.left, self.right):
                    panel.canvas.set_overlay(None, None)
                    panel.canvas.set_trail(None, False)
                    panel.canvas.set_title("", T.TEXT)
        elif phase == "racing":
            self.centre.set_big("Cast!", T.TEAL)
            self.centre.set_banner("", T.TEXT, "first to cast it wins the round")
        elif phase == "result":
            w = snap["round_winner"]
            self.centre.set_big("")
            if w:
                self.centre.set_banner(f"{label(w)} wins the round!", text_colour(w),
                                       f"{snap['scores'][snap['players'][0]]} – "
                                       f"{snap['scores'][snap['players'][1]]}")
                info = self.state.info(snap["spell"])
                self.centre.burst((info.colors if info and info.colors else ()) + (colour(w),))
                if new_phase:
                    self._play_later(info.video if info else None)     # after the burst
            else:
                self.centre.set_banner(snap.get("message", "No winner"), T.TEXT_DIM, "no point")
        elif phase == "finished":
            w = snap["winner"]
            self.round_label.setText("Duel over")
            self.centre.set_spell(None)
            self.centre.set_big("")
            if w:
                self.centre.set_banner(f"{label(w)} is victorious!", text_colour(w),
                                       f"{snap['scores'][snap['players'][0]]} – "
                                       f"{snap['scores'][snap['players'][1]]}")
                if new_phase:          # celebration video, then confetti over the result
                    confetti = [colour(w), T.GOLD, "#FFFFFF", T.VIOLET]
                    self._later.stop()
                    self._play(self.state.media.mastery_video,
                               then=lambda c=confetti: self.centre.confetti(c))
            else:
                self.centre.set_banner("A draw!", T.GOLD, "nobody reached three")

    def on_window_open(self, address: str, _target):
        panel = self._panel(address)
        if panel and self.state.duelling:
            panel.canvas.set_overlay(None, None)
            panel.canvas.set_trail(None, True)
            panel.canvas.set_title("Casting…", T.GOLD)

    def on_trail(self, address: str, trail):
        panel = self._panel(address)
        if panel and self.state.duelling:
            panel.canvas.set_trail(trail, True)

    def on_cast(self, address: str, r):
        panel = self._panel(address)
        if not (panel and self.state.duelling):
            return
        panel.canvas.set_trail(r.trail if len(r.trail) else None, False)
        tmpl = self.state.template(r.target)
        panel.canvas.set_overlay(tmpl, "match" if r.accepted else "miss")
        if r.accepted:
            panel.canvas.set_title(f"✦  {r.spell}", T.VIOLET)
            info = self.state.info(r.spell)
            panel.canvas.burst(info.colors if info and info.colors else [T.GOLD])
        else:
            panel.canvas.set_title(f"✗  {r.message()}", T.RED)
