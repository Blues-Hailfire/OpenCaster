"""Project-root-anchored data locations (independent of the working directory).

From source, everything lives in the repository.  In a PyInstaller build
(OpenCaster.exe) the spell templates ship inside the bundle (read-only),
and the user's own files – media/, casts, profiles, progress, settings –
sit next to the exe where they're easy to find, or under
%LOCALAPPDATA%\\OpenCaster if that folder isn't writable.
"""

import os
import sys
import tempfile
from pathlib import Path


def _writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=folder):
            pass
        return True
    except OSError:
        return False


FROZEN = bool(getattr(sys, "frozen", False))
if FROZEN:
    BUNDLE = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    ROOT = Path(sys.executable).resolve().parent
    if not _writable(ROOT):
        ROOT = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "OpenCaster"
else:
    BUNDLE = ROOT = Path(__file__).resolve().parent.parent

SPELLS_DIR    = BUNDLE / "spells"               # gesture templates (SVG)
ICONS_DIR     = SPELLS_DIR / "icons"            # original gesture PNGs (eigger, MIT)
MEDIA_DIR     = ROOT / "media"                  # spellbook.json + sounds/videos (gitignored)
if FROZEN and not MEDIA_DIR.is_dir():           # media/ next to the exe even when data moved
    MEDIA_DIR = Path(sys.executable).resolve().parent / "media"
CASTS_FILE    = ROOT / "casts" / "casts.jsonl"  # labelled casts
PROFILES_FILE = ROOT / "wand_profiles.json"     # per-wand motion calibration
PROGRESS_FILE = ROOT / "progress.json"          # spell mastery counts (gitignored)
SETTINGS_FILE = ROOT / "settings.json"          # default colour, house, patronus, API (gitignored)
