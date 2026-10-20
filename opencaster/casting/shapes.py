"""
opencaster.casting.shapes — Spell gesture templates (SVG)
==========================================================
Each spell is one SVG in spells/ with a single path drawn in casting order:
the path's start is where the gesture starts.  The spell's name is the file
name.  Names are compared by spell_key() (lower-case, letters and digits
only), so "Wingardium Leviosa", "wingardium leviosa" and
"wingardium_leviosa" are the same spell everywhere.
"""

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

RESAMPLE_N = 64

_NUM = r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?"


def spell_key(name: str) -> str:
    """'Wingardium Leviosa' / 'wingardium_leviosa' → 'wingardiumleviosa'."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


# ── SVG path parsing ───────────────────────────────────────────────────────────

def _cubic(p0, p1, p2, p3, steps=12):
    out = []
    for i in range(steps + 1):
        t = i / steps; u = 1 - t
        out.append((u**3*p0[0] + 3*u**2*t*p1[0] + 3*u*t**2*p2[0] + t**3*p3[0],
                    u**3*p0[1] + 3*u**2*t*p1[1] + 3*u*t**2*p2[1] + t**3*p3[1]))
    return out


def _quad(p0, p1, p2, steps=12):
    out = []
    for i in range(steps + 1):
        t = i / steps; u = 1 - t
        out.append((u**2*p0[0] + 2*u*t*p1[0] + t**2*p2[0],
                    u**2*p0[1] + 2*u*t*p1[1] + t**2*p2[1]))
    return out


def path_points(d: str) -> list:
    """Flatten an SVG path d= string into one (x, y) list (curves sampled)."""
    pts = []
    tokens = re.findall(rf"[MmLlHhVvCcQqZzSsTt]|{_NUM}", d)
    cx = cy = sx = sy = 0.0
    cmd, i = "M", 0

    def num():
        nonlocal i
        v = float(tokens[i]); i += 1
        return v

    while i < len(tokens):
        tok = tokens[i]
        if tok.isalpha():
            cmd = tok; i += 1
            continue
        if cmd in "Mm":
            x, y = num(), num()
            if cmd == "m": x += cx; y += cy
            cx, cy, sx, sy = x, y, x, y
            pts.append((cx, cy))
            cmd = "L" if cmd == "M" else "l"
        elif cmd in "Ll":
            x, y = num(), num()
            if cmd == "l": x += cx; y += cy
            cx, cy = x, y
            pts.append((cx, cy))
        elif cmd in "Hh":
            x = num()
            cx = x + cx if cmd == "h" else x
            pts.append((cx, cy))
        elif cmd in "Vv":
            y = num()
            cy = y + cy if cmd == "v" else y
            pts.append((cx, cy))
        elif cmd in "Cc":
            x1, y1, x2, y2, x, y = (num() for _ in range(6))
            if cmd == "c":
                x1 += cx; y1 += cy; x2 += cx; y2 += cy; x += cx; y += cy
            pts.extend(_cubic((cx, cy), (x1, y1), (x2, y2), (x, y)))
            cx, cy = x, y
        elif cmd in "Qq":
            x1, y1, x, y = (num() for _ in range(4))
            if cmd == "q":
                x1 += cx; y1 += cy; x += cx; y += cy
            pts.extend(_quad((cx, cy), (x1, y1), (x, y)))
            cx, cy = x, y
        elif cmd in "Zz":
            pts.append((sx, sy)); cx, cy = sx, sy; i += 1
        else:
            i += 1
    return pts


def resample(points, n: int = RESAMPLE_N) -> np.ndarray:
    """Resample a polyline to exactly n points evenly spaced by arc length."""
    if len(points) < 2:
        return np.zeros((n, 2))
    pts = np.asarray(points, dtype=float)
    seg = np.hypot(*np.diff(pts, axis=0).T)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    if cum[-1] < 1e-9:
        return np.tile(pts[0], (n, 1))
    t = np.linspace(0, cum[-1], n)
    return np.stack([np.interp(t, cum, pts[:, 0]), np.interp(t, cum, pts[:, 1])], axis=1)


def _normalise(pts: np.ndarray) -> np.ndarray:
    """Centre on the centroid; scale so the max |coordinate| is 1."""
    pts = pts - pts.mean(axis=0)
    scale = np.abs(pts).max()
    return pts / scale if scale > 1e-9 else pts


def svg_points(path: Path) -> list:
    """Every drawable point in an SVG, in document order (SVG coordinates)."""
    pts = []
    for elem in ET.parse(path).getroot().iter():
        tag = elem.tag.split("}")[-1]
        if tag == "path":
            pts.extend(path_points(elem.get("d", "")))
        elif tag in ("polyline", "polygon"):
            nums = [float(x) for x in re.findall(_NUM, elem.get("points", ""))]
            pts.extend(zip(nums[0::2], nums[1::2]))
        elif tag == "line":
            pts += [(float(elem.get("x1", 0)), float(elem.get("y1", 0))),
                    (float(elem.get("x2", 0)), float(elem.get("y2", 0)))]
    return pts


# ── Templates ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SpellTemplate:
    name: str              # display name (file name)
    key: str               # spell_key(name)
    points: np.ndarray     # (RESAMPLE_N, 2), y up, centred, max |coord| = 1
    outline: np.ndarray    # (M, 2) full-resolution path, y up, same frame as points
    file: Path


def load_template(path: Path) -> Optional[SpellTemplate]:
    try:
        raw = svg_points(path)
    except Exception as e:
        log.warning("cannot read %s: %s", path, e)
        return None
    if len(raw) < 2:
        log.warning("no usable points in %s", path)
        return None
    raw = np.asarray(raw, dtype=float)
    raw[:, 1] = -raw[:, 1]                     # SVG is y-down, the trail is y-up
    pts = resample(raw)
    centre, scale = pts.mean(axis=0), np.abs(pts - pts.mean(axis=0)).max() or 1.0
    name = path.stem
    return SpellTemplate(name, spell_key(name), _normalise(pts),
                         (raw - centre) / scale, path)


class SpellLibrary:
    """All templates in a folder, sorted by name, looked up by spell_key."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self._by_key: dict = {}
        self.reload()

    def reload(self):
        found = {}
        if self.folder.is_dir():
            for f in sorted(self.folder.glob("*.svg"), key=lambda f: f.stem.lower()):
                t = load_template(f)
                if t is not None:
                    found[t.key] = t
        else:
            log.warning("spell folder not found: %s", self.folder)
        self._by_key = found                   # swap: readers keep a consistent view
        log.info("%d spell templates loaded", len(found))

    @property
    def templates(self) -> list:
        return list(self._by_key.values())

    def get(self, name: str) -> Optional[SpellTemplate]:
        return self._by_key.get(spell_key(name)) if name else None

    def names(self) -> list:
        return [t.name for t in self._by_key.values()]

    def __len__(self):
        return len(self._by_key)
