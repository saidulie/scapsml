"""
generate -- write every definition file, absorption file, script and the
manifest for a project.

    scapsml generate project.xlsx

Output, under project!work_dir:

    defs/         one .def per design
    absorption/   one .abs per (composition, bandgap)
    scripts/      one .script per composition
    manifest.csv  one row per simulation: every feature, and the .iv name
    plan.json     the design summary and a fingerprint of the inputs

The manifest is the contract between generation and collection. build_dataset
joins results to it by .iv filename, so it records every value that went into
each simulation -- including the resolved absorber material, not just the
swept axes.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from . import absorption as absmod
from .defio import DefFile
from .design import fingerprint, plan, s_tag
from .interpolate import Interpolator
from .registry import DEF, SCRIPT, lookup
from ._io import read_rows, read_json, write_json

__all__ = ["generate", "script_for", "iv_name"]

JSC_CEILING = 0.080      # A/cm2 -- no absorber in the AM1.5 spectrum exceeds this
START_MARGIN = 1.15


def spectra_neighbours(anchors, s):
    """
    The two anchors WITH a spectrum that bracket s, and the blend weight.

    Spectrum anchors and property anchors need not coincide: bandgaps are
    best anchored at measured compositions, which rarely have a published
    absorption spectrum. So the blend uses only rows that name an abs_file.
    """
    sp = sorted((a for a in anchors if a.get("abs_file")),
                key=lambda a: a["composition"])
    if not sp:
        raise ValueError("no anchor names an abs_file")
    if s <= sp[0]["composition"]:
        return sp[0], sp[0], 0.0
    if s >= sp[-1]["composition"]:
        return sp[-1], sp[-1], 0.0
    for a, b in zip(sp, sp[1:]):
        if a["composition"] <= s <= b["composition"]:
            span = b["composition"] - a["composition"]
            return a, b, (s - a["composition"]) / span if span else 0.0
    return sp[-1], sp[-1], 0.0


def iv_name(prefix, s, idx):
    return f"{prefix}_S{s_tag(s)}_{idx:05d}.iv"


def script_name(prefix, s):
    return f"{prefix}_S{s_tag(s)}.script"


def start_voltage(pl):
    rs = [v for a in pl.post_axes if a.name == "Rs" for v in a.values]
    if not rs or max(rs) <= 0:
        return 0.0
    need = max(rs) * JSC_CEILING * START_MARGIN
    return -math.ceil(need / 0.05) * 0.05


def stop_voltage(project, eg):
    m = float(project.setting("stop_margin", 0.20))
    return round(min(max(0.30, eg - m), 3.0), 2)


def _apply_material(d, layer, mat):
    """Write every resolved material property into the absorber block."""
    for prop, value in mat:
        try:
            p = lookup(prop)
        except KeyError:
            continue
        if p.target != DEF or not p.field:
            continue
        if prop == "sigma_bulk":
            for f in ("sigma_n", "sigma_p"):
                if d.has(layer, f, sub="srhrecombination"):
                    d.set(layer, f, p.def_value(value), sub="srhrecombination")
            continue
        if d.has(layer, p.field):
            d.set(layer, p.field, p.def_value(value))


def build_def(project, base, design):
    d = base.copy()
    absorber = project.absorber
    _apply_material(d, absorber, design.material)

    # fixed overrides from the layers sheet, then swept other-layer values
    for layer, prop, value in list(project.layer_overrides) + list(design.other):
        if prop == "absorption":
            if value == "model":
                d.set_absorption_model(layer)
            else:
                d.set_absorption_file(layer, value)
            continue
        p = lookup(prop)
        if p.target == DEF and p.field:
            d.set(layer, p.field, p.def_value(value))

    if design.abs_name:
        d.set_absorption_file(absorber, design.abs_name)
    if str(project.setting("pin_defects_midgap", "yes")).lower() in (
            "yes", "true", "1", "on"):
        d.pin_defects_midgap()
    return d


def _interface_for(d, axis, absorber):
    """1-based interface number for an interface-scoped axis."""
    if axis.layer and "/" in axis.layer:
        a, b = (x.strip() for x in axis.layer.split("/", 1))
        return d.interface_index(d.interface_between(a, b))
    # default: the interface on the absorber's far (back-contact) side
    layers = d.layers
    i = layers.index(absorber)
    if i + 1 < len(layers):
        return d.interface_index(d.interface_between(absorber, layers[i + 1]))
    return d.interface_index(d.interface_between(layers[i - 1], absorber))


def script_for(project, pl, base, s, designs, prefix, points):
    absorber = project.absorber
    L = base.layer_index(absorber)
    startv = start_voltage(pl)
    lines = [
        f"// scapsml -- {project.name} -- composition {s}",
        f"// {len(designs)} definition file(s), "
        f"{len(designs) * len(pl.sims_for(designs[0]) if designs else 0)} simulations",
        "// Generated from the project workbook. Do not edit: regenerate instead.",
        "//",
    ]
    if startv < 0:
        lines += ["// The sweep starts below zero so the series-resistance shifted",
                  "// curve still contains V = 0 and Jsc is read, not extrapolated.",
                  "//"]
    ivs = []
    idx = 0
    for dz in designs:
        eg = dz.mat("Eg")
        lines += [
            "",
            f"// ==== design {dz.index}: "
            + "  ".join(f"{k}={v:.4g}" for k, v in dz.varied) + " ====",
            f"load definitionfile {dz.def_name}",
            "clear all",
            "clear actions",
            "set errorhandling.appendtofile",
            "set illumination.fromleft",
            f"action iv.startV {startv:.2f}",
            f"action iv.stopV {stop_voltage(project, eg):.2f}",
            f"action iv.points {points}",
            "action iv.stopafterVoc 1",
        ]
        for sim in pl.sims_for(dz):
            name = iv_name(prefix, s, idx)
            ivs.append((name, dz, sim))
            cmds = []
            for key, v in sim.items():
                pname, _, lay = key.partition("@")
                p = lookup(pname)
                if p.scope == "interface":
                    ax = next(a for a in pl.script_axes if a.name == pname)
                    cmds.append(p.script_line(v, interface_no=_interface_for(
                        base, ax, absorber)))
                elif p.scope == "layer":
                    ln = base.layer_index(lay) if lay else L
                    cmds.append(p.script_line(v, layer_no=ln))
                else:
                    cmds.append(p.script_line(v))
            lines += ["", f"// -- sim {idx:05d} --", "clear simulations"] + cmds + [
                "action dark", "action iv.checkaction 0", "calculate singleshot",
                "action light", "action intensity.ND 0", "action iv.checkaction 1",
                "calculate singleshot", f"save results.iv {name}"]
            idx += 1
    lines += ["", "// === done ==="]
    return lines, ivs


def generate(project, dry_run=False, verbose=True):
    pl = plan(project)
    work = project.resolve("work_dir", "work")
    prefix = str(project.name).replace(" ", "_")
    points = int(project.setting("iv_points", 150))
    base = DefFile.load(project.base_def)
    log = print if verbose else (lambda *a, **k: None)

    s = pl.summary()
    log(f"\n== scapsml generate: {project.name} ==")
    for k, v in s.items():
        log(f"  {k:<18} {v}")
    if pl.skipped:
        log(f"  {len(pl.skipped)} designs skipped as non-physical")
    if dry_run:
        return pl, None

    for sub in ("defs", "absorption", "scripts"):
        (work / sub).mkdir(parents=True, exist_ok=True)

    # ---- absorption ----------------------------------------------------
    warnings = []
    if pl.abs_files:
        it = Interpolator(project.anchors, project.interpolation)
        spectra_dir = project.resolve("spectra_dir", ".")
        done = set()
        for dz in pl.designs:
            if not dz.abs_name or dz.abs_name in done:
                continue
            lo, hi, t = spectra_neighbours(project.anchors, dz.composition)
            e, a = absmod.build(lo, hi, t, dz.mat("Eg"), spectra_dir)
            for w in absmod.verify(e, a, dz.mat("Eg")):
                warnings.append(f"{dz.abs_name}: {w}")
            absmod.write_abs(work / "absorption" / dz.abs_name, e, a, header=[
                f"scapsml: composition {dz.composition}, Eg {dz.mat('Eg'):.4f} eV",
                f"blended {lo.get('abs_file')} / {hi.get('abs_file')} at t={t:.3f}",
                "edge shifted to the design bandgap; zero below the gap"])
            done.add(dz.abs_name)
        log(f"  wrote {len(done)} absorption files")

    # ---- definition files ----------------------------------------------
    for dz in pl.designs:
        build_def(project, base, dz).save(work / "defs" / dz.def_name)
    log(f"  wrote {len(pl.designs)} definition files")

    # ---- scripts + manifest --------------------------------------------
    rows = []
    comps = sorted({d.composition for d in pl.designs})
    for c in comps:
        ds = [d for d in pl.designs if d.composition == c]
        lines, ivs = script_for(project, pl, base, c, ds, prefix, points)
        (work / "scripts" / script_name(prefix, c)).write_bytes(
            ("\r\n".join(lines) + "\r\n").encode("ascii", "replace"))
        for name, dz, sim in ivs:
            row = {"iv_file": name, "composition": c,
                   "def_file": dz.def_name, "abs_file": dz.abs_name or ""}
            row.update({k: v for k, v in dz.material})
            row.update({k: v for k, v in dz.varied})
            row.update(sim)
            rows.append(row)
    log(f"  wrote {len(comps)} scripts")

    cols = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with open(work / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    log(f"  wrote manifest.csv ({len(rows)} rows)")

    write_json(work / "plan.json", {"project": project.name, "fingerprint": fingerprint(project),
               "summary": s, "post_axes": {a.name: a.values for a in pl.post_axes},
               "start_voltage": start_voltage(pl), "warnings": warnings})
    for w in warnings:
        log(f"  WARNING {w}")
    return pl, work
