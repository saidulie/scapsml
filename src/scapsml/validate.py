"""
validate -- compare the model against the experiment sheet.

    scapsml validate project.xlsx

Two levels, reported separately because they test different things:

  MATERIAL  measured bandgaps against the anchor interpolation. This tests
            the inputs. It needs no simulation and should be run first: an
            interpolation that misses the measurements makes every device
            result wrong in a way no amount of solver work will reveal.

  DEVICE    measured Voc, Jsc, FF and PCE against simulated results at the
            same composition. For a validation project -- one configuration
            reproducing a published cell -- that is a direct comparison. For a
            sweep it reports the simulated RANGE and whether the measurement
            falls inside it, since a sweep does not predict one number.

A 1D drift-diffusion model with no reflection, series resistance, grain
boundaries or shunt paths is systematically optimistic in FF and Voc. The
report says so rather than presenting a gap to experiment as a failure.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .interpolate import Interpolator
from ._io import read_rows, read_json, write_json

__all__ = ["validate"]

DEVICE = ("Voc", "Jsc", "FF", "PCE")
UNITS = {"Voc": "V", "Jsc": "mA/cm2", "FF": "", "PCE": "%", "Eg": "eV"}
TOL = {"Voc": 0.10, "Jsc": 2.0, "FF": 0.08, "PCE": 2.5}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def validate(project, dataset=None, tol_eg=0.05, verbose=True):
    log = print if verbose else (lambda *a, **k: None)
    exp = project.experiment
    if not exp:
        log("no experiment sheet rows -- nothing to validate against")
        return {"material": [], "device": []}

    it = Interpolator(project.anchors, project.interpolation)
    lo, hi = it.span
    report = {"material": [], "device": []}

    # ---- material ------------------------------------------------------
    mat = [e for e in exp if "Eg" in e]
    if mat:
        log("\n--- MATERIAL: measured bandgap vs anchor interpolation ---")
        log(f"  {'composition':>12} {'measured':>9} {'model':>9} {'error':>9}  note")
        for e in mat:
            s = e["composition"]
            pred = it("Eg", s)
            err = pred - e["Eg"]
            inside = lo <= s <= hi
            ok = abs(err) <= tol_eg
            note = ("ok" if ok else "OUTSIDE TOLERANCE") + \
                   ("" if inside else "  (outside anchor range -- clamped)")
            log(f"  {s:>12.4f} {e['Eg']:>9.3f} {pred:>9.3f} {err:>+9.3f}  {note}")
            report["material"].append({"composition": s, "measured": e["Eg"],
                                       "model": pred, "error": err, "ok": ok})
        errs = [abs(r["error"]) for r in report["material"]]
        log(f"  mean |error| {sum(errs) / len(errs):.4f} eV, "
            f"max {max(errs):.4f} eV (tolerance {tol_eg} eV)")
        if max(errs) > tol_eg:
            log("  The interpolation misses the measurements. Every device")
            log("  result inherits that error -- fix the anchors first.")

        # A measurement that is also an anchor is reproduced by construction,
        # so the table above proves nothing about it. Leave each one out and
        # ask whether the remaining anchors predict it -- that is the test
        # that says whether the interpolation has learned the trend.
        circular = [e for e in mat if any(
            abs(a["composition"] - e["composition"]) < 1e-9 and "Eg" in a
            for a in project.anchors)]
        if circular:
            log(f"\n  {len(circular)} measurement(s) are also anchors, so the error")
            log("  above is zero by construction. Leave-one-out instead:")
            log(f"  {'composition':>12} {'measured':>9} {'held out':>9} {'error':>9}")
            loo = []
            for e in circular:
                rest = [a for a in project.anchors
                        if abs(a["composition"] - e["composition"]) > 1e-9]
                if sum("Eg" in a for a in rest) < 2:
                    continue
                p = Interpolator(rest, project.interpolation)("Eg", e["composition"])
                loo.append(p - e["Eg"])
                log(f"  {e['composition']:>12.4f} {e['Eg']:>9.3f} {p:>9.3f} "
                    f"{p - e['Eg']:>+9.3f}")
            if loo:
                m = sum(abs(x) for x in loo) / len(loo)
                log(f"  leave-one-out mean |error| {m:.4f} eV, "
                    f"max {max(abs(x) for x in loo):.4f} eV")
                report["leave_one_out"] = loo
                if max(abs(x) for x in loo) > tol_eg:
                    log("  Held-out measurements are not predicted well. The")
                    log("  anchors are too sparse for the trend between them.")

    # ---- device --------------------------------------------------------
    dev = [e for e in exp if any(k in e for k in DEVICE)]
    if not dev:
        return report
    dataset = Path(dataset) if dataset else \
        project.resolve("work_dir", "work") / "dataset.csv"
    if not dataset.is_file():
        log(f"\n--- DEVICE: skipped, no dataset at {dataset} ---")
        log("  run 'scapsml collect' first")
        return report
    rows = [r for r in read_rows(dataset)
            if r["status"] == "OK"]
    rs0 = [r for r in rows if _f(r.get("Rs")) in (0.0, None)]
    pool = rs0 or rows

    log("\n--- DEVICE: measured vs simulated ---")
    for e in dev:
        s = e["composition"]
        comps = sorted({_f(r["composition"]) for r in pool})
        if not comps:
            log("  no converged simulations to compare against")
            break
        near = min(comps, key=lambda c: abs(c - s))
        at = [r for r in pool if _f(r["composition"]) == near]
        src = e.get("source", "")
        log(f"\n  composition {s}  (nearest simulated {near}, {len(at)} runs)"
            + (f"  -- {src}" if src else ""))
        log(f"    {'metric':<6} {'measured':>10} {'simulated':>22}  verdict")
        entry = {"composition": s, "source": src, "metrics": {}}
        for k in DEVICE:
            if k not in e:
                continue
            vals = sorted(_f(r[k]) for r in at if _f(r[k]) is not None)
            if not vals:
                continue
            if len(vals) == 1:
                sim, d = f"{vals[0]:.4f}", vals[0] - e[k]
                ok = abs(d) <= TOL[k]
                verdict = f"{d:+.4f} {UNITS[k]}  " + ("ok" if ok else "outside tolerance")
            else:
                sim = f"{vals[0]:.3f} .. {vals[-1]:.3f}"
                ok = vals[0] <= e[k] <= vals[-1]
                verdict = "within simulated range" if ok else "OUTSIDE simulated range"
                d = None
            log(f"    {k:<6} {e[k]:>10.4f} {sim:>22}  {verdict}")
            entry["metrics"][k] = {"measured": e[k], "simulated": vals,
                                   "delta": d, "ok": ok}
        report["device"].append(entry)

    log("\n  A 1D model with no reflection, series resistance, grain boundaries")
    log("  or shunt paths is systematically optimistic in FF and Voc. A gap in")
    log("  that direction is expected; report it rather than tuning it away.")
    return report
