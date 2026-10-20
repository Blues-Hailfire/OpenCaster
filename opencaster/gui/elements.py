"""Element badges for the elemental duels (clash, Duelling Club): icons, the
who-beats-whom wheel, a legend of which spells belong to each element, and
the small type icon on spellbook cards."""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF, QRadialGradient
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

from .. import elements as E
from . import theme as T

COLORS = {E.FIRE: "#FF7A2F", E.EXPLOSIVE: "#FFD34D", E.BINDING: "#C08CFF",
          E.LOCOMOTIVE: "#5EEAD4", E.WATER: "#59B7FF", E.PROTECTION: "#DCE6FF"}

# Around the wheel each element beats the next two (a balanced cycle).
WHEEL = (E.FIRE, E.BINDING, E.LOCOMOTIVE, E.EXPLOSIVE, E.WATER)


def color(element) -> str:
    return COLORS.get(element, T.TEXT_DIM)


def draw_icon(p: QPainter, element: str, c: QPointF, r: float, col=None, glow: bool = True,
              outline: bool = False):
    """A small vector icon for an element, centred on c, about 2r across.
    With outline, every shape is a thin line: nothing is filled."""
    col = QColor(col or color(element))
    p.save()
    if glow:
        g = QRadialGradient(c, r * 1.6)
        g.setColorAt(0, T.qcolor(col.name(), 0.35))
        g.setColorAt(1, T.qcolor(col.name(), 0.0))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, r * 1.6, r * 1.6)
    x, y = c.x(), c.y()
    pen = QPen(col, max(1.0, r * 0.13) if outline else max(1.4, r * 0.16), Qt.SolidLine, Qt.RoundCap,
               Qt.RoundJoin)

    def solid(fill=None):
        p.setPen(pen if outline else Qt.NoPen)
        p.setBrush(Qt.NoBrush if outline else (fill or col))

    if element == E.FIRE and outline:
        # a leaning tip and a tongue on the left, so it doesn't read as a water drop
        outer = QPainterPath(QPointF(x + r * 0.15, y - r))
        outer.cubicTo(x - r * 0.05, y - r * 0.6, x + r * 0.75, y - r * 0.35, x + r * 0.72, y + r * 0.3)
        outer.cubicTo(x + r * 0.7, y + r * 0.8, x - r * 0.7, y + r * 0.8, x - r * 0.72, y + r * 0.3)
        outer.cubicTo(x - r * 0.74, y - r * 0.05, x - r * 0.55, y - r * 0.3, x - r * 0.5, y - r * 0.55)
        outer.cubicTo(x - r * 0.3, y - r * 0.3, x - r * 0.2, y - r * 0.3, x - r * 0.12, y - r * 0.38)
        outer.cubicTo(x - r * 0.15, y - r * 0.6, x, y - r * 0.85, x + r * 0.15, y - r)
        solid()
        p.drawPath(outer)
    elif element == E.FIRE:
        outer = QPainterPath(QPointF(x, y - r))
        outer.cubicTo(x + r * 0.2, y - r * 0.45, x + r * 0.85, y - r * 0.2, x + r * 0.7, y + r * 0.35)
        outer.cubicTo(x + r * 0.55, y + r * 0.85, x - r * 0.55, y + r * 0.85, x - r * 0.7, y + r * 0.35)
        outer.cubicTo(x - r * 0.8, y - r * 0.05, x - r * 0.35, y - r * 0.25, x - r * 0.3, y - r * 0.55)
        outer.cubicTo(x - r * 0.1, y - r * 0.4, x - r * 0.05, y - r * 0.7, x, y - r)
        solid()
        p.drawPath(outer)
        inner = QPainterPath(QPointF(x, y - r * 0.15))
        inner.cubicTo(x + r * 0.35, y + r * 0.15, x + r * 0.35, y + r * 0.6, x, y + r * 0.62)
        inner.cubicTo(x - r * 0.35, y + r * 0.6, x - r * 0.3, y + r * 0.2, x, y - r * 0.15)
        solid(QColor("#FFF1C9"))
        p.drawPath(inner)
    elif element == E.EXPLOSIVE:
        pts = []
        for i in range(16):
            a = -math.pi / 2 + i * math.pi / 8
            rr = r if i % 2 == 0 else r * (0.42 if i % 4 == 1 else 0.55)
            pts.append(QPointF(x + rr * math.cos(a), y + rr * math.sin(a)))
        solid()
        p.drawPolygon(QPolygonF(pts))
        if not outline:
            solid(QColor("#FFFBEA"))
            p.drawEllipse(c, r * 0.28, r * 0.28)
    elif element == E.BINDING:
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        for dx, ang in ((-0.28, -35), (0.28, -35)):
            p.save()
            p.translate(x + dx * r, y)
            p.rotate(ang)
            p.drawRoundedRect(QRectF(-r * 0.55, -r * 0.28, r * 1.1, r * 0.56), r * 0.28, r * 0.28)
            p.restore()
    elif element == E.LOCOMOTIVE:
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        for dy, k in ((-0.45, 0.75), (0.0, 1.0), (0.45, 0.6)):
            path = QPainterPath(QPointF(x - r * k, y + dy * r))
            path.cubicTo(x - r * k * 0.3, y + dy * r - r * 0.18, x + r * 0.2, y + dy * r + r * 0.18,
                         x + r * 0.75, y + dy * r)
            p.drawPath(path)
        p.drawLine(QPointF(x + r * 0.75, y), QPointF(x + r * 0.42, y - r * 0.25))
        p.drawLine(QPointF(x + r * 0.75, y), QPointF(x + r * 0.42, y + r * 0.25))
    elif element == E.WATER:
        drop = QPainterPath(QPointF(x - r * 0.15, y - r))
        drop.cubicTo(x + r * 0.15, y - r * 0.45, x + r * 0.6, y - r * 0.05, x + r * 0.55, y + r * 0.35)
        drop.cubicTo(x + r * 0.5, y + r * 0.95, x - r * 0.8, y + r * 0.95, x - r * 0.75, y + r * 0.35)
        drop.cubicTo(x - r * 0.72, y - r * 0.05, x - r * 0.35, y - r * 0.45, x - r * 0.15, y - r)
        solid()
        p.drawPath(drop)
        if not outline:                  # too small to read as a line drawing
            p.setBrush(T.qcolor("#FFFFFF", 0.7))
            p.drawEllipse(QPointF(x - r * 0.38, y + r * 0.3), r * 0.12, r * 0.2)
            # a small snowflake for ice
            p.setPen(QPen(QColor("#E8F6FF"), max(1.0, r * 0.1), Qt.SolidLine, Qt.RoundCap))
            sc = QPointF(x + r * 0.7, y - r * 0.65)
            for i in range(3):
                a = i * math.pi / 3
                d = QPointF(math.cos(a) * r * 0.28, math.sin(a) * r * 0.28)
                p.drawLine(sc - d, sc + d)
    elif element == E.PROTECTION:
        shield = QPainterPath(QPointF(x, y - r))
        shield.cubicTo(x + r * 0.45, y - r * 0.75, x + r * 0.85, y - r * 0.8, x + r * 0.85, y - r * 0.8)
        shield.cubicTo(x + r * 0.9, y + r * 0.1, x + r * 0.5, y + r * 0.7, x, y + r)
        shield.cubicTo(x - r * 0.5, y + r * 0.7, x - r * 0.9, y + r * 0.1, x - r * 0.85, y - r * 0.8)
        shield.cubicTo(x - r * 0.85, y - r * 0.8, x - r * 0.45, y - r * 0.75, x, y - r)
        if outline:
            solid()
        else:
            p.setPen(QPen(col.lighter(110), max(1.2, r * 0.1)))
            p.setBrush(T.qcolor(col.name(), 0.35))
        p.drawPath(shield)
        if not outline:
            p.setPen(QPen(col, max(1.2, r * 0.12), Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(x, y - r * 0.55), QPointF(x, y + r * 0.55))
            p.drawLine(QPointF(x - r * 0.45, y - r * 0.15), QPointF(x + r * 0.45, y - r * 0.15))
    p.restore()


def describe(element) -> str:
    """One line on what the element does in a duel."""
    if element is None:
        return "Utility spell – not used in duels"
    if element == E.PROTECTION:
        return "Protection – blocks any attack"
    return f"{E.NAMES[element]} – beats " + " and ".join(E.NAMES[b] for b in E.BEATS[element])


def draw_badge(p: QPainter, element, centre: QPointF, r: float = 6.5, alpha: float = 0.6):
    """A quiet mark for a spell's element: its icon in thin outline.
    Utility spells (no element) get none."""
    if element is None:
        return
    p.save()
    p.setOpacity(alpha)
    draw_icon(p, element, centre, r, glow=False, outline=True)
    p.restore()


def paint_wheel(p: QPainter, rect: QRectF, alpha: float = 1.0, labels: bool = True):
    """The five attack elements on a circle, arrows from each to the two it
    beats, and the shield in the middle."""
    c = rect.center()
    R = min(rect.width(), rect.height()) * (0.32 if labels else 0.38)
    node = R * 0.26
    pos = {e: QPointF(c.x() + R * math.sin(i * 2 * math.pi / 5),
                      c.y() - R * math.cos(i * 2 * math.pi / 5)) for i, e in enumerate(WHEEL)}
    p.save()
    p.setOpacity(alpha)
    for i, a in enumerate(WHEEL):
        for step in (1, 2):
            b = WHEEL[(i + step) % 5]
            _arrow(p, pos[a], pos[b], node * 1.25, color(a), 1.6 if step == 1 else 1.2,
                   0.55 if step == 1 else 0.35)
    for e, q in pos.items():
        p.setPen(QPen(T.qcolor(color(e), 0.6), 1.2))
        p.setBrush(QColor("#140d28"))
        p.drawEllipse(q, node, node)
        draw_icon(p, e, q, node * 0.58, glow=False)
        if labels:                       # above the top node, under the others
            p.setPen(T.qcolor(color(e), 0.9))
            p.setFont(T.font(max(7.0, node * 0.34), bold=True))
            dy = -node * 1.5 if e == WHEEL[0] else node * 1.5
            p.drawText(QRectF(q.x() - node * 3, q.y() + dy - node * 0.5, node * 6, node),
                       Qt.AlignCenter, E.NAMES[e].split("/")[0].upper())
    draw_icon(p, E.PROTECTION, c, node * 0.75)
    p.restore()


def _arrow(p: QPainter, a: QPointF, b: QPointF, inset: float, col: str, width: float, alpha: float):
    d = b - a
    length = math.hypot(d.x(), d.y())
    if length < inset * 2.2:
        return
    u = QPointF(d.x() / length, d.y() / length)
    start, end = a + u * inset, b - u * inset
    p.setPen(QPen(T.qcolor(col, alpha), width, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(start, end)
    n = QPointF(-u.y(), u.x())
    head = 7 + width * 2
    p.setPen(Qt.NoPen)
    p.setBrush(T.qcolor(col, min(1.0, alpha + 0.3)))
    p.drawPolygon(QPolygonF([end, end - u * head + n * head * 0.5, end - u * head - n * head * 0.5]))


class ElementWheel(QWidget):
    def __init__(self, parent=None, size: int = 220):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        paint_wheel(p, QRectF(self.rect()))


class ElementIcon(QWidget):
    def __init__(self, element: str, size: int = 26, parent=None):
        super().__init__(parent)
        self.element = element
        self.setFixedSize(size, size)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        draw_icon(p, self.element, QPointF(self.width() / 2, self.height() / 2), self.width() * 0.36,
                  glow=False)


def legend(spell_ok=lambda name: True) -> QWidget:
    """A grid: icon, element, what it beats, and its spells (spells the
    library doesn't have are left out)."""
    w = QWidget()
    g = QGridLayout(w)
    g.setContentsMargins(0, 0, 0, 0)
    g.setHorizontalSpacing(12)
    g.setVerticalSpacing(8)
    for row, e in enumerate(E.ELEMENTS):
        name = QLabel(E.NAMES[e])
        name.setFont(T.font(11.5, serif=True))
        name.setStyleSheet(f"color: {color(e)};")
        if e == E.PROTECTION:
            rule = "blocks any attack"
        else:
            wins = " and ".join(E.NAMES[b] for b in E.BEATS[e])
            rule = f"beats {wins}"
        rule_l = QLabel(rule)
        rule_l.setObjectName("Dim")
        spells = QLabel()
        # Wrapped here, not by Qt: word-wrapped labels get squashed in a scrolling grid.
        lines, fm = [""], spells.fontMetrics()
        for spell in (s for s in E.SPELLS[e] if spell_ok(s)):
            item = f"{lines[-1]}, {spell}" if lines[-1] else spell
            if lines[-1] and fm.horizontalAdvance(item + ",") > 250:
                lines[-1] += ","
                lines.append(spell)
            else:
                lines[-1] = item
        spells.setText("\n".join(lines))
        spells.setStyleSheet(f"color: {T.TEXT_FAINT};")
        g.addWidget(ElementIcon(e), row, 0, Qt.AlignTop)
        g.addWidget(name, row, 1, Qt.AlignTop)
        g.addWidget(rule_l, row, 2, Qt.AlignTop)
        g.addWidget(spells, row, 3)
    g.setColumnStretch(3, 1)
    return w
