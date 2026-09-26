"""
Build project.xlsx for the BaTi(O1-xSx)3 example.

Run once to (re)create the workbook; after that, edit project.xlsx directly.
This script exists so the example is reproducible and reviewable, not because
users need to write Python.

THE DATA
--------
Bandgaps are anchored to direct measurements on BaTi(O1-xSx)3 thin films:
    x = 0.243 -> 1.51 eV,  0.253 -> 1.45 eV,  0.287 -> 1.35 eV
(Rev. Mex. Fis., BaTi(O1-xSx)3 chalcogenide perovskite thin films with band
gap ideal for solar cell applications). The films are hexagonal at these
compositions, so the study is confined to x = 0.20-0.36 and the x = 0 and
x = 1 rows are interpolation endpoints only.

Ionisation potentials partition the gap change between the band edges (48%
valence, 52% conduction), anchored at BaTiO3 (O 2p, 7.20 eV) and a BaZrS3-
like sulfide valence band (5.80 eV). chi is derived as IP - Eg.

Reference absorption spectra at x = 0, 1/3, 2/3, 1 are digitised from a
published figure. CITE THE ORIGINAL SOURCE in any publication.
"""
import math
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
from scapsml.template import write_template

IP_O, IP_S, EG_O, EG_S = 7.20, 5.80, 3.20, 0.30
SHARE = (IP_O - IP_S) / (EG_O - EG_S)


def ip(eg):
    return round(IP_O - SHARE * (EG_O - eg), 4)


def logi(a, b, f):
    return 10 ** (math.log10(a) + (math.log10(b) - math.log10(a)) * f)


# (x, Eg, source)
EG = [(0.00, 3.20, "BaTiO3 -- different phase, endpoint only"),
      (0.20, 1.67, "extrapolated from measured trend"),
      (0.243, 1.51, "MEASURED, thin film"),
      (0.253, 1.45, "MEASURED, thin film"),
      (0.287, 1.35, "MEASURED, thin film"),
      (0.36, 1.09, "extrapolated from measured trend"),
      (1.00, 0.30, "BaTiS3 -- hexagonal P63cm, endpoint only")]

anchors = []
for x, eg, src in EG:
    anchors.append({
        "composition": x, "Eg": eg, "IP": ip(eg),
        "eps": round(logi(2500, 15, x), 3),
        "Nc": logi(2.2e18, 2.5e19, x), "Nv": logi(1.8e18, 3.3e19, x),
        "mun": round(20 + (500 - 20) * x, 3), "mup": round(10 + (100 - 10) * x, 3),
        "source": src})
# spectrum anchors (absorption only)
spectra = {0.0: "absorption_S00.abs", 1 / 3: "absorption_S11.abs",
           2 / 3: "absorption_S22.abs", 1.0: "absorption_S33.abs"}
for x, f in spectra.items():
    row = next((a for a in anchors if abs(a["composition"] - x) < 1e-9), None)
    if row is None:
        row = {"composition": round(x, 4), "source": "reference spectrum only"}
        anchors.append(row)
    row["abs_file"] = f
anchors.sort(key=lambda a: a["composition"])

example = {
    "project": {
        "name": "batio3xsx", "base_def": "base.def", "absorber": "BaTiO3",
        "composition_label": "x (S fraction)", "work_dir": "work",
        "results_dir": "results", "spectra_dir": "spectra",
        "iv_points": 150, "stop_margin": 0.20, "pin_defects_midgap": "yes"},
    "anchor_columns": ["composition", "Eg", "IP", "eps", "Nc", "Nv", "mun",
                       "mup", "abs_file", "source"],
    "anchors": anchors,
    "interpolation": [("Eg", "pchip", "smooth and monotonic through the data"),
                      ("IP", "pchip", ""), ("Nc", "log", ""), ("Nv", "log", "")],
    # THE TRANSPORT LAYERS ARE THE STUDY. With the corrected affinity the
    # absorber sits at chi = 4.79-5.09 eV and Ev = 6.18-6.46 eV across this
    # window, so the stack the base .def ships with -- TiO2 (chi 4.20) and
    # spiro (Ev 5.10) -- blocks BOTH carriers: a +0.75 eV electron spike and a
    # +1.22 eV hole barrier. Every one of those runs fails, slowly.
    #
    # Common transport layers are simply too shallow for this absorber, which
    # is the finding. So the ETL affinity and the HTL valence band are SWEPT,
    # and the result is a map of which contacts could work. Values beyond real
    # materials are a design specification -- say so in the methods:
    #   ETL chi   4.2 TiO2/MoS2 | 4.5 WS2 | 4.8, 5.1 specification
    #   HTL Ev    5.1 spiro | 5.4 NiO | 5.8, 6.2 specification (MoO3 ~6.7)
    "layers": [("TiO2", "chi", 5.10, "baseline ETL matched to the absorber"),
               ("Spiro-OmeTAD", "chi", 3.70,
                "Ev = chi + Eg = 3.70 + 2.90 = 6.60, matched to the absorber")],
    "sweep": [
        # 0.02 steps keep the example to a few hours. Change to 0.01 for the
        # full grid -- one cell, and twice the runtime.
        ("composition", "", "absolute", "0.20:0.36:0.02",
         "uniform grid over the window where the material has been made"),
        ("Eg", "", "offset", "-0.1, 0, 0.1",
         "breaks the Eg-composition collinearity; bandgap sensitivity"),
        ("chi", "", "offset", "-0.1, 0, 0.1",
         "affinity is the least certain input -- sweep it, do not assume it"),
        # Permittivity has no measurement for this system. Set "0.5, 1, 2" to
        # measure the sensitivity; that triples the run.
        ("eps", "", "factor", "1", "permittivity has no measurement"),
        ("NA", "", "absolute", "log:1e15:1e17:3", "acceptor density, cm^-3"),
        # The back contact must be at least as deep as the HTL valence band,
        # or it becomes a third barrier. With the HTL at Ev 6.3-6.6 eV the
        # usual 5.1-5.4 eV metals are far too shallow. No elemental metal is
        # this deep (Pt is 5.65): treat these as a specification, as with the
        # HTL itself.
        ("BCM", "", "absolute", "6.3, 6.6", "back-contact work function, eV"),
        ("chi", "TiO2", "absolute", "4.8, 5.1, 5.4",
         "ETL electron affinity -- the binding constraint (4.8 is already "
         "deeper than any common ETL)"),
        ("chi", "Spiro-OmeTAD", "absolute", "3.4, 3.7",
         "HTL: Ev = chi + 2.90, so 6.30 and 6.60 eV"),
        ("Rs", "", "absolute", "0, 2, 5, 8, 12",
         "series resistance -- free, applied analytically after SCAPS runs")],
    "experiment_columns": ["composition", "Eg", "Voc", "Jsc", "FF", "PCE", "source"],
    "experiment": [
        {"composition": 0.243, "Eg": 1.51, "source": "BaTi(O1-xSx)3 thin film"},
        {"composition": 0.253, "Eg": 1.45, "source": "BaTi(O1-xSx)3 thin film"},
        {"composition": 0.287, "Eg": 1.35, "source": "BaTi(O1-xSx)3 thin film"}],
}

if __name__ == "__main__":
    out = write_template(HERE / "project.xlsx", base_def=HERE / "base.def",
                         example=example)
    print(f"wrote {out}")
