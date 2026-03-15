"""
spell_shapes.py — SVG spell template loader
============================================
Loads every .svg file from the spells/ folder and converts each path
into a normalised sequence of (x, y) points that spell_matcher.py
can compare against a wand trail.
"""

import os
import re
import xml.etree.ElementTree as ET
from typing import Optional

import numpy as np

RESAMPLE_N = 64


def _parse_numbers(s: str) -> list:
    return [float(x) for x in re.findall(r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?", s)]


def _cubic_bezier(p0, p1, p2, p3, steps=12):
    pts = []
    for i in range(steps + 1):
        t = i / steps; u = 1 - t
        x = u**3*p0[0] + 3*u**2*t*p1[0] + 3*u*t**2*p2[0] + t**3*p3[0]
        y = u**3*p0[1] + 3*u**2*t*p1[1] + 3*u*t**2*p2[1] + t**3*p3[1]
        pts.append((x, y))
    return pts

def _quad_bezier(p0, p1, p2, steps=12):
    pts = []
    for i in range(steps + 1):
        t = i / steps; u = 1 - t
        x = u**2*p0[0] + 2*u*t*p1[0] + t**2*p2[0]
        y = u**2*p0[1] + 2*u*t*p1[1] + t**2*p2[1]
        pts.append((x, y))
    return pts


def _path_to_strokes(d: str) -> list:
    """Parse an SVG path d= string into a list of strokes (each stroke is a
    list of (x,y) points). A new stroke begins on every M/m command so that
    multi-stroke spells (pen-up/pen-down) are preserved separately."""
    strokes = []
    current = []
    tokens = re.findall(r"[MmLlHhVvCcQqZzSsTt]|[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?", d)
    cx, cy = 0.0, 0.0
    sx, sy = 0.0, 0.0
    cmd = "M"
    i = 0

    def consume():
        nonlocal i
        v = float(tokens[i]); i += 1; return v

    while i < len(tokens):
        tok = tokens[i]
        if re.match(r"[A-Za-z]", tok):
            cmd = tok; i += 1; continue
        if cmd in ("M", "m"):
            # Pen-up: save current stroke and start a new one
            if current:
                strokes.append(current)
                current = []
            x, y = consume(), consume()
            if cmd == "m": x += cx; y += cy
            cx, cy, sx, sy = x, y, x, y
            current.append((cx, cy))
            cmd = "L" if cmd == "M" else "l"
        elif cmd in ("L", "l"):
            x, y = consume(), consume()
            if cmd == "l": x += cx; y += cy
            cx, cy = x, y
            current.append((cx, cy))
        elif cmd in ("H", "h"):
            x = consume()
            if cmd == "h": x += cx
            cx = x; current.append((cx, cy))
        elif cmd in ("V", "v"):
            y = consume()
            if cmd == "v": y += cy
            cy = y; current.append((cx, cy))
        elif cmd in ("C", "c"):
            x1, y1 = consume(), consume()
            x2, y2 = consume(), consume()
            x,  y  = consume(), consume()
            if cmd == "c":
                x1+=cx; y1+=cy; x2+=cx; y2+=cy; x+=cx; y+=cy
            current.extend(_cubic_bezier((cx,cy),(x1,y1),(x2,y2),(x,y)))
            cx, cy = x, y
        elif cmd in ("Q", "q"):
            x1, y1 = consume(), consume()
            x,  y  = consume(), consume()
            if cmd == "q": x1+=cx; y1+=cy; x+=cx; y+=cy
            current.extend(_quad_bezier((cx,cy),(x1,y1),(x,y)))
            cx, cy = x, y
        elif cmd in ("Z", "z"):
            current.append((sx, sy)); cx, cy = sx, sy; i += 1
        else:
            i += 1

    if current:
        strokes.append(current)
    return strokes


def _path_to_points(d: str) -> list:
    """Flatten all strokes from a path into a single point list.
    Strokes are joined in sequence (used for resampling the full shape)."""
    all_pts = []
    for stroke in _path_to_strokes(d):
        all_pts.extend(stroke)
    return all_pts

def _polyline_to_points(pts_str: str) -> list:
    nums = _parse_numbers(pts_str)
    return [(nums[i], nums[i+1]) for i in range(0, len(nums)-1, 2)]


def _resample(points: list, n: int) -> np.ndarray:
    """Resample a polyline to exactly n evenly-spaced points by arc length."""
    if len(points) < 2:
        return np.zeros((n, 2))
    pts = np.array(points, dtype=float)
    diffs = np.diff(pts, axis=0)
    seg_lens = np.hypot(diffs[:,0], diffs[:,1])
    cum = np.concatenate([[0.0], np.cumsum(seg_lens)])
    total = cum[-1]
    if total < 1e-9:
        return np.tile(pts[0], (n, 1))
    targets = np.linspace(0, total, n)
    xs = np.interp(targets, cum, pts[:,0])
    ys = np.interp(targets, cum, pts[:,1])
    return np.stack([xs, ys], axis=1)


def normalise(pts: np.ndarray) -> np.ndarray:
    """Translate to centroid, scale so max extent = 1."""
    pts = pts - pts.mean(axis=0)
    scale = np.abs(pts).max()
    if scale > 1e-9:
        pts = pts / scale
    return pts

def load_svg(path: str) -> Optional[np.ndarray]:
    """Load an SVG and return a normalised (RESAMPLE_N, 2) array, or None."""
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        all_points = []
        for elem in root.iter():
            tag = elem.tag.split("}")[-1]
            if tag == "path":
                all_points.extend(_path_to_points(elem.get("d", "")))
            elif tag in ("polyline", "polygon"):
                all_points.extend(_polyline_to_points(elem.get("points", "")))
            elif tag == "line":
                x1=float(elem.get("x1",0)); y1=float(elem.get("y1",0))
                x2=float(elem.get("x2",0)); y2=float(elem.get("y2",0))
                all_points += [(x1,y1),(x2,y2)]
        if len(all_points) < 2:
            print(f"  [spells] WARNING: no usable points in {path}")
            return None
        pts = _resample(all_points, RESAMPLE_N)
        pts[:, 1] = -pts[:, 1]   # flip Y: SVG is top-down, wand is bottom-up
        return normalise(pts)
    except Exception as e:
        print(f"  [spells] ERROR loading {path}: {e}")
        return None


class SpellLibrary:
    """Holds all loaded spell templates, keyed by spell name (case-insensitive)."""

    def __init__(self, folder: str = "spells"):
        self._templates: dict = {}
        self._folder = folder
        self.reload()

    def reload(self):
        """Scan the spells/ folder and load any SVG files found."""
        self._templates.clear()
        if not os.path.isdir(self._folder):
            print(f"  [spells] Folder not found: {self._folder}")
            return
        for fname in os.listdir(self._folder):
            if fname.lower().endswith(".svg"):
                name = os.path.splitext(fname)[0]
                pts = load_svg(os.path.join(self._folder, fname))
                if pts is not None:
                    self._templates[name.lower()] = pts
                    print(f"  [spells] Loaded template: {name}")
        print(f"  [spells] {len(self._templates)} spell template(s) loaded.")

    def get(self, spell_name: str) -> Optional[np.ndarray]:
        return self._templates.get(spell_name.lower())

    def names(self) -> list:
        return list(self._templates.keys())
