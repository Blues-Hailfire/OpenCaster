"""Colours, fonts and the Qt stylesheet (night-sky look of the original app)."""

from pathlib import Path

from PySide6.QtGui import QColor, QFont

ASSETS = Path(__file__).resolve().parent / "assets"

BG_TOP     = "#1d1038"     # deep violet
BG_BOTTOM  = "#080a1c"     # night navy
SURFACE    = "rgba(255, 255, 255, 0.045)"
SURFACE_HI = "rgba(255, 255, 255, 0.085)"
BORDER     = "rgba(255, 255, 255, 0.09)"
TEXT       = "#f1ebf8"
TEXT_DIM   = "#a59dc2"
TEXT_FAINT = "#6e6790"
GOLD       = "#e6c46f"
GOLD_DEEP  = "#a8822f"
VIOLET     = "#b49cff"
BLUE       = "#7cc4ff"
TEAL       = "#5eead4"
RED        = "#fb7185"
AMBER      = "#fbbf24"

PAD_COLORS = (TEAL, BLUE, GOLD, VIOLET)

# Template overlay colours by kind
OVERLAY = {"match": VIOLET, "guess": RED, "miss": RED, "preview": BLUE, "guide": BLUE}

SERIF = ["Palatino Linotype", "Book Antiqua", "Georgia", "serif"]
SANS  = ["Segoe UI", "Helvetica Neue", "Arial", "sans-serif"]


def font(size: float, serif: bool = False, bold: bool = False, italic: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(SERIF if serif else SANS)
    f.setPointSizeF(size)
    f.setBold(bold)
    f.setItalic(italic)
    return f


def qcolor(c: str, alpha: float = 1.0) -> QColor:
    q = QColor(c)
    q.setAlphaF(alpha)
    return q


def _tone(c: QColor, v: float, s_min: float = 0.0) -> QColor:
    return QColor.fromHsvF(max(c.hsvHueF(), 0.0), max(c.hsvSaturationF(), s_min), v)


def card_colors(colors) -> tuple:
    """(top, middle, bottom, glow) for a spell card.

    `colors` is the spell's cast colours (brightest/most prominent first) or
    a single dark background colour.  Cast colours are capped in brightness
    so the white icon and name stay readable; a dark background colour is
    lifted instead, keeping its hue."""
    cols = [QColor(c) for c in ((colors,) if isinstance(colors, str) else colors)] \
        or [QColor("#2a1f4a")]
    first, second = cols[0], cols[1] if len(cols) > 1 else cols[0]
    if len(cols) == 1 and first.valueF() < 0.3:          # a dark background colour
        s, v = first.hsvSaturationF(), first.valueF()
        top = QColor.fromHsvF(max(first.hsvHueF(), 0.0), min(1.0, s * 0.9 + 0.12), min(1.0, 0.36 + v))
        return top, _tone(first, max(0.08, v * 0.9)), _tone(first, max(0.05, v * 0.55)), \
            QColor.fromHsvF(max(first.hsvHueF(), 0.0), min(1.0, s * 0.6 + 0.1), 0.95)
    pale = first.hsvSaturationF() < 0.3                  # e.g. CDFFFF, near-white light
    top = _tone(first, 0.50 if pale else 0.62, 0.0 if pale else 0.55)
    middle = _tone(second, 0.30, 0.0 if second.hsvSaturationF() < 0.3 else 0.6)
    bottom = _tone(first, 0.06, 0.4)
    glow = _tone(first, 1.0, 0.0 if pale else 0.45)
    return top, middle, bottom, glow


STYLESHEET = f"""
* {{ color: {TEXT}; }}
QMainWindow, QDialog {{ background: {BG_BOTTOM}; }}
QToolTip {{ background: #241a3d; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 6px; }}

QFrame#Card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 16px; }}
QFrame#Stage {{ background: rgba(6, 6, 22, 0.55); border: 1px solid {BORDER}; border-radius: 20px; }}
QLabel#Section {{ color: {TEXT_FAINT}; font-size: 8pt; font-weight: 600; letter-spacing: 2px; }}
QLabel#Dim {{ color: {TEXT_DIM}; }}

QPushButton {{
    background: {SURFACE_HI}; border: 1px solid {BORDER}; border-radius: 10px;
    padding: 6px 14px; color: {TEXT};
}}
QPushButton:hover {{ background: rgba(255, 255, 255, 0.14); border-color: rgba(230, 196, 111, 0.55); }}
QPushButton:pressed {{ background: rgba(255, 255, 255, 0.06); }}
QPushButton:disabled {{ color: {TEXT_FAINT}; background: {SURFACE}; }}
QPushButton:checked {{ background: rgba(230, 196, 111, 0.16); border-color: rgba(230, 196, 111, 0.6); color: {GOLD}; }}
QPushButton#Primary {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f0d283, stop:1 {GOLD_DEEP});
    color: #1a1029; border: none; font-weight: 600;
}}
QPushButton#Primary:hover {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f8e2a6, stop:1 #c49a3c); }}
QPushButton#Nav {{
    background: transparent; border: none; border-radius: 0; padding: 6px 4px; margin: 0 6px;
    color: {TEXT_DIM}; font-family: "Palatino Linotype"; font-size: 13pt;
    border-bottom: 2px solid transparent;
}}
QPushButton#Nav:hover {{ color: {TEXT}; }}
QPushButton#Nav:checked {{ color: {GOLD}; border-bottom: 2px solid {GOLD}; background: transparent; }}
QPushButton#Chip {{ border-radius: 12px; padding: 4px 12px; }}
QPushButton#ChipGuess {{
    border-radius: 12px; padding: 4px 12px; color: #1a1029; border: none;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f0d283, stop:1 {GOLD_DEEP});
}}
QPushButton#Ghost {{ background: transparent; border: none; color: {TEXT_DIM}; padding: 4px 8px; }}
QPushButton#Ghost:hover {{ color: {GOLD}; }}
QPushButton#Danger {{ color: {RED}; }}

QComboBox, QLineEdit {{
    background: rgba(255, 255, 255, 0.06); border: 1px solid {BORDER}; border-radius: 10px;
    padding: 5px 10px; min-height: 20px; selection-background-color: rgba(230, 196, 111, 0.35);
}}
QComboBox:hover, QLineEdit:focus {{ border-color: rgba(230, 196, 111, 0.55); }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url("{(ASSETS / 'chevron.svg').as_posix()}"); width: 12px; height: 8px;
    margin-right: 8px; }}
QComboBox QAbstractItemView {{
    background: #1b1431; border: 1px solid {BORDER}; selection-background-color: rgba(230, 196, 111, 0.25);
    outline: none; padding: 4px;
}}

QCheckBox {{ spacing: 7px; color: {TEXT_DIM}; }}
QCheckBox:hover {{ color: {TEXT}; }}
QCheckBox::indicator {{ width: 30px; height: 16px; border-radius: 8px; background: rgba(255,255,255,0.12);
    border: 1px solid {BORDER}; }}
QCheckBox::indicator:checked {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {GOLD_DEEP}, stop:1 {GOLD}); }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: rgba(255,255,255,0.14); border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: rgba(230,196,111,0.45); }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}
QScrollBar:horizontal {{ height: 0; }}

QListWidget, QPlainTextEdit {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ padding: 5px 4px; border-bottom: 1px solid rgba(255,255,255,0.05); }}
QListWidget::item:selected {{ background: transparent; color: {TEXT}; }}
QPlainTextEdit {{ font-family: Consolas, "Courier New"; font-size: 8.5pt; color: {TEXT_DIM}; }}

QProgressBar {{ background: rgba(255,255,255,0.08); border: none; border-radius: 4px; height: 8px; text-align: center; }}
QProgressBar::chunk {{ border-radius: 4px; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {GOLD_DEEP}, stop:1 {GOLD}); }}
"""
