"""
dataset -- join the manifest with parsed results, expanding the post axes.

    scapsml collect project.xlsx

Series and shunt resistance are applied here rather than simulated. SCAPS has
no series-resistance field in the .def: it applies Rs as a lumped
post-process on the finished IV curve, and series.py reproduces that exactly.
One simulation therefore yields a row for every Rs x Rsh combination in the
sweep sheet, for no extra runtime.

Failed rows are KEPT with a status. Failures cluster at particular
compositions and contact pairings, so dropping them removes exactly the hard
region and biases anything trained afterwards. Filter at analysis time.

Partial runs are fine: rows with no .iv yet are marked MISSING and everything
else is written, so the pipeline can be checked long before the sweep ends.
"""

from __future__ import annotations

import csv
import itertools
import json
import math
from pathlib import Path

from .iv import classify, read_curve
from .series import apply_rs, iv_metrics
from ._io import read_rows, read_json, write_json

__all__ = ["collect"]

TARGETS = ("Voc", "Jsc", "FF", "PCE")


def collect(project, results_dir=None, out=None, verbose=True):
    log = print if verbose else (lambda *a, **k: None)
    work = project.resolve("work_dir", "work")
    results = Path(results_dir) if results_dir else project.resolve(
        "results_dir", "results")
    manifest = work / "manifest.csv"
    if not manifest.is_file():
        raise FileNotFoundError(f"{manifest} -- run 'scapsml generate' first")
    out = Path(out) if out else work / "dataset.csv"

    plan_json = work / "plan.json"
    post = json.loads(plan_json.read_text())["post_axes"] if plan_json.is_file() else {}
    rs_vals = post.get("Rs", [0.0])
    rsh_vals = post.get("Rsh", [math.inf])

    sims = list(read_rows(manifest))
    features = [c for c in sims[0] if c not in ("iv_file", "def_file", "abs_file")]
    log(f"manifest : {len(sims)} simulations")
    log(f"results  : {results}")
    log(f"post     : Rs {rs_vals}" + (f", Rsh {rsh_vals}" if "Rsh" in post else ""))

    rows, counts = [], {}
    for sim in sims:
        path = results / sim["iv_file"]
        exists = path.is_file()
        v, j, n, gen = read_curve(path, with_generation=True) if exists \
            else ([], [], 0, None)
        for rs, rsh in itertools.product(rs_vals, rsh_vals):
            m = iv_metrics(*apply_rs(v, j, rs, rsh)) if n >= 2 else \
                dict.fromkeys(TARGETS)
            st = classify(n, m, exists, gen)
            r = {"iv_file": sim["iv_file"]}
            r.update({k: sim[k] for k in features})
            r["Rs"] = rs
            r["Rsh"] = "inf" if math.isinf(rsh) else rsh
            for t in TARGETS:
                r[t] = "" if m[t] is None else f"{m[t]:.6f}"
            r["status"], r["n_points"] = st, n
            counts[st] = counts.get(st, 0) + 1
            rows.append(r)

    cols = ["iv_file"] + features + ["Rs", "Rsh"] + list(TARGETS) + ["status", "n_points"]
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    n = len(rows)
    for st in ("OK", "NO_VOC", "CONV_FAIL", "NO_DATA", "MISSING", "SUSPECT"):
        if counts.get(st):
            log(f"  {st:<10} {counts[st]:>7} / {n}  ({100 * counts[st] / n:.1f}%)")
    if counts.get("SUSPECT"):
        log(f"\n  {counts['SUSPECT']} rows are SUSPECT: an extracted Jsc exceeds the")
        log("  generation current, or FF falls outside (0, 1]. That is never")
        log("  physics -- it means metric extraction failed on those curves.")
        log("  They are excluded from modelling. Please report them.")
    log(f"wrote {out}")
    return out, counts
