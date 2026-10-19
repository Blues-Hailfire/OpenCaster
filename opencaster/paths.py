"""Project-root-anchored data locations (independent of the working directory)."""

from pathlib import Path

ROOT          = Path(__file__).resolve().parent.parent
SPELLS_DIR    = ROOT / "spells"                 # gesture templates (SVG)
ICONS_DIR     = SPELLS_DIR / "icons"            # original gesture PNGs (eigger, MIT)
MEDIA_DIR     = ROOT / "media"                  # spellbook.json + sounds/videos (gitignored)
CASTS_FILE    = ROOT / "casts" / "casts.jsonl"  # labelled casts
PROFILES_FILE = ROOT / "wand_profiles.json"     # per-wand motion calibration
PROGRESS_FILE = ROOT / "progress.json"          # spell mastery counts (gitignored)
SETTINGS_FILE = ROOT / "settings.json"          # default colour, house, patronus, API (gitignored)
