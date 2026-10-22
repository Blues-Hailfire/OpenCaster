"""
opencaster.recognition.gpu — Bulk DTW scoring on the GPU (OpenCL)
=================================================================
The same scores as SpellMatcher.scores(), for many trails at once.  Trail
preparation (trim, resample, smooth, tilt, features) stays on the CPU and
reuses the matcher's own functions; only the banded DTW, every tilt against
every template, runs on the GPU, one work-item per pair, two DTW rows in
private memory.  The GPU works in float32, the CPU matcher in float64, so
scores agree to about 1e-6 (check with parity()).

Needs pyopencl and an OpenCL GPU driver (AMD, NVIDIA and Intel all ship one).
"""

from typing import Optional

import numpy as np

from ..casting.matcher import BAND_FRAC, TILT_DEG, TRIM_FRAC, SpellMatcher, _features, _normalise, \
    _rotate, prepare
from ..casting.shapes import RESAMPLE_N

CHUNK = 4096                    # trails per GPU launch: ~0.15 s, well under Windows' 2 s GPU watchdog

_KERNEL = r"""
#define N %(n)d
#define F 4
__kernel void dtw(__global const float *q, __global const float *t, __global float *out,
                  const int n_templates, const int band) {
    const int qi = get_global_id(0), ti = get_global_id(1);
    __global const float *a = q + qi * N * F;
    __global const float *b = t + ti * N * F;
    float prev[N + 1], cur[N + 1];
    prev[0] = 0.0f;
    for (int j = 1; j <= N; j++) prev[j] = INFINITY;
    for (int i = 1; i <= N; i++) {
        for (int j = 0; j <= N; j++) cur[j] = INFINITY;
        const int lo = max(1, i - band), hi = min(N, i + band);
        for (int j = lo; j <= hi; j++) {
            float c = 0.0f;
            for (int k = 0; k < F; k++) {
                const float d = a[(i - 1) * F + k] - b[(j - 1) * F + k];
                c += d * d;
            }
            cur[j] = sqrt(c) + fmin(fmin(prev[j], cur[j - 1]), prev[j - 1]);
        }
        for (int j = 0; j <= N; j++) prev[j] = cur[j];
    }
    out[qi * n_templates + ti] = prev[N] / (2 * N);
}
"""


def available() -> bool:
    try:
        return _context() is not None
    except Exception:
        return False


_ctx = None


def _context():
    """(context, queue, kernel, device name) on the first OpenCL GPU, built once."""
    global _ctx
    if _ctx is None:
        import pyopencl as cl
        gpus = [d for p in cl.get_platforms() for d in p.get_devices(cl.device_type.GPU)]
        if not gpus:
            return None
        ctx = cl.Context([gpus[0]])
        prog = cl.Program(ctx, _KERNEL % {"n": RESAMPLE_N}).build()
        _ctx = (ctx, cl.CommandQueue(ctx), cl.Kernel(prog, "dtw"), gpus[0].name)
    return _ctx


def device_name() -> str:
    return _context()[3]


def query_features(trail: np.ndarray) -> np.ndarray:
    """One trail → (tilts, N, 4) features, exactly as SpellMatcher.scores builds them."""
    pts = prepare(trail, TRIM_FRAC)
    return np.stack([_features(_normalise(_rotate(pts, deg))) for deg in TILT_DEG]).astype(np.float32)


def template_features(templates) -> np.ndarray:
    return SpellMatcher()._template_features(templates).astype(np.float32)


def dtw_scores(queries: np.ndarray, templates: np.ndarray) -> np.ndarray:
    """queries (Q, tilts, N, 4), templates (T, N, 4) → (Q, T) best-tilt score."""
    import pyopencl as cl
    ctx, queue, kernel, _ = _context()
    q_n, tilts = queries.shape[:2]
    t_n = len(templates)
    band = max(1, int(BAND_FRAC * RESAMPLE_N))
    mf = cl.mem_flags
    t_buf = cl.Buffer(ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=np.ascontiguousarray(templates))
    out = np.empty((q_n, t_n), np.float32)
    for s in range(0, q_n, CHUNK):
        q = np.ascontiguousarray(queries[s:s + CHUNK].reshape(-1, RESAMPLE_N, 4))
        rows = len(q)
        q_buf = cl.Buffer(ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=q)
        o = np.empty((rows, t_n), np.float32)
        o_buf = cl.Buffer(ctx, mf.WRITE_ONLY, o.nbytes)
        kernel(queue, (rows, t_n), None, q_buf, t_buf, o_buf, np.int32(t_n), np.int32(band))
        cl.enqueue_copy(queue, o, o_buf)
        out[s:s + CHUNK] = o.reshape(-1, tilts, t_n).min(axis=1)
    return out


def parity(trails: list, templates, cpu_scores: Optional[np.ndarray] = None) -> float:
    """Largest |GPU − CPU| score over these trails (CPU computed if not given)."""
    m = SpellMatcher()
    cpu = cpu_scores if cpu_scores is not None else np.stack([m.scores(t, templates) for t in trails])
    gpu = dtw_scores(np.stack([query_features(t) for t in trails]), template_features(templates))
    return float(np.abs(gpu - cpu).max())
