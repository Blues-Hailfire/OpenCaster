"""
Painting helpers for spell glyphs: a stroke with a start dot and an
arrowhead at the end, like the original app's gesture diagrams.
"""

from typing import Optional

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF


def fit(points: np.ndarray, rect: QRectF, pad: float = 0.0) -> np.ndarray:
    """Map y-up points into rect (y-down), preserving aspect ratio, centred."""
    lo, hi = points.min(axis=0), points.max(axis=0)
    span = float(max(hi - lo)) or 1.0
    s = (min(rect.width(), rect.height()) - 2 * pad) / span
    c = (lo + hi) / 2
    out = np.empty_like(points, dtype=float)
    out[:, 0] = rect.center().x() + (points[:, 0] - c[0]) * s
    out[:, 1] = rect.center().y() - (points[:, 1] - c[1]) * s
    return out


def path_of(screen_pts: np.ndarray) -> QPainterPath:
    path = QPainterPath(QPointF(*screen_pts[0]))
    for x, y in screen_pts[1:]:
        path.lineTo(x, y)
    return path


def arrow_head(screen_pts: np.ndarray, size: float) -> Optional[QPolygonF]:
    """Arrowhead at the path end, pointing along the last `size` of travel."""
    end = screen_pts[-1]
    back = None
    acc = 0.0
    for i in range(len(screen_pts) - 2, -1, -1):
        acc += float(np.hypot(*(screen_pts[i + 1] - screen_pts[i])))
        if acc >= size * 0.9:
            back = screen_pts[i]
            break
    if back is None:
        back = screen_pts[0]
    d = end - back
    n = float(np.hypot(*d))
    if n < 1e-6:
        return None
    d /= n
    perp = np.array([-d[1], d[0]])
    tip = end + d * size * 0.35
    left = tip - d * size + perp * size * 0.55
    right = tip - d * size - perp * size * 0.55
    return QPolygonF([QPointF(*tip), QPointF(*left), QPointF(*right)])


def draw_glyph(p: QPainter, screen_pts: np.ndarray, color: QColor, width: float,
               glow: Optional[QColor] = None, dashed: bool = False,
               dot: bool = True, arrow: bool = True):
    """Stroke with optional soft glow, start dot and end arrowhead."""
    if len(screen_pts) < 2:
        return
    path = path_of(screen_pts)
    p.setBrush(Qt.NoBrush)
    if glow is not None:
        for w, a in ((width * 5, 0.10), (width * 2.6, 0.22)):
            g = QColor(glow)
            g.setAlphaF(a)
            p.setPen(QPen(g, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)
    pen = QPen(color, width, Qt.DashLine if dashed else Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    if dashed:
        pen.setDashPattern([3.0, 2.2])
    p.setPen(pen)
    p.drawPath(path)
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(color))
    if dot:
        p.drawEllipse(QPointF(*screen_pts[0]), width * 1.9, width * 1.9)
    if arrow:
        head = arrow_head(screen_pts, max(8.0, width * 4.2))
        if head is not None:
            p.drawPolygon(head)
