"""
opencaster.recognition — Spell recognition testing and training
================================================================
Offline tools for improving spell recognition: synthetic casts and
near-misses generated from the templates, scored in bulk (on the GPU when
one is available), and per-spell thresholds fitted from the results.

The live recogniser stays in opencaster.casting (and is what the app and the
ESP32 port run); this package only measures and tunes it, and writes nothing
the app reads at runtime — its output is pasted into casting/matcher.py.

    python -m opencaster.recognition synth --per 500 --save synth.npz
    python -m opencaster.recognition synth --load synth.npz --fa-weight 2

Depends on numpy and scipy; pyopencl is optional (GPU scoring).
"""

from .synth import Generator, Synthetic, decide, fit_thresholds, generate, score_trails, summary

__all__ = ["Generator", "Synthetic", "generate", "score_trails", "decide",
           "fit_thresholds", "summary"]
