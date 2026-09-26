"""
Build project.xlsx for the CsPbI3 validation example.

A validation project reproduces ONE published device with the same numerical
setup used for a study, to show the machinery -- mesh, numerics, contact
model, sign conventions and this package's own code -- gives the right answer
for a cell whose answer is known.

    ITO (100 nm) / SnO2 (25) / CsPbI3 (350) / spiro-OMeTAD (170)
    flat-band back contact

Parameters: Rahman et al., ChemistrySelect 2026, Tables 1-2, replicating the
experimental cell of Wang et al.

    experiment (Wang)   Voc 1.097 V   Jsc 18.00 mA/cm2   FF 0.741   PCE 14.67 %
    reference SCAPS     Voc 1.093 V   Jsc 16.45 mA/cm2   FF 0.862   PCE 15.50 %

The absorber uses the RSC CsPbI3 absorption spectrum -- the only one of five
library files whose edge is consistent with Eg = 1.745 eV (edge 679 nm
against the 711 nm the gap implies). ITO, SnO2 and spiro use SCAPS's
analytical model: their library absorption files carry infrared free-carrier
absorption that pushed generation to 70 mA/cm2 when used.
"""
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
from scapsml.template import write_template

example = {
    "project": {"name": "cspbi3", "base_def": "base.def", "absorber": "CsPbI3",
                "composition_label": "(single material)", "work_dir": "work",
                "results_dir": "results", "iv_points": 150, "stop_margin": -0.10,
                "pin_defects_midgap": "no"},
    "anchor_columns": ["composition", "Eg", "chi", "eps", "Nc", "Nv", "mun",
                       "mup", "source"],
    "anchors": [{"composition": 0, "Eg": 1.745, "chi": 3.95, "eps": 6.0,
                 "Nc": 2.80e18, "Nv": 1.03e19, "mun": 109.31, "mup": 72.90,
                 "source": "Rahman et al. 2026, Table 1"}],
    "interpolation": [],
    "sweep": [("composition", "", "absolute", "0", "one device"),
              ("Rs", "", "absolute", "0, 2, 5",
               "Rs=0 is the comparison; the rest show the sensitivity")],
    "experiment_columns": ["composition", "Voc", "Jsc", "FF", "PCE", "source"],
    "experiment": [
        {"composition": 0, "Voc": 1.097, "Jsc": 18.00, "FF": 0.741, "PCE": 14.67,
         "source": "experiment, Wang et al."},
        {"composition": 0, "Voc": 1.093, "Jsc": 16.45, "FF": 0.8615, "PCE": 15.50,
         "source": "reference SCAPS, Rahman et al."}],
}

if __name__ == "__main__":
    print(f"wrote {write_template(HERE / 'project.xlsx', base_def=HERE / 'base.def', example=example)}")
