"""
Spell recognition testing and training.

    python -m opencaster.recognition synth [--per 500]       fit per-spell thresholds on
                                                             synthetic casts and near-misses
    python -m opencaster.recognition synth --load synth.npz  refit from saved scores

synth (see synth.py) scores generated casts and near-misses, fits a threshold
per spell, and reports held-out synthetic and real-cast results for several
false-accept weights before printing PER_SPELL_THRESHOLDS for
opencaster/casting/matcher.py.
"""

import argparse
import sys
import time

import numpy as np

from ..casting.castlog import NOT_A_SPELL, CastLog
from ..casting.matcher import DEFAULT_THRESHOLD
from ..casting.shapes import SpellLibrary, spell_key
from ..paths import CASTS_FILE, SPELLS_DIR
from . import synth as S


def cmd_synth(args):
    use_gpu = False
    if not args.cpu:
        from . import gpu
        use_gpu = gpu.available()
        print(f"scoring on {'GPU ' + gpu.device_name() if use_gpu else 'CPU (no OpenCL GPU found)'}")
    if args.load:
        data = S.Synthetic.load(args.load)
    else:
        print(f"generating {args.per} casts + {args.per} near-misses per spell "
              f"(noise x{args.noise}, seed {args.seed}) ...", flush=True)
        t0 = time.monotonic()
        log = lambda msg: print(f"  {time.monotonic() - t0:6.1f}s  {msg}", flush=True)
        data = S.generate(args.spells, args.per, args.seed, args.noise, args.jobs, use_gpu, log)
        if args.save:
            data.save(args.save)
    keys = list(data.keys)
    spell = data.kind == S.SPELL
    print(f"{int(spell.sum())} synthetic spell casts, {int((~spell).sum())} near-misses "
          f"({data.dropped} dropped: their clean shape is a real spell)")

    # Real casts, scored the same way, for calibration and as the final check.
    casts = [c for c in CastLog(args.file).load()
             if c["label"] == NOT_A_SPELL or spell_key(c["label"]) in keys]
    real = S.score_trails([np.array(c["trail"], float) for c in casts], args.spells, args.jobs, use_gpu)
    label = np.array([-1 if c["label"] == NOT_A_SPELL else keys.index(spell_key(c["label"]))
                      for c in casts])
    own = lambda sc, src, ok: np.median(sc[ok, src[ok]]) if ok.any() else float("nan")
    print(f"median own-template score: synthetic {own(data.scores, data.source, spell):.3f}, "
          f"real {own(real, label, label >= 0):.3f}")

    def real_line(thr):
        dec = S.decide(real, thr)
        sp = label >= 0
        return (f"{int((dec[sp] == label[sp]).sum())}/{int(sp.sum())} spells, "
                f"{int(((dec[sp] >= 0) & (dec[sp] != label[sp])).sum())} wrong, "
                f"{int((dec[~sp] >= 0).sum())}/{int((~sp).sum())} non-spells accepted")

    def synth_line(d, thr):
        s = S.summary(d, thr)
        near = "  ".join(f"{k} {s[k][0]}/{s[k][1]}" for k, _ in S.NEAR_MISS_MIX)
        return (f"{s['correct']}/{s['spells']} spells ({100 * s['correct'] / s['spells']:.0f}%), "
                f"{s['wrong']} wrong | near-misses accepted: {near}")

    # Random halves: casts are generated spell by spell in a fixed rotation,
    # so splitting by position would put whole spells on one side.
    half = np.random.default_rng(0).random(len(data.kind)) < 0.5
    fit, held = data.subset(half), data.subset(~half)
    default = S.threshold_array(data.keys, {})
    print("\nheld-out synthetic half (thresholds fitted on the other half), and real casts")
    print(f"  {'current':>12}  synthetic: {synth_line(held, default)}")
    print(f"  {'':>12}  real:      {real_line(default)}")
    for w in sorted({0.5, 1.0, 2.0, args.fa_weight}):
        thr = S.threshold_array(data.keys, S.fit_thresholds(fit, w))
        print(f"  {f'fa-weight {w:g}':>12}  synthetic: {synth_line(held, thr)}")
        print(f"  {'':>12}  real:      {real_line(thr)}")

    fitted = {k: v for k, v in S.fit_thresholds(data, args.fa_weight).items()
              if v != DEFAULT_THRESHOLD}
    names = {t.key: t.name for t in SpellLibrary(args.spells).templates}
    print(f"\n# fa-weight {args.fa_weight:g}, fitted on all {len(data.kind)} synthetic casts; "
          f"{len(keys) - len(fitted)} spells keep the default {DEFAULT_THRESHOLD}")
    print("# Paste into opencaster/casting/matcher.py -> PER_SPELL_THRESHOLDS")
    print("PER_SPELL_THRESHOLDS: dict = {")
    for k, v in fitted.items():
        print(f'    "{k}": {v},' + (f"   # {names[k]}" if k in names else ""))
    print("}")


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="python -m opencaster.recognition", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spells", default=str(SPELLS_DIR), help="template folder")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("synth", help="fit per-spell thresholds on synthetic casts and near-misses")
    s.add_argument("--per", type=int, default=100, help="casts and near-misses per spell")
    s.add_argument("--noise", type=float, default=S.NOISE, help="perturbation strength")
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--jobs", type=int, help="worker processes (default: CPUs - 1)")
    s.add_argument("--cpu", action="store_true", help="score on the CPU even if a GPU is available")
    s.add_argument("--fa-weight", type=float, default=1.0,
                   help="cost of accepting a near-miss relative to missing a real cast")
    s.add_argument("--save", help="write the scored casts to this .npz")
    s.add_argument("--load", help="refit from a saved .npz instead of generating")
    s.add_argument("--file", default=str(CASTS_FILE), help="real labelled casts to check against")
    args = ap.parse_args(argv)
    globals()[f"cmd_{args.cmd}"](args)


if __name__ == "__main__":
    main()
