"""
eval_matcher.py — Score the spell matcher against labelled casts
=================================================================
Re-runs every cast in casts/casts.jsonl (labelled in wand_gui.py) through
the current SpellMatcher and spell library, and prints:

  - how often each spell is accepted correctly, rejected, or accepted as the
    wrong spell, and how often "not a spell" casts are falsely accepted
  - a confusion table (label → what the matcher did)
  - per-spell score distributions and suggested PER_SPELL_THRESHOLDS

Usage:
    python eval_matcher.py
    python eval_matcher.py --threshold 0.3 --margin 1.2
    python eval_matcher.py --misses          # list every wrong cast
"""

import argparse
import os
from collections import Counter, defaultdict

import numpy as np

from cast_log import CAST_FILE, NOT_A_SPELL, load_casts
from spell_matcher import SpellMatcher, MIN_TRAIL_PTS, DEFAULT_THRESHOLD, MARGIN_RATIO
from spell_shapes import SpellLibrary

HERE = os.path.dirname(os.path.abspath(__file__))

# Same pre-matcher gate as WandGUI.MIN_GESTURE_DEG
MIN_GESTURE_DEG = 15.0

REJECTED = "(rejected)"


def outcome(trail: np.ndarray, matcher: SpellMatcher, library) -> tuple:
    """Return (decision, results): decision is a spell name or REJECTED."""
    if len(trail) < MIN_TRAIL_PTS or float(np.ptp(trail, axis=0).max()) < MIN_GESTURE_DEG:
        return REJECTED, []
    results = matcher.match_all(trail, library)
    if results and results[0]["success"]:
        return results[0]["spell"], results
    return REJECTED, results


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default=CAST_FILE)
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--margin", type=float, default=MARGIN_RATIO)
    ap.add_argument("--misses", action="store_true", help="list every wrong cast")
    args = ap.parse_args()

    casts = load_casts(args.file)
    if not casts:
        print(f"No labelled casts in {args.file} - cast with 'Label casts' on in wand_gui.py.")
        return

    library = SpellLibrary(folder=os.path.join(HERE, "spells"))
    matcher = SpellMatcher(threshold=args.threshold, margin_ratio=args.margin)
    spells  = sorted(library.names())

    confusion = defaultdict(Counter)
    own_scores = defaultdict(list)       # spell -> score of its own template on its casts
    impostor   = defaultdict(list)       # spell -> its template's score on other casts
    top1 = top1_n = 0
    misses = []

    for c in casts:
        label = c["label"]
        trail = np.array(c["trail"], dtype=float)
        decision, results = outcome(trail, matcher, library)
        confusion[label][decision] += 1

        for r in results:
            (own_scores if r["spell"] == label else impostor)[r["spell"]].append(r["score"])
        if label != NOT_A_SPELL and results:
            top1_n += 1
            top1 += results[0]["spell"] == label
        if decision != label and not (label == NOT_A_SPELL and decision == REJECTED):
            top = ", ".join(f"{r['spell']} {r['score']:.3f}" for r in results[:3]) or c.get("gate")
            misses.append(f"{c['timestamp']}  {label:>12} -> {decision:<12} [{top}]")

    # -- Summary --------------------------------------------------------------
    labels = Counter(c["label"] for c in casts)
    spell_casts = sum(n for l, n in labels.items() if l != NOT_A_SPELL)
    correct = sum(confusion[l][l] for l in labels if l != NOT_A_SPELL)
    wrong   = sum(n for l in labels if l != NOT_A_SPELL
                  for d, n in confusion[l].items() if d not in (l, REJECTED))
    none_n  = labels.get(NOT_A_SPELL, 0)
    none_fa = none_n - confusion[NOT_A_SPELL][REJECTED]

    print(f"\n{len(casts)} labelled casts   threshold {args.threshold}   margin {args.margin}")
    if spell_casts:
        print(f"  spell casts:   {correct}/{spell_casts} accepted correctly "
              f"({100 * correct / spell_casts:.0f}%), {wrong} accepted as the WRONG spell")
    if top1_n:
        print(f"  top-1 (ignoring thresholds): {top1}/{top1_n} ({100 * top1 / top1_n:.0f}%)")
    if none_n:
        print(f"  not-a-spell:   {none_fa}/{none_n} falsely accepted")

    # -- Confusion table ------------------------------------------------------
    cols = spells + [REJECTED]
    w = max(8, max(len(s) for s in cols[:-1]) if spells else 8)
    print("\nlabel -> decision")
    print(" " * (w + 2) + " ".join(f"{s[:w]:>{w}}" for s in cols))
    for label in sorted(labels, key=lambda l: (l == NOT_A_SPELL, l)):
        row = " ".join(f"{confusion[label][d] or '.':>{w}}" for d in cols)
        print(f"{label[:w]:>{w}}  {row}")

    # -- Per-spell scores + suggested thresholds ------------------------------
    print("\nper-spell scores (own = template vs its own casts, impostor = vs everything else)")
    print(f"{'spell':>{w}}  {'n':>3}  {'own p50':>7}  {'own p90':>7}  {'imp p5':>7}  {'suggest':>7}")
    suggested = {}
    for s in spells:
        own, imp = own_scores.get(s, []), impostor.get(s, [])
        if not own:
            print(f"{s:>{w}}  {0:>3}  {'-':>7}  {'-':>7}  {'-':>7}  {'-':>7}")
            continue
        o50, o90 = np.percentile(own, [50, 90])
        i5 = float(np.percentile(imp, 5)) if imp else float("nan")
        # Midway between "most real casts" and "the closest impostors";
        # if they overlap, favour rejecting impostors.
        sug = o90 if not imp else (o90 + i5) / 2 if o90 < i5 else i5 * 0.9
        suggested[s] = round(float(sug), 3)
        print(f"{s:>{w}}  {len(own):>3}  {o50:7.3f}  {o90:7.3f}  {i5:7.3f}  {sug:7.3f}"
              + ("   !! overlaps impostors" if imp and o90 >= i5 else ""))

    if suggested:
        print("\n# Paste into spell_matcher.py -> PER_SPELL_THRESHOLDS")
        print("PER_SPELL_THRESHOLDS: dict[str, float] = {")
        for s, v in suggested.items():
            print(f'    "{s}": {v},')
        print("}")

    if args.misses and misses:
        print(f"\n{len(misses)} wrong casts:")
        print("\n".join(misses))


if __name__ == "__main__":
    main()
