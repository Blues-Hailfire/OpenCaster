"""
analyze_thresholds.py — Score distribution analyser for spell recognition tuning
=================================================================================
Reads feedback_log.csv and prints per-spell score statistics.
Run this after collecting a session of casts to tune thresholds.

Usage:
    python analyze_thresholds.py

Output:
    Per-spell table: median, mean, min, max score + recommended threshold
    Suggested PER_SPELL_THRESHOLDS dict to paste into spell_matcher.py
"""

import csv
import os
import sys
from collections import defaultdict

import numpy as np

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feedback_log.csv")


def load_log(path: str) -> list[dict]:
    rows = []
    if not os.path.isfile(path):
        print(f"  Log not found: {path}")
        return rows
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                rows.append({
                    "spell":    row.get("matched_spell", "").strip().lower(),
                    "score":    float(row.get("score", 1.0)),
                    "success":  row.get("matcher_success", "").strip().lower() == "true",
                    "confirmed": row.get("user_confirmed", "").strip().lower(),
                })
            except ValueError:
                continue
    return rows


def main():
    rows = load_log(LOG_FILE)
    if not rows:
        print("No data in feedback_log.csv yet — cast some spells first.")
        sys.exit(0)

    print(f"\nLoaded {len(rows)} feedback entries from {os.path.basename(LOG_FILE)}\n")

    # Group scores by spell name
    by_spell: dict[str, list[float]] = defaultdict(list)
    confirmed_match:  dict[str, list[float]] = defaultdict(list)   # user said ✓
    confirmed_miss:   dict[str, list[float]] = defaultdict(list)   # user said ✗

    for row in rows:
        spell = row["spell"]
        score = row["score"]
        if not spell:
            continue
        by_spell[spell].append(score)
        conf = row["confirmed"]
        if conf in ("yes", "true", "1", "correct"):
            confirmed_match[spell].append(score)
        elif conf in ("no", "false", "0", "wrong"):
            confirmed_miss[spell].append(score)

    # Print table
    header = f"{'Spell':<22} {'N':>4}  {'Min':>6}  {'Median':>7}  {'Mean':>6}  {'Max':>6}  {'Suggested thresh':>16}"
    print(header)
    print("─" * len(header))

    suggestions: dict[str, float] = {}

    for spell in sorted(by_spell):
        scores = np.array(by_spell[spell])
        n = len(scores)
        mn  = scores.min()
        med = np.median(scores)
        avg = scores.mean()
        mx  = scores.max()

        # Suggested threshold: median of confirmed matches + 20% headroom,
        # capped at 0.35 and floored at 0.12.
        if confirmed_match[spell]:
            thresh = float(np.median(confirmed_match[spell])) * 1.20
        else:
            # No confirmed data — use 75th percentile of all scores as a guess
            thresh = float(np.percentile(scores, 75))
        thresh = round(min(max(thresh, 0.12), 0.35), 3)
        suggestions[spell] = thresh

        flag = ""
        if confirmed_miss[spell]:
            # Check if any misses would be incorrectly accepted at this threshold
            false_accepts = [s for s in confirmed_miss[spell] if s <= thresh]
            if false_accepts:
                flag = f"  ⚠  {len(false_accepts)} false-accept(s) at thresh"

        print(f"{spell:<22} {n:>4}  {mn:>6.3f}  {med:>7.3f}  {avg:>6.3f}  {mx:>6.3f}  {thresh:>16.3f}{flag}")

    # Print suggested dict
    print("\n\n# ── Paste this into spell_matcher.py → PER_SPELL_THRESHOLDS ──────────────")
    print("PER_SPELL_THRESHOLDS: dict[str, float] = {")
    for spell, thresh in sorted(suggestions.items()):
        print(f'    "{spell}":{" " * max(1, 22 - len(spell))} {thresh},')
    print("}")

    total  = len(rows)
    hits   = sum(1 for r in rows if r["success"])
    misses = total - hits
    print(f"\nOverall:  {hits}/{total} matched  ({100*hits/total:.1f}%)  |  {misses} misses")


if __name__ == "__main__":
    main()
