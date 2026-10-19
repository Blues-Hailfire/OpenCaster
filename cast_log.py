"""
cast_log.py — Labelled cast storage
====================================
Every cast labelled in wand_gui.py is appended as one JSON line to
casts/casts.jsonl.  The trail is stored raw (degrees of tip travel, straight
from motion.GestureTracker) so eval_matcher.py can re-run any matcher
version against the same data.

Record fields:
    timestamp   ISO time of the cast
    wand        wand MAC address (or null)
    label       spell name the user says they cast, or "none" (not a spell)
    trail       [[x, y], ...] in degrees
    gate        "ok", "too_short", "too_small" or "no_spells"
    predicted   best-matching spell at cast time (or null)
    accepted    whether the matcher accepted that prediction
    scores      [[spell, score], ...] best-first, at cast time
    target      spell chosen in the GUI's SPELLS dropdown, or null for Any
"""

import json
import os

HERE      = os.path.dirname(os.path.abspath(__file__))
CAST_DIR  = os.path.join(HERE, "casts")
CAST_FILE = os.path.join(CAST_DIR, "casts.jsonl")

NOT_A_SPELL = "none"


def append_cast(record: dict, path: str = CAST_FILE) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def load_casts(path: str = CAST_FILE) -> list:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def count_casts(path: str = CAST_FILE) -> int:
    if not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())
