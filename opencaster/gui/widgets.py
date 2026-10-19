"""Reusable widgets: backdrop, cards, flow layout, pads, connection pill, spell art."""

import random
from typing import Optional

import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap, QRadialGradient)
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLayout, QSizePolicy, QVBoxLayout,
                               QWidget)

from . import theme as T
from .glyph import draw_glyph, fit


# ── Containers ─────────────────────────────────────────────────────────────────

class Backdrop(QWidget):
    """Violet-to-navy night sky with a cached starfield."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cache: Optional[QPixmap] = None

    def resizeEvent(self, e):
        self._cache = None
        super().resizeEvent(e)

    def _render(self) -> QPixmap:
        pm = QPixmap(self.size())
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0.0, QColor(T.BG_TOP))
        g.setColorAt(0.55, QColor("#120c2a"))
        g.setColorAt(1.0, QColor(T.BG_BOTTOM))
        p.fillRect(pm.rect(), g)
        # faint nebula glow
        r = QRadialGradient(self.width() * 0.78, self.height() * 0.05, self.width() * 0.55)
        r.setColorAt(0, T.qcolor("#6d3fc4", 0.20))
        r.setColorAt(1, T.qcolor("#6d3fc4", 0.0))
        p.fillRect(pm.rect(), r)
        rng = random.Random(7)
        p.setPen(Qt.NoPen)
        for _ in range(int(self.width() * self.height() / 2600)):
            x, y = rng.random() * self.width(), rng.random() ** 1.6 * self.height()
            a = rng.uniform(0.15, 0.75) * (1 - y / self.height() * 0.6)
            s = rng.choice((0.6, 0.8, 1.0, 1.0, 1.4))
            p.setBrush(T.qcolor("#ffffff" if rng.random() > 0.2 else T.GOLD, a))
            p.drawEllipse(QPointF(x, y), s, s)
        p.end()
        return pm

    def paintEvent(self, _e):
        if self._cache is None or self._cache.size() != self.size():
            self._cache = self._render()
        QPainter(self).drawPixmap(0, 0, self._cache)


def card(title: Optional[str] = None, margins=(16, 14, 16, 14), spacing=10) -> tuple:
    """A rounded translucent panel; returns (frame, inner VBox layout)."""
    f = QFrame()
    f.setObjectName("Card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(*margins)
    lay.setSpacing(spacing)
    if title:
        lay.addWidget(section(title))
    return f, lay


def section(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setObjectName("Section")
    return lbl


class FlowLayout(QLayout):
    """Lays children left-to-right, wrapping to new rows (Qt's flow example)."""

    def __init__(self, parent=None, spacing: int = 8, center: bool = False):
        super().__init__(parent)
        self._items = []
        self._space = spacing
        self._center = center

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._layout(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _layout(self, rect, apply: bool) -> int:
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        rows, row, x = [], [], r.x()
        for it in self._items:
            if it.widget() and it.widget().isHidden():
                continue
            w = it.sizeHint().width()
            if row and x + w > r.right() + 1:
                rows.append(row)
                row, x = [], r.x()
            row.append(it)
            x += w + self._space
        if row:
            rows.append(row)
        y = r.y()
        for row in rows:
            used = sum(it.sizeHint().width() for it in row) + self._space * (len(row) - 1)
            x = r.x() + (max(0, r.width() - used) // 2 if self._center else 0)
            row_h = max(it.sizeHint().height() for it in row)
            for it in row:
                hint = it.sizeHint()
                if apply:
                    it.setGeometry(QRect(x, y, hint.width(), hint.height()))
                x += hint.width() + self._space
            y += row_h + self._space
        return (y - self._space if rows else y) - rect.y() + m.bottom()

    def clear(self):
        while self._items:
            it = self._items.pop()
            if it.widget():
                it.widget().deleteLater()


# ── Status widgets ─────────────────────────────────────────────────────────────

class SensorPads(QWidget):
    """The wand's four touch pads as glowing orbs.  Click one to force it on
    (workaround for a broken sensor); forced pads get a gold ring."""
    toggled = Signal(int)

    def __init__(self, parent=None, radius: float = 17):
        super().__init__(parent)
        self.mask = 0
        self.overrides = 0
        self.radius = radius
        self.setMinimumHeight(int(radius * 3.8))
        if radius < 14:
            self.setFixedWidth(int(radius * 2 * 4 + radius * 1.4 * 5))
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Touch pads 1-4.  Hold all four to cast.\n"
                        "Click a pad to force it on (for a faulty sensor).")

    def set_state(self, mask: int, overrides: Optional[int] = None):
        self.mask = mask
        if overrides is not None:
            self.overrides = overrides
        self.update()

    def _centres(self):
        n, r = 4, self.radius
        gap = (self.width() - 2 * r * n) / (n + 1)
        return [QPointF(gap + r + i * (2 * r + gap), self.height() / 2) for i in range(n)], r

    def mousePressEvent(self, e):
        centres, r = self._centres()
        for i, c in enumerate(centres):
            if (QPointF(e.position()) - c).manhattanLength() <= r * 1.6:
                self.overrides ^= 1 << i
                self.toggled.emit(i)
                self.update()
                return

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        centres, r = self._centres()
        # the wand body linking the pads
        p.setPen(QPen(T.qcolor("#ffffff", 0.08), 6, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(centres[0], centres[-1])
        for i, c in enumerate(centres):
            lit = bool(self.mask & (1 << i))
            col = QColor(T.PAD_COLORS[i])
            if lit:
                g = QRadialGradient(c, r * 2.1)
                g.setColorAt(0, T.qcolor(T.PAD_COLORS[i], 0.55))
                g.setColorAt(1, T.qcolor(T.PAD_COLORS[i], 0.0))
                p.setPen(Qt.NoPen)
                p.setBrush(g)
                p.drawEllipse(c, r * 2.1, r * 2.1)
                fill = QRadialGradient(c - QPointF(r * 0.3, r * 0.3), r * 1.2)
                fill.setColorAt(0, col.lighter(160))
                fill.setColorAt(1, col)
                p.setBrush(fill)
            else:
                p.setBrush(T.qcolor("#ffffff", 0.06))
            forced = bool(self.overrides & (1 << i))
            p.setPen(QPen(QColor(T.GOLD), 2.2) if forced else
                     QPen(T.qcolor("#ffffff", 0.16 if not lit else 0.0), 1))
            p.drawEllipse(c, r, r)
            if r >= 12:
                p.setPen(QColor("#160f26") if lit else T.qcolor(T.TEXT_FAINT))
                p.setFont(T.font(9, bold=True))
                p.drawText(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), Qt.AlignCenter, str(i + 1))


class StatusDot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.color = QColor(T.RED)
        self.setFixedSize(14, 14)

    def set_color(self, c: str):
        self.color = QColor(c)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(7, 7)
        g = QRadialGradient(c, 7)
        glow = QColor(self.color)
        glow.setAlphaF(0.45)
        g.setColorAt(0, glow)
        g.setColorAt(1, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, 7, 7)
        p.setBrush(self.color)
        p.drawEllipse(c, 3.6, 3.6)


class ConnectionPill(QFrame):
    """A wand in the header: ● (its colour) name  battery.  Click for its
    settings.  Also used as the "Searching… / No wand" placeholder."""
    clicked = Signal(str)

    def __init__(self, address: str = "", parent=None):
        super().__init__(parent)
        self.address = address
        self.setObjectName("Card")
        self.setStyleSheet("QFrame#Card { border-radius: 14px; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 5, 14, 5)
        lay.setSpacing(8)
        self.dot = StatusDot()
        self.name = QLabel("No wand")
        self.name.setFont(T.font(10, bold=True))
        self.battery = QLabel("")
        self.battery.setObjectName("Dim")
        for w in (self.dot, self.name, self.battery):
            lay.addWidget(w)
        if address:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip("Wand settings: nickname, colour, calibration, disconnect")

    def mouseReleaseEvent(self, e):
        if self.address and e.button() == Qt.LeftButton:
            self.clicked.emit(self.address)

    def set_wand(self, info: dict):
        state = "ready" if info.get("ready") else "connected" if info.get("connected") else "connecting"
        self.dot.set_color(info.get("color", T.TEAL) if state == "ready" else
                           T.AMBER if state != "ready" else T.TEAL)
        self.name.setText(info.get("label") or info.get("name") or self.address)
        self.name.setStyleSheet("" if info.get("connected") else f"color: {T.TEXT_DIM};")
        pct = info.get("battery")
        self.battery.setText(f"▮ {pct}%" if pct is not None and info.get("connected") else
                             "" if info.get("connected") else "reconnecting…")
        self.battery.setStyleSheet(f"color: {T.RED if pct is not None and pct < 20 else T.TEXT_DIM};")

    def set_state(self, state: str, text: str = ""):
        self.dot.set_color({"scanning": T.AMBER, "connecting": T.AMBER}.get(state, T.RED))
        self.name.setText(text or {"scanning": "Searching…", "connecting": "Connecting…"}
                          .get(state, "No wand"))
        self.battery.setText("")


class ColorSwatch(QWidget):
    """A clickable colour chip (opens a colour picker)."""
    picked = Signal(str)

    def __init__(self, color: str = "#0000FF", parent=None, title: str = "Choose a colour"):
        super().__init__(parent)
        self.color = color
        self.title = title
        self.setFixedSize(46, 28)
        self.setCursor(Qt.PointingHandCursor)

    def set_color(self, color: str):
        self.color = color
        self.update()

    def mouseReleaseEvent(self, e):
        from PySide6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(QColor(self.color), self, self.title)
        if c.isValid():
            self.set_color(c.name().upper())
            self.picked.emit(self.color)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        g = QRadialGradient(r.center(), r.width() * 0.7)
        g.setColorAt(0, QColor(self.color).lighter(130))
        g.setColorAt(1, QColor(self.color))
        p.setBrush(g)
        p.setPen(QPen(T.qcolor("#ffffff", 0.35), 1.2))
        p.drawRoundedRect(r, 9, 9)


# ── Particles ──────────────────────────────────────────────────────────────────

class Particles:
    """A tiny particle system for sparkles, spell bursts and confetti.

    The owner widget calls step() from its paint (or a timer) and paint()
    after drawing; `active` tells it whether to keep animating, so nothing
    ticks while there is nothing to show."""

    def __init__(self):
        self.items: list = []           # [x, y, vx, vy, life, max_life, colour, size, gravity]
        self._rng = random.Random()

    @property
    def active(self) -> bool:
        return bool(self.items)

    def burst(self, x: float, y: float, colors, n: int = 70, speed: float = 260.0,
              life: float = 1.3, size: float = 3.0, gravity: float = 60.0):
        for _ in range(n):
            a = self._rng.uniform(0, 6.2832)
            v = speed * self._rng.uniform(0.25, 1.0)
            ttl = life * self._rng.uniform(0.6, 1.0)
            self.items.append([x, y, v * np.cos(a), v * np.sin(a), ttl, ttl,
                               QColor(self._rng.choice(colors)), size * self._rng.uniform(0.5, 1.3),
                               gravity])

    def sparkle(self, x: float, y: float, color, n: int = 3):
        for _ in range(n):
            ttl = self._rng.uniform(0.35, 0.7)
            self.items.append([x + self._rng.uniform(-3, 3), y + self._rng.uniform(-3, 3),
                               self._rng.uniform(-40, 40), self._rng.uniform(-60, 10), ttl, ttl,
                               QColor(color if self._rng.random() > 0.3 else "#FFF6D8"),
                               self._rng.uniform(1.0, 2.4), 30.0])

    def confetti(self, width: float, colors, n: int = 140):
        for _ in range(n):
            ttl = self._rng.uniform(2.0, 3.4)
            self.items.append([self._rng.uniform(0, width), self._rng.uniform(-60, 0),
                               self._rng.uniform(-30, 30), self._rng.uniform(60, 160), ttl, ttl,
                               QColor(self._rng.choice(colors)), self._rng.uniform(2.0, 4.0), 20.0])

    def step(self, dt: float):
        keep = []
        for it in self.items:
            it[4] -= dt
            if it[4] <= 0:
                continue
            it[0] += it[2] * dt
            it[1] += it[3] * dt
            it[2] *= 0.985
            it[3] = it[3] * 0.985 + it[8] * dt
            keep.append(it)
        self.items = keep

    def paint(self, p: QPainter):
        p.setPen(Qt.NoPen)
        for x, y, _vx, _vy, life, max_life, col, size, _g in self.items:
            k = life / max_life
            c = QColor(col)
            c.setAlphaF(min(1.0, k * 1.4) * 0.9)
            p.setBrush(c)
            p.drawEllipse(QPointF(x, y), size * (0.4 + 0.6 * k), size * (0.4 + 0.6 * k))


class Animator:
    """Drives a widget's repaints at ~60 fps only while something animates."""

    def __init__(self, widget: QWidget):
        from PySide6.QtCore import QElapsedTimer, QTimer
        self.widget = widget
        self.timer = QTimer(widget)
        self.timer.setInterval(16)
        self.timer.timeout.connect(widget.update)
        self.clock = QElapsedTimer()
        self.clock.start()
        self._last = 0

    def kick(self):
        if not self.timer.isActive():
            self._last = self.clock.elapsed()
            self.timer.start()

    def dt(self, still_active: bool) -> float:
        """Seconds since the last frame; stops the timer when idle."""
        now = self.clock.elapsed()
        dt = min(0.05, (now - self._last) / 1000) if self._last else 0.016
        self._last = now
        if not still_active:
            self.timer.stop()
            self._last = 0
        return dt


# ── Spell art ──────────────────────────────────────────────────────────────────

def paint_spell_art(p: QPainter, rect: QRectF, color, outline: Optional[np.ndarray],
                    seed: str, radius: float, glyph_rect: Optional[QRectF] = None,
                    glyph_width: float = 3.0, border: Optional[QColor] = None,
                    icon: Optional[QImage] = None):
    """Card background in the spell's cast colours (or a tinted dark colour),
    with magic dust and the white gesture glyph: the spell's original icon
    PNG if there is one, else its SVG outline."""
    top, middle, bottom, glow = T.card_colors(color)
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    p.save()
    p.setClipPath(path)
    g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    g.setColorAt(0, top)
    g.setColorAt(0.5, middle)
    g.setColorAt(1, bottom)
    p.fillRect(rect, g)
    gr = glyph_rect or rect
    halo = QRadialGradient(gr.center(), max(gr.width(), gr.height()) * 0.62)
    halo.setColorAt(0, T.qcolor(glow.name(), 0.30))
    halo.setColorAt(1, T.qcolor(glow.name(), 0.0))
    p.fillRect(rect, halo)
    rng = random.Random(seed)
    p.setPen(Qt.NoPen)
    for _ in range(int(rect.width() * rect.height() / 650)):
        x = rect.left() + rng.random() * rect.width()
        y = rect.top() + rng.random() * rect.height()
        p.setBrush(T.qcolor("#ffffff" if rng.random() > 0.35 else glow.name(), rng.uniform(0.08, 0.5)))
        s = rng.uniform(0.4, 1.3)
        p.drawEllipse(QPointF(x, y), s, s)
    shade = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    shade.setColorAt(0.55, QColor(0, 0, 0, 0))
    shade.setColorAt(1, QColor(0, 0, 0, 120))
    p.fillRect(rect, shade)
    if icon is not None:
        size = icon.size().scaled(gr.size().toSize(), Qt.KeepAspectRatio)
        target = QRectF(0, 0, size.width(), size.height())
        target.moveCenter(gr.center())
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(target, icon)
    elif outline is not None and len(outline) >= 2:
        pts = fit(outline, gr, pad=glyph_width * 3)
        draw_glyph(p, pts, QColor("#ffffff"), glyph_width, glow=glow)
    p.restore()
    if border is not None:
        p.setPen(QPen(border, 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect.adjusted(0.75, 0.75, -0.75, -0.75), radius, radius)


class SpellCard(QWidget):
    """Spellbook grid card: tinted art, glyph, serif name, mastery star."""
    clicked = Signal(str)
    W, H = 168, 236

    def __init__(self, name: str, color: str, outline, mastered: bool = False,
                 icon: Optional[QImage] = None, parent=None):
        super().__init__(parent)
        self.name, self.color, self.outline, self.mastered = name, color, outline, mastered
        self.icon = icon
        self._lift = 0.0                 # 0 → 1 while hovered (animated)
        self._anim = None
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(name)

    def sizeHint(self):
        return QSize(self.W, self.H)

    def _animate_to(self, target: float):
        from PySide6.QtCore import QEasingCurve, QVariantAnimation
        if self._anim:
            self._anim.stop()
        self._anim = QVariantAnimation(self, startValue=self._lift, endValue=target, duration=140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(lambda v: (setattr(self, "_lift", float(v)), self.update()))
        self._anim.start()

    def enterEvent(self, _e):
        self._animate_to(1.0)

    def leaveEvent(self, _e):
        self._animate_to(0.0)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit(self.name)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        k = self._lift
        r = QRectF(self.rect()).adjusted(2, 2 + 3 * (1 - k), -2, -2 - 3 * k)
        glyph = QRectF(r.left() + 18, r.top() + 22, r.width() - 36, r.height() * 0.58)
        border = QColor(T.GOLD)
        border.setAlphaF(0.10 + 0.75 * k)
        paint_spell_art(p, r, self.color, self.outline, self.name, 16, glyph, 2.6,
                        border=border, icon=self.icon)
        p.setPen(QColor("#ffffff"))
        p.setFont(T.font(12.5, serif=True))
        p.drawText(QRectF(r.left() + 8, r.bottom() - 62, r.width() - 16, 52),
                   Qt.AlignHCenter | Qt.AlignVCenter | Qt.TextWordWrap, self.name)
        if self.mastered:
            draw_star(p, QPointF(r.right() - 18, r.top() + 18), 8)


def draw_star(p: QPainter, c: QPointF, r: float):
    pts = []
    for i in range(10):
        a = -np.pi / 2 + i * np.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append(QPointF(c.x() + rr * np.cos(a), c.y() + rr * np.sin(a)))
    path = QPainterPath(pts[0])
    for q in pts[1:]:
        path.lineTo(q)
    path.closeSubpath()
    p.setPen(QPen(QColor("#5b4210"), 1))
    p.setBrush(QColor(T.GOLD))
    p.drawPath(path)


class SpellArt(QWidget):
    """Large art panel (last spell, spell detail): tinted art + glyph, with
    optional name / pronunciation drawn over the lower part."""

    def __init__(self, parent=None, show_text: bool = True, glyph_width: float = 3.4):
        super().__init__(parent)
        self.name, self.color, self.outline, self.pronunciation = "", "#2a1f4a", None, ""
        self.icon: Optional[QImage] = None
        self.show_text = show_text
        self.glyph_width = glyph_width
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_spell(self, name: str, color: str, outline, pronunciation: str = "",
                  icon: Optional[QImage] = None):
        self.name, self.color, self.outline, self.pronunciation = name, color, outline, pronunciation
        self.icon = icon
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        text_h = r.height() * 0.30 if self.show_text and self.name else 0
        side = min(r.width() - 40, r.height() - text_h - 30)
        glyph = QRectF(r.center().x() - side / 2, r.top() + 18, side, side)
        paint_spell_art(p, r, self.color, self.outline, self.name or "empty", 18, glyph,
                        self.glyph_width, border=T.qcolor("#ffffff", 0.10), icon=self.icon)
        if not text_h:
            return
        p.setPen(QColor("#ffffff"))
        big = max(14.0, min(30.0, r.width() / 11))
        p.setFont(T.font(big, serif=True))
        name_r = QRectF(r.left() + 10, r.bottom() - text_h, r.width() - 20, text_h * 0.58)
        p.drawText(name_r, Qt.AlignHCenter | Qt.AlignBottom | Qt.TextWordWrap, self.name)
        if self.pronunciation:
            p.setPen(T.qcolor("#ffffff", 0.78))
            p.setFont(T.font(max(9.0, big * 0.42), italic=True))
            p.drawText(QRectF(r.left() + 10, name_r.bottom() + 4, r.width() - 20, text_h * 0.4),
                       Qt.AlignHCenter | Qt.AlignTop, self.pronunciation)
