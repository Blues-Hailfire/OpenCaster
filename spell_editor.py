"""
spell_editor.py — OpenCaster Spell Shape Editor
================================================
Draw spell shapes with your mouse, preview them normalised,
and save directly to the spells/ folder as SVG files.

Controls:
  Left-click + drag  : Draw
  Right-click        : Clear canvas
  Scroll wheel       : Undo last stroke segment (hold to undo more)
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import math, os, re

SPELLS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spells")

BG       = "#0a0c1a"
BG2      = "#0f1228"
BG3      = "#161a38"
GOLD     = "#c9a84c"
GOLD_DIM = "#7a6328"
BLUE     = "#4a9eff"
GREEN    = "#34d399"
RED      = "#f87171"
TEXT     = "#e8e4d8"
TEXT_DIM = "#6b6880"
BORDER   = "#2a2d4a"
DRAW_CLR = "#7dd3fc"   # light blue drawing line
NORM_CLR = "#a78bfa"   # purple normalised preview
GRID_CLR = "#1a1f3a"   # subtle grid

CANVAS_W = 600
CANVAS_H = 600
PREV_W   = 280
PREV_H   = 280

# ── SVG helpers ────────────────────────────────────────────────────────────────

# ── Smoothing / simplification ─────────────────────────────────────────────────

def _rdp(points: list, epsilon: float) -> list:
    """Ramer-Douglas-Peucker line simplification (recursive)."""
    if len(points) < 3:
        return points
    # Find the point with the maximum distance from the line start→end
    x1, y1 = points[0]
    x2, y2 = points[-1]
    dx, dy = x2 - x1, y2 - y1
    line_len = math.hypot(dx, dy)
    max_dist, max_idx = 0.0, 0
    for i, (px, py) in enumerate(points[1:-1], 1):
        if line_len < 1e-9:
            dist = math.hypot(px - x1, py - y1)
        else:
            dist = abs(dy*px - dx*py + x2*y1 - y2*x1) / line_len
        if dist > max_dist:
            max_dist, max_idx = dist, i
    if max_dist > epsilon:
        left  = _rdp(points[:max_idx+1], epsilon)
        right = _rdp(points[max_idx:],   epsilon)
        return left[:-1] + right
    return [points[0], points[-1]]


def _chaikin(points: list, iterations: int = 2) -> list:
    """Chaikin corner-cutting smooth (preserves start/end exactly)."""
    if len(points) < 3:
        return points
    for _ in range(iterations):
        out = [points[0]]
        for i in range(len(points) - 1):
            x0, y0 = points[i]
            x1, y1 = points[i+1]
            out.append((0.75*x0 + 0.25*x1, 0.75*y0 + 0.25*y1))
            out.append((0.25*x0 + 0.75*x1, 0.25*y0 + 0.75*y1))
        out.append(points[-1])
        points = out
    return points


def smooth_and_simplify(points: list, epsilon: float = 4.0,
                         chaikin_iter: int = 2) -> list:
    """Split on pen-up gaps → RDP simplify each stroke → Chaikin smooth → rejoin."""
    if len(points) < 2:
        return points

    # Split into sub-strokes on large gaps (pen-up)
    strokes, cur = [], [points[0]]
    for p in points[1:]:
        if math.hypot(p[0]-cur[-1][0], p[1]-cur[-1][1]) > 60:
            strokes.append(cur)
            cur = [p]
        else:
            cur.append(p)
    strokes.append(cur)

    result = []
    for i, stroke in enumerate(strokes):
        simplified = _rdp(stroke, epsilon)
        smoothed   = _chaikin(simplified, chaikin_iter)
        if i > 0:
            result.append(None)   # pen-up marker
        result.extend(smoothed)
    return result


def points_to_svg_path(points: list) -> str:
    """Convert a list of (x,y) tuples (with None as pen-up) to SVG path d=.
    Relies solely on None markers for pen-up — no distance heuristics."""
    if not points:
        return ""
    parts = []
    need_move = True
    for p in points:
        if p is None:
            need_move = True
            continue
        if need_move:
            parts.append(f"M {p[0]:.2f} {p[1]:.2f}")
            need_move = False
        else:
            parts.append(f"L {p[0]:.2f} {p[1]:.2f}")
    return " ".join(parts)


def normalise_points(points: list, size: float = 200.0) -> list:
    """Centre and scale points to fit in [margin, size-margin]. Handles None pen-up markers."""
    real = [p for p in points if p is not None]
    if len(real) < 2:
        return points
    xs = [p[0] for p in real]
    ys = [p[1] for p in real]
    cx = (min(xs)+max(xs)) / 2
    cy = (min(ys)+max(ys)) / 2
    span = max(max(xs)-min(xs), max(ys)-min(ys))
    if span < 1:
        return points
    margin = size * 0.12
    scale  = (size - 2*margin) / span
    return [
        None if p is None else ((p[0]-cx)*scale + size/2, (p[1]-cy)*scale + size/2)
        for p in points
    ]


def save_svg(path: str, points: list, epsilon: float = 4.0, chaikin_iter: int = 2):
    """Smooth, simplify, normalise and save points as SVG."""
    processed = smooth_and_simplify(points, epsilon=epsilon, chaikin_iter=chaikin_iter)
    norm = normalise_points(processed, size=200.0)
    real_pts = [p for p in norm if p is not None]
    d = points_to_svg_path(norm)
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">'
        f'<path d="{d}" fill="none" stroke="black" stroke-width="3" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        '</svg>'
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)
    return len(real_pts)


def load_svg_points(path: str) -> list:
    """Parse an existing SVG path back into a point list with None pen-up markers."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        m = re.search(r'd="([^"]+)"', content)
        if not m:
            return []
        d = m.group(1)
        # Tokenise: commands as single letters, numbers separately
        tokens = re.findall(r"[MLCQZmlcqz]|[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?", d)
        pts = []
        cmd = "M"
        cx, cy = 0.0, 0.0
        prev_was_m = False
        i = 0
        while i < len(tokens):
            t = tokens[i]
            if re.match(r"[MLml]", t):
                cmd = t
                i += 1
                continue
            if re.match(r"[ZzCcQq]", t):
                i += 1
                continue
            # Consume a coordinate pair
            if i + 1 >= len(tokens):
                break
            x, y = float(tokens[i]), float(tokens[i+1])
            i += 2
            if cmd == "m":
                x += cx; y += cy
                cmd = "l"   # implicit subsequent coords are lineto
            elif cmd == "l":
                x += cx; y += cy
            # M = absolute moveto — treat as pen-up if we already have points
            if cmd in ("M",) and pts:
                pts.append(None)
            cx, cy = x, y
            pts.append((x, y))
        return pts
    except Exception as e:
        print(f"  [load_svg] Error: {e}")
        return []


# ── Main application ───────────────────────────────────────────────────────────

class SpellEditor:
    PEN_UP_DIST = 60    # pixel gap that counts as lifting the pen

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("✦ OpenCaster — Spell Editor")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)

        # Drawing state
        self._points: list = []          # all drawn points (raw canvas coords)
        self._strokes: list = []         # list of stroke point-lists (for undo)
        self._cur_stroke: list = []      # current in-progress stroke
        self._drawing = False
        self._last_x = self._last_y = 0

        # Spell list
        self._spell_var = tk.StringVar()
        self._spell_names: list = []

        self._build_ui()
        self._refresh_spell_list()
        self._draw_grid()

    # ── UI construction ────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Top bar ────────────────────────────────────────────────────────────
        top = tk.Frame(self.root, bg=BG, pady=8)
        top.pack(fill="x", padx=14)

        tk.Label(top, text="✦  SPELL EDITOR", bg=BG, fg=GOLD,
                 font=("Georgia", 18, "bold")).pack(side="left")
        tk.Label(top, text="draw your spell shape", bg=BG, fg=TEXT_DIM,
                 font=("Georgia", 9, "italic")).pack(side="left", padx=(10,0), pady=(6,0))

        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x", padx=14)

        # ── Body ───────────────────────────────────────────────────────────────
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", padx=14, pady=10)

        # Left: drawing canvas
        self._build_canvas(body)

        # Right: controls
        self._build_controls(body)

    def _build_canvas(self, parent):
        left = tk.Frame(parent, bg=BG)
        left.pack(side="left")

        tk.Label(left, text="DRAW HERE", bg=BG, fg=GOLD_DIM,
                 font=("Georgia", 8, "bold")).pack(anchor="w", pady=(0,4))

        canvas_outer = tk.Frame(left, bg=BORDER, padx=1, pady=1)
        canvas_outer.pack()

        self.canvas = tk.Canvas(canvas_outer, width=CANVAS_W, height=CANVAS_H,
                                bg=BG2, cursor="crosshair",
                                highlightthickness=0, bd=0)
        self.canvas.pack()

        self.canvas.bind("<ButtonPress-1>",   self._on_press)
        self.canvas.bind("<B1-Motion>",        self._on_drag)
        self.canvas.bind("<ButtonRelease-1>",  self._on_release)
        self.canvas.bind("<ButtonPress-3>",    self._on_right_click)
        self.canvas.bind("<MouseWheel>",       self._on_scroll)

        # Hint bar below canvas
        hint = tk.Frame(left, bg=BG)
        hint.pack(fill="x", pady=(4,0))
        tk.Label(hint, text="Left-drag: draw   |   Right-click: clear   |   Scroll: undo stroke",
                 bg=BG, fg=TEXT_DIM, font=("Courier New", 8)).pack(side="left")


    def _build_controls(self, parent):
        right = tk.Frame(parent, bg=BG, padx=14)
        right.pack(side="left", fill="y")

        # ── Normalised preview ─────────────────────────────────────────────────
        tk.Label(right, text="NORMALISED PREVIEW", bg=BG, fg=GOLD_DIM,
                 font=("Georgia", 8, "bold")).pack(anchor="w", pady=(0,4))

        prev_outer = tk.Frame(right, bg=BORDER, padx=1, pady=1)
        prev_outer.pack()
        self.preview = tk.Canvas(prev_outer, width=PREV_W, height=PREV_H,
                                 bg=BG3, highlightthickness=0, bd=0)
        self.preview.pack()

        tk.Frame(right, bg=BORDER, height=1).pack(fill="x", pady=10)

        # ── Spell selector ─────────────────────────────────────────────────────
        tk.Label(right, text="SPELL", bg=BG, fg=GOLD_DIM,
                 font=("Georgia", 8, "bold")).pack(anchor="w")

        spell_row = tk.Frame(right, bg=BG)
        spell_row.pack(fill="x", pady=(4, 0))

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Ed.TCombobox",
                         fieldbackground=BG3, background=BG3,
                         foreground=TEXT, selectbackground=BG3,
                         selectforeground=TEXT, arrowcolor=GOLD_DIM,
                         bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
        style.map("Ed.TCombobox", fieldbackground=[("readonly", BG3)],
                  selectbackground=[("readonly", BG3)])

        self._spell_combo = ttk.Combobox(spell_row, textvariable=self._spell_var,
                                          style="Ed.TCombobox", state="readonly",
                                          font=("Courier New", 9), width=20)
        self._spell_combo.pack(side="left", fill="x", expand=True)
        self._spell_combo.bind("<<ComboboxSelected>>", self._on_spell_selected)

        tk.Button(spell_row, text="↺", bg=BG3, fg=TEXT_DIM, bd=0,
                  padx=6, font=("Courier New", 10),
                  activebackground=BORDER,
                  command=self._refresh_spell_list).pack(side="left", padx=(4,0))

        tk.Frame(right, bg=BORDER, height=1).pack(fill="x", pady=10)

        # ── Smoothing controls ─────────────────────────────────────────────────
        tk.Label(right, text="SMOOTHING", bg=BG, fg=GOLD_DIM,
                 font=("Georgia", 8, "bold")).pack(anchor="w")

        # RDP epsilon slider
        rdp_row = tk.Frame(right, bg=BG)
        rdp_row.pack(fill="x", pady=(4,0))
        tk.Label(rdp_row, text="Simplify", bg=BG, fg=TEXT_DIM,
                 font=("Courier New", 8), width=8, anchor="w").pack(side="left")
        self._epsilon_var = tk.DoubleVar(value=4.0)
        self._epsilon_label = tk.Label(rdp_row, text="4.0", bg=BG, fg=BLUE,
                                        font=("Courier New", 8), width=4)
        self._epsilon_label.pack(side="right")
        tk.Scale(rdp_row, variable=self._epsilon_var, from_=0.5, to=20.0,
                 resolution=0.5, orient="horizontal", bg=BG, fg=TEXT_DIM,
                 troughcolor=BG3, highlightthickness=0, bd=0, sliderlength=12,
                 command=self._on_smooth_change, showvalue=False,
                 length=130).pack(side="left", fill="x", expand=True)

        # Chaikin iterations slider
        ch_row = tk.Frame(right, bg=BG)
        ch_row.pack(fill="x", pady=(2,0))
        tk.Label(ch_row, text="Rounds", bg=BG, fg=TEXT_DIM,
                 font=("Courier New", 8), width=8, anchor="w").pack(side="left")
        self._chaikin_var = tk.IntVar(value=2)
        self._chaikin_label = tk.Label(ch_row, text="2", bg=BG, fg=BLUE,
                                        font=("Courier New", 8), width=4)
        self._chaikin_label.pack(side="right")
        tk.Scale(ch_row, variable=self._chaikin_var, from_=0, to=5,
                 resolution=1, orient="horizontal", bg=BG, fg=TEXT_DIM,
                 troughcolor=BG3, highlightthickness=0, bd=0, sliderlength=12,
                 command=self._on_smooth_change, showvalue=False,
                 length=130).pack(side="left", fill="x", expand=True)

        # Point count readout
        self._pt_count_var = tk.StringVar(value="raw: 0 pts  →  smooth: 0 pts")
        tk.Label(right, textvariable=self._pt_count_var, bg=BG, fg=TEXT_DIM,
                 font=("Courier New", 7)).pack(anchor="w", pady=(2,0))

        tk.Frame(right, bg=BORDER, height=1).pack(fill="x", pady=10)
        def btn(text, fg, cmd, pady=3):
            tk.Button(right, text=text, bg=BG3, fg=fg, bd=0,
                      padx=10, pady=pady, font=("Courier New", 9, "bold"),
                      activebackground=BORDER, command=cmd,
                      width=22).pack(fill="x", pady=2)

        btn("💾  Save to spell", GREEN, self._save_spell)
        btn("📂  Load spell",    BLUE,  self._load_spell)
        btn("✨  New spell…",    GOLD,  self._new_spell)
        btn("🗑   Clear canvas",  RED,   self._clear)

        tk.Frame(right, bg=BORDER, height=1).pack(fill="x", pady=10)

        # ── Stats readout ──────────────────────────────────────────────────────
        tk.Label(right, text="STROKE INFO", bg=BG, fg=GOLD_DIM,
                 font=("Georgia", 8, "bold")).pack(anchor="w")
        self._stats_var = tk.StringVar(value="No stroke yet")
        tk.Label(right, textvariable=self._stats_var, bg=BG, fg=TEXT_DIM,
                 font=("Courier New", 8), justify="left").pack(anchor="w", pady=(4,0))

        # ── SVG path readout ───────────────────────────────────────────────────
        tk.Frame(right, bg=BORDER, height=1).pack(fill="x", pady=10)
        tk.Label(right, text="SVG PATH (normalised)", bg=BG, fg=GOLD_DIM,
                 font=("Georgia", 8, "bold")).pack(anchor="w")
        self._svg_text = tk.Text(right, bg=BG3, fg=BLUE, bd=0, relief="flat",
                                  font=("Courier New", 7), wrap="word",
                                  height=6, width=28, state="disabled")
        self._svg_text.pack(fill="x", pady=(4,0))


    # ── Grid ───────────────────────────────────────────────────────────────────

    def _draw_grid(self):
        step = 60
        for x in range(0, CANVAS_W+1, step):
            self.canvas.create_line(x, 0, x, CANVAS_H, fill=GRID_CLR, tags="grid")
        for y in range(0, CANVAS_H+1, step):
            self.canvas.create_line(0, y, CANVAS_W, y, fill=GRID_CLR, tags="grid")
        # Centre crosshair
        cx, cy = CANVAS_W//2, CANVAS_H//2
        self.canvas.create_line(cx-12, cy, cx+12, cy, fill=GOLD_DIM, width=1, tags="grid")
        self.canvas.create_line(cx, cy-12, cx, cy+12, fill=GOLD_DIM, width=1, tags="grid")

    # ── Drawing events ─────────────────────────────────────────────────────────

    def _on_press(self, event):
        self._drawing = True
        self._cur_stroke = [(event.x, event.y)]
        self._last_x, self._last_y = event.x, event.y

    def _on_drag(self, event):
        if not self._drawing:
            return
        x, y = event.x, event.y
        dist = math.hypot(x - self._last_x, y - self._last_y)
        if dist < 3:   # skip micro-jitter
            return
        self.canvas.create_line(self._last_x, self._last_y, x, y,
                                 fill=DRAW_CLR, width=3,
                                 capstyle=tk.ROUND, joinstyle=tk.ROUND,
                                 tags="drawing")
        self._cur_stroke.append((x, y))
        self._last_x, self._last_y = x, y

    def _on_release(self, event):
        self._drawing = False
        if len(self._cur_stroke) >= 2:
            self._strokes.append(self._cur_stroke)
            self._points.extend(self._cur_stroke)
        self._cur_stroke = []
        self._update_preview()

    def _on_right_click(self, event):
        self._clear()

    def _on_scroll(self, event):
        """Scroll up = undo last stroke."""
        if event.delta > 0 and self._strokes:
            removed = self._strokes.pop()
            # Rebuild _points from remaining strokes
            self._points = [p for stroke in self._strokes for p in stroke]
            # Redraw canvas from scratch
            self.canvas.delete("drawing")
            for stroke in self._strokes:
                for i in range(1, len(stroke)):
                    x0,y0 = stroke[i-1]; x1,y1 = stroke[i]
                    self.canvas.create_line(x0,y0,x1,y1, fill=DRAW_CLR,
                                             width=3, capstyle=tk.ROUND,
                                             joinstyle=tk.ROUND, tags="drawing")
            self._update_preview()

    def _on_smooth_change(self, _=None):
        """Called when either smoothing slider moves — refresh preview."""
        eps = self._epsilon_var.get()
        self._epsilon_label.configure(text=f"{eps:.1f}")
        ch  = self._chaikin_var.get()
        self._chaikin_label.configure(text=str(ch))
        self._update_preview()

    # ── Preview + stats ────────────────────────────────────────────────────────

    def _update_preview(self):
        self.preview.delete("all")

        if len(self._points) < 2:
            self._stats_var.set("No stroke yet")
            self._pt_count_var.set("raw: 0 pts  →  smooth: 0 pts")
            self._set_svg_text("")
            return

        eps = self._epsilon_var.get()
        ch  = self._chaikin_var.get()

        # Compute smoothed points
        smoothed = smooth_and_simplify(self._points, epsilon=eps, chaikin_iter=ch)
        smoothed_real = [p for p in smoothed if p is not None]

        # Update point count label
        self._pt_count_var.set(
            f"raw: {len(self._points)} pts  →  smooth: {len(smoothed_real)} pts")

        # Draw smoothed + normalised preview
        norm = normalise_points(smoothed, size=float(PREV_W))
        norm_real = [p for p in norm if p is not None]

        # Draw as connected segments, skipping None pen-ups
        prev_pt = None
        real_idx = 0
        n = len(norm_real)
        for p in norm:
            if p is None:
                prev_pt = None
                continue
            if prev_pt is not None:
                t = real_idx / max(n - 1, 1)
                r = int(74  + t * (167 - 74))
                g = int(158 + t * (139 - 158))
                b = int(255 + t * (250 - 255))
                colour = f"#{r:02x}{g:02x}{b:02x}"
                self.preview.create_line(prev_pt[0], prev_pt[1], p[0], p[1],
                                          fill=colour, width=2.5,
                                          capstyle=tk.ROUND, joinstyle=tk.ROUND)
            prev_pt = p
            real_idx += 1

        # Start/end dots
        if norm_real:
            s = norm_real[0]
            e = norm_real[-1]
            self.preview.create_oval(s[0]-4,s[1]-4,s[0]+4,s[1]+4, fill=GREEN, outline="")
            self.preview.create_oval(e[0]-4,e[1]-4,e[0]+4,e[1]+4, fill=GOLD,  outline="")

        # Stats
        total_len = sum(math.hypot(self._points[i][0]-self._points[i-1][0],
                                    self._points[i][1]-self._points[i-1][1])
                        for i in range(1, len(self._points)))
        xs = [p[0] for p in self._points]
        ys = [p[1] for p in self._points]
        self._stats_var.set(
            f"Points:  {len(self._points)}\n"
            f"Strokes: {len(self._strokes)}\n"
            f"Length:  {total_len:.0f}px\n"
            f"Bounds:  {max(xs)-min(xs):.0f}×{max(ys)-min(ys):.0f}")

        # SVG path readout (smoothed)
        norm200 = normalise_points(smoothed, size=200.0)
        self._set_svg_text(points_to_svg_path(norm200))

    def _set_svg_text(self, txt: str):
        self._svg_text.configure(state="normal")
        self._svg_text.delete("1.0", "end")
        self._svg_text.insert("end", txt)
        self._svg_text.configure(state="disabled")


    # ── Spell management ───────────────────────────────────────────────────────

    def _refresh_spell_list(self):
        if not os.path.isdir(SPELLS_DIR):
            os.makedirs(SPELLS_DIR, exist_ok=True)
        names = sorted(
            os.path.splitext(f)[0]
            for f in os.listdir(SPELLS_DIR)
            if f.lower().endswith(".svg"))
        self._spell_names = names
        self._spell_combo["values"] = names
        if names and not self._spell_var.get():
            self._spell_var.set(names[0])

    def _on_spell_selected(self, _event=None):
        pass   # just selecting — user must click Load explicitly

    def _clear(self):
        self.canvas.delete("drawing")
        self._points.clear()
        self._strokes.clear()
        self._cur_stroke.clear()
        self._update_preview()

    def _save_spell(self):
        name = self._spell_var.get().strip()
        if not name:
            messagebox.showerror("No Spell", "Select or create a spell first.")
            return
        if len(self._points) < 4:
            messagebox.showerror("Too Short", "Draw more of the shape first.")
            return
        path = os.path.join(SPELLS_DIR, f"{name}.svg")
        eps = self._epsilon_var.get()
        ch  = self._chaikin_var.get()
        saved_pts = save_svg(path, self._points, epsilon=eps, chaikin_iter=ch)
        self._refresh_spell_list()
        self._spell_var.set(name)
        messagebox.showinfo("Saved",
            f"Saved {name}.svg\n"
            f"Raw: {len(self._points)} pts  →  Saved: {saved_pts} pts\n"
            f"(Simplify ε={eps:.1f}, Chaikin rounds={ch})")

    def _load_spell(self):
        name = self._spell_var.get().strip()
        if not name:
            messagebox.showerror("No Spell", "Select a spell from the dropdown.")
            return
        path = os.path.join(SPELLS_DIR, f"{name}.svg")
        if not os.path.isfile(path):
            messagebox.showerror("Not Found", f"No SVG found for {name}.")
            return
        pts = load_svg_points(path)
        if not pts:
            messagebox.showerror("Parse Error", "Could not read points from SVG.")
            return

        # Scale loaded normalised points (0-200 space) up to canvas centre
        pad = CANVAS_W * 0.1
        scale = (CANVAS_W - 2*pad) / 200.0
        def tx(p):
            if p is None:
                return None
            return (p[0] * scale + pad, p[1] * scale + pad)
        scaled = [tx(p) for p in pts]

        self._clear()
        # Rebuild strokes list (split on None) and flat points list
        cur_stroke = []
        for p in scaled:
            if p is None:
                if cur_stroke:
                    self._strokes.append(cur_stroke)
                    self._points.extend(cur_stroke)
                    cur_stroke = []
            else:
                cur_stroke.append(p)
        if cur_stroke:
            self._strokes.append(cur_stroke)
            self._points.extend(cur_stroke)

        # Redraw all strokes on canvas
        for stroke in self._strokes:
            for i in range(1, len(stroke)):
                x0, y0 = stroke[i-1]
                x1, y1 = stroke[i]
                self.canvas.create_line(x0, y0, x1, y1, fill=DRAW_CLR,
                                         width=3, capstyle=tk.ROUND,
                                         joinstyle=tk.ROUND, tags="drawing")
        self._update_preview()

    def _new_spell(self):
        name = simpledialog.askstring(
            "New Spell", "Enter spell name (e.g. Bombarda):",
            parent=self.root)
        if not name:
            return
        name = name.strip()
        self._spell_var.set(name)
        if name not in self._spell_names:
            self._spell_names.append(name)
            self._spell_combo["values"] = sorted(self._spell_names)
        self._clear()


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()
    root.tk_setPalette(background=BG, foreground=TEXT)
    try:
        root.iconbitmap(default="")
    except Exception:
        pass
    SpellEditor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
