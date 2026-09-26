"""
scapsml command line.

    scapsml init      project.xlsx [--def base.def]   new workbook
    scapsml check     project.xlsx                    validate before running
    scapsml generate  project.xlsx [--dry-run]        defs, spectra, scripts
    scapsml run       project.xlsx [comp ...] [--next N] [--force]
    scapsml status    project.xlsx
    scapsml collect   project.xlsx [--results DIR]
    scapsml validate  project.xlsx
    scapsml ml        project.xlsx [--target PCE] [--kfold 10]
    scapsml calibrate project.xlsx                    record GUI button positions
    scapsml inspect-abs FILE --eg GAP [--window] [--thickness NM]
    scapsml params                                     every sweepable parameter
    scapsml inspect-def FILE                           layers and key values
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import __version__


def _load(path):
    from .workbook import WorkbookError, load
    try:
        return load(path)
    except WorkbookError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(2)


def cmd_init(a):
    from .template import write_template
    out = Path(a.workbook)
    if out.exists() and not a.force:
        raise SystemExit(f"{out} exists -- use --force to overwrite")
    write_template(out, base_def=a.def_file)
    print(f"wrote {out}")
    print("Next: fill in the 'anchors' and 'sweep' sheets, then run\n"
          f"    scapsml check {out}")


def cmd_check(a):
    from .defio import DefFile
    from .design import plan
    from .generate import build_def
    from .interpolate import Interpolator

    p = _load(a.workbook)
    print(f"workbook  : {p.path}")
    print(f"base .def : {p.base_def}")
    d = DefFile.load(p.base_def)
    print(f"stack     : {' / '.join(d.layers)}   (absorber: {p.absorber})")
    ok = True
    stale = d.interface_names_stale()
    if stale:
        print("\n  note: interface names in the .def do not match their layers")
        for k, name, want in stale:
            print(f"    interface {k}: named {name!r}, sits between {want}")
        print("  Harmless -- SCAPS and scapsml address interfaces by position --")
        print("  but worth tidying so the file reads correctly.")

    it = Interpolator(p.anchors, p.interpolation)
    lo, hi = it.span
    comp = p.composition_axis
    if comp:
        out = [c for c in comp.values if not lo <= c <= hi]
        if out:
            print(f"\n  WARNING {len(out)} composition(s) outside the anchor range "
                  f"[{lo}, {hi}] are clamped, not extrapolated: {out[:5]}")
        steps = {round(b - a, 9) for a, b in zip(comp.values, comp.values[1:])}
        if len(steps) > 1:
            print(f"\n  WARNING composition grid is not uniformly spaced "
                  f"(steps {sorted(steps)}). Uneven density biases any model and "
                  f"its SHAP attribution toward the densely sampled region.")

    pl = plan(p)
    print()
    for k, v in pl.summary().items():
        print(f"  {k:<18} {v}")
    if pl.skipped:
        print(f"  skipped: {pl.skipped[:3]}")

    print("\n-- building every definition file in memory --")
    bad = 0
    for dz in pl.designs:
        try:
            build_def(p, d, dz)
        except Exception as exc:
            bad += 1
            if bad <= 3:
                print(f"  FAIL design {dz.index}: {exc}")
    if bad:
        ok = False
        print(f"  {bad} designs failed to build")
    else:
        print(f"  ok: all {len(pl.designs)} build")

    from .bands import report, verdict, barriers
    print("\n-- band alignment at the absorber's contacts --")
    lines, n_fail, n_warn, _ = report(d, p.absorber, pl.designs, build_def, p)
    for ln in lines:
        print(ln)
    if n_fail:
        ok = False
        print(f"\n  FAIL {n_fail} of {len(pl.designs)} designs cannot extract "
              f"carriers at one contact.")
        print("  These will not converge, and SCAPS is slow to fail. Fix the")
        print("  transport layers before running: set the ETL affinity and HTL")
        print("  valence band in the 'layers' sheet, or sweep them by naming")
        print("  the layer in the 'sweep' sheet, e.g.")
        print("      chi   TiO2           absolute   4.7, 4.9, 5.1")
        print("      chi   Spiro-OmeTAD   absolute   3.2, 3.4, 3.6")
    elif n_warn:
        print(f"\n  {n_warn} designs have a barrier above "
              f"{__import__('scapsml.bands', fromlist=['x']).SPIKE_WARN} eV; "
              f"current will be throttled there.")
    else:
        print(f"  ok: all {len(pl.designs)} designs extract at both contacts")

    missing = []
    if pl.abs_files:
        sd = p.resolve("spectra_dir", ".")
        for a_ in p.anchors:
            f = a_.get("abs_file")
            if f and not (sd / f).is_file():
                missing.append(f)
    if missing:
        ok = False
        print(f"\n  FAIL missing reference spectra in {sd}: {missing}")

    if p.experiment:
        from .validate import validate
        print("\n-- validation against the experiment sheet --")
        validate(p, verbose=True)

    print("\n" + ("READY" if ok else "NOT READY -- fix the failures above"))
    raise SystemExit(0 if ok else 1)


def cmd_generate(a):
    from .generate import generate
    generate(_load(a.workbook), dry_run=a.dry_run)


def cmd_run(a):
    from .runner import run
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    raise SystemExit(run(_load(a.workbook), comps=a.compositions or None,
                         next_n=a.next, force=a.force))


def cmd_status(a):
    from .runner import status
    status(_load(a.workbook))


def cmd_collect(a):
    from .dataset import collect
    collect(_load(a.workbook), results_dir=a.results)


def cmd_validate(a):
    from .validate import validate
    validate(_load(a.workbook))


def cmd_ml(a):
    from .ml import run
    p = _load(a.workbook)
    work = p.resolve("work_dir", "work")
    run(work / "dataset.csv", work / "ml", target=a.target, kfold=a.kfold)


def cmd_calibrate(a):
    from .runner import calibrate
    calibrate(_load(a.workbook))


def cmd_inspect_abs(a):
    from .absorption import check_file
    print(f"{'file':<40} {'edge':>7} {'expect':>7} {'a@500':>9} {'tail':>9}  verdict")
    for f in a.files:
        r = check_file(f, a.eg, a.thickness, a.spectrum, a.window)
        print(f"{Path(f).name:<40} {r['edge_nm']:>7.0f} {r['expected_edge_nm']:>7.0f} "
              f"{r['alpha_500_cm']:>9.3g} {r['tail_cm']:>9.3g}  {r['verdict']}")


def cmd_inspect_def(a):
    from .defio import DefFile
    d = DefFile.load(a.file)
    print(d.summary())
    for k, n in enumerate(d.interfaces, 1):
        between = f"{d.layers[k-1]} / {d.layers[k]}" if k < len(d.layers) else "?"
        print(f"  interface {k}: {n!r:<26} (between {between})")
    for k, name, want in d.interface_names_stale():
        print(f"  note: interface {k} is named {name!r} but sits between {want}")


def cmd_figures(a):
    from .defio import DefFile
    from .interpolate import Interpolator
    from .iv import read_curve
    from .series import apply_rs, iv_metrics
    from . import figures as F
    from ._io import read_rows

    p = _load(a.workbook)
    out = Path(a.outdir or (p.resolve("work_dir", "work") / "figures"))
    made = []

    from .design import plan as _plan
    _s = _plan(p).summary()
    made += F.fig_system(out, "fig_system")
    made += F.fig_workflow(out, "fig_workflow", counts={
        "defs": _s["definition_files"], "spectra": _s["absorption_files"],
        "sims": _s["simulations"], "rows": _s["dataset_rows"],
        "compositions": _s["compositions"]})
    base = DefFile.load(p.base_def)
    made += F.fig_architecture(base, out, "fig_architecture", absorber=p.absorber)
    made += F.fig_bands(base, out, "fig_bands", absorber=p.absorber)

    if p.anchors:
        it = Interpolator(p.anchors, p.interpolation)
        meas = [e for e in p.experiment if "Eg" in e]
        loo = []
        for e in meas:
            rest = [x for x in p.anchors
                    if abs(x["composition"] - e["composition"]) > 1e-9]
            if sum("Eg" in x for x in rest) >= 2:
                loo.append((e["composition"],
                            Interpolator(rest, p.interpolation)("Eg",
                                                               e["composition"])))
        if meas:
            made += F.fig_bandgap(p.anchors, meas, lambda x: it("Eg", x), out,
                                  "fig_bandgap", loo or None)

    ds = p.resolve("work_dir", "work") / "dataset.csv"
    results = p.resolve("results_dir", "results")
    if ds.is_file():
        rows = [r for r in read_rows(ds) if r["status"] == "OK"]
        if rows:
            best = max(rows, key=lambda r: float(r["PCE"]))
            v, j, n = read_curve(results / best["iv_file"])
            if n:
                rs_vals = sorted({float(r["Rs"]) for r in rows})[:4]
                curves = [(f"$R_s$ = {rv:g} " + r"$\Omega$ cm$^2$",)
                          + apply_rs(v, j, rv) for rv in rs_vals]
                made += F.fig_jv(curves, out, "fig_jv")
            xk, yk = a.map_x, a.map_y
            if xk and yk and xk in rows[0] and yk in rows[0]:
                sel = [r for r in rows if float(r.get("Rs", 0)) == 0] or rows
                agg = {}
                for r in sel:
                    k = (float(r[xk]), float(r[yk]))
                    agg[k] = max(agg.get(k, -1e9), float(r["PCE"]))
                made += F.fig_contact_map([k[0] for k in agg], [k[1] for k in agg],
                                          list(agg.values()), xk, yk, out,
                                          "fig_contact_map")
    dev = [e for e in p.experiment if any(k in e for k in ("Voc", "Jsc", "FF", "PCE"))]
    if dev and ds.is_file():
        rows = [r for r in read_rows(ds) if r["status"] == "OK"
                and float(r.get("Rs", 0)) == 0]
        if rows:
            best = max(rows, key=lambda r: float(r["PCE"]))
            series = [(e.get("source", "measured")[:18],
                       {k: e[k] for k in ("Voc", "Jsc", "FF", "PCE") if k in e})
                      for e in dev]
            series.append(("this work", {k: float(best[k])
                                         for k in ("Voc", "Jsc", "FF", "PCE")}))
            made += F.fig_validation(series, out, "fig_validation")

    for m in made:
        print(f"  {m}")
    print(f"\n{len(made) // 2} figures (PDF + PNG) in {out}")


def cmd_params(a):
    from .registry import describe
    print(describe())


def _quiet_pipe():
    """Exit silently when output is piped into head, less, etc."""
    import signal
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)


def main(argv=None):
    _quiet_pipe()
    ap = argparse.ArgumentParser(prog="scapsml",
                                 description="Workbook-driven SCAPS-1D sweeps and ML")
    ap.add_argument("--version", action="version", version=f"scapsml {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="write a new project workbook")
    s.add_argument("workbook")
    s.add_argument("--def", dest="def_file", help="base .def to read the stack from")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init)

    for name, fn, hlp in (("check", cmd_check, "validate everything first"),
                          ("generate", cmd_generate, "write defs, spectra, scripts"),
                          ("status", cmd_status, "progress of a run"),
                          ("validate", cmd_validate, "compare to the experiment sheet"),
                          ("calibrate", cmd_calibrate, "record SCAPS button positions")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("workbook")
        if name == "generate":
            s.add_argument("--dry-run", action="store_true")
        s.set_defaults(fn=fn)

    s = sub.add_parser("run", help="drive SCAPS (Windows), resumably")
    s.add_argument("workbook")
    s.add_argument("compositions", nargs="*", type=float)
    s.add_argument("--next", type=int)
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("collect", help="parse results into a dataset")
    s.add_argument("workbook")
    s.add_argument("--results")
    s.set_defaults(fn=cmd_collect)

    s = sub.add_parser("ml", help="models, SHAP, inverse design")
    s.add_argument("workbook")
    s.add_argument("--target", default="PCE", choices=["PCE", "Voc", "Jsc", "FF"])
    s.add_argument("--kfold", type=int, default=10)
    s.set_defaults(fn=cmd_ml)

    s = sub.add_parser("inspect-abs", help="check absorption files")
    s.add_argument("files", nargs="+")
    s.add_argument("--eg", type=float, required=True)
    s.add_argument("--thickness", type=float, default=500)
    s.add_argument("--spectrum")
    s.add_argument("--window", action="store_true")
    s.set_defaults(fn=cmd_inspect_abs)

    s = sub.add_parser("inspect-def", help="summarise a .def")
    s.add_argument("file")
    s.set_defaults(fn=cmd_inspect_def)

    s = sub.add_parser("figures", help="publication figures from this project")
    s.add_argument("workbook")
    s.add_argument("--outdir")
    s.add_argument("--map-x", default="chi@TiO2", help="x axis of the contact map")
    s.add_argument("--map-y", default="chi@Spiro-OmeTAD", help="y axis")
    s.set_defaults(fn=cmd_figures)

    s = sub.add_parser("params", help="list sweepable parameters")
    s.set_defaults(fn=cmd_params)

    a = ap.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
