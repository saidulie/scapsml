"""
iv -- read SCAPS .iv output.

SCAPS appends every simulation still in memory to a .iv file, so a script
that forgets `clear simulations` produces files holding several curves. The
LAST block is the one the filename refers to, and that is what is returned.

The current sign depends on which contact the bias is applied to, and SCAPS
states which in the header. Rather than trusting one convention, the curve is
normalised so J is positive at short circuit -- a parser that assumes a sign
silently reports "no Voc" for every file written the other way.

A file containing only a header means SCAPS rejected the problem before
solving (typically a defect level outside the gap). It is returned as an empty
curve and classified NO_DATA downstream, never as a crash.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .series import iv_metrics

__all__ = ["read_curve", "read_metrics", "classify", "STATUSES"]

STATUSES = ("OK", "NO_VOC", "CONV_FAIL", "NO_DATA", "MISSING", "SUSPECT")

# A Jsc more than this fraction above the generation current is not physics.
GENERATION_TOLERANCE = 1.02


def read_curve(path, with_generation=False):
    """
    (V, J, n_points) -- or (V, J, n_points, J_gen) with with_generation --
    J in mA/cm2 positive at short circuit, V ASCENDING.

    SCAPS does not always write a sweep in the order it was requested. A sweep
    from 0 V is written ascending; a sweep from -0.5 V to 1.85 V came back
    DESCENDING, 1.85 V first. Metric extraction walks the curve in order, so a
    descending file was read from the forward-bias end: the zero-current
    crossing it found first was Voc, it truncated away the whole working
    curve, and then extrapolated Jsc from two points at 1.85 V -- reporting
    56.6 mA/cm2 for a cell whose true Jsc is 16.4. The file ordering is
    arbitrary, so it is normalised here, once, where it enters the program.

    J_gen is SCAPS's total generation current (fourth column). No cell can
    deliver more short-circuit current than it generates, which makes it a
    hard physical check on any extracted Jsc.
    """
    p = Path(path)
    if not p.is_file():
        e = (np.array([]), np.array([]), 0)
        return e + (None,) if with_generation else e
    blocks, cur = [], []
    for line in p.read_bytes().decode("latin-1").splitlines():
        t = line.strip().split("\t")
        if len(t) >= 2:
            try:
                g = float(t[3]) if len(t) >= 4 else np.nan
                cur.append((float(t[0]), float(t[1]), g))
                continue
            except ValueError:
                pass
        if cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    if not blocks:
        e = (np.array([]), np.array([]), 0)
        return e + (None,) if with_generation else e
    arr = np.asarray(blocks[-1], float)
    arr = arr[np.argsort(arr[:, 0], kind="stable")]          # ascending V
    v, j, gen = arr[:, 0], arr[:, 1], arr[:, 2]
    if j[int(np.argmin(np.abs(v)))] < 0:
        j = -j
    if with_generation:
        g = np.abs(gen[np.isfinite(gen)])
        return v, j, len(v), (float(g.max()) if g.size else None)
    return v, j, len(v)


def classify(n_points, metrics, exists, generation=None):
    if not exists:
        return "MISSING"
    if n_points == 0:
        return "NO_DATA"
    if n_points <= 2:
        return "CONV_FAIL"
    jsc = metrics.get("Jsc")
    if (generation and jsc is not None
            and jsc > GENERATION_TOLERANCE * generation):
        # physically impossible -- an extraction fault, never a result
        return "SUSPECT"
    ff = metrics.get("FF")
    if ff is not None and not 0.0 < ff <= 1.0:
        return "SUSPECT"
    return "OK" if metrics.get("PCE") is not None else "NO_VOC"


def read_metrics(path):
    v, j, n, gen = read_curve(path, with_generation=True)
    m = iv_metrics(v, j) if n >= 2 else dict.fromkeys(("Voc", "Jsc", "FF", "PCE"))
    m["n_points"] = n
    m["generation"] = gen
    m["status"] = classify(n, m, Path(path).is_file(), gen)
    return m
