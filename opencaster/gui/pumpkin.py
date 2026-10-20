"""
The enchanted jack-o'-lantern, drawn the way the original Magic Caster art
is: flat 2D shapes and dark silhouettes in a single hue, with the spell's
effect as the one vivid colour.  The world (night sky, hills, castle, tree,
the pumpkin's body) is painted in grey levels and graded through a one-hue
gradient map whose hue follows the last spell – warm for fire, blue for
water, green for growing things – cross-fading as it changes.  The magic
(candle glow, water, ropes, shields, particles) is drawn on top in full
colour.

PumpkinScene paints an opencaster.environment.Pumpkin and plays each
spell's one-shot cues.  Event driven: the 60 fps timer runs only while
something moves (a lit candle flickers, so it runs while the jack-o'-lantern
glows) and stops when the page is hidden.  Sizes are in units of `u` (a
tenth of the scene), so it scales with the window.
"""

import math
import random
import time
from typing import Optional

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPainterPathStroker,
                           QPen, QPixmap, QPolygonF, QRadialGradient, QTransform)
from PySide6.QtWidgets import QWidget

from .. import elements as E
from ..casting.shapes import spell_key
from ..environment import (EMPTY, FALLEN, FIRE, FLOWERS, GONE, ICE, LEVITATING, VANISHED, WATER,
                           Outcome, Pumpkin)
from . import theme as T
from .widgets import Animator, Particles, draw_star

TOP_Y = -3.0                     # the lid seam, where things leave the pumpkin
PIVOT_Y = -1.6                   # centre of the body: rotation centre (fallen, dizzy …)
FADE_S = 0.9                     # hue cross-fade
STEER_DEG = 8.0                  # degrees of wand turn per u the steered pumpkin moves
GRAVITY = 24.0                   # u/s² once nothing holds it up
BOUNCE = 0.28                    # how much of its speed a landing gives back
LAND_SPEED = 2.5                 # u/s: slower than this it just settles
# Body lobes, back to front: centre x, y, radii (u), grey level (lit from the upper left)
LOBES = ((-1.3, -1.52, 1.05, 1.45, 0.36), (1.3, -1.52, 1.05, 1.45, 0.27),
         (-0.62, -1.6, 1.0, 1.58, 0.46), (0.62, -1.6, 1.0, 1.58, 0.37), (0.0, -1.62, 0.86, 1.62, 0.5))
STONE_LOBES = (0.42, 0.36, 0.47, 0.42, 0.5)
BODY_BOX = (-2.7, -4.3, 5.4, 4.65)             # x, y, w, h (u) of the cached body image
FLOWER_COLOURS = ("#ff8fb3", "#ffffff", "#c9a6ff", "#ffd36e", "#ff5f7a", "#9fd8ff", "#ffb36b")
LEAF_COLOURS = ("#c8642a", "#e09a3a", "#8a3b1c", "#b8542a", "#f0b04a")
PULP_COLOURS = ("#ff8a2a", "#e8661c", "#ffb35c", "#f3e2b0")

# Smashed pieces: polygons (u) over the pumpkin, and where each comes to rest
SHARDS = (
    ((-2.7, -4.3), (0.2, -4.3), (0.0, -3.0), (-0.6, -2.2), (-2.7, -2.0)),
    ((0.2, -4.3), (2.7, -4.3), (2.7, -2.4), (1.0, -2.0), (0.0, -3.0)),
    ((-2.7, -2.0), (-0.6, -2.2), (0.3, -1.4), (-0.4, -0.6), (-2.7, -0.8)),
    ((-0.6, -2.2), (0.0, -3.0), (1.0, -2.0), (2.7, -2.4), (2.7, -0.9), (0.3, -1.4)),
    ((-2.7, -0.8), (-0.4, -0.6), (0.3, -1.4), (2.7, -0.9), (2.7, 0.35), (-2.7, 0.35)),
)
SCATTER = ((-3.0, 2.75, -62, 0.55), (3.1, 2.75, 70, 0.55), (-2.1, 1.2, -24, 0.7), (2.0, 1.7, 28, 0.7),
           (0.0, 0.0, 0, 1.0))                  # dx, dy (u), turn, shrink as it flies off

CUE_S = {"launch": 1.8, "summon": 1.2, "strain": 0.6, "gust": 1.3, "fling": 1.0, "knock": 0.8,
         "shock": 0.9, "zap": 0.35, "finite": 0.9, "block": 0.8, "blast": 0.4, "light": 0.5,
         "traces": 4.5, "spill": 3.5, "recolour": 0.8, "freeze": 0.8}

# The scene's hue (degrees, saturation) after each spell: the original's
# purple night, or the colour family of the spell's effect.
NIGHT = (268.0, 0.70)
LANTERN = {"orange": (24.0, 0.85), "green": (125.0, 0.7)}     # a lit pumpkin's own hue
ELEMENT_GRADES = {E.FIRE: (16.0, 0.78), E.EXPLOSIVE: (30.0, 0.8), E.BINDING: (292.0, 0.55),
                  E.LOCOMOTIVE: (176.0, 0.5), E.WATER: (214.0, 0.72), E.PROTECTION: (218.0, 0.45)}
SPELL_GRADES = {
    "verdimillious": (130.0, 0.6), "glacius": (192.0, 0.5), "petrificustotalus": (240.0, 0.08),
    "expectopatronum": (196.0, 0.35), "salviohexia": (40.0, 0.5), "lumos": (226.0, 0.75),
    "nox": (245.0, 0.18), "orchideous": (128.0, 0.5), "herbivicus": (118.0, 0.55),
    "cantis": (318.0, 0.55), "quietus": (318.0, 0.4), "silencio": (250.0, 0.25),
    "rictusempra": (330.0, 0.55), "thecheeringcharm": (335.0, 0.5), "riddikulus": (300.0, 0.55),
    "thesleepingcharm": (238.0, 0.55), "confundo": (282.0, 0.55), "evanesco": (262.0, 0.35),
    "finite": (262.0, 0.35), "reparo": (186.0, 0.45), "scourgify": (190.0, 0.4),
    "alohomora": (40.0, 0.6), "aberto": (40.0, 0.6), "colloportus": (40.0, 0.6),
    "apparevestigium": (44.0, 0.55), "colovaria": None,          # None: keep the hue
}


def grade_for(out: Outcome, current: tuple) -> tuple:
    """The scene hue that shows off a cast's effect."""
    if out.blocked:
        return ELEMENT_GRADES[E.PROTECTION] if "block" in out.fx else current
    key = spell_key(out.spell)
    if key in SPELL_GRADES:
        return SPELL_GRADES[key] or current
    return ELEMENT_GRADES.get(E.element_of(out.spell), NIGHT)


def _mix_grade(a: tuple, b: tuple, k: float) -> tuple:
    d = (b[0] - a[0] + 540.0) % 360.0 - 180.0
    return (a[0] + d * k) % 360.0, a[1] + (b[1] - a[1]) * k


def _tone(grade: tuple, level: float) -> tuple:
    """Value and saturation of a grey level in the graded image: darks keep
    the hue, highlights fade towards a pale tint."""
    v = min(1.0, level * 1.05)
    s = grade[1] * (1 - 0.8 * min(1.0, max(0.0, (level - 0.6) / 0.4)) ** 1.5)
    return v, s


def ink(grade: tuple, level: float, alpha: float = 1.0) -> QColor:
    """A grey level as it looks after grading."""
    v, s = _tone(grade, max(0.0, min(1.0, level)))
    return QColor.fromHsvF((grade[0] % 360) / 360, s, v, max(0.0, min(1.0, alpha)))


def _lut(grade: tuple) -> np.ndarray:
    """The gradient map: 256 grey levels → RGB."""
    level = np.arange(256) / 255.0
    v = np.clip(level * 1.05, 0, 1)
    s = grade[1] * (1 - 0.8 * np.clip((level - 0.6) / 0.4, 0, 1) ** 1.5)
    h6 = (grade[0] % 360) / 60.0
    i, f = int(h6) % 6, h6 - int(h6)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    r, g, b = ((v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q))[i]
    return (np.stack([r, g, b], 1) * 255 + 0.5).astype(np.uint8)


def _grey_canvas(w: int, h: int, dpr: float) -> QImage:
    img = QImage(max(1, int(w * dpr)), max(1, int(h * dpr)), QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(Qt.transparent)
    return img


def _levels(img: QImage, grain: float, seed: int, vignette=None) -> tuple:
    """Grey levels and alpha of a grey canvas, with film grain baked in."""
    w, h = img.width(), img.height()
    px = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine() // 4, 4)[:, :w]
    alpha = px[..., 3].astype(np.float32)
    level = px[..., 2].astype(np.float32) * 255.0 / np.maximum(alpha, 1.0)
    if vignette is not None:
        level *= vignette(w, h)
    level += np.random.default_rng(seed).normal(0.0, grain, (h, w)).astype(np.float32)
    return np.clip(level, 0, 255).astype(np.uint8), px[..., 3].copy()


def _graded(levels: tuple, grade: tuple, dpr: float) -> QImage:
    level, alpha = levels
    h, w = level.shape
    rgb = _lut(grade)[level].astype(np.uint16)
    a = alpha.astype(np.uint16)
    out = np.empty((h, w, 4), np.uint8)
    for ch, src in ((0, 2), (1, 1), (2, 0)):        # BGRA in memory
        out[..., ch] = (rgb[..., src] * a // 255).astype(np.uint8)
    out[..., 3] = alpha
    img = QImage(out.data, w, h, w * 4, QImage.Format_ARGB32_Premultiplied).copy()
    img.setDevicePixelRatio(dpr)
    return img


def _grey(level: float, alpha: float = 1.0) -> QColor:
    level = max(0.0, min(1.0, level))
    return QColor.fromRgbF(level, level, level, alpha)


def _smooth(cur: float, target: float, rate: float, dt: float) -> float:
    return target + (cur - target) * math.exp(-rate * dt)


def _stroked(path: QPainterPath, width: float) -> QPainterPath:
    s = QPainterPathStroker()
    s.setWidth(width)
    s.setCapStyle(Qt.RoundCap)
    s.setJoinStyle(Qt.RoundJoin)
    return s.createStroke(path)


class PumpkinScene(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = Pumpkin()
        self.fx = Particles()
        self.floaters: list = []         # [x, y, vx, vy, life, max, text, colour, px]
        self.spiders: list = []          # [x, y, vx, vy, life, phase]
        self.cues: list = []             # [name, start t, data]
        self.caption = ("", "")          # spell, outcome line
        self._caption_t = -99.0
        self.t = 0.0                     # scene time
        self.ct = 0.0                    # pumpkin time (stops under Immobulus)
        self.v = {"x": 0.0, "y": 0.0, "angle": 0.0, "alpha": 1.0, "broken": 0.0, "seal": 0.0,
                  "vines": 0.0, "flowers": 0.0, "fill": 0.0, "fire": 1.0, "ice": 0.0, "shield": 0.0,
                  "dark": 0.0, "lit": 0.0, "weather": 0.0, "bound": 0.0, "stuck": 0.0, "rune": 0.0,
                  "hat": 0.0, "aura": 0.0, "held": 0.0, "legs": 0.0, "frost": 0.0}
        self._kind = {"contents": EMPTY, "bound": "", "shield": "", "weather": "rain", "held": ""}
        self._spawn: dict = {}           # periodic emitters: key → seconds until the next
        self.grade = NIGHT               # the hue being faded to
        self._grade_from = NIGHT
        self._grade_t = -99.0
        self._world_levels = None        # (size, grey levels) of the backdrop
        self._backdrops: dict = {}       # grade → QPixmap (the current one and the one fading out)
        self._body_levels = None         # (key, grey levels)
        self._bodies: dict = {}          # (key, grade) → QImage
        self._faces: dict = {}
        self.steer: Optional[tuple] = None       # Wingardium Leviosa: (x, y) offset (u) the wand asks for
        self.hover: Optional[tuple] = None       # let go but frozen in mid-air (Immobulus)
        self.rest_x = 0.0                        # where it sits on the ground after a drop (u)
        self._steer_from = (0.0, 0.0)
        self.steer_color = T.GOLD
        self._vy = 0.0                           # falling speed (u/s)
        self._squash = (-99.0, 0.0)              # landing: (time, strength)
        self._xf = QTransform()
        self._u = 1.0
        self.animator = Animator(self)
        self._expiry = QTimer(self)
        self._expiry.setSingleShot(True)
        self._expiry.timeout.connect(self._expire)
        self.setMinimumSize(420, 420)

    # ── control ───────────────────────────────────────────────────────────────

    def apply(self, out: Outcome, before: dict):
        """Play a cast's cues.  `before` is the model's state before the cast
        (contents, pose …) for cues that need it."""
        self._sync_geometry()
        self.caption = (out.spell, out.text)
        self._caption_t = self.t
        self._set_grade(grade_for(out, self.grade))
        if "summon" in out.fx:                 # Accio brings it back to the middle
            self.rest_x = 0.0
        for cue in out.fx:
            self._cue(cue, before)
        self._schedule_expiry()
        self.animator.kick()
        self.update()

    def reset(self):
        self.model.reset()
        self.steer = self.hover = None
        self.rest_x, self._vy = 0.0, 0.0
        self.fx.items.clear()
        self.floaters.clear()
        self.spiders.clear()
        self.cues.clear()
        self.caption = ("", "")
        self._set_grade(NIGHT)
        self._schedule_expiry()
        self.animator.kick()
        self.update()

    def start_steer(self, color: str):
        """Wingardium Leviosa: the levitating pumpkin follows a wand."""
        self._steer_from = self.hover or (self.rest_x, 0.0)     # picked up where it is
        self.steer, self.steer_color = self._steer_from, color
        self.animator.kick()

    def steer_to(self, right: float, up: float):
        """The wand has turned right/up this many degrees since the spell."""
        if self.steer is None:
            return
        u, _cx, floor = self._geometry()
        reach = max(0.0, self.width() / (2 * u) - 2.6)
        x0, y0 = self._steer_from
        self.steer = (max(-reach, min(reach, x0 + right / STEER_DEG)),
                      max(5.6 - floor / u, min(1.15, y0 - up / STEER_DEG)))
        self.animator.kick()

    def stop_steer(self):
        """The wand lets go.  Still afloat (frozen), it stays where it was
        steered; once it drops, it falls straight down from there."""
        if self.steer is not None:
            self.hover, self.rest_x = self.steer, self.steer[0]
        self.steer = None
        self.animator.kick()

    def say(self, title: str, text: str = ""):
        """A caption without a spell (someone casting, a miss)."""
        self.caption = (title, text)
        self._caption_t = self.t
        self.animator.kick()
        self.update()

    def _set_grade(self, grade: tuple):
        if grade == self.grade:
            return
        self._grade_from, self.grade, self._grade_t = self._current_grade(), grade, self.t

    def _fade(self) -> float:
        k = min(1.0, max(0.0, (self.t - self._grade_t) / FADE_S))
        return k * k * (3 - 2 * k)

    def _current_grade(self) -> tuple:
        return _mix_grade(self._grade_from, self.grade, self._fade())

    def _ink(self, level: float, alpha: float = 1.0) -> QColor:
        return ink(self._current_grade(), level, alpha)

    def _body_grade(self, grade: tuple) -> tuple:
        """The pumpkin takes the scene's hue, or its candle's when lit."""
        m = self.model
        if m.stone:
            return (250.0, 0.06)
        if m.tint:
            c = QColor(m.tint)
            return (max(0, c.hsvHue()) * 1.0, max(0.5, c.hsvSaturationF()))
        lit = round(self.v["fire"] * 4) / 4
        return _mix_grade(grade, LANTERN[m.fire_color], lit) if lit else grade

    def _sync_geometry(self):
        u, cx, floor = self._geometry()
        self._u = u
        self._xf = self._pose_transform(u, cx, floor)

    def fizzle(self):
        self._sync_geometry()
        u, top = self._u, self._world(0, TOP_Y)
        self.fx.burst(top.x(), top.y(), ["#8a8aa0", "#c9c9d6"], n=18, speed=u * 2.2, life=0.7,
                      size=2.2, gravity=-u * 0.5)
        self.animator.kick()

    def _schedule_expiry(self):
        at = self.model.next_expiry()
        if at is None:
            self._expiry.stop()
        else:
            self._expiry.start(max(10, int((at - time.monotonic()) * 1000) + 30))

    def _expire(self):
        if self.model.expire():
            self.animator.kick()
            self.update()
        self._schedule_expiry()

    def showEvent(self, e):
        self.animator.kick()
        super().showEvent(e)

    def hideEvent(self, e):
        self.animator.timer.stop()
        super().hideEvent(e)

    def resizeEvent(self, e):
        self._world_levels = None
        self._backdrops.clear()
        self._body_levels = None
        self._bodies.clear()
        self._faces.clear()
        super().resizeEvent(e)

    # ── cues ──────────────────────────────────────────────────────────────────

    def _cue(self, cue: str, before: dict):
        u = self._u
        top, mid, foot = self._world(0, TOP_Y), self._world(0, PIVOT_Y), self._world(0, 0)
        if cue in CUE_S:
            self.cues.append([cue, self.t, dict(before)])
        burst = lambda at, cols, n=60, sp=3.0, life=1.1, size=3.0, g=1.0: self.fx.burst(
            at.x(), at.y(), cols, n=n, speed=u * sp, life=life, size=size, gravity=u * g)
        if cue == "flare":
            burst(top, ["#ff7a2f", "#ffd36e", "#fff1c9", "#ff3b1f"], 70, 3.2, 1.0, 3.0, -1.0)
        elif cue == "smoke":
            self._rise(top, ["#5b5868", "#7c7889", "#3d3b48"], 26, 1.6, 4.5)
        elif cue == "steam":
            self._rise(top, ["#e6eef8", "#c9d6e6", "#ffffff"], 30, 1.4, 3.5)
        elif cue == "splash":
            self._fountain(top, ["#59b7ff", "#9fd8ff", "#ffffff", "#2e86de"], 60, 3.4, 4.0)
        elif cue == "frost":
            burst(mid, ["#e8f6ff", "#9fd8ff", "#ffffff"], 70, 3.4, 1.2, 2.4, 0.3)
        elif cue == "sparks":
            self._fountain(top, ["#2bd96b", "#9dff9d", "#e6ffe6"], 80, 4.2, 3.0)
        elif cue == "blast":
            burst(mid, ["#ffd34d", "#ff7a2f", "#ffffff", "#ff3b1f"], 140, 5.5, 1.3, 3.4, 2.0)
            self._rise(mid, ["#4a4757", "#6b6878"], 24, 1.2, 3.0)
        elif cue == "shatter":
            burst(mid, list(PULP_COLOURS), 70, 3.5, 1.4, 2.8, 4.0)
        elif cue == "bind":
            col = {"ropes": "#c48a4f", "cords": "#e16a78", "cuffs": "#fff3c4"}.get(self.model.bound, T.GOLD)
            burst(mid, [col, "#ffffff"], 40, 2.4, 0.8, 2.4, 0.0)
        elif cue == "petrify":
            burst(mid, ["#a9a6b6", "#dcdae6", "#7d7a8a"], 60, 2.4, 1.0, 2.2, 2.0)
        elif cue == "goo":
            burst(foot, ["#b6e35a", "#7fbf2a", "#e2ff9a"], 40, 2.0, 0.8, 3.0, 4.0)
        elif cue == "rune":
            burst(self._world(1.72, -1.75), ["#ff7a2f", "#ffd36e"], 40, 1.8, 0.8, 2.2, -0.5)
        elif cue in ("shield", "patronus"):
            burst(mid, ["#bfe6ff", "#ffffff", "#dff3ff"] if cue == "patronus" else
                  ["#8fd0ff", "#ffffff", T.GOLD], 60, 3.0, 1.0, 2.4, 0.0)
        elif cue == "block":
            burst(mid, ["#bfe6ff", "#ffffff"], 70, 4.0, 0.8, 2.6, 0.0)
        elif cue in ("lift", "launch", "summon", "hop"):
            burst(foot, ["#ffffff", T.GOLD, "#ffb35c"], 30, 1.8, 0.8, 2.0, -0.5)
        elif cue == "spiders":
            rng = random.Random()
            for _ in range(8):
                a = rng.uniform(-0.3, math.pi + 0.3)
                self.spiders.append([foot.x() + rng.uniform(-u, u), foot.y() + rng.uniform(-0.1, 0.1) * u,
                                     math.cos(a) * u * rng.uniform(3, 5) * (1 if rng.random() > 0.5 else -1),
                                     -abs(math.sin(a)) * u * 0.6, 1.6, rng.random() * 6])
            burst(foot, ["#ffffff", "#dfe8ff"], 40, 4.0, 0.6, 2.4, 0.0)
        elif cue == "gust":
            for _ in range(70):
                y = mid.y() + random.uniform(-3.0, 2.0) * u
                ttl = random.uniform(0.6, 1.1)
                leaf = random.random() < 0.4
                self.fx.items.append([mid.x() - random.uniform(4, 6) * u, y, u * random.uniform(8, 12),
                                      random.uniform(-0.3, 0.3) * u, ttl, ttl,
                                      QColor(random.choice(LEAF_COLOURS) if leaf else "#dfe8ff"),
                                      random.uniform(2.5, 4.0) if leaf else random.uniform(1.0, 2.0), 0.0])
        elif cue == "petals":
            burst(top, ["#ff8fb3", "#ffd1e0", "#c9a6ff", "#ffffff"], 50, 3.0, 2.0, 2.6, 0.6)
        elif cue in ("bloom", "grow"):
            burst(top if cue == "bloom" else mid, ["#ff8fb3", "#9dff9d", "#ffffff", "#ffd36e"], 50,
                  2.4, 1.2, 2.4, -0.3)
        elif cue == "notes":
            for _ in range(4):
                self._note(top)
        elif cue == "hush":
            self._float(top, "shh…", "#c9c3e6", 15, vy=-0.6)
        elif cue == "dizzy":
            self._float(top, "✦", T.GOLD, 16)
        elif cue == "giggle":
            for _ in range(3):
                self._float(top, "ha", "#ffd36e", 14)
        elif cue == "cheer":
            burst(mid, [T.GOLD, "#ffffff", "#ff8fb3"], 60, 3.0, 1.2, 2.6, 0.3)
        elif cue == "silly":
            self.fx.confetti(self.width(), ["#ff8fb3", "#ffd36e", "#9fd8ff", "#b49cff", "#9dff9d"], n=120)
        elif cue == "sleep":
            self._float(top, "Z", "#c9c3e6", 18)
        elif cue == "wake":
            self._float(top, "!", T.GOLD, 22, vy=-1.2)
        elif cue == "poof":
            burst(mid, ["#ffffff", "#b49cff", "#dfe8ff"], 90, 3.6, 1.0, 3.0, -0.6)
            self._rise(mid, ["#b9b4cf", "#8a86a3"], 20, 1.2, 3.0)
        elif cue == "mend":
            burst(mid, [T.GOLD, "#fff4cf", "#ffb35c"], 80, 2.8, 1.2, 2.4, -0.4)
        elif cue == "bubbles":
            for _ in range(14):
                self._float(QPointF(mid.x() + random.uniform(-2.0, 2.0) * u, mid.y() + random.uniform(-1, 1.4) * u),
                            "○", "#dff3ff", random.uniform(10, 22), vy=-1.0)
            burst(mid, ["#ffffff", "#dff3ff"], 40, 2.2, 0.9, 2.0, -0.2)
        elif cue == "recolour":
            burst(mid, [self.model.tint or T.GOLD, "#ffffff", "#ff8fb3", "#9fd8ff", "#9dff9d"], 70, 3.0,
                  1.0, 2.6, 0.0)
        elif cue in ("freeze", "slow"):
            col = "#9fe6ff" if cue == "freeze" else "#b49cff"
            burst(mid, [col, "#ffffff"], 50, 2.6, 1.0, 2.2, 0.0)
        elif cue in ("knock", "shock", "zap"):
            col = {"zap": "#ff4d4d", "shock": "#c9b8ff"}.get(cue, "#ffffff")
            burst(mid, [col, "#ffffff"], 50, 3.4, 0.8, 2.6, 1.0)
        elif cue == "finite":
            burst(mid, ["#ffffff", "#dfe8ff"], 50, 3.6, 0.8, 2.2, 0.0)
        elif cue in ("sparkle", "fizzle", "strain", "unseal", "seal", "cloud", "light", "dark",
                     "fling", "traces"):
            cols = {"fizzle": ["#8a8aa0", "#c9c9d6"], "strain": ["#ffffff", T.GOLD],
                    "light": ["#fff4cf", "#ffffff"], "dark": ["#3d3b48", "#6b6878"]}.get(
                cue, [T.GOLD, "#ffffff", "#ffb35c"])
            burst(top, cols, 30 if cue == "fizzle" else 45, 2.4, 0.9, 2.2, 0.0)

    def _rise(self, at: QPointF, colors, n: int, speed: float, life: float):
        u = self._u
        for _ in range(n):
            ttl = life * random.uniform(0.5, 1.0)
            self.fx.items.append([at.x() + random.uniform(-1.2, 1.2) * u, at.y(),
                                  random.uniform(-0.4, 0.4) * u, -u * speed * random.uniform(0.6, 1.2),
                                  ttl, ttl, QColor(random.choice(colors)), random.uniform(3.0, 7.0), -u * 0.2])

    def _fountain(self, at: QPointF, colors, n: int, speed: float, gravity: float):
        u = self._u
        for _ in range(n):
            a = -math.pi / 2 + random.uniform(-0.55, 0.55)
            v = u * speed * random.uniform(0.6, 1.1)
            ttl = random.uniform(0.8, 1.4)
            self.fx.items.append([at.x() + random.uniform(-0.8, 0.8) * u, at.y(), v * math.cos(a),
                                  v * math.sin(a), ttl, ttl, QColor(random.choice(colors)),
                                  random.uniform(1.6, 3.2), u * gravity])

    def _float(self, at: QPointF, text: str, colour: str, px: float, vy: float = -0.9):
        u = self._u
        ttl = random.uniform(1.6, 2.4)
        self.floaters.append([at.x() + random.uniform(-0.8, 0.8) * u, at.y() - random.uniform(0, 0.4) * u,
                              random.uniform(-0.35, 0.35) * u, vy * u, ttl, ttl, text, colour, px])

    def _note(self, at: QPointF, quiet: bool = False):
        self._float(at, random.choice("♪♫♬"), "#ffe9a8" if not quiet else "#a59dc2",
                    random.uniform(16, 24) * (0.65 if quiet else 1.0), vy=-0.7 if quiet else -1.0)

    # ── geometry ──────────────────────────────────────────────────────────────

    def _geometry(self):
        w, h = self.width(), self.height()
        u = min(w / 10.0, h / 9.6)
        return u, w / 2, h * 0.74

    def _ground(self, x: float) -> float:
        """How far below the floor line the patch is at x (u from the
        middle): the mound slopes away to the sides."""
        u, cx, _floor = self._geometry()
        return 0.35 * (x * u / cx) ** 2 if cx else 0.0

    def _world(self, x: float, y: float) -> QPointF:
        """A point on the pumpkin (u, base origin) in widget pixels."""
        return self._xf.map(QPointF(x * self._u, y * self._u))

    def _pose_transform(self, u: float, cx: float, floor: float) -> QTransform:
        """Pumpkin transform (local u-space → widget) from the smoothed
        state, moods and cues."""
        m, v, ct = self.model, self.v, self.ct
        x, y, angle, sx, sy = v["x"], v["y"], v["angle"], 1.0, 1.0
        mood = m.mood
        if m.pose == LEVITATING:
            y += math.sin(ct * 2.2) * 0.13
        if mood == "alive":
            hop = abs(math.sin(ct * 5.5))
            y -= hop * 0.7
            x += math.sin(ct * 1.3) * 0.9
            sy, sx = 1 - (1 - hop) * 0.12, 1 + (1 - hop) * 0.08
        elif mood == "dizzy":
            angle += math.sin(ct * 4.5) * 10
        elif mood == "giggling":
            angle += math.sin(ct * 38) * 2.6
            x += math.sin(ct * 31) * 0.04
        elif mood == "cheerful":
            y -= abs(math.sin(ct * 3.6)) * 0.18
        elif mood == "silly":
            k = math.sin(ct * 7.5)
            sx, sy = 1 + k * 0.13, 1 - k * 0.13
        elif mood == "asleep":
            angle += 7 + math.sin(ct * 1.1) * 1.5
            sy = 1 + math.sin(ct * 1.1) * 0.015
        if m.music == "singing":
            angle += math.sin(ct * 3.2) * 4
        elif m.music == "humming":
            angle += math.sin(ct * 2.0) * 1.5
        if self._steering:                     # lean into the wand's pull
            angle += max(-14.0, min(14.0, (self.steer[0] - v["x"]) * 9))
        landed, strength = self._squash        # squashes as it lands, then springs back
        k = max(0.0, 1 - (self.t - landed) / 0.35)
        if k > 0:
            wobble = math.cos((self.t - landed) * 30) * k * strength
            sy *= 1 - 0.2 * wobble
            sx *= 1 + 0.12 * wobble
        y += self._ground(x)
        scale = 1.0
        for name, start, _data in self.cues:
            k = min(1.0, (self.t - start) / CUE_S[name])
            if name == "launch":
                y -= 4.6 * math.sin(math.pi * k)
                angle += 360 * k * k
            elif name == "summon":
                scale *= 1 + 0.25 * math.sin(math.pi * k)
            elif name == "strain":
                angle += math.sin(k * 60) * 3 * (1 - k)
            elif name == "gust":
                angle += math.sin(math.pi * k) * 9
            elif name == "fling":
                angle += 900 * k
            elif name == "knock":
                angle += 360 * (1 - (1 - k) ** 3) if m.pose == FALLEN else 0
            elif name == "shock":
                x += math.sin(k * 50) * 0.12 * (1 - k)
        xf = QTransform()
        xf.translate(cx + x * u, floor + y * u)
        xf.translate(0, PIVOT_Y * u)
        xf.rotate(angle)
        xf.translate(0, -PIVOT_Y * u)
        xf.scale(sx * scale, sy * scale)
        return xf

    # ── animation step ────────────────────────────────────────────────────────

    def _targets(self) -> dict:
        m = self.model
        dark = {"dark": 1.0, "lit": 0.0}.get(m.light, 0.0)
        if m.pose != LEVITATING:
            self.hover = None
        afloat = self.steer if self._steering else self.hover if m.pose == LEVITATING and self.hover \
            else (self.rest_x, 0.0)
        return {
            "x": 7.5 if m.pose == GONE else afloat[0],
            "y": (-1.3 + afloat[1] if m.pose == LEVITATING else
                  -0.75 if m.pose == FALLEN else
                  -0.45 if m.mood == "alive" else 0.0),
            "angle": 90.0 if m.pose == FALLEN else 0.0,       # rolled onto its side
            "alpha": 0.0 if m.pose == VANISHED else 1.0,
            "broken": 1.0 if m.broken else 0.0,
            "seal": 1.0 if m.sealed else 0.0,
            "vines": 1.0 if m.vines else 0.0,
            "flowers": 1.0 if m.contents == FLOWERS else 0.0,
            "fill": 1.0 if m.contents in (WATER, ICE) else 0.0,
            "ice": 1.0 if m.contents == ICE else 0.0,
            "fire": 1.0 if m.contents == FIRE else 0.0,
            "frost": 1.0 if m.frost else 0.0,
            "shield": 1.0 if m.shield else 0.0,
            "dark": dark,
            "lit": 1.0 if m.light == "lit" else 0.0,
            "weather": 1.0 if m.weather else 0.0,
            "bound": 1.0 if m.bound else 0.0,
            "stuck": 1.0 if m.stuck else 0.0,
            "rune": 1.0 if m.rune else 0.0,
            "hat": 1.0 if m.mood == "silly" else 0.0,
            "aura": 1.0 if m.mood == "cheerful" else 0.0,
            "held": 1.0 if m.held else 0.0,
            "legs": 1.0 if m.mood == "alive" else 0.0,
        }

    @property
    def _steering(self) -> bool:
        return self.steer is not None and self.model.pose == LEVITATING

    RATES = {"x": 3.0, "y": 5.0, "angle": 7.0, "alpha": 3.0, "broken": 5.0, "dark": 2.5, "lit": 3.0,
             "fire": 3.0}

    def _fall(self, ground: float, dt: float) -> bool:
        """Nothing holds it up: fall under gravity, bounce once, settle.
        True while it's still moving."""
        if self.model.held == "frozen":
            return False
        self._vy += GRAVITY * dt
        y = self.v["y"] + self._vy * dt
        if y >= ground:
            hit, y = self._vy, ground
            self._vy = -hit * BOUNCE if hit > LAND_SPEED else 0.0
            if hit > LAND_SPEED:
                self._land(hit)
        self.v["y"] = y
        return bool(self._vy) or y < ground

    def _land(self, speed: float):
        """It hits the ground: a squash, a puff of dust, and whatever's
        inside sloshes."""
        k = min(1.0, speed / 10.0)
        self._squash = (self.t, k)
        u, m = self._u, self.model
        foot = self._world(0, 0)
        dust = [self._ink(0.45).name(), self._ink(0.62).name(), self._ink(0.3).name()]
        for _ in range(int(16 + 34 * k)):
            side = random.choice((-1, 1))
            ttl = random.uniform(0.5, 0.9)
            self.fx.items.append([foot.x() + side * random.uniform(0.6, 2.2) * u, foot.y(),
                                  side * u * random.uniform(1.0, 3.5) * k, -u * random.uniform(0.2, 1.1) * k,
                                  ttl, ttl, QColor(random.choice(dust)), random.uniform(2.0, 4.5), u * 2.5])
        top = self._world(0, TOP_Y)
        if m.contents == WATER and k > 0.3:
            self._fountain(top, ["#59b7ff", "#9fd8ff", "#ffffff"], int(20 * k), 2.2, 5.0)
        elif m.contents == FIRE and k > 0.3:
            self.fx.burst(top.x(), top.y(), ["#ffd36e", "#ff7a2f"], n=int(20 * k), speed=u * 1.6, life=0.7,
                          size=2.0, gravity=-u * 0.6)

    def _step(self, dt: float) -> bool:
        """Advance everything by dt; True while anything still moves."""
        m = self.model
        self.t += dt
        speed = {"frozen": 0.0, "slowed": 0.25}.get(m.held, 1.0)
        self.ct += dt * speed
        moving = self._fade() < 1.0
        if m.pose == LEVITATING:
            self._vy = 0.0
        for k, target in self._targets().items():
            cur = self.v[k]
            if k == "y" and m.pose != LEVITATING and (self._vy or target > cur + 0.002):
                moving |= self._fall(target, dt * (speed if m.held == "slowed" else 1.0))
            elif abs(cur - target) > 0.002:
                rate = 9.0 if self._steering and k in ("x", "y") else self.RATES.get(k, 4.0)
                self.v[k] = _smooth(cur, target, rate, dt)
                moving = True
            else:
                self.v[k] = target
        for key, attr in (("contents", m.contents), ("bound", m.bound), ("shield", m.shield),
                          ("weather", m.weather), ("held", m.held)):
            if attr and attr != EMPTY:
                self._kind[key] = attr
        self.cues = [c for c in self.cues if self.t - c[1] < CUE_S[c[0]]]
        self.fx.step(dt * (speed if m.held == "slowed" else 1.0))
        keep = []
        for f in self.floaters:
            f[4] -= dt
            if f[4] > 0:
                f[0] += f[2] * dt
                f[1] += f[3] * dt
                keep.append(f)
        self.floaters = keep
        keep = []
        for s in self.spiders:
            s[4] -= dt
            if s[4] > 0:
                s[0] += s[2] * dt
                s[1] += s[3] * dt
                s[3] += self._u * 3 * dt
                s[1] = min(s[1], self._geometry()[2] + self._u * 0.1)
                s[5] += dt * 22
                keep.append(s)
        self.spiders = keep
        self._periodic(dt)
        ambient = (m.present and (m.contents in (FIRE, WATER) or m.pose == LEVITATING or bool(m.mood)
                                  or bool(m.music) or bool(m.shield) or m.rune or m.bound == "cuffs"
                                  or m.held == "slowed")) or bool(m.weather) or m.light == "lit"
        caption = self.t - self._caption_t < 7.0
        return moving or ambient or caption or bool(self.cues or self.fx.active or self.floaters
                                                    or self.spiders)

    def _periodic(self, dt: float):
        """Ongoing emitters: music notes, Zs, hearts, embers, drips."""
        m = self.model
        if not m.present or m.broken:
            self._spawn.clear()
            return
        top = self._world(0, TOP_Y)
        wanted = {}
        if m.music:
            wanted["note"] = 0.45 if m.music == "singing" else 1.1
        if m.mood == "asleep":
            wanted["z"] = 1.1
        if m.mood == "cheerful":
            wanted["heart"] = 0.45
        if m.mood == "giggling":
            wanted["ha"] = 0.5
        if m.contents == FIRE and m.held != "frozen" and not m.sealed:
            wanted["ember"] = 0.16
        if self._steering:
            wanted["steer"] = 0.07
        if m.contents == WATER and m.pose != FALLEN and m.held != "frozen":
            wanted["drip"] = 0.7
        for key in list(self._spawn):
            if key not in wanted:
                del self._spawn[key]
        u = self._u
        for key, every in wanted.items():
            left = self._spawn.get(key, 0.0) - dt
            if left <= 0:
                left = every
                if key == "note":
                    self._note(top, quiet=m.music == "humming")
                elif key == "z":
                    self._float(top, "Z", "#c9c3e6", random.uniform(14, 22), vy=-0.55)
                elif key == "heart":
                    self._float(top, "♥", "#ff8fb3", random.uniform(14, 20))
                elif key == "ha":
                    self._float(top, "ha", "#ffd36e", 13)
                elif key == "ember":
                    col = "#9dff9d" if m.fire_color == "green" else random.choice(("#ffd36e", "#ff7a2f"))
                    at = self._world(random.uniform(-0.9, 0.9), TOP_Y + 0.25)
                    ttl = random.uniform(0.8, 1.4)
                    self.fx.items.append([at.x(), at.y(), random.uniform(-0.3, 0.3) * u,
                                          -u * random.uniform(1.2, 2.2), ttl, ttl, QColor(col),
                                          random.uniform(1.2, 2.2), -u * 0.3])
                elif key == "steer":                  # charm dust trailing from it
                    at = self._world(random.uniform(-1.6, 1.6), random.uniform(-0.3, 0.2))
                    ttl = random.uniform(0.6, 1.0)
                    self.fx.items.append([at.x(), at.y(), random.uniform(-0.2, 0.2) * u, u * 0.3, ttl, ttl,
                                          QColor(random.choice((self.steer_color, "#ffffff"))),
                                          random.uniform(1.2, 2.2), u * 0.4])
                elif key == "drip":
                    at = self._world(random.uniform(-0.9, 0.9), -0.4)
                    ttl = random.uniform(0.5, 0.8)
                    self.fx.items.append([at.x(), at.y(), 0.0, u * 0.2, ttl, ttl, QColor("#7fc0ff"),
                                          random.uniform(1.8, 2.6), u * 9])
            self._spawn[key] = left

    # ── painting ──────────────────────────────────────────────────────────────

    def paintEvent(self, _e):
        alive = self._step(self.animator.dt(True) if self.animator.timer.isActive() else 0.0)
        u, cx, floor = self._geometry()
        self._sync_geometry()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        self._paint_backdrop(p, u, cx, floor)
        v = self.v
        if v["lit"] > 0.01:
            g = QRadialGradient(QPointF(cx, floor - 3 * u), 6 * u)
            g.setColorAt(0, T.qcolor("#fff1c9", 0.16 * v["lit"]))
            g.setColorAt(1, T.qcolor("#fff1c9", 0.0))
            p.fillRect(self.rect(), g)
        self._paint_floor_fx(p, u, cx, floor)
        if v["alpha"] > 0.01 and v["x"] < 7.4:
            p.save()
            p.setOpacity(v["alpha"])
            p.setTransform(self._xf)
            self._paint_pumpkin(p, u)
            p.restore()
        self._paint_world_fx(p, u, cx, floor)
        if v["dark"] > 0.01:
            p.save()
            p.setClipPath(self._frame())
            p.fillRect(self.rect(), QColor(2, 2, 10, int(205 * v["dark"])))
            p.restore()
            self._paint_emissive(p, u)
        self._paint_light(p, u, cx, floor)
        self.fx.paint(p)
        self._paint_floaters(p)
        self._paint_caption(p)
        p.end()
        if alive:
            self.animator.kick()
        else:
            self.animator.dt(False)

    def _frame(self) -> QPainterPath:
        frame = QPainterPath()
        frame.addRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 20, 20)
        return frame

    # backdrop ----------------------------------------------------------------------

    def _paint_backdrop(self, p: QPainter, u: float, cx: float, floor: float):
        """The graded night: the new hue, with the old one fading out over it."""
        k = self._fade()
        new = self._backdrop(self.grade, u, cx, floor)
        p.drawPixmap(0, 0, new)
        if k < 1.0 and self._grade_from != self.grade:
            p.setOpacity(1 - k)
            p.drawPixmap(0, 0, self._backdrop(self._grade_from, u, cx, floor))
            p.setOpacity(1.0)
        for g in [g for g in self._backdrops if g not in (self.grade, self._grade_from)]:
            del self._backdrops[g]

    def _backdrop(self, grade: tuple, u: float, cx: float, floor: float) -> QPixmap:
        dpr = self.devicePixelRatioF()
        size = (self.width(), self.height(), dpr)
        if self._world_levels is None or self._world_levels[0] != size:
            img = _grey_canvas(self.width(), self.height(), dpr)
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            p.setClipPath(self._frame())
            self._paint_world(p, self.width(), self.height(), u, cx, floor)
            p.end()

            def vignette(w, h):
                yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
                r = np.hypot((xx - w / 2) / (w * 0.62), (yy - h * 0.48) / (h * 0.7))
                return 1 - 0.5 * np.clip(r - 0.55, 0, 1) ** 1.2

            self._world_levels = (size, _levels(img, 6.0, 7, vignette))
            self._backdrops.clear()
        if grade not in self._backdrops:
            self._backdrops[grade] = QPixmap.fromImage(_graded(self._world_levels[1], grade, dpr))
        return self._backdrops[grade]

    def _paint_world(self, p: QPainter, w: float, h: float, u: float, cx: float, floor: float):
        """The night in grey levels: sky, moon and dust, hills with a castle,
        a bare tree, gravestones and the patch the pumpkin sits in."""
        sky = QLinearGradient(0, 0, 0, floor)
        sky.setColorAt(0, _grey(0.15))
        sky.setColorAt(0.55, _grey(0.27))
        sky.setColorAt(0.8, _grey(0.40))
        sky.setColorAt(1, _grey(0.34))
        p.fillRect(QRectF(0, 0, w, h), sky)
        moon = QPointF(cx - 3.1 * u, max(0.85 * u, floor - 6.6 * u))
        for r, a in ((7.0, 0.16), (3.4, 0.45)):
            g = QRadialGradient(moon, r * u)
            g.setColorAt(0, _grey(0.9, a))
            g.setColorAt(1, _grey(0.9, 0.0))
            p.fillRect(QRectF(0, 0, w, h), g)
        haze = QRadialGradient(QPointF(cx + 1.0 * u, floor - 1.8 * u), 6 * u)
        haze.setColorAt(0, _grey(0.55, 0.35))
        haze.setColorAt(1, _grey(0.55, 0.0))
        p.fillRect(QRectF(0, 0, w, h), haze)
        p.setPen(Qt.NoPen)
        p.setBrush(_grey(0.97))
        p.drawEllipse(moon, 0.62 * u, 0.62 * u)
        p.setBrush(_grey(0.87))
        for dx, dy, r in ((-0.18, -0.12, 0.13), (0.2, 0.15, 0.09), (0.05, -0.3, 0.06)):
            p.drawEllipse(moon + QPointF(dx * u, dy * u), r * u, r * u)
        # stipple dust, thickest around the moon
        rng = random.Random(11)
        for _ in range(int(w * h / 2400)):
            if rng.random() < 0.55:
                at = QPointF(rng.gauss(moon.x(), 2.6 * u), rng.gauss(moon.y(), 1.8 * u))
            else:
                at = QPointF(rng.random() * w, rng.random() ** 1.3 * (floor - 1.5 * u))
            p.setBrush(_grey(rng.uniform(0.6, 1.0), rng.uniform(0.2, 0.85)))
            s = rng.uniform(0.5, 1.4)
            p.drawEllipse(at, s, s)

        def ridge(y_of, level):
            path = QPainterPath(QPointF(0, h))
            x = 0.0
            while x <= w + 4:
                path.lineTo(x, y_of(x))
                x += 4
            path.lineTo(w, h)
            path.closeSubpath()
            p.setBrush(_grey(level))
            p.drawPath(path)

        far = lambda x: floor - 1.9 * u + 0.45 * u * math.sin(x / (3.1 * u) + 2.2) + 0.15 * u * math.sin(x / (1.1 * u))
        ridge(far, 0.28)
        # a castle on the far hill
        x0 = cx + 2.3 * u
        base = far(x0 + u) + 0.15 * u
        p.setBrush(_grey(0.21))
        for dx, tw, th, roof in ((0.0, 0.35, 1.6, 0.6), (0.3, 0.7, 1.0, 0.0), (1.0, 0.32, 2.2, 0.7),
                                 (1.3, 0.75, 1.25, 0.0), (2.0, 0.3, 1.5, 0.5)):
            x, top = x0 + dx * u, base - th * u
            p.drawRect(QRectF(x, top, tw * u, th * u + 0.3 * u))
            if roof:
                p.drawPolygon(QPolygonF([QPointF(x - 0.06 * u, top), QPointF(x + (tw + 0.06) * u, top),
                                         QPointF(x + tw * u / 2, top - roof * u)]))
            else:
                for i in range(int(tw / 0.18)):
                    p.drawRect(QRectF(x + i * 0.18 * u, top - 0.1 * u, 0.1 * u, 0.1 * u))
        p.setBrush(_grey(0.8))
        for dx, dy in ((0.12, 1.1), (1.11, 1.6), (1.12, 1.2), (1.6, 0.8), (2.1, 1.0)):
            p.drawRect(QRectF(x0 + dx * u, base - dy * u, 0.07 * u, 0.12 * u))
        fog = QLinearGradient(0, floor - 1.9 * u, 0, floor - 0.5 * u)
        fog.setColorAt(0, _grey(0.6, 0.0))
        fog.setColorAt(0.5, _grey(0.6, 0.3))
        fog.setColorAt(1, _grey(0.6, 0.0))
        p.fillRect(QRectF(0, floor - 1.9 * u, w, 1.4 * u), fog)
        mid = lambda x: floor - 0.95 * u + 0.35 * u * math.sin(x / (2.3 * u) + 1) + 0.18 * u * math.sin(x / (0.9 * u))
        ridge(mid, 0.17)
        # gravestones, dark with a moonlit edge
        for gx, gy, gw, gh, tilt in ((3.3, -0.05, 0.7, 1.0, 0), (4.25, 0.1, 0.55, 0.78, -7)):
            stone = QPainterPath()
            stone.moveTo(-gw / 2 * u, 0)
            stone.lineTo(-gw / 2 * u, -(gh - gw / 2) * u)
            stone.arcTo(QRectF(-gw / 2 * u, -gh * u, gw * u, gw * u), 180, -180)
            stone.lineTo(gw / 2 * u, 0)
            stone.closeSubpath()
            p.save()
            p.translate(cx + gx * u, floor + gy * u)
            p.rotate(tilt)
            p.setBrush(_grey(0.11))
            p.drawPath(stone)
            p.setBrush(_grey(0.34))
            p.drawPath(stone.subtracted(stone.translated(0.07 * u, 0.05 * u)))
            p.setBrush(_grey(0.08))
            p.drawRect(QRectF(-gw * 0.25 * u, -(gh - 0.35) * u, gw * 0.5 * u, 0.06 * u))
            p.restore()
        self._paint_tree(p, u, cx, floor)
        # the patch: a low mound with grass, and a small pumpkin
        ground = lambda x: floor + 0.35 * u * ((x - cx) / (w / 2)) ** 2 + 0.05 * u * math.sin(x / u * 1.3)
        ridge(ground, 0.07)
        rng = random.Random(4)
        x = 0.0
        p.setBrush(_grey(0.07))
        while x < w:
            if abs(x - cx) > 2.3 * u or rng.random() < 0.3:
                y, bh = ground(x) + 0.03 * u, rng.uniform(0.08, 0.3) * u
                lean = rng.uniform(-0.08, 0.08) * u
                p.drawPolygon(QPolygonF([QPointF(x - 0.03 * u, y), QPointF(x + 0.03 * u, y),
                                         QPointF(x + lean, y - bh)]))
            x += rng.uniform(0.08, 0.25) * u
        small = QPainterPath()
        small.setFillRule(Qt.WindingFill)
        sp = QPointF(cx - 3.0 * u, ground(cx - 3.0 * u) + 0.12 * u)
        for dx, rx in ((-0.25, 0.32), (0.25, 0.32), (0.0, 0.3)):
            small.addEllipse(sp + QPointF(dx * u, -0.33 * u), rx * u, 0.36 * u)
        small = small.simplified()
        p.setBrush(_grey(0.1))
        p.drawPath(small)
        p.setBrush(_grey(0.3))
        p.drawPath(small.subtracted(small.translated(0.05 * u, 0.04 * u)))
        p.setPen(QPen(_grey(0.06), 0.03 * u))
        p.setBrush(Qt.NoBrush)
        for dx in (-0.12, 0.12):                  # its grooves
            p.drawLine(sp + QPointF(dx * u, -0.62 * u), sp + QPointF(dx * 1.2 * u, -0.05 * u))
        p.setPen(Qt.NoPen)
        p.setPen(QPen(_grey(0.1), 0.07 * u, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(sp + QPointF(0, -0.66 * u), sp + QPointF(0.08 * u, -0.86 * u))
        vine = QPainterPath(sp + QPointF(0.4 * u, -0.1 * u))
        vine.cubicTo(sp + QPointF(0.9 * u, 0.1 * u), sp + QPointF(1.2 * u, -0.3 * u), sp + QPointF(1.5 * u, -0.05 * u))
        p.setPen(QPen(_grey(0.08), 0.04 * u, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawPath(vine)
        p.setPen(Qt.NoPen)

    def _paint_tree(self, p: QPainter, u: float, cx: float, floor: float):
        """A bare, crooked tree on the left, reaching over the scene."""
        rng = random.Random(5)
        p.setBrush(Qt.NoBrush)

        def branch(at: QPointF, angle: float, length: float, width: float, depth: int):
            end = at + QPointF(math.cos(angle) * length, -math.sin(angle) * length)
            bend = at + QPointF(math.cos(angle + rng.uniform(-0.35, 0.35)) * length * 0.5,
                                -math.sin(angle + rng.uniform(-0.35, 0.35)) * length * 0.5)
            path = QPainterPath(at)
            path.quadTo(bend, end)
            p.setPen(QPen(_grey(0.06), max(0.8, width), Qt.SolidLine, Qt.RoundCap))
            p.drawPath(path)
            if depth == 0:
                return
            for spread in ((-1, 1) if depth > 3 else (-1, 1, 0) if rng.random() < 0.4 else (-1, 1)):
                a = angle + spread * rng.uniform(0.25, 0.65) - 0.12
                branch(end, a, length * rng.uniform(0.6, 0.78), width * 0.62, depth - 1)

        trunk = QPainterPath(QPointF(cx - 4.9 * u, floor + 0.6 * u))
        trunk.cubicTo(QPointF(cx - 4.3 * u, floor - 0.6 * u), QPointF(cx - 4.7 * u, floor - 2.2 * u),
                      QPointF(cx - 4.1 * u, floor - 3.4 * u))
        p.setPen(QPen(_grey(0.06), 0.42 * u, Qt.SolidLine, Qt.RoundCap))
        p.drawPath(trunk)
        top = QPointF(cx - 4.1 * u, floor - 3.4 * u)
        branch(top, math.radians(70), 1.3 * u, 0.26 * u, 5)
        branch(top, math.radians(28), 1.5 * u, 0.22 * u, 5)
        branch(QPointF(cx - 4.45 * u, floor - 1.9 * u), math.radians(18), 1.2 * u, 0.16 * u, 4)
        for dx in (-0.5, 0.45):                   # roots
            root = QPainterPath(QPointF(cx - 4.75 * u, floor + 0.2 * u))
            root.quadTo(QPointF(cx + (-4.75 + dx) * u, floor + 0.05 * u),
                        QPointF(cx + (-4.75 + dx * 2) * u, floor + 0.35 * u))
            p.setPen(QPen(_grey(0.06), 0.12 * u, Qt.SolidLine, Qt.RoundCap))
            p.drawPath(root)
        p.setPen(Qt.NoPen)

    # pumpkin -----------------------------------------------------------------------

    @staticmethod
    def _silhouette(u: float) -> QPainterPath:
        path = QPainterPath()
        path.setFillRule(Qt.WindingFill)
        for x, y, rx, ry, _level in LOBES:
            path.addEllipse(QPointF(x * u, y * u), rx * u, ry * u)
        return path.simplified()

    @staticmethod
    def _seam(u: float) -> QPainterPath:
        """The zigzag cut of the lid, across the front of the top."""
        path = QPainterPath()
        n = 13
        for i in range(n):
            a = math.pi * (1 - i / (n - 1))
            r = 0.05 if i % 2 else -0.04
            pt = QPointF(math.cos(a) * 1.05 * u, (TOP_Y + math.sin(a) * 0.3 + r) * u)
            if i == 0:
                path.moveTo(pt)
            else:
                path.lineTo(pt)
        return path

    def _body_image(self, u: float, grade: tuple) -> QImage:
        m = self.model
        key = (round(u, 1), round(self.v["frost"], 1), round(m.soot, 2), m.stone)
        dpr = self.devicePixelRatioF()
        if self._body_levels is None or self._body_levels[0] != key:
            bx, by, bw, bh = BODY_BOX
            img = _grey_canvas(bw * u, bh * u, dpr)
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            p.translate(-bx * u, -by * u)
            self._paint_body(p, u)
            p.end()
            self._body_levels = (key, _levels(img, 7.0, 3))
            self._bodies.clear()
        body_grade = self._body_grade(grade)
        if body_grade not in self._bodies:
            if len(self._bodies) > 3:
                self._bodies.clear()
            self._bodies[body_grade] = _graded(self._body_levels[1], body_grade, dpr)
        return self._bodies[body_grade]

    def _paint_body(self, p: QPainter, u: float):
        """The pumpkin in grey levels: flat lobes with dark grooves, a cel
        shadow, a moonlit rim, the stem and the lid's cut."""
        m = self.model
        sil = self._silhouette(u)
        p.setPen(QPen(_grey(0.1), 0.08 * u))
        p.setBrush(_grey(0.12))
        p.drawPath(sil)
        levels = STONE_LOBES if m.stone else [lobe[4] for lobe in LOBES]
        for (x, y, rx, ry, _l), level in zip(LOBES, levels):
            p.setPen(QPen(_grey(0.13), 0.07 * u))
            p.setBrush(_grey(level))
            p.drawEllipse(QPointF((x - 0.03) * u, (y - 0.03) * u), rx * 0.93 * u, ry * 0.95 * u)
        p.save()
        p.setClipPath(sil)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 70))                     # flat shadow on the right and below
        p.drawEllipse(QPointF(1.5 * u, -0.35 * u), 2.7 * u, 1.9 * u)
        p.setPen(QPen(_grey(0.62, 0.7), 0.07 * u, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        for x, y in ((-1.32, -1.55), (-0.66, -1.62)):      # short shine strokes on the lit lobes
            shine = QPainterPath(QPointF((x + 0.05) * u, (y - 1.05) * u))
            shine.quadTo(QPointF((x - 0.4) * u, (y - 0.8) * u), QPointF((x - 0.5) * u, (y - 0.25) * u))
            p.drawPath(shine)
        if m.stone:
            rng = random.Random(3)
            p.setPen(Qt.NoPen)
            for _ in range(220):
                p.setBrush(_grey(0.0 if rng.random() > 0.5 else 1.0, rng.uniform(0.05, 0.2)))
                p.drawEllipse(QPointF(rng.uniform(-2.3, 2.3) * u, rng.uniform(-3.2, 0) * u),
                              rng.uniform(0.01, 0.04) * u, rng.uniform(0.01, 0.04) * u)
            p.setPen(QPen(_grey(0.08, 0.7), 0.035 * u))
            p.setBrush(Qt.NoBrush)
            crack = QPolygonF([QPointF(x * u, y * u) for x, y in
                               ((1.2, -2.9), (1.05, -2.4), (1.35, -2.0), (1.15, -1.5), (1.3, -1.2))])
            p.drawPolyline(crack)
        if m.soot > 0:
            rng = random.Random(5)
            p.setPen(Qt.NoPen)
            for _ in range(14):
                sx, sy = rng.uniform(-2.0, 2.0) * u, rng.uniform(-3.0, -0.3) * u
                r = rng.uniform(0.3, 0.8) * u
                sg = QRadialGradient(QPointF(sx, sy), r)
                sg.setColorAt(0, QColor(0, 0, 0, int(170 * m.soot)))
                sg.setColorAt(1, QColor(0, 0, 0, 0))
                p.setBrush(sg)
                p.drawEllipse(QPointF(sx, sy), r, r)
        frost = self.v["frost"]
        if frost > 0.05:
            p.fillRect(QRectF(-2.7 * u, -4.3 * u, 5.4 * u, 4.6 * u), _grey(0.95, 0.3 * frost))
            rng = random.Random(9)
            p.setPen(Qt.NoPen)
            for _ in range(90):
                p.setBrush(_grey(1.0, rng.uniform(0.3, 0.8) * frost))
                p.drawEllipse(QPointF(rng.uniform(-2.3, 2.3) * u, rng.uniform(-3.2, 0) * u), 0.025 * u, 0.025 * u)
        p.restore()
        p.setPen(Qt.NoPen)
        p.setBrush(_grey(0.8, 0.85))                       # moonlit rim, upper left
        p.drawPath(sil.subtracted(sil.translated(0.09 * u, 0.08 * u)))
        p.setPen(QPen(_grey(0.04), 0.06 * u, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawPath(self._seam(u))
        stem = QPainterPath(QPointF(-0.24 * u, -3.05 * u))
        stem.cubicTo(QPointF(-0.2 * u, -3.45 * u), QPointF(-0.12 * u, -3.75 * u), QPointF(0.22 * u, -4.0 * u))
        stem.lineTo(QPointF(0.36 * u, -3.9 * u))
        stem.cubicTo(QPointF(0.12 * u, -3.7 * u), QPointF(0.16 * u, -3.4 * u), QPointF(0.24 * u, -3.08 * u))
        stem.closeSubpath()
        p.setPen(QPen(_grey(0.08), 0.04 * u))
        p.setBrush(_grey(0.22))
        p.drawPath(stem)
        p.setPen(QPen(_grey(0.45), 0.05 * u, Qt.SolidLine, Qt.RoundCap))
        edge = QPainterPath(QPointF(-0.16 * u, -3.12 * u))
        edge.cubicTo(QPointF(-0.13 * u, -3.45 * u), QPointF(-0.07 * u, -3.7 * u), QPointF(0.18 * u, -3.92 * u))
        p.drawPath(edge)
        curl = QPainterPath(QPointF(0.2 * u, -3.25 * u))
        curl.cubicTo(QPointF(0.7 * u, -3.2 * u), QPointF(0.85 * u, -3.65 * u), QPointF(0.6 * u, -3.7 * u))
        curl.cubicTo(QPointF(0.42 * u, -3.72 * u), QPointF(0.45 * u, -3.5 * u), QPointF(0.58 * u, -3.52 * u))
        p.setPen(QPen(_grey(0.2), 0.035 * u, Qt.SolidLine, Qt.RoundCap))
        p.drawPath(curl)

    def _face(self, u: float) -> list:
        """The carved holes for the current expression: [(hole, inner)],
        where inner leaves a strip of cut flesh along each hole's bottom."""
        m = self.model
        mood = m.mood
        eyes = {"asleep": "sleep", "dizzy": "dizzy", "stunned": "dizzy", "giggling": "happy",
                "cheerful": "happy", "silly": "happy", "alive": "happy"}.get(mood, "normal")
        mouth = ("sing" if m.music == "singing" else "hum" if m.music == "humming" else
                 {"asleep": "o", "dizzy": "wavy", "stunned": "wavy", "giggling": "big", "cheerful": "big",
                  "silly": "big", "alive": "big"}.get(mood, "grin"))
        phase = round(abs(math.sin(self.ct * 6.5)) * 8) if mouth == "sing" else 0
        key = (round(u, 1), eyes, mouth, phase)
        if key not in self._faces:
            if len(self._faces) > 40:
                self._faces.clear()
            P = lambda x, y: QPointF(x * u, y * u)
            holes = []
            for s in (-1, 1):
                c = s * 0.85
                eye = QPainterPath()
                if eyes == "happy":
                    eye.moveTo(P(c - 0.47, -1.82))
                    eye.quadTo(P(c, -2.62), P(c + 0.47, -1.82))
                    eye.quadTo(P(c, -2.25), P(c - 0.47, -1.82))
                elif eyes == "sleep":
                    eye.moveTo(P(c - 0.47, -2.02))
                    eye.quadTo(P(c, -1.6), P(c + 0.47, -2.02))
                    eye.quadTo(P(c, -1.84), P(c - 0.47, -2.02))
                elif eyes == "dizzy":
                    cross = QPainterPath(P(c - 0.33, -2.38))
                    cross.lineTo(P(c + 0.33, -1.78))
                    cross.moveTo(P(c - 0.33, -1.78))
                    cross.lineTo(P(c + 0.33, -2.38))
                    eye = _stroked(cross, 0.17 * u).simplified()
                else:
                    eye.addPolygon(QPolygonF([P(s * 1.32, -1.72), P(s * 0.38, -1.74), P(s * 0.85, -2.46)]))
                    eye.closeSubpath()
                holes.append(eye)
            nose = QPainterPath()
            nose.addPolygon(QPolygonF([P(-0.2, -1.3), P(0.2, -1.3), P(0.0, -1.6)]))
            nose.closeSubpath()
            holes.append(nose)
            lip = QPainterPath()
            if mouth in ("grin", "big"):
                b = mouth == "big"
                lip.moveTo(P(-1.75 if b else -1.65, -1.2 if b else -1.12))
                lip.cubicTo(P(-0.9, -0.95 if b else -0.72), P(0.9, -0.95 if b else -0.72),
                            P(1.75 if b else 1.65, -1.2 if b else -1.12))
                lip.cubicTo(P(1.3 if b else 1.15, 0.05 if b else -0.18), P(-1.3 if b else -1.15, 0.05 if b else -0.18),
                            P(-1.75 if b else -1.65, -1.2 if b else -1.12))
                teeth = QPainterPath()
                teeth.addRect(QRectF(P(-0.62, -1.25), P(-0.3, -0.6)))
                teeth.addRect(QRectF(P(0.28, -0.62 if b else -0.66), P(0.6, 0.1)))
                lip = lip.subtracted(teeth)
            elif mouth == "wavy":
                wave = QPainterPath(P(-1.2, -0.78))
                for x, y in ((-0.6, -0.56), (0.0, -0.78), (0.6, -0.56), (1.2, -0.78)):
                    wave.lineTo(P(x, y))
                lip = _stroked(wave, 0.2 * u).simplified()
            else:
                ry = {"o": 0.24, "hum": 0.11}.get(mouth, 0.2 + 0.2 * phase / 8)
                lip.addEllipse(P(0, -0.72), (0.3 if mouth == "o" else 0.42 if mouth == "hum" else 0.48) * u, ry * u)
            holes.append(lip)
            self._faces[key] = [(h, h.intersected(h.translated(0, -0.075 * u))) for h in holes]
        return self._faces[key]

    def _paint_pumpkin(self, p: QPainter, u: float):
        m, v, ct = self.model, self.v, self.ct
        origin = QPointF(BODY_BOX[0] * u, BODY_BOX[1] * u)
        if v["aura"] > 0.01:
            g = QRadialGradient(QPointF(0, -1.7 * u), 3.6 * u)
            g.setColorAt(0, T.qcolor(T.GOLD, 0.35 * v["aura"]))
            g.setColorAt(1, T.qcolor(T.GOLD, 0.0))
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawEllipse(QPointF(0, -1.7 * u), 3.6 * u, 3.6 * u)
        if self._steering:                     # the charm's glow round it, as on the wand
            c = QPointF(0, PIVOT_Y * u)
            g = QRadialGradient(c, 3.6 * u)
            g.setColorAt(0, T.qcolor(self.steer_color, 0.75))
            g.setColorAt(0.6, T.qcolor(self.steer_color, 0.25))
            g.setColorAt(1, T.qcolor(self.steer_color, 0.0))
            p.save()
            p.setCompositionMode(QPainter.CompositionMode_Screen)
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawEllipse(c, 3.6 * u, 3.6 * u)
            p.restore()
        if v["legs"] > 0.01:
            self._paint_legs(p, u, ct, v["legs"])
        if v["broken"] > 0.001:
            self._paint_shards(p, u, self._body_image(u, self.grade), origin, v["broken"])
            return
        if v["held"] > 0.01:
            col = "#9fe6ff" if self._kind["held"] == "frozen" else "#b49cff"
            p.setPen(QPen(T.qcolor(col, 0.45 * v["held"]), 0.22 * u))
            p.setBrush(Qt.NoBrush)
            p.drawPath(self._silhouette(u))
        p.drawImage(origin, self._body_image(u, self.grade))
        k = self._fade()
        if k < 1.0 and self._body_grade(self._grade_from) != self._body_grade(self.grade):
            p.setOpacity(p.opacity() * (1 - k))
            p.drawImage(origin, self._body_image(u, self._grade_from))
            p.setOpacity(self.v["alpha"])
        self._paint_face(p, u)
        if v["fire"] > 0.01:
            self._paint_glow(p, u, v["fire"])
        if v["frost"] > 0.01:
            self._paint_icicles(p, u, v["frost"])
        if v["flowers"] > 0.01:
            self._paint_flowers(p, u, ct, v["flowers"])
        if v["seal"] > 0.01:
            self._paint_seal(p, u, v["seal"])
        if v["rune"] > 0.01:
            self._paint_rune(p, u, v["rune"])
        if v["vines"] > 0.01:
            self._paint_vines(p, u, v["vines"])
        if v["bound"] > 0.01:
            self._paint_bindings(p, u, self._kind["bound"], v["bound"])
        if v["hat"] > 0.01:
            self._paint_hat(p, u, v["hat"])
        if m.mood in ("dizzy", "stunned"):
            for i in range(3):
                a = self.t * 3 + i * 2.094
                draw_star(p, QPointF(math.cos(a) * 1.0 * u, (TOP_Y - 1.4) * u + math.sin(a) * 0.25 * u),
                          0.17 * u)
        if v["shield"] > 0.01:
            self._paint_shield(p, u, self._kind["shield"], v["shield"])

    def _paint_face(self, p: QPainter, u: float):
        """The carved holes, unlit: dark inside, or water or ice showing."""
        v, ct = self.v, self.ct
        flesh, dark = self._ink(0.52), self._ink(0.02)
        level = (-2.0 + 0.03 * math.sin(ct * 2.0)) * u
        p.setPen(Qt.NoPen)
        for hole, inner in self._face(u):
            p.fillPath(hole, flesh)
            p.fillPath(inner, dark)
            if v["fill"] > 0.01:
                p.save()
                p.setClipPath(inner)
                water = v["fill"] * (1 - v["ice"])
                if water > 0.01:
                    g = QLinearGradient(0, level, 0, 0)
                    g.setColorAt(0, T.qcolor("#4a9dff", 0.95 * water))
                    g.setColorAt(1, T.qcolor("#173f9e", 0.95 * water))
                    p.fillRect(QRectF(-3 * u, level, 6 * u, -level), g)
                    p.setPen(QPen(T.qcolor("#bfe4ff", 0.8 * water), 0.035 * u))
                    p.drawLine(QPointF(-3 * u, level), QPointF(3 * u, level))
                    p.setPen(Qt.NoPen)
                if v["ice"] > 0.01:
                    g = QLinearGradient(0, -2.5 * u, 0, 0)
                    g.setColorAt(0, T.qcolor("#f2fbff", 0.95 * v["ice"]))
                    g.setColorAt(1, T.qcolor("#8fd3ff", 0.9 * v["ice"]))
                    p.fillRect(QRectF(-3 * u, -2.6 * u, 6 * u, 2.6 * u), g)
                    p.setPen(QPen(T.qcolor("#ffffff", 0.6 * v["ice"]), 0.025 * u))
                    for x in (-1.0, -0.3, 0.5, 1.1):
                        p.drawLine(QPointF(x * u, -2.5 * u), QPointF((x + 0.35) * u, -0.2 * u))
                    p.setPen(Qt.NoPen)
                p.restore()

    def _fire_colours(self) -> tuple:
        """(hot core, body, edge, outer), flesh, skin glow"""
        if self.model.fire_color == "green":
            return ("#f0ffe0", "#8dff7a", "#2bd96b", "#119a45"), "#d8ffcf", "#3bff7a"
        return ("#fff6cf", "#ffc65a", "#ff8a24", "#e0561a"), "#ffe4a0", "#ff8a2a"

    def _flicker(self) -> float:
        ct = self.ct
        return 0.86 + 0.08 * math.sin(ct * 9.1) + 0.06 * math.sin(ct * 23.7 + 1.3)

    def _paint_glow(self, p: QPainter, u: float, k: float, halo: bool = True):
        """The lit candle: glowing holes, light through the skin and the lid's
        cut, a halo, and the flame itself in the grin."""
        cols, flesh, skin = self._fire_colours()
        f = self._flicker()
        c = QPointF(0, -1.1 * u)
        p.save()
        p.setPen(Qt.NoPen)
        if halo:
            p.setCompositionMode(QPainter.CompositionMode_Screen)
            g = QRadialGradient(QPointF(0, -1.5 * u), 4.6 * u)
            g.setColorAt(0, T.qcolor(skin, 0.30 * k * f))
            g.setColorAt(0.45, T.qcolor(skin, 0.10 * k * f))
            g.setColorAt(1, T.qcolor(skin, 0.0))
            p.setBrush(g)
            p.drawEllipse(QPointF(0, -1.5 * u), 4.6 * u, 4.6 * u)
            p.save()
            p.setClipPath(self._silhouette(u))
            g = QRadialGradient(QPointF(0, -1.45 * u), 2.7 * u)
            g.setColorAt(0, T.qcolor(skin, 0.55 * k * f))
            g.setColorAt(0.55, T.qcolor(skin, 0.2 * k * f))
            g.setColorAt(1, T.qcolor(skin, 0.0))
            p.setBrush(g)
            p.drawEllipse(QPointF(0, -1.45 * u), 2.7 * u, 2.7 * u)
            p.restore()
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        g = QRadialGradient(c, 2.1 * u * (0.92 + 0.08 * f))
        for at, col in zip((0.0, 0.35, 0.75, 1.0), cols):
            g.setColorAt(at, T.qcolor(col, k))
        for hole, inner in self._face(u):
            p.fillPath(hole, T.qcolor(flesh, k))
            p.fillPath(inner, g)
        # the candle flame, seen through the grin
        mouth = self._face(u)[-1][1]
        p.setClipPath(mouth)
        sway = math.sin(self.ct * 5.3) * 0.04 * u
        flame = QPainterPath(QPointF(-0.1 * u, -0.38 * u))
        flame.cubicTo(QPointF(-0.12 * u, -0.6 * u), QPointF(sway - 0.02 * u, -0.78 * u), QPointF(sway, -0.9 * u * f))
        flame.cubicTo(QPointF(sway + 0.02 * u, -0.78 * u), QPointF(0.12 * u, -0.6 * u), QPointF(0.1 * u, -0.38 * u))
        flame.closeSubpath()
        p.fillPath(flame, T.qcolor("#ffffff", 0.9 * k))
        p.setClipping(False)
        for width, alpha in ((0.16, 0.16), (0.035, 0.55)):  # light leaking from the lid's cut
            p.setPen(QPen(T.qcolor(flesh if width < 0.1 else skin, alpha * k * f), width * u,
                          Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(self._seam(u))
        p.restore()

    def _paint_shards(self, p: QPainter, u: float, img: QImage, origin: QPointF, k: float):
        e = 1 - (1 - k) ** 3
        face = [hole for hole, _inner in self._face(u)]
        for poly, (dx, dy, rot, shrink) in zip(SHARDS, SCATTER):
            pts = [QPointF(x * u, y * u) for x, y in poly]
            c = QPointF(sum(q.x() for q in pts) / len(pts), sum(q.y() for q in pts) / len(pts))
            p.save()
            p.translate(c.x() + dx * u * e, c.y() + dy * u * e)
            p.rotate(rot * e)
            p.scale(1 + (shrink - 1) * e, 1 + (shrink - 1) * e)
            p.translate(-c.x(), -c.y())
            clip = QPainterPath()
            clip.addPolygon(QPolygonF(pts))
            p.setClipPath(clip)
            p.drawImage(origin, img)
            for hole in face:
                p.fillPath(hole, self._ink(0.04))
            p.restore()
        if e > 0.5:                                   # seeds and pulp on the ground
            rng = random.Random(8)
            p.setPen(Qt.NoPen)
            for _ in range(26):
                at = QPointF(rng.uniform(-2.6, 2.6) * u, rng.uniform(-0.15, 0.1) * u)
                p.setBrush(T.qcolor(rng.choice(PULP_COLOURS), (e - 0.5) * 2))
                p.drawEllipse(at, rng.uniform(0.04, 0.09) * u, rng.uniform(0.025, 0.05) * u)

    def _paint_icicles(self, p: QPainter, u: float, k: float):
        rng = random.Random(4)
        p.setPen(Qt.NoPen)
        p.setBrush(T.qcolor("#e8f8ff", 0.9 * k))
        for i in range(11):                           # under the lid's cut
            a = math.pi * (0.08 + 0.84 * i / 10)
            x, y = -math.cos(a) * 1.05 * u, (TOP_Y + math.sin(a) * 0.3 + 0.04) * u
            ln = rng.uniform(0.15, 0.4) * u * k
            p.drawPolygon(QPolygonF([QPointF(x - 0.05 * u, y), QPointF(x + 0.05 * u, y), QPointF(x, y + ln)]))
        for x in (-1.25, -0.8, -0.3, 0.75, 1.2):      # and the grin
            y = -0.3 * u - (abs(x) ** 2) * 0.28 * u
            ln = rng.uniform(0.2, 0.42) * u * k
            p.drawPolygon(QPolygonF([QPointF((x - 0.06) * u, y), QPointF((x + 0.06) * u, y),
                                     QPointF(x * u, y + ln)]))

    def _paint_flowers(self, p: QPainter, u: float, ct: float, k: float):
        ry = (TOP_Y - 0.1) * u
        heads = ((-1.1, -1.0), (-0.6, -1.5), (0.0, -1.75), (0.55, -1.45), (1.1, -0.95), (-0.3, -1.1),
                 (0.35, -0.9))
        for i, (hx, hy) in enumerate(heads):
            sway = math.sin(ct * 1.5 + i) * 0.06
            end = QPointF((hx + sway) * u * k, ry + hy * u * k)
            stem = QPainterPath(QPointF(hx * 0.4 * u, ry + 0.15 * u))
            stem.quadTo(QPointF(hx * 0.6 * u, ry + hy * 0.4 * u * k), end)
            p.setPen(QPen(QColor("#3e9b4f"), 0.07 * u, Qt.SolidLine, Qt.RoundCap))
            p.setBrush(Qt.NoBrush)
            p.drawPath(stem)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#4fbf62"))
            leaf = stem.pointAtPercent(0.55)
            p.drawEllipse(leaf + QPointF(0.1 * u, 0), 0.13 * u * k, 0.06 * u * k)
            col = QColor(FLOWER_COLOURS[i % len(FLOWER_COLOURS)])
            r = 0.24 * u * k
            p.save()
            p.translate(end)
            p.rotate(ct * 8 + i * 30)
            p.setBrush(col)
            for j in range(5):
                p.rotate(72)
                p.drawEllipse(QPointF(r * 0.75, 0), r * 0.7, r * 0.4)
            p.setBrush(QColor("#ffd36e"))
            p.drawEllipse(QPointF(0, 0), r * 0.35, r * 0.35)
            p.restore()

    def _paint_vines(self, p: QPainter, u: float, k: float):
        """Pumpkin vines curling up both sides, with leaves, tendrils and
        yellow blossoms."""
        for side in (-1, 1):
            P = lambda x, y: QPointF(side * x * u, y * u)
            path = QPainterPath(P(2.75, 0.05))
            path.cubicTo(P(2.6, -0.9), P(2.75, -1.9), P(2.1, -2.75))
            path.cubicTo(P(1.6, -3.3), P(0.9, -3.4), P(0.4, -3.2))
            n = max(2, int(48 * k))
            pts = [path.pointAtPercent(min(1.0, k * i / (n - 1))) for i in range(n)]
            p.setPen(QPen(QColor("#2f7d3d"), 0.08 * u, Qt.SolidLine, Qt.RoundCap))
            p.setBrush(Qt.NoBrush)
            p.drawPolyline(QPolygonF(pts))
            for s in (0.3, 0.7):                      # curly tendrils
                if s <= k:
                    at = path.pointAtPercent(s)
                    curl = QPainterPath(at)
                    curl.cubicTo(at + P(-0.35, -0.05), at + P(-0.4, -0.4), at + P(-0.2, -0.38))
                    curl.cubicTo(at + P(-0.08, -0.36), at + P(-0.1, -0.22), at + P(-0.2, -0.24))
                    p.setPen(QPen(QColor("#5fae4a"), 0.03 * u, Qt.SolidLine, Qt.RoundCap))
                    p.drawPath(curl)
            p.setPen(Qt.NoPen)
            for j, s in enumerate((0.12, 0.25, 0.42, 0.55, 0.68, 0.82, 0.92)):
                if s > k:
                    break
                at = path.pointAtPercent(s)
                p.save()
                p.translate(at)
                p.rotate(-path.angleAtPercent(s) + (55 if j % 2 else -55))
                p.setBrush(QColor("#4fbf62" if j % 2 else "#3ea552"))
                for dx, r in ((0.16, 0.13), (0.3, 0.11), (0.24, 0.1)):
                    p.drawEllipse(QPointF(dx * u, (0.06 if dx == 0.24 else 0) * u), r * u, r * 0.8 * u)
                p.restore()
            for s in (0.48, 0.97):
                if s <= k:
                    at = path.pointAtPercent(s)
                    p.setBrush(QColor("#ffc93a"))
                    for j in range(5):
                        a = j * 1.2566
                        p.drawEllipse(at + QPointF(math.cos(a) * 0.09 * u, math.sin(a) * 0.09 * u),
                                      0.08 * u, 0.08 * u)
                    p.setBrush(QColor("#ff8a24"))
                    p.drawEllipse(at, 0.05 * u, 0.05 * u)

    def _paint_bindings(self, p: QPainter, u: float, kind: str, k: float):
        P = lambda x, y: QPointF(x * u, y * u)
        if kind == "cuffs":
            pulse = 0.75 + 0.25 * math.sin(self.t * 4)
            for rect in (QRectF(-2.2 * u, -2.6 * u, 4.4 * u, 0.7 * u), QRectF(-2.0 * u, -1.15 * u, 4.0 * u, 0.6 * u)):
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(T.qcolor(T.GOLD, 0.3 * k * pulse), 0.35 * u, Qt.SolidLine, Qt.RoundCap))
                p.drawArc(rect, 180 * 16, 180 * 16)
                p.setPen(QPen(T.qcolor("#fff3c4", 0.95 * k), 0.08 * u, Qt.SolidLine, Qt.RoundCap))
                p.drawArc(rect, 180 * 16, 180 * 16)
            return
        bands = []
        b = QPainterPath(P(-2.3, -2.4))
        b.cubicTo(P(-0.9, -2.3), P(0.9, -1.0), P(2.25, -0.85))
        bands.append(b)
        b = QPainterPath(P(-2.25, -0.85))
        b.cubicTo(P(-0.9, -1.0), P(0.9, -2.3), P(2.3, -2.4))
        bands.append(b)
        b = QPainterPath(P(-0.42, -3.12))
        b.cubicTo(P(-0.3, -2.95), P(0.3, -2.95), P(0.44, -3.1))
        bands.append(b)
        width, base, dark, hi = (0.2, "#8b5a2b", "#5e3a17", "#c48a4f") if kind == "ropes" else \
            (0.11, "#b03a48", "#7a1f2b", "#e16a78")
        for path in bands:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(T.qcolor(base, k), width * u, Qt.SolidLine, Qt.RoundCap))
            p.drawPath(path)
            twist = QPen(T.qcolor(dark, k), width * u, Qt.CustomDashLine, Qt.FlatCap)
            twist.setDashPattern([0.35, 0.8])
            p.setPen(twist)
            p.drawPath(path)
            p.setPen(QPen(T.qcolor(hi, 0.8 * k), width * 0.25 * u, Qt.SolidLine, Qt.RoundCap))
            p.drawPath(path.translated(0, -width * 0.25 * u))

    def _paint_seal(self, p: QPainter, u: float, k: float):
        """Colloportus: a gold band over the lid's cut and a padlock."""
        for width, col, alpha in ((0.2, "#b8862b", 0.9), (0.08, "#ffe9a8", 0.95)):
            p.setPen(QPen(T.qcolor(col, alpha * k), width * u * (0.6 + 0.4 * k), Qt.SolidLine, Qt.RoundCap,
                          Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(self._seam(u))
        lock = QPointF(0, -2.42 * u)
        p.setPen(QPen(T.qcolor("#e6c46f", k), 0.07 * u))
        p.drawArc(QRectF(lock.x() - 0.17 * u, lock.y() - 0.42 * u, 0.34 * u, 0.4 * u), 0, 180 * 16)
        p.setPen(QPen(T.qcolor("#6b4c12", k), 0.03 * u))
        p.setBrush(T.qcolor("#d9b25a", k))
        p.drawRoundedRect(QRectF(lock.x() - 0.26 * u, lock.y() - 0.22 * u, 0.52 * u, 0.42 * u),
                          0.06 * u, 0.06 * u)
        p.setBrush(T.qcolor("#3d2a0c", k))
        p.drawEllipse(QPointF(lock.x(), lock.y() - 0.04 * u), 0.05 * u, 0.06 * u)

    def _paint_rune(self, p: QPainter, u: float, k: float):
        c, r = QPointF(1.72 * u, -1.75 * u), 0.28 * u
        pulse = 0.7 + 0.3 * math.sin(self.t * 3)
        pts = [c + QPointF(math.sin(i * 2.513) * r, -math.cos(i * 2.513) * r) for i in range(6)]
        for width, col, alpha in ((0.2, "#ff7a2f", 0.35 * pulse), (0.05, "#ffe08a", 1.0)):
            p.setPen(QPen(T.qcolor(col, alpha * k), width * u, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, r * 1.15, r * 1.15)
            p.drawPolyline(QPolygonF(pts))

    def _paint_hat(self, p: QPainter, u: float, k: float):
        base_y = (TOP_Y - 0.2) * u
        tri = QPolygonF([QPointF(-0.6 * u, base_y), QPointF(0.6 * u, base_y),
                         QPointF(0.15 * u, base_y - 1.5 * u * k)])
        clip = QPainterPath()
        clip.addPolygon(tri)
        p.save()
        p.setClipPath(clip)
        p.fillRect(QRectF(-0.7 * u, base_y - 1.6 * u, 1.4 * u, 1.6 * u), QColor("#ff8fb3"))
        p.setPen(QPen(QColor("#ffd36e"), 0.14 * u))
        for i in range(-4, 6):
            p.drawLine(QPointF((i * 0.3 - 0.6) * u, base_y), QPointF((i * 0.3 + 0.4) * u, base_y - 1.6 * u))
        p.restore()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#9fd8ff"))
        p.drawEllipse(QPointF(0.15 * u, base_y - 1.5 * u * k), 0.16 * u * k, 0.16 * u * k)

    def _paint_legs(self, p: QPainter, u: float, ct: float, k: float):
        """Piertotum Locomotor: two little vine legs."""
        p.setPen(QPen(QColor("#2f7d3d"), 0.12 * u, Qt.SolidLine, Qt.RoundCap))
        for side, phase in ((-1, 0.0), (1, math.pi)):
            swing = math.sin(ct * 11 + phase) * 0.18 * u
            hip = QPointF(side * 0.85 * u, -0.1 * u)
            foot = QPointF(side * 0.95 * u + swing, 0.45 * u * k)
            p.drawLine(hip, foot)
            p.setBrush(QColor("#3ea552"))
            p.drawEllipse(foot + QPointF(side * 0.08 * u, 0), 0.18 * u, 0.08 * u)

    def _paint_shield(self, p: QPainter, u: float, kind: str, k: float):
        c = QPointF(0, -1.9 * u)
        if kind == "protego":
            g = QRadialGradient(c, 3.2 * u)
            g.setColorAt(0, T.qcolor("#8fd0ff", 0.0))
            g.setColorAt(0.75, T.qcolor("#8fd0ff", 0.08 * k))
            g.setColorAt(1, T.qcolor("#8fd0ff", 0.3 * k))
            p.setPen(QPen(T.qcolor("#bfe6ff", 0.7 * k), 0.05 * u))
            p.setBrush(g)
            p.drawEllipse(c, 3.1 * u, 2.75 * u)
            p.setBrush(Qt.NoBrush)
            rect = QRectF(c.x() - 2.95 * u, c.y() - 2.6 * u, 5.9 * u, 5.2 * u)
            for i in range(3):
                start = int((self.t * 60 + i * 120) % 360)
                p.setPen(QPen(T.qcolor("#ffffff", 0.45 * k), 0.04 * u, Qt.SolidLine, Qt.RoundCap))
                p.drawArc(rect, start * 16, 40 * 16)
        elif kind == "salvio":
            p.setPen(Qt.NoPen)
            g = QRadialGradient(c, 3.0 * u)
            g.setColorAt(0, T.qcolor(T.GOLD, 0.0))
            g.setColorAt(1, T.qcolor(T.GOLD, 0.12 * k))
            p.setBrush(g)
            p.drawEllipse(c, 3.0 * u, 2.7 * u)
            p.setFont(T.font(max(8.0, 0.32 * u)))
            for i in range(12):
                a = self.t * 0.8 + i * math.pi / 6
                front = math.sin(a) > 0
                at = QPointF(math.cos(a) * 2.8 * u, -1.6 * u + math.sin(a) * 0.55 * u)
                p.setPen(T.qcolor(T.GOLD, (0.95 if front else 0.35) * k))
                p.drawText(QRectF(at.x() - 0.3 * u, at.y() - 0.3 * u, 0.6 * u, 0.6 * u), Qt.AlignCenter,
                           "✦✧◇"[i % 3])
        else:                                       # the Patronus: silver wisps circling
            for i in range(3):
                for j in range(9):
                    a = self.t * 1.6 + i * 2.094 - j * 0.09
                    at = QPointF(math.cos(a) * 2.7 * u, -2.0 * u + math.sin(a) * 0.9 * u + math.sin(a * 2) * 0.3 * u)
                    alpha = (1 - j / 9) * 0.85 * k
                    p.setPen(Qt.NoPen)
                    p.setBrush(T.qcolor("#dff3ff", alpha))
                    p.drawEllipse(at, (0.13 - j * 0.01) * u, (0.13 - j * 0.01) * u)
            g = QRadialGradient(c, 3.2 * u)
            g.setColorAt(0, T.qcolor("#dff3ff", 0.10 * k))
            g.setColorAt(1, T.qcolor("#dff3ff", 0.0))
            p.setBrush(g)
            p.drawEllipse(c, 3.2 * u, 3.2 * u)

    # world -------------------------------------------------------------------------

    def _paint_floor_fx(self, p: QPainter, u: float, cx: float, floor: float):
        v = self.v
        floor += self._ground(v["x"]) * u            # the patch under wherever it is
        if v["alpha"] > 0.01 and v["x"] < 7.4:     # contact shadow, smaller as it rises
            lift = max(0.0, -v["y"] - (0.75 if self.model.pose == FALLEN else 0.0))
            k = max(0.25, 1 - lift / 5)
            sx = cx + v["x"] * u
            g = QRadialGradient(QPointF(sx, floor), 2.6 * u * k)
            g.setColorAt(0, QColor(0, 0, 0, int(170 * k * v["alpha"])))
            g.setColorAt(1, QColor(0, 0, 0, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawEllipse(QPointF(sx, floor), 2.6 * u * k, 0.4 * u * k)
        for name, start, data in self.cues:
            if name == "spill" and data.get("contents") == WATER:
                k = (self.t - start) / CUE_S["spill"]
                p.setPen(Qt.NoPen)
                p.setBrush(T.qcolor("#59b7ff", 0.45 * (1 - k)))
                p.drawEllipse(QPointF(cx + (2.6 + v["x"]) * u, floor + 0.05 * u), 1.8 * u * min(1.0, k * 4),
                              0.24 * u)
        if v["stuck"] > 0.01:
            p.setPen(Qt.NoPen)
            for dx, r in ((-1.9, 0.38), (-1.1, 0.3), (0.0, 0.26), (1.2, 0.34), (2.0, 0.4)):
                p.setBrush(T.qcolor("#9fd23a", 0.75 * v["stuck"]))
                p.drawEllipse(QPointF(cx + (dx + v["x"]) * u, floor - 0.02 * u), r * u, r * 0.4 * u)
                p.setBrush(T.qcolor("#e2ff9a", 0.6 * v["stuck"]))
                p.drawEllipse(QPointF(cx + (dx + v["x"] - 0.08) * u, floor - 0.06 * u), r * 0.3 * u,
                              r * 0.12 * u)

    def _paint_world_fx(self, p: QPainter, u: float, cx: float, floor: float):
        v = self.v
        if v["weather"] > 0.01:
            self._paint_weather(p, u, cx, floor, v["weather"])
        mid = self._world(0, PIVOT_Y)
        for name, start, data in self.cues:
            k = (self.t - start) / CUE_S[name]
            if name in ("finite", "shock", "block", "freeze"):
                col = {"finite": "#ffffff", "shock": "#c9b8ff", "block": "#bfe6ff", "freeze": "#9fe6ff"}[name]
                r = (1.0 + 4.0 * k) * u
                p.setPen(QPen(T.qcolor(col, 0.7 * (1 - k)), 0.08 * u + 6 * (1 - k)))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(mid, r, r * 0.85)
            elif name == "zap":
                p.setPen(QPen(T.qcolor("#ff4d4d", 0.35 * (1 - k)), 0.5 * u, Qt.SolidLine, Qt.RoundCap))
                p.drawLine(QPointF(0, mid.y() - 1.5 * u), mid)
                p.setPen(QPen(T.qcolor("#ffd6d6", 0.9 * (1 - k)), 0.1 * u, Qt.SolidLine, Qt.RoundCap))
                p.drawLine(QPointF(0, mid.y() - 1.5 * u), mid)
            elif name in ("blast", "light"):
                col = "#ffe0a8" if name == "blast" else "#fff8e6"
                p.save()
                p.setClipPath(self._frame())
                p.fillRect(self.rect(), T.qcolor(col, 0.55 * (1 - k) ** 2))
                p.restore()
            elif name == "traces":
                names = [n for n in self.model.history[:-1]][-5:]
                p.setFont(T.font(max(10.0, 0.3 * u), serif=True, italic=True))
                fade = min(1.0, k * 6) * min(1.0, (1 - k) * 4)
                for i, n in enumerate(names):
                    a = i * 2 * math.pi / max(1, len(names)) + self.t * 0.4
                    at = QPointF(mid.x() + math.cos(a) * 3.4 * u, mid.y() + math.sin(a) * 1.6 * u - k * u)
                    p.setPen(T.qcolor(T.GOLD, 0.85 * fade))
                    p.drawText(QRectF(at.x() - 2 * u, at.y() - 0.3 * u, 4 * u, 0.6 * u), Qt.AlignCenter, n)
        for s in self.spiders:
            alpha = min(1.0, s[4] * 2)
            p.save()
            p.translate(s[0], s[1])
            p.setPen(QPen(T.qcolor("#0d0a14", alpha), max(1.0, 0.03 * u)))
            for j in range(4):
                for side in (-1, 1):
                    wig = math.sin(s[5] + j) * 0.05 * u
                    p.drawLine(QPointF(0, 0), QPointF(side * 0.22 * u, (j - 1.5) * 0.08 * u - 0.06 * u + wig))
            p.setPen(Qt.NoPen)
            p.setBrush(T.qcolor("#140f1e", alpha))
            p.drawEllipse(QPointF(0, 0), 0.12 * u, 0.1 * u)
            p.drawEllipse(QPointF(0, -0.11 * u), 0.07 * u, 0.06 * u)
            p.restore()

    def _paint_weather(self, p: QPainter, u: float, cx: float, floor: float, k: float):
        kind = self._kind["weather"]
        top = max(0.6 * u, floor - 6.5 * u)
        bottom = top + 0.9 * u
        rng = random.Random(21)
        if kind == "rain":
            p.setPen(QPen(T.qcolor("#9fc8ff", 0.6 * k), max(1.0, 0.03 * u), Qt.SolidLine, Qt.RoundCap))
            for _ in range(40):
                x = cx + rng.uniform(-2.2, 2.2) * u
                y = bottom + ((rng.random() + self.t * 1.3) % 1.0) * (floor - bottom)
                p.drawLine(QPointF(x, y), QPointF(x - 0.05 * u, y + 0.35 * u))
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(T.qcolor("#ffffff", 0.85 * k))
            for _ in range(46):
                ph = rng.random()
                y = bottom + ((ph + self.t * 0.25) % 1.0) * (floor - bottom)
                x = cx + rng.uniform(-2.3, 2.3) * u + math.sin(self.t * 1.5 + ph * 9) * 0.2 * u
                p.drawEllipse(QPointF(x, y), 0.05 * u, 0.05 * u)
        p.setPen(Qt.NoPen)
        for dx, dy, r in ((-1.5, 0.3, 0.75), (-0.6, 0.0, 0.95), (0.4, 0.1, 0.9), (1.35, 0.3, 0.7),
                          (-0.1, 0.45, 0.85)):
            c = QPointF(cx + dx * u, top + dy * u)
            p.setBrush(self._ink(0.42, 0.95 * k))
            p.drawEllipse(c, r * u, r * 0.75 * u)
            p.setBrush(self._ink(0.7, 0.9 * k))         # flat moonlit top
            p.drawEllipse(c - QPointF(0.08 * u, 0.12 * u), r * 0.8 * u, r * 0.5 * u)

    def _paint_light(self, p: QPainter, u: float, cx: float, floor: float):
        lit = self.v["lit"]
        if lit < 0.01:
            return
        c = QPointF(cx + 2.7 * u, floor - 5.4 * u + math.sin(self.t * 1.7) * 0.12 * u)
        g = QRadialGradient(c, 3.6 * u)
        g.setColorAt(0, T.qcolor("#fff8e6", 0.45 * lit))
        g.setColorAt(0.25, T.qcolor("#ffe9b0", 0.18 * lit))
        g.setColorAt(1, T.qcolor("#ffe9b0", 0.0))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, 3.6 * u, 3.6 * u)
        rng = random.Random(2)
        for _ in range(40):                          # stipple sparkle round the light
            at = c + QPointF(rng.gauss(0, 0.6) * u, rng.gauss(0, 0.6) * u)
            p.setBrush(T.qcolor("#ffffff", rng.uniform(0.3, 0.9) * lit))
            p.drawEllipse(at, 1.0, 1.0)
        p.setBrush(T.qcolor("#ffffff", lit))
        p.drawEllipse(c, 0.18 * u, 0.18 * u)

    def _paint_emissive(self, p: QPainter, u: float):
        """In the dark, light sources still shine."""
        v = self.v
        if v["alpha"] < 0.01 or v["x"] > 7.4 or v["broken"] > 0.5:
            return
        p.save()
        p.setTransform(self._xf)
        p.setOpacity(v["alpha"])
        if v["fire"] > 0.01:
            self._paint_glow(p, u, v["fire"] * v["dark"])
        if v["rune"] > 0.01:
            self._paint_rune(p, u, v["rune"])
        if v["bound"] > 0.01 and self._kind["bound"] == "cuffs":
            self._paint_bindings(p, u, "cuffs", v["bound"])
        if v["shield"] > 0.01:
            self._paint_shield(p, u, self._kind["shield"], v["shield"])
        p.restore()

    def _paint_floaters(self, p: QPainter):
        for x, y, _vx, _vy, life, max_life, text, colour, px in self.floaters:
            k = life / max_life
            p.setPen(T.qcolor(colour, min(1.0, k * 1.6)))
            p.setFont(T.font(px * 0.75, serif=text in ("Z", "ha", "shh…")))
            p.drawText(QRectF(x - px * 2, y - px, px * 4, px * 2), Qt.AlignCenter, text)

    def _paint_caption(self, p: QPainter):
        title, text = self.caption
        age = self.t - self._caption_t
        if not title or age > 7.0:
            return
        alpha = min(1.0, age * 4) * min(1.0, (7.0 - age) / 1.2)
        w, h = self.width(), self.height()
        box = QRectF(24, h - 92, w - 48, 80)
        p.setPen(T.qcolor(T.GOLD, alpha))
        p.setFont(T.font(19, serif=True))
        p.drawText(QRectF(box.left(), box.top(), box.width(), 36), Qt.AlignCenter, title)
        if text:
            p.setPen(T.qcolor(T.TEXT, 0.92 * alpha))
            p.setFont(T.font(11.5, italic=True))
            p.drawText(QRectF(box.left(), box.top() + 36, box.width(), 40),
                       Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, text)
