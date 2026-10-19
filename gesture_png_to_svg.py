"""
gesture_png_to_svg.py — Trace gesture diagrams (PNG) into spell template SVGs
==============================================================================
Built for the MIT-licensed gesture images in eigger/hass-magic-caster-wand
(docs/gestures/*.png): a white stroke on a transparent background that starts
at a round dot and ends at an arrowhead.  Direction matters to
spell_matcher.py, so every trace runs dot → arrowhead.

Fully automatic tracing proved unreliable at crossings, hairpins and
arrowheads, so each gesture is described by a few hand-placed guide points
in gesture_waypoints.json (pixel x, y in the source PNG, in drawing order:
the dot, each corner, both sides of a crossing, the arrow tip).  Between
consecutive points the trace follows the drawn stroke itself — the cheapest
path through the stroke mask, weighted to stay on its centre line — so the
SVG matches the drawing exactly and the guide points only pin the order.

Usage:
    python gesture_png_to_svg.py grid   PNG_DIR OUT_DIR       # gridded images for placing points
    python gesture_png_to_svg.py trace  PNG_DIR OUT_DIR [--review review.png]

Check the review sheet: it overlays each trace (green start, red end, cyan
direction arrows) on its source image.
"""

import argparse
import json
import os

import numpy as np
from scipy import ndimage
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import dijkstra

HERE           = os.path.dirname(os.path.abspath(__file__))
WAYPOINTS_FILE = os.path.join(HERE, "gesture_waypoints.json")

CENTRE_WEIGHT = 6.0    # extra cost near the stroke's edge: keeps routes centred
SNAP_PX       = 25     # guide points snap to stroke within this distance
VIEW, MARGIN  = 200, 24


def load_mask(path: str) -> np.ndarray:
    import matplotlib.image as mpimg
    img = mpimg.imread(path)
    alpha = img[..., 3] if img.ndim == 3 and img.shape[2] == 4 else img[..., :3].mean(-1)
    return alpha > 0.5 * float(alpha.max())


class StrokeRouter:
    """Shortest paths through a stroke mask that prefer its centre line."""

    def __init__(self, mask: np.ndarray):
        self.mask = mask
        self.edt = ndimage.distance_transform_edt(mask)
        ys, xs = np.nonzero(mask)
        self.idx = -np.ones(mask.shape, int)
        self.idx[ys, xs] = np.arange(len(ys))
        self.yx = np.column_stack([ys, xs])
        rows, cols, w = [], [], []
        h, wd = mask.shape
        for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
            ny, nx = ys + dy, xs + dx
            ok = (ny >= 0) & (ny < h) & (nx >= 0) & (nx < wd)
            ok[ok] = mask[ny[ok], nx[ok]]
            a = self.idx[ys[ok], xs[ok]]
            b = self.idx[ny[ok], nx[ok]]
            depth = (self.edt[ys[ok], xs[ok]] + self.edt[ny[ok], nx[ok]]) / 2
            cost = np.hypot(dy, dx) * (1 + CENTRE_WEIGHT / (depth + 0.5))
            rows += [a, b]
            cols += [b, a]
            w += [cost, cost]
        n = len(ys)
        self.graph = coo_matrix((np.concatenate(w), (np.concatenate(rows), np.concatenate(cols))),
                                shape=(n, n)).tocsr()

    def snap(self, x: float, y: float) -> int:
        """Nearest centre-line pixel to a guide point (x, y)."""
        d = np.hypot(self.yx[:, 0] - y, self.yx[:, 1] - x)
        if d.min() > SNAP_PX:
            raise ValueError(f"guide point ({x}, {y}) is {d.min():.0f} px from the stroke")
        cand = np.nonzero(d <= float(d.min()) + 6)[0]
        return int(cand[np.argmax(self.edt[self.yx[cand, 0], self.yx[cand, 1]])])

    def route(self, a: int, b: int) -> list:
        _, pred = dijkstra(self.graph, indices=a, return_predecessors=True)
        if pred[b] < 0 and a != b:
            raise ValueError("guide points are on disconnected parts of the stroke")
        path, cur = [b], b
        while cur != a:
            cur = pred[cur]
            path.append(cur)
        return [tuple(self.yx[i]) for i in path[::-1]]


def trace(png: str, points: list) -> np.ndarray:
    """Route through the stroke along the guide points; returns (N, 2) x, y."""
    r = StrokeRouter(load_mask(png))
    nodes = [r.snap(x, y) for x, y in points]
    path = []
    for a, b in zip(nodes, nodes[1:]):
        seg = r.route(a, b)
        path.extend(seg if not path else seg[1:])
    return np.array(path, float)[:, ::-1]                      # (y, x) → (x, y)


# ── Points → SVG ──────────────────────────────────────────────────────────────

def rdp(pts: np.ndarray, eps: float) -> np.ndarray:
    if len(pts) < 3:
        return pts
    a, b = pts[0], pts[-1]
    ab = b - a
    n = np.linalg.norm(ab)
    rel = pts - a
    d = (np.abs(ab[0] * rel[:, 1] - ab[1] * rel[:, 0]) / n) if n > 0 \
        else np.linalg.norm(rel, axis=1)
    i = int(np.argmax(d))
    if d[i] > eps:
        return np.vstack([rdp(pts[:i + 1], eps)[:-1], rdp(pts[i:], eps)])
    return np.vstack([a, b])


def to_svg(xy: np.ndarray, source: str) -> str:
    xy = ndimage.uniform_filter1d(xy, size=7, axis=0, mode="nearest")
    xy = rdp(xy, 0.8)
    lo, hi = xy.min(0), xy.max(0)
    scale = (VIEW - 2 * MARGIN) / max(float((hi - lo).max()), 1e-9)
    xy = (xy - (lo + hi) / 2) * scale + VIEW / 2
    d = "M " + " L ".join(f"{x:.2f} {y:.2f}" for x, y in xy)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {VIEW} {VIEW}">'
            f'<!-- traced from {source}, eigger/hass-magic-caster-wand (MIT) -->'
            f'<path d="{d}" fill="none" stroke="black" stroke-width="3" '
            f'stroke-linecap="round" stroke-linejoin="round"/></svg>\n')


# ── Sheets ────────────────────────────────────────────────────────────────────

def _sheets(items: list, out: str, draw, cols: int = 6, per_sheet: int = 12,
            dpi: int = 60) -> list:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    files = []
    for k in range(0, len(items), per_sheet):
        chunk = items[k:k + per_sheet]
        rows = -(-len(chunk) // cols)
        fig, axs = plt.subplots(rows, cols, figsize=(cols * 3.0, rows * 4.6), squeeze=False)
        for ax in axs.flat:
            ax.axis("off")
        for ax, item in zip(axs.flat, chunk):
            draw(ax, item)
        fig.tight_layout()
        path = out if len(items) <= per_sheet else out.replace(".png", f"_{k // per_sheet + 1}.png")
        fig.savefig(path, dpi=dpi)
        plt.close(fig)
        files.append(path)
    return files


def grid_sheets(png_dir: str, names: list, out: str) -> list:
    """Images with a 25 px grid (labels every 50) for reading guide points."""
    import matplotlib.image as mpimg

    def draw(ax, name):
        a = mpimg.imread(os.path.join(png_dir, name + ".png"))[..., 3]
        ax.imshow(a, cmap="gray")
        h, w = a.shape
        for v in range(0, max(h, w), 25):
            major = v % 50 == 0
            kw = dict(color="tab:blue" if major else "tab:gray", lw=0.6 if major else 0.3)
            if v < w:
                ax.axvline(v, **kw)
            if v < h:
                ax.axhline(v, **kw)
        ax.axis("on")
        ax.set_xticks(range(0, w, 50))
        ax.set_yticks(range(0, h, 50))
        ax.tick_params(labelsize=7)
        ax.set_title(name, fontsize=9)
    return _sheets(names, out, draw, per_sheet=6, dpi=100)


def review_sheets(results: list, out: str) -> list:
    import matplotlib.image as mpimg

    def draw(ax, item):
        name, src, p, pts = item
        ax.imshow(mpimg.imread(src)[..., 3], cmap="gray", alpha=0.5)
        ax.plot(p[:, 0], p[:, 1], color="tab:orange", lw=1.6)
        ax.plot(*np.array(pts).T, "x", color="yellow", ms=4)
        ax.plot(*p[0], "o", color="lime", ms=8)
        ax.plot(*p[-1], "s", color="red", ms=6)
        for k in np.linspace(0.1, 0.9, 6):
            i = int(k * (len(p) - 1))
            j = min(i + 8, len(p) - 1)
            ax.annotate("", xy=p[j], xytext=p[i],
                        arrowprops=dict(arrowstyle="-|>", color="cyan", lw=1.5))
        ax.set_title(name, fontsize=9)
    return _sheets(results, out, draw)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=("grid", "trace"))
    ap.add_argument("png_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--only", help="comma-separated PNG names (without .png)")
    ap.add_argument("--review", help="trace mode: write overlay review sheet(s) here")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    waypoints = {}
    if os.path.exists(WAYPOINTS_FILE):
        with open(WAYPOINTS_FILE, encoding="utf-8") as f:
            waypoints = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    names = args.only.split(",") if args.only else sorted(waypoints)

    if args.mode == "grid":
        for p in grid_sheets(args.png_dir, names, os.path.join(args.out_dir, "grid.png")):
            print(p)
        return

    results = []
    for name in names:
        src = os.path.join(args.png_dir, name + ".png")
        try:
            xy = trace(src, waypoints[name])
        except (ValueError, KeyError) as e:
            print(f"{name:>22}: FAILED - {e}")
            continue
        with open(os.path.join(args.out_dir, name + ".svg"), "w", encoding="utf-8") as fh:
            fh.write(to_svg(xy, name + ".png"))
        results.append((name, src, xy, waypoints[name]))
        print(f"{name:>22}: {len(xy)} px")
    if args.review and results:
        for p in review_sheets(results, args.review):
            print("review sheet:", p)


if __name__ == "__main__":
    main()
