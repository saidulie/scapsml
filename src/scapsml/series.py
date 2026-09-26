"""
series -- apply lumped series and shunt resistance to an IV curve.

WHY THIS IS NOT A SIMULATION AXIS
---------------------------------
SCAPS has no series-resistance field in the .def. It applies Rs as a lumped
post-process on the finished IV curve, which means the transformation is exact
and can be done here instead -- one simulation yields every Rs value for free.

For the "photocurrent positive" convention SCAPS writes (J > 0 at V = 0,
falling to 0 at Voc), the simulated curve IS the junction curve. A series
resistance drops J * Rs of voltage between the junction and the terminals, so

    V_terminal = V_junction - J * Rs           J in A/cm2, Rs in ohm.cm2

The sign matters and is easy to get backwards: with a plus the transformation
ADDS power and the fill factor exceeds 1, which the tests catch.

A shunt resistance Rsh leaks current in parallel with the junction:

    J_terminal = J_simulated - V_junction / Rsh

Both leave Jsc and Voc untouched to first order and act on the fill factor,
which is the textbook behaviour and is asserted in the tests.

Doing this analytically rather than as a SCAPS axis is not an approximation:
it is the same lumped model SCAPS itself applies, evaluated exactly, and it
removes a multiplicative factor from the simulation budget.
"""

from __future__ import annotations

import numpy as np

__all__ = ["apply_rs", "iv_metrics", "metrics_vs_rs"]


def apply_rs(v, j, rs=0.0, rsh=np.inf):
    """
    Transform an IV curve for lumped series/shunt resistance.

    v   : array of applied voltage, V
    j   : array of current density, mA/cm2, positive at short circuit
    rs  : series resistance, ohm.cm2
    rsh : shunt resistance, ohm.cm2 (np.inf for none)

    Returns (v_terminal, j_terminal) in the same units.
    """
    v = np.asarray(v, dtype=float)
    j = np.asarray(j, dtype=float)
    # The input is a JUNCTION curve and must be in ascending junction voltage
    # before the transformation, because iv_metrics walks the result in order
    # (it cannot sort it: with Rs the terminal voltage can fold back). Sorting
    # here protects any caller that hands over a curve as SCAPS wrote it.
    o = np.argsort(v, kind="stable")
    v, j = v[o], j[o]
    j_a = j * 1e-3                                  # mA/cm2 -> A/cm2

    j_out = j_a - (v / rsh if np.isfinite(rsh) else 0.0)
    v_out = v - j_out * rs
    return v_out, j_out * 1e3


MAX_EXTRAPOLATION_V = 0.10      # V -- never extrapolate Jsc further than this


def _first_crossing(x, y):
    """
    Linear interpolation of y where x first crosses zero, walking the array in
    its given order. Returns None if x never changes sign.
    """
    s = np.sign(x)
    k = np.where(np.diff(s) != 0)[0]
    if not len(k):
        return None
    i = int(k[0])
    dx = x[i + 1] - x[i]
    if dx == 0:
        return float(y[i])
    return float(y[i] + (y[i + 1] - y[i]) * (-x[i] / dx))


def iv_metrics(v, j, p_in=100.0):
    """
    Voc (V), Jsc (mA/cm2), FF, PCE (%) from an IV curve.

    The curve is treated PARAMETRICALLY, in the order given, not as a function
    of voltage. This matters once series resistance is applied: where the
    junction slope exceeds 1/Rs the terminal voltage folds back, so V is no
    longer monotonic and sorting by it scrambles the curve. Walking the array
    in sweep order handles the fold correctly and costs nothing otherwise.

    Returns None for any quantity the curve does not support -- a curve that
    never crosses zero current has no Voc, and therefore no FF or PCE.
    p_in is the incident power in mW/cm2.
    """
    v = np.asarray(v, dtype=float)
    j = np.asarray(j, dtype=float)
    if v.size < 2:
        return {"Voc": None, "Jsc": None, "FF": None, "PCE": None}

    # Truncate just past the first J = 0 crossing. Nothing beyond Voc enters
    # any of the four metrics, and keeping it is actively harmful: a sweep
    # that runs well into forward bias reaches enormous negative J, which the
    # series-resistance mapping turns into an enormous negative terminal
    # voltage and a spurious second V = 0 crossing. SCAPS normally stops at
    # Voc (stopafterVoc 1), but a curve that does not must not break this.
    k = np.where(np.diff(np.sign(j)) != 0)[0]
    if len(k):
        v, j = v[: int(k[0]) + 2], j[: int(k[0]) + 2]

    jsc = _first_crossing(v, j)                 # J where V = 0
    if jsc is None and v.size >= 2 and 0 < v[0] <= MAX_EXTRAPOLATION_V \
            and v[1] != v[0]:
        # A curve starting JUST above V = 0 can be extended the short way to
        # it: near short circuit J is flat, so two points suffice. Beyond that
        # it is refused. An unbounded version of this fallback once
        # extrapolated from two points at 1.85 V down to 0 V and reported
        # Jsc = 56.6 mA/cm2 -- a confident wrong number, where a missing one
        # would have been honest.
        jsc = float(j[0] + (j[1] - j[0]) * (0.0 - v[0]) / (v[1] - v[0]))
    voc = _first_crossing(j, v)                 # V where J = 0

    out = {"Voc": voc, "Jsc": jsc, "FF": None, "PCE": None}
    if voc is None or jsc is None or voc <= 0 or jsc <= 0:
        return out

    p = v * j                                    # mW/cm2, valid in quadrant I
    m = (v >= 0) & (j >= 0)
    if m.sum() < 1:
        return out
    pmax = float(p[m].max())
    if pmax <= 0:
        return out

    out["FF"] = pmax / (voc * jsc)
    out["PCE"] = 100.0 * pmax / p_in
    return out


def metrics_vs_rs(v, j, rs_values, rsh=np.inf, p_in=100.0):
    """{rs: metrics} for a list of series resistances."""
    return {rs: iv_metrics(*apply_rs(v, j, rs, rsh), p_in=p_in)
            for rs in rs_values}
