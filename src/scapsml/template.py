"""
template -- write a fresh, self-documenting project workbook.

    scapsml init my_project.xlsx
    scapsml init my_project.xlsx --def my_cell.def     # pre-fills the stack

The generated workbook has dropdowns on the parameter and mode columns so an
invalid name cannot be typed, a README sheet explaining every other sheet, and
a reference sheet listing every parameter with its unit and where it goes.
When a base .def is given, the layers found in it are written into the
workbook so the absorber name and layer overrides start out correct.
"""

from __future__ import annotations

from pathlib import Path

from .registry import _P

HEAD_FILL = "1F4E78"
HEAD_FONT = "FFFFFF"
NOTE_FONT = "666666"


def _style_header(ws, row=1):
    from openpyxl.styles import Alignment, Font, PatternFill
    for c in ws[row]:
        if c.value is None:
            continue
        c.font = Font(bold=True, color=HEAD_FONT)
        c.fill = PatternFill("solid", fgColor=HEAD_FILL)
        c.alignment = Alignment(vertical="center")
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def _widths(ws, widths):
    from openpyxl.utils import get_column_letter
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _note(ws, text):
    from openpyxl.styles import Font
    ws.append([])
    for line in text.strip().split("\n"):
        ws.append(["# " + line.strip()])
        ws.cell(row=ws.max_row, column=1).font = Font(italic=True, color=NOTE_FONT)


def write_template(path, base_def=None, example=None):
    """
    Write a project workbook. `example` is an optional dict with keys
    project, anchors, sweep, layers, experiment to pre-fill it.
    """
    import openpyxl
    from openpyxl.worksheet.datavalidation import DataValidation

    from .defio import DefFile

    ex = dict(example or {})
    wb = openpyxl.Workbook()

    layers = []
    if base_def:
        from .defio import DefFile
        layers = DefFile.load(base_def).layers
        if not example:
            ex = baseline_from_def(base_def)

    # ---- README --------------------------------------------------------
    ws = wb.active
    ws.title = "README"
    for line in README.strip().split("\n"):
        ws.append([line])
    ws.column_dimensions["A"].width = 110
    from openpyxl.styles import Font
    ws["A1"].font = Font(bold=True, size=14)

    # ---- project -------------------------------------------------------
    ws = wb.create_sheet("project")
    ws.append(["key", "value", "description"])
    defaults = [
        ("name", "my_project", "label used in output filenames"),
        ("base_def", Path(base_def).name if base_def else "base.def",
         "starting .def file, relative to this workbook"),
        ("absorber", _guess_absorber(DefFile.load(base_def)) if base_def
         else "Absorber",
         "name of the absorber layer exactly as it appears in the .def"),
        ("composition_label", "x", "what the composition axis is called"),
        ("work_dir", "work", "generated defs, scripts, manifest"),
        ("results_dir", "results", "where SCAPS .iv files are collected"),
        ("scaps_dir", r"C:\Program Files (x86)\Scaps3312",
         "SCAPS installation"),
        ("iv_points", 150, "voltage points per IV sweep"),
        ("stop_margin", 0.20, "sweep stops at Eg - this (V)"),
        ("pin_defects_midgap", "yes",
         "put every trap at midgap by construction (strongly recommended)"),
    ]
    given = dict(ex.get("project", {}))
    for k, v, d in defaults:
        ws.append([k, given.pop(k, v), d])
    for k, v in given.items():
        ws.append([k, v, ""])
    if layers:
        ws.append([])
        ws.append(["# layers found in the base .def: " + ", ".join(layers)])
    _style_header(ws)
    _widths(ws, [22, 38, 70])

    # ---- anchors -------------------------------------------------------
    ws = wb.create_sheet("anchors")
    cols = ex.get("anchor_columns",
                  ["composition", "Eg", "chi", "eps", "Nc", "Nv", "mun", "mup",
                   "abs_file", "source"])
    ws.append(cols)
    for row in ex.get("anchors", []):
        ws.append([row.get(c) for c in cols])
    _style_header(ws)
    _widths(ws, [14] + [12] * (len(cols) - 2) + [40])
    _note(ws, """
Material properties at known compositions. Values between anchors are interpolated.
Units: Eg, chi, IP in eV | Nc, Nv in cm^-3 | mun, mup in cm^2/Vs | eps dimensionless.
Give EITHER chi OR IP (ionisation potential). With IP, chi is derived as IP - Eg.
abs_file: optional per-anchor absorption spectrum; spectra are blended between anchors.
Anchor at measured compositions wherever you can -- that is what makes the study defensible.
""")

    # ---- interpolation -------------------------------------------------
    ws = wb.create_sheet("interpolation")
    ws.append(["property", "method", "note"])
    for row in ex.get("interpolation", [("Nc", "log", "densities span decades"),
                                        ("Nv", "log", ""),
                                        ("Eg", "pchip", "smooth, never overshoots")]):
        ws.append(list(row))
    _style_header(ws)
    _widths(ws, [14, 12, 60])
    _note(ws, """
Optional. Default is linear for everything except log-scaled densities.
pchip is smooth and monotonic between anchors -- it never overshoots, unlike a cubic spline.
""")

    # ---- sweep ---------------------------------------------------------
    ws = wb.create_sheet("sweep")
    ws.append(["parameter", "layer", "mode", "values", "note"])
    for row in ex.get("sweep", [
            ("composition", "", "absolute", "0.20:0.36:0.01", "the composition grid"),
            ("NA", "", "absolute", "log:1e15:1e17:3", "acceptor density, cm^-3"),
            ("Rs", "", "absolute", "0, 2, 5, 8, 12", "free -- computed, not simulated")]):
        ws.append(list(row))
    _style_header(ws)
    _widths(ws, [16, 16, 12, 30, 50])
    names = sorted({p.name for p in _P}) + ["composition"]
    dv = DataValidation(type="list", formula1='"' + ",".join(names) + '"',
                        allow_blank=True, showErrorMessage=True,
                        errorTitle="unknown parameter",
                        error="Pick a parameter from the list; see the "
                              "'reference' sheet for what each one means.")
    ws.add_data_validation(dv)
    dv.add("A2:A200")
    dm = DataValidation(type="list", formula1='"absolute,offset,factor"',
                        allow_blank=True)
    ws.add_data_validation(dm)
    dm.add("C2:C200")
    if layers:
        dl = DataValidation(type="list", formula1='"' + ",".join(layers) + '"',
                            allow_blank=True)
        ws.add_data_validation(dl)
        dl.add("B2:B200")
    _note(ws, """
One row per swept parameter. Every combination is simulated (a full factorial).
values: '1e15, 1e16'  |  '20:36:1' (start:stop:step, inclusive)  |  'lin:1:2:5'  |  'log:1e14:1e18:5'
mode: absolute = the values themselves | offset = added to the interpolated anchor value | factor = multiplies it.
offset/factor only apply to material properties (Eg, chi, eps, ...) -- use them to sweep around the anchors.
layer: blank = the absorber. For Nt_interface give the interface as 'LayerA/LayerB'.
Rs and Rsh cost nothing: they are applied to the finished IV curve, exactly, after SCAPS runs.
""")

    # ---- layers --------------------------------------------------------
    ws = wb.create_sheet("layers")
    ws.append(["layer", "parameter", "value", "note"])
    for row in ex.get("layers", []):
        ws.append(list(row))
    _style_header(ws)
    _widths(ws, [18, 16, 16, 60])
    _note(ws, """
Optional fixed changes to ANY layer in the stack, applied to every generated .def.
parameter 'absorption' with value 'model' or a filename switches that layer's absorption source.
Check an absorption file before using it: scapsml inspect-abs FILE --eg GAP --window
""")

    # ---- experiment ----------------------------------------------------
    ws = wb.create_sheet("experiment")
    cols = ex.get("experiment_columns",
                  ["composition", "Eg", "Voc", "Jsc", "FF", "PCE", "source"])
    ws.append(cols)
    for row in ex.get("experiment", []):
        ws.append([row.get(c) for c in cols])
    _style_header(ws)
    _widths(ws, [14, 10, 10, 10, 10, 10, 60])
    _note(ws, """
Optional measurements. 'scapsml validate' compares the model against every filled cell.
Eg is checked against the anchor interpolation; Voc/Jsc/FF/PCE against simulated results.
Units: V, mA/cm^2, FF as a fraction (0-1), PCE in percent.
""")

    # ---- reference -----------------------------------------------------
    ws = wb.create_sheet("reference")
    ws.append(["parameter", "where", "unit", "description"])
    for p in _P:
        ws.append([p.name, p.target, p.unit, p.doc])
    _style_header(ws)
    _widths(ws, [16, 9, 12, 70])
    _note(ws, """
def    = written into the .def. Each distinct value needs its own definition file.
script = set from the SCAPS script. Costs one simulation per value, no new files.
post   = applied to the finished IV curve after SCAPS runs. Costs nothing.
""")

    wb.save(path)
    return Path(path)


def baseline_from_def(base_def, absorber=None):
    """
    A working starting point read back out of a .def.

    The absorber's material properties are already in the file, in SI. They
    are read, converted to the workbook's units, and written as a single
    anchor row, with a one-point sweep. So `scapsml init --def cell.def`
    followed by `scapsml check` passes immediately and `generate` reproduces
    the original cell -- a baseline to edit, rather than an empty form that
    fails its first check.
    """
    from .defio import DefFile, DefError
    from .registry import DEF, _P

    d = DefFile.load(base_def)
    layers = d.layers
    absorber = absorber or _guess_absorber(d)
    row = {"composition": 0.0, "source": f"read from {Path(base_def).name}"}
    cols = ["composition"]
    for p in _P:
        if p.target != DEF or not p.field or p.name == "sigma_bulk":
            continue
        try:
            v = d.get(absorber, p.field)
        except DefError:
            continue
        if isinstance(v, float):
            row[p.name] = round(v / p.to_si, 10) if p.to_si != 1 else v
            cols.append(p.name)
    cols.append("source")
    return {
        "project": {"name": Path(base_def).stem, "base_def": Path(base_def).name,
                    "absorber": absorber},
        "anchor_columns": cols,
        "anchors": [row],
        "interpolation": [],
        "sweep": [("composition", "", "absolute", "0",
                   "single material -- add anchors and widen this for a series"),
                  ("Rs", "", "absolute", "0, 2, 5",
                   "free: applied to the finished IV curve")],
    }


def _guess_absorber(d):
    """
    Identify the absorber from evidence in the .def itself.

    Bandgap alone is unreliable: a wide-gap absorber such as BaTiO3 (3.2 eV)
    can be wider than its own hole transport layer (spiro, 2.9 eV), so
    "narrowest gap wins" picks the HTL. The file carries better signals --
    the absorber is normally the layer with a measured absorption spectrum
    and a bulk defect block, while transport layers use SCAPS's analytical
    absorption and no bulk traps. Scored in that order, with bandgap only as
    a tie-break. The guess is written into project!absorber and printed by
    `scapsml check`, so it is visible and a one-cell fix if wrong.
    """
    def score(b):
        n = b.name
        s = 0.0
        if d.absorption_source(n).startswith("file:"):
            s += 4
        if "srhrecombination" in b.subblocks:
            s += 2
        try:
            eg = d.get(n, "Eg")
            s += 1.0 / (1.0 + eg) if isinstance(eg, float) else 0
        except Exception:
            pass
        return s
    layers = [b for b in d.blocks if b.kind == "layer"]
    return max(layers, key=score).name if layers else "Absorber"


README = """
scapsml project workbook

This workbook is the only file you edit. The code reads it, builds every SCAPS definition file and
script, runs the sweep, and assembles an ML-ready dataset. You should never need to open a .py file.

SHEETS
  project        settings: which .def to start from, which layer is the absorber, where files go
  anchors        material properties at known compositions -- interpolated in between
  interpolation  optional: how each property is interpolated (linear, log, pchip)
  sweep          which parameters to vary, and over what values
  layers         optional: fixed changes to any other layer (ETL, HTL, contacts...)
  experiment     optional: measurements to validate the model against
  reference      every valid parameter name, its unit, and where it goes

WORKFLOW
  scapsml check    project.xlsx     validate the workbook and the .def before anything runs
  scapsml generate project.xlsx     write defs, absorption files, scripts and the manifest
  scapsml run      project.xlsx     drive SCAPS (Windows); resumable, Ctrl-C safe
  scapsml status   project.xlsx     how much is done
  scapsml collect  project.xlsx     parse results into a dataset
  scapsml validate project.xlsx     compare against the experiment sheet
  scapsml ml       project.xlsx     train models, SHAP, inverse design

THREE THINGS THAT MATTER
  1. Anchor to measurements. A composition grid interpolated only from end-member DFT values can be
     badly wrong in the middle -- one study found 0.46 eV of error exactly where data existed.
  2. Check absorption files before trusting them. Library files are frequently mislabelled or
     carry an infrared free-carrier tail that inflates Jsc. Use 'scapsml inspect-abs'.
  3. Keep 'pin_defects_midgap' on. It places every trap at midgap by construction, so a trap can
     never fall outside the band gap -- the failure that makes SCAPS silently reject a problem.
"""
