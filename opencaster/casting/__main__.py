"""
Headless spell assessment.

    python -m opencaster.casting list                       spell templates
    python -m opencaster.casting evaluate [--misses]        score the matcher on labelled casts
    python -m opencaster.casting evaluate --threshold 0.3 --margin 1.2
    python -m opencaster.casting replay capture.csv         run a recorded IMU capture through
                                                            the casting session

evaluate re-runs every cast in casts/casts.jsonl and prints accuracy, a
confusion table, per-spell score distributions and suggested
PER_SPELL_THRESHOLDS for matcher.py.

replay takes a CSV from `python -m opencaster.wand record` (t, buttons,
ax..gz); casts open and close exactly as they would live.
"""

import argparse
import csv
import sys
from collections import Counter, defaultdict

import numpy as np

from ..paths import CASTS_FILE, PROFILES_FILE, SPELLS_DIR
from .castlog import NOT_A_SPELL, CastLog
from .matcher import DEFAULT_THRESHOLD, MARGIN_RATIO, SpellMatcher
from .profiles import WandProfiles
from .session import CastSession, assess
from .shapes import SpellLibrary, spell_key

REJECTED = "(rejected)"


def cmd_list(args):
    lib = SpellLibrary(args.spells)
    for t in lib.templates:
        print(f"{t.name:24} {t.file.name}")
    print(f"{len(lib)} templates")


def cmd_evaluate(args):
    casts = CastLog(args.file).load()
    if not casts:
        print(f"No labelled casts in {args.file} - cast with 'Label casts' on in the GUI.")
        return
    lib = SpellLibrary(args.spells)
    matcher = SpellMatcher(threshold=args.threshold, margin_ratio=args.margin)
    names = {t.key: t.name for t in lib.templates}
    disp = lambda key: names.get(key, NOT_A_SPELL if key == NOT_A_SPELL else key)

    confusion = defaultdict(Counter)
    own, impostor = defaultdict(list), defaultdict(list)
    top1 = top1_n = 0
    misses = []

    for c in casts:
        label = NOT_A_SPELL if c["label"] == NOT_A_SPELL else spell_key(c["label"])
        r = assess(np.array(c["trail"], dtype=float), lib, matcher)
        decision = r.best.key if r.accepted else REJECTED
        confusion[label][decision] += 1
        for m in r.ranked:
            (own if m.key == label else impostor)[m.key].append(m.score)
        if label != NOT_A_SPELL and r.ranked:
            top1_n += 1
            top1 += r.best.key == label
        if decision != label and not (label == NOT_A_SPELL and decision == REJECTED):
            top = ", ".join(f"{m.spell} {m.score:.3f}" for m in r.ranked[:3]) or r.gate
            misses.append(f"{c['timestamp']}  {disp(label):>16} -> "
                          f"{disp(decision) if decision != REJECTED else REJECTED:<16} [{top}]")

    labels = Counter(NOT_A_SPELL if c["label"] == NOT_A_SPELL else spell_key(c["label"])
                     for c in casts)
    spell_casts = sum(n for l, n in labels.items() if l != NOT_A_SPELL)
    correct = sum(confusion[l][l] for l in labels if l != NOT_A_SPELL)
    wrong = sum(n for l in labels if l != NOT_A_SPELL
                for d, n in confusion[l].items() if d not in (l, REJECTED))
    none_n = labels.get(NOT_A_SPELL, 0)
    none_fa = none_n - confusion[NOT_A_SPELL][REJECTED]

    print(f"\n{len(casts)} labelled casts   threshold {args.threshold}   margin {args.margin}")
    if spell_casts:
        print(f"  spell casts:   {correct}/{spell_casts} accepted correctly "
              f"({100 * correct / spell_casts:.0f}%), {wrong} accepted as the WRONG spell")
    if top1_n:
        print(f"  top-1 (ignoring thresholds): {top1}/{top1_n} ({100 * top1 / top1_n:.0f}%)")
    if none_n:
        print(f"  not-a-spell:   {none_fa}/{none_n} falsely accepted")

    keys = list(names)
    cols = keys + [REJECTED]
    w = max(8, max((len(names[k]) for k in keys), default=8))
    print("\nlabel -> decision")
    print(" " * (w + 2) + " ".join(f"{disp(k)[:w]:>{w}}" for k in cols))
    for label in sorted(labels, key=lambda l: (l == NOT_A_SPELL, l)):
        row = " ".join(f"{confusion[label][d] or '.':>{w}}" for d in cols)
        print(f"{disp(label)[:w]:>{w}}  {row}")

    print("\nper-spell scores (own = template vs its own casts, impostor = vs everything else)")
    print(f"{'spell':>{w}}  {'n':>3}  {'own p50':>7}  {'own p90':>7}  {'imp p5':>7}  {'suggest':>7}")
    suggested = {}
    for k in keys:
        o, imp = own.get(k, []), impostor.get(k, [])
        if not o:
            print(f"{names[k]:>{w}}  {0:>3}  {'-':>7}  {'-':>7}  {'-':>7}  {'-':>7}")
            continue
        o50, o90 = np.percentile(o, [50, 90])
        i5 = float(np.percentile(imp, 5)) if imp else float("nan")
        # Midway between "most real casts" and "the closest impostors"; if
        # they overlap, favour rejecting impostors.
        sug = o90 if not imp else (o90 + i5) / 2 if o90 < i5 else i5 * 0.9
        suggested[k] = round(float(sug), 3)
        print(f"{names[k]:>{w}}  {len(o):>3}  {o50:7.3f}  {o90:7.3f}  {i5:7.3f}  {sug:7.3f}"
              + ("   !! overlaps impostors" if imp and o90 >= i5 else ""))

    if suggested:
        print("\n# Paste into opencaster/casting/matcher.py -> PER_SPELL_THRESHOLDS")
        print("PER_SPELL_THRESHOLDS: dict = {")
        for k, v in suggested.items():
            print(f'    "{k}": {v},')
        print("}")

    if args.misses and misses:
        print(f"\n{len(misses)} wrong casts:")
        print("\n".join(misses))


def cmd_replay(args):
    lib = SpellLibrary(args.spells)
    now = {"t": 0.0}

    def on_event(name, payload=None):
        if name == "cast":
            top = ", ".join(f"{m.spell} {m.score:.3f}" for m in payload.ranked[:3])
            print(f"{now['t']:8.2f}s  {payload.message():<28} {len(payload.trail):4d} pts  {top}")
        elif name in ("tap", "timeout", "window_open"):
            print(f"{now['t']:8.2f}s  {name}" + (f" ({payload:.2f} s)" if name == "tap" else ""))

    session = CastSession(lib, on_event=on_event, clock=lambda: now["t"])
    session.set_target(args.target)
    if args.wand:
        session.set_motion(WandProfiles(PROFILES_FILE).motion(args.wand))

    with open(args.file, newline="") as f:
        rows = list(csv.DictReader(f))
    batch, mask = [], 0
    for row in rows:
        m = int(row["buttons"])
        if m != mask:                  # pad change: flush samples before it
            session.feed_imu(batch)
            batch, mask = [], m
            session.feed_buttons(m)
        now["t"] = float(row["t"])
        batch.append(tuple(float(row[k]) for k in ("ax", "ay", "az", "gx", "gy", "gz")))
        if len(batch) >= 19:           # one BLE packet's worth
            session.feed_imu(batch)
            batch = []
    session.feed_imu(batch)
    session.feed_buttons(0)


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="python -m opencaster.casting", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spells", default=str(SPELLS_DIR), help="template folder")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list spell templates")
    e = sub.add_parser("evaluate", help="score the matcher against labelled casts")
    e.add_argument("--file", default=str(CASTS_FILE))
    e.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    e.add_argument("--margin", type=float, default=MARGIN_RATIO)
    e.add_argument("--misses", action="store_true", help="list every wrong cast")
    r = sub.add_parser("replay", help="replay a recorded IMU capture")
    r.add_argument("file")
    r.add_argument("--wand", help="use this wand's motion calibration (MAC address)")
    r.add_argument("--target", help="practise one spell")
    args = ap.parse_args(argv)
    globals()[f"cmd_{args.cmd}"](args)


if __name__ == "__main__":
    main()
