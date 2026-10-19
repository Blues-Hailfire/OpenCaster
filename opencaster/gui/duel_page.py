"""
Duel page: set up a wizard's duel between two wands and watch it play out.

Three modes (the rules live in opencaster.duel, run by the core):
  Quick-draw      two wizards get the same spell; the first to cast it wins
                  the round.  Best of five.
  Clash           two wizards, three seconds to cast any battle spell; picks
                  stay hidden until both are in, then the elements decide
                  (opencaster.elements).  Best of five.
  Duelling Club   two to five wizards, turn by turn (in seat order or at
                  random): answer each spell with one that beats it, or block
                  it and attack.  One rally, until somebody slips up.

Any seat may be the NPC, a computer opponent (opencaster.npc) at one of
three skill levels; with one wand connected, Wizard 2 is the NPC.

This page renders the core's snapshots: countdown, live trails (hidden in a
clash until the reveal), round results, the duel intro / payoff / victory
videos and a confetti finish.
"""

import time

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QStackedLayout, QStackedWidget,
                               QVBoxLayout, QWidget)

from .. import elements as E
from ..duel import CLUB_MAX_PLAYERS
from ..npc import COLOR as NPC_COLOR, LEVELS as NPC_LEVELS, NPC
from . import elements as GE
from . import theme as T
from .media import VideoPanel
from .trail import TrailCanvas
from .widgets import Animator, ColorSwatch, Particles, card, paint_spell_art

NPC_ITEM = "NPC  –  computer opponent"
NPC_TIPS = {"easy": "Slow; fumbles one gesture in four; answers right about two times in three",
            "medium": "Quicker; fumbles one gesture in eight; answers right four times in five",
            "hard": "Quick and sure – and in a clash it learns your favourite element"}

POOL_NAMES = {"cast": "Spells you've cast", "all": "All spells", "Beginner": "Beginner spells",
              "Intermediate": "Intermediate spells", "Expert": "Expert spells"}

MODES = {
    "race": ("Quick-draw",
             "Each round you're both shown the same spell: the first to cast it wins the round.  "
             "Best of five.  Wait for “Cast!” – a gesture started during the countdown doesn't "
             "count."),
    "clash": ("Clash",
              "After “Cast!” you each have three seconds to cast any battle spell.  Spells stay "
              "hidden until both are in, then the elements decide: each beats two others, and a "
              "shield blocks anything.  An attack beats no spell at all; a draw scores nothing.  "
              "Best of five."),
    "club": ("Duelling Club",
             "Two to five wizards take turns, in seat order or at random.  Wizard 1 opens with "
             "an attack (three seconds); the next wizard has five seconds to answer with a spell "
             "that beats it – which the wizard after them must answer – or to block it with a "
             "shield and attack within three seconds.  There are no rounds: the rally goes on "
             "until someone answers too late or with a spell that doesn't beat the attack, and "
             "the wizard whose spell went unanswered wins."),
}
ORDERS = (("in_order", "In order"), ("random", "Random"))


class ArenaCenter(QWidget):
    """The round's spell card (quick-draw), the element wheel and the two
    revealed picks (clash), or the spell to answer and the rally so far
    (Duelling Club), with the countdown, turn timer, banners and particles."""

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.mode = "race"
        self.spell = None
        self.picks = None                # clash reveal: [(spell or None, element), …] per player
        self.pick_winner = None          # 0, 1 or None
        self.pick_colors = (T.GOLD, T.GOLD)
        self.chain: list = []            # Duelling Club rally: [(spell, element, colour), …]
        self.big = ""                    # "3", "2", "1", "Cast!"
        self.big_color = T.GOLD
        self.banner, self.banner_color = "", T.TEXT
        self.sub = ""
        self._pop = 1.0                  # countdown pop animation 0 → 1
        self._anim = None
        self._ring_end = None            # clash timer: monotonic end time
        self._ring_total = 1.0
        self.fx = Particles()
        self.animator = Animator(self)
        self.setMinimumSize(300, 360)

    def set_mode(self, mode: str):
        self.mode = mode
        self.update()

    def set_spell(self, name):
        self.spell = name
        self.update()

    def set_picks(self, picks, winner=None, colors=(T.GOLD, T.GOLD)):
        self.picks, self.pick_winner, self.pick_colors = picks, winner, colors
        self.update()

    def set_chain(self, items):
        self.chain = list(items)
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

    def start_ring(self, seconds: float):
        self._ring_total = max(0.1, seconds)
        self._ring_end = time.monotonic() + seconds
        self.animator.kick()

    def stop_ring(self):
        self._ring_end = None
        self.update()

    def _ring_left(self):
        if self._ring_end is None:
            return None
        return max(0.0, self._ring_end - time.monotonic())

    def burst(self, colors, x: float = 0.5):
        self.fx.burst(self.width() * x, self.height() * 0.42, list(colors) + ["#FFFFFF"],
                      n=110, speed=self.width() * 0.7)
        self.animator.kick()

    def confetti(self, colors):
        self.fx.confetti(self.width(), list(colors), n=180)
        self.animator.kick()

    # ── painting ──────────────────────────────────────────────────────────────

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        ring = self._ring_left()
        animating = self.fx.active or (ring is not None and ring > 0)
        self.fx.step(self.animator.dt(animating))
        r = QRectF(self.rect()).adjusted(4, 4, -4, -4)
        card_w = min(r.width() * 0.8, r.height() * 0.62)
        card_r = QRectF(r.center().x() - card_w / 2, r.top() + 10, card_w, card_w * 1.25)
        big_rect = None
        if self.mode == "clash":
            big_rect = self._paint_clash(p, r, card_r, ring)
        elif self.mode == "club":
            big_rect = self._paint_club(p, r, card_r, ring)
        elif self.spell:
            self._paint_card(p, card_r)
        if self.big:
            k = self._pop
            size = max(30.0, card_w / (3.2 if self.mode == "race" else 4.2)) * (0.6 + 0.4 * k)
            p.setFont(T.font(size, serif=True, bold=True))
            col = T.qcolor(self.big_color, min(1.0, 0.3 + k))
            rect = big_rect or QRectF(r.left(), card_r.top() + card_r.height() * 0.18, r.width(),
                                      size * 1.6)
            p.setPen(QPen(T.qcolor("#000000", 0.55)))
            p.drawText(rect.translated(2, 3), Qt.AlignCenter, self.big)
            p.setPen(col)
            p.drawText(rect, Qt.AlignCenter, self.big)
        if self.banner:
            p.setPen(QColor(self.banner_color))
            p.setFont(T.font(20 if len(self.banner) < 34 else 16 if len(self.banner) < 42 else 14,
                             serif=True))
            p.drawText(QRectF(r.left(), card_r.bottom() + 8, r.width(), 36), Qt.AlignCenter,
                       self.banner)
        if self.sub:
            p.setPen(T.qcolor(T.TEXT_DIM))
            p.setFont(T.font(10, italic=True))
            p.drawText(QRectF(r.left(), card_r.bottom() + 42, r.width(), 22), Qt.AlignCenter, self.sub)
        if self.chain:
            self._paint_chain(p, r, card_r.bottom() + 74)
        if self.fx.active:
            self.fx.paint(p)
        if animating:
            self.animator.kick()

    def _paint_card(self, p: QPainter, card_r: QRectF):
        card_w = card_r.width()
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

    def _paint_clash(self, p: QPainter, r: QRectF, card_r: QRectF, ring):
        """Wheel (+ timer ring) before the reveal, both picks after it.
        Returns the rect for the big countdown text."""
        if self.picks:
            self._paint_picks(p, r, card_r)
            return None
        side = min(card_r.width(), card_r.height()) * 0.98
        wheel = QRectF(card_r.center().x() - side / 2, card_r.center().y() - side / 2, side, side)
        GE.paint_wheel(p, wheel, alpha=0.28 if self.big else 0.95)
        if ring is not None:
            k = ring / self._ring_total
            col = T.RED if ring < 1.0 else T.TEAL
            box = wheel.adjusted(6, 6, -6, -6)
            p.setPen(QPen(T.qcolor("#FFFFFF", 0.08), 7))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(box)
            p.setPen(QPen(QColor(col), 7, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(box, 90 * 16, int(360 * 16 * k))
        return wheel

    def _paint_club(self, p: QPainter, r: QRectF, card_r: QRectF, ring):
        """The spell to answer, its timer running round the card; on an
        attack turn the wheel and ring instead."""
        if not self.spell:
            return self._paint_clash(p, r, card_r, ring)
        self._paint_card(p, card_r)
        if ring is not None:
            edge = QPainterPath()
            edge.addRoundedRect(card_r.adjusted(-6, -6, 6, 6), 24, 24)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(T.qcolor("#FFFFFF", 0.08), 5))
            p.drawPath(edge)
            k = ring / self._ring_total
            n = max(2, int(160 * k))
            pts = [edge.pointAtPercent(k * i / (n - 1)) for i in range(n)]
            p.setPen(QPen(QColor(T.RED if ring < 1.5 else T.TEAL), 5, Qt.SolidLine, Qt.RoundCap))
            p.drawPolyline(QPolygonF(pts))
        return None

    def _paint_chain(self, p: QPainter, r: QRectF, y: float):
        """The rally so far, newest last: icon + spell, joined by arrows."""
        p.setFont(T.font(9.5, bold=True))
        fm = QFontMetricsF(p.font())
        items, arrow = list(self.chain), 18.0
        while True:
            widths = [fm.horizontalAdvance(spell) + 24 for spell, _e, _c in items]
            total = sum(widths) + arrow * (len(items) - 1)
            if total <= r.width() or len(items) == 1:
                break
            items = items[1:]
        x = r.center().x() - total / 2
        for i, ((spell, element, colour), w) in enumerate(zip(items, widths)):
            if i:
                p.setPen(T.qcolor(T.TEXT_FAINT))
                p.drawText(QRectF(x, y, arrow, 20), Qt.AlignCenter, "›")
                x += arrow
            GE.draw_icon(p, element, QPointF(x + 8, y + 10), 7, glow=False)
            p.setPen(QColor(colour).lighter(160))
            p.drawText(QRectF(x + 19, y, w - 19, 20), Qt.AlignLeft | Qt.AlignVCenter, spell)
            x += w

    def _paint_picks(self, p: QPainter, r: QRectF, card_r: QRectF):
        gap = 44.0
        w = min((r.width() - gap * 2) / 2, card_r.width() * 0.6)
        h = w * 1.3
        top = card_r.top() + max(0.0, (card_r.height() - h - 34) / 2)
        for i, (spell, element) in enumerate(self.picks):
            x = r.center().x() - gap / 2 - w if i == 0 else r.center().x() + gap / 2
            rc = QRectF(x, top, w, h)
            won = self.pick_winner == i
            p.save()
            if self.pick_winner is not None and not won:
                p.setOpacity(0.5)
            if spell:
                t = self.state.template(spell)
                glyph = rc.adjusted(w * 0.14, w * 0.12, -w * 0.14, -h * 0.36)
                border = QColor(self.pick_colors[i]) if won else T.qcolor("#ffffff", 0.12)
                paint_spell_art(p, rc, self.state.color(spell), t.outline if t else None, spell, 16,
                                glyph, 2.6, border, self.state.icon(spell))
                if won:
                    p.setPen(QPen(T.qcolor(self.pick_colors[i], 0.45), 6))
                    p.setBrush(Qt.NoBrush)
                    p.drawRoundedRect(rc.adjusted(-3, -3, 3, 3), 18, 18)
                p.setPen(QColor("#FFFFFF"))
                p.setFont(T.font(max(11.0, w / 10), serif=True))
                p.drawText(QRectF(rc.left() + 4, rc.bottom() - h * 0.3, w - 8, h * 0.22),
                           Qt.AlignCenter | Qt.TextWordWrap, spell)
            else:
                p.setPen(QPen(T.qcolor("#ffffff", 0.18), 1.5, Qt.DashLine))
                p.setBrush(T.qcolor("#ffffff", 0.03))
                p.drawRoundedRect(rc, 16, 16)
                p.setPen(T.qcolor(T.TEXT_FAINT))
                p.setFont(T.font(11, italic=True))
                p.drawText(rc, Qt.AlignCenter, "no spell")
            if element:
                name = E.NAMES[element].upper()
                p.setFont(T.font(9.5, bold=True))
                tw = QFontMetricsF(p.font()).horizontalAdvance(name)
                left = rc.center().x() - (tw + 24) / 2
                GE.draw_icon(p, element, QPointF(left + 9, rc.bottom() + 16), 9, glow=False)
                p.setPen(QColor(GE.color(element)))
                p.drawText(QRectF(left + 24, rc.bottom() + 6, tw + 4, 20),
                           Qt.AlignLeft | Qt.AlignVCenter, name)
            p.restore()
        p.setPen(T.qcolor(T.GOLD, 0.9))
        p.setFont(T.font(15, serif=True, italic=True))
        p.drawText(QRectF(r.center().x() - gap, top + h / 2 - 14, gap * 2, 28), Qt.AlignCenter, "vs")


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
        self.color = T.GOLD
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

    def set_player(self, info: dict, wins: int, needed: int, seat: int = 0):
        """seat > 0 numbers the panel (Duelling Club with three or more)."""
        self.address = info["address"]
        self.color = info.get("color", T.GOLD)
        self.bar.setStyleSheet(f"background: {self.color}; border-radius: 2px;")
        label = info.get("label", self.address)
        if info.get("npc") and info.get("level"):
            label += f"  ·  {info['level'].title()}"
        self.name.setText(f"{seat}.  {label}" if seat else label)
        self.pips.set_state(wins, needed, self.color)
        self.canvas.set_accent(self.color)

    def reset(self):
        self.canvas.set_overlay(None, None)
        self.canvas.set_trail(None, False)
        self.canvas.set_title("", T.TEXT)
        self.set_active(False)

    def set_active(self, on: bool):
        """Duelling Club: a gold edge on the panel whose turn it is."""
        self.setStyleSheet("QFrame#Stage { border: 2px solid rgba(230, 196, 111, 0.85); }" if on else "")

    def set_compact(self, on: bool):
        """Smaller, for three to five panels stacked in the side columns."""
        self.canvas.setMinimumSize(150, 100) if on else self.canvas.setMinimumSize(240, 240)
        self.name.setFont(T.font(13 if on else 17, serif=True))
        self.layout().setContentsMargins(*((12, 8, 12, 8) if on else (14, 12, 14, 12)))


class DuelPage(QWidget):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.bridge = state.bridge
        self.snap = None
        self._last_phase = None
        self._held: dict = {}            # clash: address → locked-in CastResult, until the reveal
        self._last_turn = None           # Duelling Club turn_no on show
        self._no_one: set = set()        # seats 3-5 the user set to "no one"
        self._npc_seat = None            # the seat the user gave the NPC (else it only fills Wizard 2)
        self._seated = 0                 # panels laid out in the arena
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.pages = QStackedWidget()
        root.addWidget(self.pages)
        self.pages.addWidget(self._build_setup())
        self.pages.addWidget(self._build_arena())
        state.wands_changed.connect(self._refresh_setup)
        state.library_changed.connect(self._refresh_pools)
        self._refresh_setup()

    @property
    def mode(self) -> str:
        return list(MODES)[max(0, self.mode_group.checkedId())]

    @property
    def order(self) -> str:
        return ORDERS[max(0, self.order_group.checkedId())][0]

    @property
    def npc_level(self) -> str:
        return NPC_LEVELS[max(0, self.npc_group.checkedId())]

    def seats(self) -> list:
        """The chosen wands in seat order (two, or up to five for the club)."""
        n = CLUB_MAX_PLAYERS if self.mode == "club" else 2
        return [a for a in (c.currentData() for c in self.player_boxes[:n]) if a]

    # ── setup ─────────────────────────────────────────────────────────────────

    def _build_setup(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        kicker = QLabel("MAGIC CASTER")
        kicker.setObjectName("Section")
        title = QLabel("Wizard's Duel")
        title.setFont(T.font(30, serif=True))
        modes = QHBoxLayout()
        modes.setSpacing(8)
        self.mode_group = QButtonGroup(self)
        for i, key in enumerate(MODES):
            b = QPushButton(MODES[key][0])
            b.setObjectName("Chip")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.mode_group.addButton(b, i)
            modes.addWidget(b)
        modes.addStretch()
        self.rules = QLabel("")
        self.rules.setObjectName("Dim")
        self.rules.setWordWrap(True)
        self.rules.setMaximumWidth(860)
        for x in (kicker, title):
            outer.addWidget(x)
        outer.addSpacing(4)
        outer.addLayout(modes)
        outer.addWidget(self.rules)
        outer.addSpacing(12)

        box, bl = card(margins=(24, 20, 24, 20), spacing=14)
        box.setMaximumWidth(860)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)
        self.player_boxes, self.swatches, self.extra_seats = [], [], []
        for i in range(CLUB_MAX_PLAYERS):
            lbl = QLabel(f"Wizard {i + 1}")
            lbl.setFont(T.font(12, serif=True))
            combo = QComboBox()
            combo.setMinimumWidth(240)
            combo.currentIndexChanged.connect(lambda _i, k=i: self._player_changed(k))
            combo.activated.connect(lambda _i, k=i: self._seat_chosen(k))     # user choices only
            sw = ColorSwatch(title="Wand colour")
            sw.setToolTip("This wand's colour (cast glow, connect animation, duel colour)")
            sw.picked.connect(lambda c, k=i: self._colour_picked(k, c))
            grid.addWidget(lbl, i, 0)
            grid.addWidget(combo, i, 1)
            grid.addWidget(sw, i, 2)
            self.player_boxes.append(combo)
            self.swatches.append(sw)
            if i >= 2:                                   # Duelling Club only
                self.extra_seats.append((lbl, combo, sw))
        self.pool_label = QLabel("Spells")
        self.pool_label.setFont(T.font(12, serif=True))
        self.pool = QComboBox()
        grid.addWidget(self.pool_label, CLUB_MAX_PLAYERS, 0)
        grid.addWidget(self.pool, CLUB_MAX_PLAYERS, 1, 1, 2)
        self.order_label = QLabel("Who answers")
        self.order_label.setFont(T.font(12, serif=True))
        self.order_row = QWidget()
        orow = QHBoxLayout(self.order_row)
        orow.setContentsMargins(0, 0, 0, 0)
        orow.setSpacing(8)
        self.order_group = QButtonGroup(self)
        for i, (key, text) in enumerate(ORDERS):
            b = QPushButton(text)
            b.setObjectName("Chip")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip("The next wizard in seat order answers each spell" if key == "in_order" else
                         "Any wizard but the caster may be picked to answer – at random")
            self.order_group.addButton(b, i)
            orow.addWidget(b)
        orow.addStretch()
        saved = self.state.prefs.value("club_order", "in_order")
        self.order_group.button(1 if saved == "random" else 0).setChecked(True)
        self.order_group.idToggled.connect(
            lambda _i, on: on and self.state.prefs.setValue("club_order", self.order))
        grid.addWidget(self.order_label, CLUB_MAX_PLAYERS + 1, 0)
        grid.addWidget(self.order_row, CLUB_MAX_PLAYERS + 1, 1, 1, 2)
        self.npc_label = QLabel("NPC skill")
        self.npc_label.setFont(T.font(12, serif=True))
        self.npc_row = QWidget()
        nrow = QHBoxLayout(self.npc_row)
        nrow.setContentsMargins(0, 0, 0, 0)
        nrow.setSpacing(8)
        self.npc_group = QButtonGroup(self)
        for i, key in enumerate(NPC_LEVELS):
            b = QPushButton(key.title())
            b.setObjectName("Chip")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(NPC_TIPS[key])
            self.npc_group.addButton(b, i)
            nrow.addWidget(b)
        nrow.addStretch()
        saved = self.state.prefs.value("npc_level", "medium")
        self.npc_group.button(NPC_LEVELS.index(saved) if saved in NPC_LEVELS else 1).setChecked(True)
        self.npc_group.idToggled.connect(
            lambda _i, on: on and self.state.prefs.setValue("npc_level", self.npc_level))
        grid.addWidget(self.npc_label, CLUB_MAX_PLAYERS + 2, 0)
        grid.addWidget(self.npc_row, CLUB_MAX_PLAYERS + 2, 1, 1, 2)
        self._npc_shown = False
        self.npc_label.hide()
        self.npc_row.hide()
        grid.setColumnStretch(3, 1)
        bl.addLayout(grid)
        self.legend = QWidget()
        ll = QHBoxLayout(self.legend)
        ll.setContentsMargins(0, 6, 0, 0)
        ll.setSpacing(18)
        ll.addWidget(GE.ElementWheel(size=210), 0, Qt.AlignTop)
        ll.addWidget(GE.legend(lambda s: self.state.template(s) is not None), 1)
        row = QHBoxLayout()                          # above the legend: always in view
        self.setup_note = QLabel("")
        self.setup_note.setObjectName("Dim")
        self.begin = QPushButton("Begin the duel")
        self.begin.setObjectName("Primary")
        self.begin.clicked.connect(self._begin)
        row.addWidget(self.setup_note, 1)
        row.addWidget(self.begin)
        bl.addLayout(row)
        bl.addWidget(self.legend)
        outer.addWidget(box)
        outer.addStretch()
        self.mode_group.idToggled.connect(lambda _i, on: on and self._mode_changed())
        saved = self.state.prefs.value("duel_mode", "race")
        self.mode_group.button(list(MODES).index(saved) if saved in MODES else 0).setChecked(True)
        self._refresh_pools()
        scroll = QScrollArea()                       # five seats + the legend outgrow short windows
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(w)
        self._setup_inner = w
        QTimer.singleShot(0, self._fit_setup)
        return scroll

    def _fit_setup(self):
        """Never squeeze the setup below what it needs (word-wrapped text makes
        the scroll area underestimate); scroll instead."""
        lay = self._setup_inner.layout()
        lay.invalidate()
        self._setup_inner.setMinimumHeight(lay.sizeHint().height())

    def _mode_changed(self):
        mode = self.mode
        self.state.prefs.setValue("duel_mode", mode)
        self.rules.setText(MODES[mode][1])
        elemental = mode in ("clash", "club")        # spell elements instead of a spell pool
        self.pool_label.setVisible(not elemental)
        self.pool.setVisible(not elemental)
        self.legend.setVisible(elemental)
        club = mode == "club"
        for row in self.extra_seats:
            for w in row:
                w.setVisible(club)
        self.order_label.setVisible(club)
        self.order_row.setVisible(club)
        if hasattr(self, "begin"):
            self._validate()
        if hasattr(self, "_setup_inner"):
            QTimer.singleShot(0, self._fit_setup)

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
        """Refill the seats from the connected wands and the NPC, keeping
        choices (this runs on every wand update, battery levels included).
        Wizards 1 and 2 fall back to the NPC when there's no wand for them."""
        wands = self.state.connected_wands()
        taken = []
        for i, combo in enumerate(self.player_boxes):
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            if i >= 2:
                combo.addItem("—  no one", None)
            for a in wands:
                combo.addItem(self.state.wand_label(a), a)
            combo.addItem(NPC_ITEM, NPC)
            if current == NPC and self._npc_seat != i:
                current = None                       # an NPC we filled in gives way to a wand
            free = [a for a in wands + [NPC] if a not in taken]
            free_wands = [a for a in free if a != NPC]
            pick = None if i in self._no_one else current if current in free else \
                free_wands[0] if free_wands else NPC if i == 1 and NPC in free else None
            combo.setCurrentIndex(combo.findData(pick) if pick else 0 if i >= 2 else -1)
            if pick:
                taken.append(pick)
            combo.blockSignals(False)
            self._player_changed(i)
        self._validate()

    def _seat_chosen(self, i: int):
        if self.player_boxes[i].currentData() == NPC:
            self._npc_seat = i
        elif self._npc_seat == i:
            self._npc_seat = None
        if i >= 2:
            (self._no_one.add if self.player_boxes[i].currentData() is None else self._no_one.discard)(i)

    def _player_changed(self, i: int):
        a = self.player_boxes[i].currentData()
        self.swatches[i].setEnabled(a != NPC)
        if a:
            self.swatches[i].set_color(NPC_COLOR if a == NPC else self.state.wand_color(a))
        if hasattr(self, "begin"):
            self._validate()

    def _validate(self):
        wands = self.state.connected_wands()
        seats = self.seats()
        first_two = all(c.currentData() for c in self.player_boxes[:2])
        different = len(seats) == len(set(seats))
        anyone = any(a != NPC for a in seats)
        ok = first_two and different and anyone and not self.state.duelling
        self.begin.setEnabled(ok)
        self.setup_note.setText(
            "" if ok else "Connect a wand to duel (Scan, pick a wand, Connect) – the NPC can be "
            "your opponent." if not wands else "Pick a wand or the NPC for wizards 1 and 2."
            if not first_two else "Pick a different wand for each wizard." if not different
            else "Pick a wand for someone – the NPC can't duel itself." if not anyone else "")
        npc = NPC in seats
        if npc != self._npc_shown:                   # its skill, only when it has a seat
            self._npc_shown = npc
            self.npc_label.setVisible(npc)
            self.npc_row.setVisible(npc)
            if hasattr(self, "_setup_inner"):
                QTimer.singleShot(0, self._fit_setup)

    def _colour_picked(self, i: int, color: str):
        a = self.player_boxes[i].currentData()
        if a and a != NPC:
            self.bridge.call("set_wand_color", a, color)

    def _begin(self):
        self.bridge.call("start_duel", self.seats(), self.pool.currentData() or "all", self.mode,
                         self.order, self.npc_level)

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
        self.panels = [PlayerPanel(self.state) for _ in range(CLUB_MAX_PLAYERS)]
        self.left_col, self.right_col = QVBoxLayout(), QVBoxLayout()
        for col in (self.left_col, self.right_col):
            col.setSpacing(12)
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
        row.addLayout(self.left_col, 3)
        row.addWidget(centre, 3)
        row.addLayout(self.right_col, 3)
        lay.addLayout(row, 1)
        self._seat_panels(2)
        return w

    def _seat_panels(self, n: int):
        """Seats 1..ceil(n/2) down the left column, the rest down the right."""
        if n == self._seated:
            return
        self._seated = n
        for p in self.panels:
            self.left_col.removeWidget(p)
            self.right_col.removeWidget(p)
            p.hide()
        k = (n + 1) // 2
        for i, p in enumerate(self.panels[:n]):
            (self.left_col if i < k else self.right_col).addWidget(p, 1)
            p.set_compact(n > 2)
            p.show()

    @property
    def _active_panels(self) -> list:
        return self.panels[:self._seated]

    def _panel(self, address):
        return next((p for p in self._active_panels if p.address == address), None)

    def _clash(self) -> bool:
        return bool(self.snap and self.snap.get("mode") == "clash")

    def _club(self) -> bool:
        return bool(self.snap and self.snap.get("mode") == "club")

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
            self.bridge.call("start_duel", self.snap["players"], self.pool.currentData() or "all",
                             self.snap.get("mode", "race"), self.snap.get("order", "in_order"),
                             self.snap.get("npc_level") or self.npc_level)

    # ── core events ───────────────────────────────────────────────────────────

    def on_duel(self, snap: dict):
        self.snap = snap
        phase = snap["phase"]
        clash, club = snap.get("mode") == "clash", snap.get("mode") == "club"
        infos = snap.get("player_info") or []
        if phase == "cancelled":
            self._stop_video()
            self.centre.stop_ring()
            self.centre.set_chain([])
            for panel in self._active_panels:
                panel.set_active(False)
            self.pages.setCurrentIndex(0)
            self._refresh_setup()
            self.setup_note.setText(snap.get("message", ""))
            return
        self.pages.setCurrentIndex(1)
        self.centre.set_mode(snap.get("mode", "race"))
        players = snap["players"]
        self._seat_panels(len(players))
        for seat, (panel, info) in enumerate(zip(self.panels, infos), 1):
            panel.set_player(info, snap["scores"].get(info["address"], 0), snap["wins_needed"],
                             seat if len(players) > 2 else 0)
        live = phase in ("intro", "countdown", "racing", "result")
        self.skip_btn.setVisible(phase in ("countdown", "racing") and snap.get("mode") == "race")
        self.cancel_btn.setVisible(live)
        self.rematch_btn.setVisible(phase == "finished")
        self.back_btn.setVisible(phase == "finished")
        label = lambda a: next((i["label"] for i in infos if i["address"] == a), a)
        colour = lambda a: next((i["color"] for i in infos if i["address"] == a), T.GOLD)
        text_colour = lambda a: QColor(colour(a)).lighter(165).name()   # readable on the dark
        score = " – ".join(str(snap["scores"][a]) for a in players)
        rally = len(snap.get("chain", []))
        rally_text = f"a rally of {rally} spell{'' if rally == 1 else 's'}"
        new_phase = phase != self._last_phase
        self._last_phase = phase

        if phase == "intro":
            self.round_label.setText("The duel begins" + {"clash": "  ·  Clash", "club": "  ·  Duelling Club"}
                                     .get(snap.get("mode"), ""))
            self.centre.set_spell(None)
            self.centre.set_picks(None)
            self.centre.set_big("")
            if len(players) == 2:
                self.centre.set_banner(f"{label(players[0])}  vs  {label(players[1])}",
                                       T.GOLD, "Wands at the ready…")
            else:
                self.centre.set_banner(f"{len(players)} wizards", T.GOLD,
                                       ",  ".join(label(a) for a in players))
            if new_phase:
                self._play(self.state.media.duel_intro)
        elif phase == "countdown":
            self._stop_video()
            self.round_label.setText(
                f"Duelling Club  ·  {'random order' if snap.get('order') == 'random' else 'in order'}"
                if club else f"Round {snap['round']}")
            self.centre.set_spell(snap["spell"])
            self.centre.set_picks(None)
            self.centre.set_big(str(snap["count"]), T.GOLD)
            self.centre.set_banner("Get ready…", T.TEXT_DIM,
                                   f"any battle spell – {snap.get('window_s', 3):.0f} seconds"
                                   if clash else f"{label(snap['starter'])} attacks first"
                                   if club else "")
            if new_phase:
                self._held, self._last_turn = {}, None
                self.centre.set_chain([])
                for panel in self._active_panels:
                    panel.reset()
        elif phase == "racing" and club:
            self.round_label.setText(f"Duelling Club  ·  {rally_text}" if rally else "Duelling Club")
            self._club_turn(snap, label, colour, text_colour)
        elif phase == "racing" and clash:
            if new_phase:
                self.centre.set_big("Cast!", T.TEAL)
                self.centre.start_ring(snap.get("window_s", 3.0))
            if snap.get("overtime"):
                self.centre.set_big("Time!", T.RED)
                self.centre.set_banner("", T.TEXT, "finishing the last gesture…")
            else:
                ready = [label(a) for a in snap.get("locked", [])]
                self.centre.set_banner("", T.TEXT, f"{' & '.join(ready)} ready" if ready else
                                       "any battle spell – first one counts")
        elif phase == "racing":
            self.centre.set_big("Cast!", T.TEAL)
            self.centre.set_banner("", T.TEXT, "first to cast it wins the round")
        elif phase == "result" and clash:
            self.centre.stop_ring()
            self.centre.set_big("")
            self._reveal(snap, label, colour, text_colour, score, new_phase)
        elif phase == "result" and club:
            self._club_result(snap, label, colour, text_colour, rally_text, new_phase)
        elif phase == "finished" and club:
            self._club_finish(snap, label, colour, text_colour, rally_text, new_phase)
        elif phase == "result":
            w = snap["round_winner"]
            self.centre.set_big("")
            if w:
                self.centre.set_banner(f"{label(w)} wins the round!", text_colour(w), score)
                info = self.state.info(snap["spell"])
                self.centre.burst((info.colors if info and info.colors else ()) + (colour(w),))
                if new_phase:
                    self._play_later(info.video if info else None)     # after the burst
            else:
                self.centre.set_banner(snap.get("message", "No winner"), T.TEXT_DIM, "no point")
        elif phase == "finished":
            w = snap["winner"]
            self.round_label.setText("Duel over")
            self.centre.stop_ring()
            self.centre.set_spell(None)
            self.centre.set_picks(None)
            self.centre.set_chain([])
            self.centre.set_big("")
            if w:
                self.centre.set_banner(f"{label(w)} is victorious!", text_colour(w), score)
                if new_phase:          # celebration video, then confetti over the result
                    confetti = [colour(w), T.GOLD, "#FFFFFF", T.VIOLET]
                    self._later.stop()
                    self._play(self.state.media.mastery_video,
                               then=lambda c=confetti: self.centre.confetti(c))
            else:
                self.centre.set_banner("A draw!", T.GOLD, "nobody reached three")

    def _reveal(self, snap, label, colour, text_colour, score, new_phase):
        """Clash result: both picks side by side, the outcome line, and each
        player's hidden trail."""
        players, picks, elements = snap["players"], snap.get("picks", {}), snap.get("elements", {})
        w = snap["round_winner"]
        side = players.index(w) if w in players else None
        self.centre.set_picks([(picks.get(a), elements.get(a)) for a in players], side,
                              tuple(colour(a) for a in players))
        if w:
            self.centre.set_banner(snap.get("line", ""), text_colour(w),
                                   f"{label(w)} wins the round  ·  {score}")
        else:
            self.centre.set_banner(snap.get("line", ""), T.GOLD, f"no point  ·  {score}")
        for a in players:
            panel, spell = self._panel(a), picks.get(a)
            if not panel:
                continue
            held = self._held.get(a)
            if spell:
                if held is not None and len(held.trail):
                    panel.canvas.set_trail(held.trail, False)
                    panel.canvas.set_overlay(self.state.template(spell), "match")
                element = elements.get(a)
                panel.canvas.set_title(f"✦  {spell}", GE.color(element),
                                       E.NAMES.get(element, "") if element else "")
            else:
                panel.canvas.set_title("no spell", T.TEXT_FAINT)
        if w and new_phase:
            info = self.state.info(picks.get(w))
            self.centre.burst((info.colors if info and info.colors else ()) + (colour(w),),
                              x=0.27 if side == 0 else 0.73)
            panel = self._panel(w)
            if panel:
                panel.canvas.burst(info.colors if info and info.colors else [colour(w)])
            self._play_later(info.video if info else None)

    def _club_turn(self, snap, label, colour, text_colour):
        """Duelling Club: a new turn (or overtime on the current one)."""
        turn, incoming = snap["turn"], snap.get("incoming")
        self.centre.set_chain([(c["spell"], c["element"], colour(c["player"])) for c in snap["chain"]])
        if snap.get("overtime"):
            self.centre.set_big("Time!", T.RED)
            self.centre.set_banner(self.centre.banner, self.centre.banner_color,
                                   "finishing the last gesture…")
            return
        if snap["turn_no"] == self._last_turn:
            return
        self._last_turn = snap["turn_no"]
        self.centre.set_big("")
        self.centre.set_spell(incoming)
        self.centre.start_ring(snap["window_s"])
        secs = f"{snap['window_s']:.0f} seconds"
        if snap["turn_kind"] == "counter":
            element = snap.get("incoming_element")
            answers = " or ".join(E.NAMES[a] for a in E.ATTACKS if E.beats(a, element))
            self.centre.set_banner(f"{label(turn)}: beat {incoming} or block it!", text_colour(turn),
                                   f"{E.NAMES.get(element, '')} – beaten by {answers}  ·  {secs}")
            title, sub = f"Beat {incoming}!", f"{answers} – or a shield"
        else:
            after_block = bool(snap["chain"]) and snap["chain"][-1]["move"] == "block"
            self.centre.set_banner(f"{label(turn)}: attack!", text_colour(turn),
                                   f"any attack spell  ·  {secs}")
            title, sub = ("Blocked – now attack!" if after_block else "Your turn – attack!"), \
                "any attack spell"
        for a in snap["players"]:
            panel = self._panel(a)
            if panel:
                panel.set_active(a == turn)
        panel = self._panel(turn)
        if panel:
            panel.canvas.set_overlay(None, None)
            panel.canvas.set_trail(None, False)
            panel.canvas.set_title(title, T.GOLD, sub)

    def _club_result(self, snap, label, colour, text_colour, rally_text, new_phase):
        """Duelling Club: somebody slipped up; the spell that went unanswered
        (if any) takes the centre.  The finish follows."""
        w, loser, line = snap["round_winner"], snap.get("loser"), snap.get("line", "")
        finisher = snap.get("incoming")
        self.centre.stop_ring()
        self.centre.set_big("")
        self.centre.set_spell(finisher)
        self.centre.set_chain([(c["spell"], c["element"], colour(c["player"])) for c in snap["chain"]])
        self.centre.set_banner(line[:1].upper() + line[1:], text_colour(w) if w else T.GOLD,
                               f"{label(loser)} slips up  ·  {rally_text}")
        for panel in self._active_panels:
            panel.set_active(False)
        lost = self._panel(loser)
        if lost and line.startswith("no "):
            lost.canvas.set_title("✗  out of time", T.RED, line)
        if w and new_phase:
            info = self.state.info(finisher) if finisher else None
            self.centre.burst((info.colors if info and info.colors else ()) + (colour(w),))
            if info:
                self._play_later(info.video)

    def _club_finish(self, snap, label, colour, text_colour, rally_text, new_phase):
        """Duelling Club: the duel is over – the rally stays on show."""
        w, loser, line = snap["winner"], snap.get("loser"), snap.get("line", "")
        self.round_label.setText(f"Duel over  ·  {rally_text}")
        self.centre.stop_ring()
        self.centre.set_big("")
        if w:
            self.centre.set_banner(f"{label(w)} wins the duel!", text_colour(w),
                                   f"{label(loser)}: {line}")
            if new_phase:              # celebration video, then confetti over the result
                confetti = [colour(w), T.GOLD, "#FFFFFF", T.VIOLET]
                self._later.stop()
                self._play(self.state.media.mastery_video,
                           then=lambda c=confetti: self.centre.confetti(c))
        else:
            self.centre.set_banner(f"{label(loser)} slipped up", T.GOLD, f"{line}  ·  no winner")

    def on_window_open(self, address: str, _target):
        panel = self._panel(address)
        if panel and self.state.duelling:
            panel.canvas.set_overlay(None, None)
            panel.canvas.set_trail(None, not self._clash())    # a clash keeps the shape hidden
            panel.canvas.set_title("Casting…", T.GOLD)

    def on_trail(self, address: str, trail):
        panel = self._panel(address)
        if panel and self.state.duelling and not self._clash():
            panel.canvas.set_trail(trail, True)

    def on_cast(self, address: str, r):
        panel = self._panel(address)
        if not (panel and self.state.duelling):
            return
        if self._club():
            self._club_cast(panel, address, r)
            return
        if self._clash():
            if self.snap and self.snap["phase"] != "racing":
                return                                       # late; the reveal stays up
            if r.accepted:
                self._held[address] = r
                panel.canvas.set_title("✓  Spell chosen", QColor(panel.color).lighter(165).name(),
                                       "hidden until the reveal")
                panel.canvas.burst([panel.color, "#FFFFFF"])
            else:
                panel.canvas.set_title(f"✗  {r.message()}", T.RED,
                                       "cast again – quickly!" if r.gate == "ok" else "")
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

    def _club_cast(self, panel, address: str, r):
        """Duelling Club: show the move on the caster's panel."""
        panel.canvas.set_trail(r.trail if len(r.trail) else None, False)
        snap = self.snap or {}
        if r.accepted:
            spell, element = r.spell, E.element_of(r.spell)
            incoming = snap.get("incoming") if snap.get("turn_kind") == "counter" else None
            against = E.element_of(incoming)
            sub = "attacks" if not incoming else f"blocks {incoming}" if element == E.PROTECTION \
                else f"{E.BEATS[element][against]} {incoming}" if E.beats(element, against) else ""
            panel.canvas.set_overlay(self.state.template(spell), "match")
            panel.canvas.set_title(f"✦  {spell}", GE.color(element), sub)
            info = self.state.info(spell)
            panel.canvas.burst(info.colors if info and info.colors else [GE.color(element)])
            return
        best = r.best
        panel.canvas.set_overlay(self.state.template(best.spell) if best else None,
                                 "miss" if best else None)
        again = (not r.note or r.note.startswith(("too early", "not your turn"))) \
            and snap.get("phase") == "racing" and snap.get("turn") == address
        panel.canvas.set_title(f"✗  {r.message()}", T.RED, "cast again – quickly!" if again else "")
