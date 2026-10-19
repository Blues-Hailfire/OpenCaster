"""
TrailCanvas — the live gesture trail (tip direction in degrees), painted
with QPainter.  Repaints only when a new trail batch or overlay arrives.

View rules (kept from the original matplotlib view):
  - Mid-cast: a steady view centred on the start, sized for a typical cast,
    growing only if the stroke runs past it.
  - Finished: fitted to the trail, with the matched/closest template drawn
    over it (fitted to the trail's centroid and size).
  - Practising one spell: its template is drawn as a guide at your typical
    size for that spell, starting where the trail starts.
"""

from typing import Callable, Optional

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import theme as T
from .glyph import draw_glyph
from .widgets import Animator, Particles

TRAIL_START = np.array([0x5e, 0xea, 0xd4], float)   # teal
TRAIL_END   = np.array([0xd9, 0x6b, 0xff], float)   # violet-magenta
TITLE_FADE_S = 0.3


class TrailCanvas(QWidget):
    def __init__(self, typical: Callable[[Optional[str]], float], parent=None):
        super().__init__(parent)
        self.typical = typical
        self.trail: Optional[np.ndarray] = None
        self.live = False
        self.guide = None               # SpellTemplate being practised
        self.overlay = None             # (SpellTemplate, kind) over a finished trail
        self.title, self.title_color = "", T.TEXT
        self.subtitle = ""
        self.hint = "Hold all four pads and draw a spell"
        self.accent = T.GOLD            # the wand's colour: tip glow and sparkles
        self.fx = Particles()
        self.anim = Animator(self)
        self._title_t = 1.0             # title fade-in progress
        self._tip: Optional[QPointF] = None
        self._sparkle = False
        self._burst = None
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(240, 240)

    # ── state ─────────────────────────────────────────────────────────────────

    def set_accent(self, color: str):
        self.accent = color
        self.update()

    def set_trail(self, trail: Optional[np.ndarray], live: bool):
        self.trail, self.live = trail, live
        if live and trail is not None and len(trail) >= 2:
            self._sparkle = True
            self.anim.kick()
        self.update()

    def set_title(self, title: str, color: str = T.TEXT, subtitle: str = ""):
        if (title, subtitle) != (self.title, self.subtitle):
            self._title_t = 0.0
            self.anim.kick()
        self.title, self.title_color, self.subtitle = title, color, subtitle
        self.update()

    def burst(self, colors):
        """A burst of particles in these colours from the wand tip (or the
        centre if there is no trail): a successful spell."""
        self._burst = list(colors) or [self.accent]
        self.anim.kick()
        self.update()

    def set_overlay(self, template, kind: Optional[str]):
        self.overlay = (template, kind) if template is not None and kind else None
        self.update()

    def set_guide(self, template):
        self.guide = template
        self.update()

    # ── geometry ──────────────────────────────────────────────────────────────

    def _shapes(self) -> tuple:
        """World-space things to draw: (trail, [(points, colour, dashed)], view)."""
        trail = self.trail if self.trail is not None and len(self.trail) >= 2 else None
        shapes = []
        if self.overlay and trail is not None and not self.live:
            tmpl, kind = self.overlay
            span = float(np.ptp(tmpl.points, axis=0).max()) or 1.0
            scale = float(np.ptp(trail, axis=0).max()) / span
            shapes.append((tmpl.outline * scale + trail.mean(axis=0), T.OVERLAY[kind], True))
        elif self.guide is not None:
            span = float(np.ptp(self.guide.points, axis=0).max()) or 1.0
            start = trail[0] if trail is not None else np.zeros(2)
            pts = (self.guide.outline - self.guide.outline[0]) * (self.typical(self.guide.name) / span)
            shapes.append((pts + start, T.OVERLAY["guide"], True))

        if shapes:                                    # fit everything drawn
            both = np.vstack([s[0] for s in shapes] + ([trail] if trail is not None else []))
            lo, hi = both.min(axis=0), both.max(axis=0)
            c, half = (lo + hi) / 2, float((hi - lo).max()) / 2 * 1.15 or 5.0
        elif trail is None or self.live:              # cast view around the start
            half = self.typical(None)
            if trail is not None:
                half = max(half, float(np.abs(trail).max()) * 1.1)
            c = np.zeros(2)
        else:                                         # finished trail: fit it
            lo, hi = trail.min(axis=0), trail.max(axis=0)
            pad = float(np.abs(trail).max()) * 0.15 or 5.0
            c, half = (lo + hi) / 2, float((hi - lo).max()) / 2 + pad
        return trail, shapes, (c, max(half, 1.0))

    # ── painting ──────────────────────────────────────────────────────────────

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        top, bottom = 64, 40
        side = max(10.0, min(w - 40, h - top - bottom))
        area = QRectF((w - side) / 2, top + (h - top - bottom - side) / 2, side, side)

        trail, shapes, (c, half) = self._shapes()
        scale = side / (2 * half)

        def to_screen(pts):
            out = np.empty_like(pts, dtype=float)
            out[:, 0] = area.center().x() + (pts[:, 0] - c[0]) * scale
            out[:, 1] = area.center().y() - (pts[:, 1] - c[1]) * scale
            return out

        dt = self.anim.dt(self.fx.active or self._title_t < 1.0 or self._burst is not None)
        self._title_t = min(1.0, self._title_t + dt / TITLE_FADE_S)
        self.fx.step(dt)

        self._paint_grid(p, area, c, half, scale)
        for pts, colour, dashed in shapes:
            draw_glyph(p, to_screen(pts), T.qcolor(colour, 0.95), 2.0,
                       glow=QColor(colour), dashed=dashed)
        self._tip = None
        if trail is not None:
            screen = to_screen(trail)
            self._paint_trail(p, screen)
            self._tip = QPointF(*screen[-1])
        if self._sparkle and self._tip is not None:
            self.fx.sparkle(self._tip.x(), self._tip.y(), self.accent)
        self._sparkle = False
        if self._burst is not None:
            at = self._tip or area.center()
            self.fx.burst(at.x(), at.y(), self._burst + ["#FFFFFF"], speed=side * 0.55)
            self._burst = None
        if self.fx.active:
            self.fx.paint(p)
            self.anim.kick()
        self._paint_text(p, w, h)

    def _paint_grid(self, p: QPainter, area: QRectF, c, half: float, scale: float):
        glow = QRadialGradient(area.center(), area.width() * 0.7)
        glow.setColorAt(0, T.qcolor("#6a4bd6", 0.10))
        glow.setColorAt(1, T.qcolor("#6a4bd6", 0.0))
        p.fillRect(self.rect(), glow)
        step = 10.0 if half < 60 else 30.0
        for axis in (0, 1):
            v = np.floor((c[axis] - half) / step) * step
            while v <= c[axis] + half:
                major = abs(v) < 1e-6
                p.setPen(QPen(T.qcolor("#ffffff", 0.10 if major else 0.035), 1))
                if axis == 0:
                    x = area.center().x() + (v - c[0]) * scale
                    if area.left() <= x <= area.right():
                        p.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
                else:
                    y = area.center().y() - (v - c[1]) * scale
                    if area.top() <= y <= area.bottom():
                        p.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
                v += step
        p.setPen(T.qcolor(T.TEXT_FAINT))
        p.setFont(T.font(7.5))
        p.drawText(QRectF(area.left(), area.bottom() + 2, area.width(), 16),
                   Qt.AlignRight, f"grid {step:.0f}°")

    def _paint_trail(self, p: QPainter, pts: np.ndarray):
        n = len(pts) - 1
        cols = [QColor(*(TRAIL_START + (TRAIL_END - TRAIL_START) * (i / max(n - 1, 1))).astype(int))
                for i in range(n)]
        for width, alpha in ((9.0, 0.10), (4.5, 0.22), (2.2, 1.0)):
            for i in range(n):
                col = QColor(cols[i])
                col.setAlphaF(alpha)
                p.setPen(QPen(col, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.drawLine(QPointF(*pts[i]), QPointF(*pts[i + 1]))
        p.setPen(Qt.NoPen)
        p.setBrush(T.qcolor("#ffffff", 0.45))
        p.drawEllipse(QPointF(*pts[0]), 3.2, 3.2)
        tip = QPointF(*pts[-1])
        g = QRadialGradient(tip, 18)
        g.setColorAt(0, T.qcolor(self.accent, 0.85))
        g.setColorAt(0.35, T.qcolor(self.accent, 0.35))
        g.setColorAt(1, T.qcolor(self.accent, 0.0))
        p.setBrush(g)
        p.drawEllipse(tip, 18, 18)
        p.setBrush(QColor("#fff6d8"))
        p.drawEllipse(tip, 3.4, 3.4)

    def _paint_text(self, p: QPainter, w: int, h: int):
        k = 1 - (1 - self._title_t) ** 3              # ease-out fade and rise
        rise = 8 * (1 - k)
        if self.title:
            p.setPen(T.qcolor(self.title_color, k))
            p.setFont(T.font(19, serif=True))
            p.drawText(QRectF(12, 10 + rise, w - 24, 32), Qt.AlignHCenter | Qt.AlignVCenter,
                       self.title)
        if self.subtitle:
            p.setPen(T.qcolor(T.TEXT_DIM, k))
            p.setFont(T.font(9.5, italic=True))
            p.drawText(QRectF(12, 40 + rise, w - 24, 20), Qt.AlignHCenter | Qt.AlignVCenter,
                       self.subtitle)
        if self.hint and (self.trail is None or len(self.trail) < 2) and not self.live:
            p.setPen(T.qcolor(T.TEXT_FAINT))
            p.setFont(T.font(10, italic=True))
            p.drawText(QRectF(12, h - 34, w - 24, 24), Qt.AlignHCenter | Qt.AlignVCenter, self.hint)
