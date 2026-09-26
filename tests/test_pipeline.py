"""
End to end on the shipped examples, against experimental data.

  batio3xsx         bandgaps anchored to measured BaTi(O1-xSx)3 thin films
  cspbi3_validation a published device, with the REAL SCAPS output of
                    simulating it, compared against the measured cell
"""
import csv
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scapsml import workbook
from scapsml.absorption import measure_onset, read_spectrum
from scapsml.dataset import collect
from scapsml.defio import DefFile
from scapsml.design import plan
from scapsml.generate import generate
from scapsml.validate import validate
from scapsml._io import read_rows, read_json, write_json

EX = Path(__file__).parents[1] / "examples"


def _copy(name, tmp_path):
    dst = tmp_path / name
    shutil.copytree(EX / name, dst, ignore=shutil.ignore_patterns("work", "results"))
    return dst


# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def batio3(tmp_path_factory):
    d = _copy("batio3xsx", tmp_path_factory.mktemp("b"))
    p = workbook.load(d / "project.xlsx")
    pl, work = generate(p, verbose=False)
    return p, pl, work


class TestBaTiO3Generation:
    def test_counts(self, batio3):
        p, pl, work = batio3
        assert len(list((work / "defs").glob("*.def"))) == len(pl.designs)
        rows = list(read_rows(work / "manifest.csv"))
        assert len(rows) == pl.n_sims

    def test_uniform_composition_grid(self, batio3):
        comps = sorted({d.composition for d in batio3[1].designs})
        assert len({round(b - a, 9) for a, b in zip(comps, comps[1:])}) == 1

    def test_every_def_matches_its_manifest_row(self, batio3):
        """What the manifest records is what SCAPS will actually read."""
        p, pl, work = batio3
        rows = {r["def_file"]: r for r in read_rows(work / "manifest.csv")}
        for f, r in list(rows.items())[::7]:
            d = DefFile.load(work / "defs" / f)
            for k in ("Eg", "chi", "eps"):
                assert d.get(p.absorber, k) == pytest.approx(float(r[k]), rel=1e-5), (f, k)

    def test_absorption_edge_tracks_the_bandgap(self, batio3):
        p, pl, work = batio3
        for dz in pl.designs[::23]:
            e, a = read_spectrum(work / "absorption" / dz.abs_name)
            edge = measure_onset(e, a, threshold_cm=1e-3)
            assert edge == pytest.approx(dz.mat("Eg"), abs=0.01), dz.abs_name

    def test_no_subgap_absorption(self, batio3):
        p, pl, work = batio3
        for dz in pl.designs[::23]:
            e, a = read_spectrum(work / "absorption" / dz.abs_name)
            assert (a[e < dz.mat("Eg") - 1e-3] == 0).all()

    def test_every_trap_pinned_midgap(self, batio3):
        """
        The failure that emptied 2178 of 4422 runs in one campaign: a trap
        placed outside the gap. Pinned by construction, it cannot happen.
        """
        p, pl, work = batio3
        for f in list((work / "defs").glob("*.def"))[::31]:
            t = DefFile.load(f).text()
            assert set(re.findall(r"Reference for defect energy\s*:\s*(\d+)", t)) <= {"1", "9"}
            assert all(float(x) == 0 for x in re.findall(r"^\s*Et\s*:\s*(\S+)", t, re.M))

    def test_sampling_columns_and_resolved_values_both_recorded(self, batio3):
        rows = list(read_rows(batio3[2] / "manifest.csv"))
        for c in ("Eg", "chi", "eps", "Eg_offset", "chi_offset", "eps_factor"):
            assert c in rows[0]


class TestBaTiO3AgainstMeasuredBandgaps:
    def test_measured_points_reproduced(self, batio3):
        rep = validate(batio3[0], verbose=False)
        assert all(r["ok"] for r in rep["material"])

    def test_leave_one_out_predicts_held_out_measurements(self, batio3):
        """
        The measured points are also anchors, so reproducing them proves
        nothing. Leave-one-out asks whether the rest of the data predicts each
        one -- the real test of the interpolation.
        """
        rep = validate(batio3[0], verbose=False)
        loo = rep["leave_one_out"]
        assert len(loo) == 3
        assert max(abs(x) for x in loo) < 0.05


# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def cspbi3(tmp_path_factory):
    d = _copy("cspbi3_validation", tmp_path_factory.mktemp("c"))
    p = workbook.load(d / "project.xlsx")
    pl, work = generate(p, verbose=False)
    row = read_rows(work / "manifest.csv")[0]
    res = d / "results"
    res.mkdir()
    shutil.copy(d / "reference_run.iv", res / row["iv_file"])
    collect(p, verbose=False)
    return p, work


class TestCsPbI3AgainstPublishedDevice:
    def test_generated_def_matches_the_published_parameters(self, cspbi3):
        p, work = cspbi3
        d = DefFile.load(next((work / "defs").glob("*.def")))
        assert d.get("CsPbI3", "Eg") == pytest.approx(1.745)
        assert d.get("CsPbI3", "chi") == pytest.approx(3.95)
        assert d.get("CsPbI3", "Nc") == pytest.approx(2.80e24)       # cm-3 -> m-3
        assert d.get("CsPbI3", "mu_n") == pytest.approx(109.31e-4)   # cm2/Vs -> m2/Vs

    def test_absorber_keeps_its_validated_spectrum(self, cspbi3):
        d = DefFile.load(next((cspbi3[1] / "defs").glob("*.def")))
        assert d.absorption_source("CsPbI3") == "file:CsPbI3_RSC.abs"

    def test_real_scaps_result_is_collected(self, cspbi3):
        rows = list(read_rows(cspbi3[1] / "dataset.csv"))
        r0 = next(r for r in rows if float(r["Rs"]) == 0)
        assert r0["status"] == "OK"
        assert float(r0["Voc"]) == pytest.approx(1.2910, abs=1e-3)
        assert float(r0["Jsc"]) == pytest.approx(16.2666, abs=1e-3)
        assert float(r0["FF"]) == pytest.approx(0.8688, abs=1e-3)

    def test_matches_the_reference_simulation_in_jsc_and_ff(self, cspbi3):
        """
        Against the published SCAPS result the setup reproduces Jsc to 1.1%
        and FF to 0.8%. Voc differs because the source quotes interface
        defect density in cm-3 where SCAPS needs cm-2.
        """
        rep = validate(cspbi3[0], verbose=False)
        ref = next(e for e in rep["device"] if "reference" in e["source"])
        assert abs(ref["metrics"]["Jsc"]["delta"]) / 16.45 < 0.02
        assert abs(ref["metrics"]["FF"]["delta"]) / 0.8615 < 0.02

    def test_optimistic_relative_to_experiment_as_a_1d_model_should_be(self, cspbi3):
        rep = validate(cspbi3[0], verbose=False)
        exp = next(e for e in rep["device"] if "experiment" in e["source"])
        assert exp["metrics"]["FF"]["delta"] > 0
        assert exp["metrics"]["Voc"]["delta"] > 0

    def test_series_resistance_reduces_pce_on_the_real_curve(self, cspbi3):
        rows = list(read_rows(cspbi3[1] / "dataset.csv"))
        pce = {float(r["Rs"]): float(r["PCE"]) for r in rows if r["status"] == "OK"}
        assert pce[0] > pce[2] > pce[5]


# --------------------------------------------------------------------------
class TestCLI:
    def _run(self, *args, cwd=None):
        return subprocess.run([sys.executable, "-m", "scapsml.cli", *args],
                              capture_output=True, text=True, cwd=cwd)

    def test_params(self):
        r = self._run("params")
        assert r.returncode == 0 and "Nt_interface" in r.stdout

    def test_init_then_check_flags_the_empty_template(self, tmp_path):
        shutil.copy(EX / "batio3xsx" / "base.def", tmp_path / "base.def")
        r = self._run("init", str(tmp_path / "new.xlsx"), "--def",
                      str(tmp_path / "base.def"))
        assert r.returncode == 0 and (tmp_path / "new.xlsx").is_file()

    def test_check_passes_on_the_example(self, tmp_path):
        d = _copy("batio3xsx", tmp_path)
        r = self._run("check", str(d / "project.xlsx"))
        assert r.returncode == 0, r.stdout + r.stderr
        assert "READY" in r.stdout

    def test_check_reports_workbook_errors_cleanly(self, tmp_path):
        r = self._run("check", str(tmp_path / "missing.xlsx"))
        assert r.returncode == 2 and "not found" in r.stderr


class TestInitFromDef:
    """
    `init --def` must give a WORKING baseline read out of the .def, so a new
    user's first check passes and generate reproduces the original cell.
    """

    @pytest.mark.parametrize("fixture,absorber", [
        ("batio3_base.def", "BaTiO3"), ("cspbi3_base.def", "CsPbI3")])
    def test_init_check_generate_reproduces_the_cell(self, tmp_path, fixture, absorber):
        from scapsml.template import write_template
        src = Path(__file__).parent / "fixtures" / fixture
        shutil.copy(src, tmp_path / "cell.def")
        write_template(tmp_path / "cell.xlsx", base_def=tmp_path / "cell.def")

        p = workbook.load(tmp_path / "cell.xlsx")          # validates
        assert p.absorber == absorber, "absorber should be the narrowest-gap layer"
        pl, work = generate(p, verbose=False)
        assert len(pl.designs) == 1

        orig, gen = DefFile.load(src), DefFile.load(next((work / "defs").glob("*.def")))
        for field in ("Eg", "chi", "eps", "Nc", "Nv", "mu_n", "mu_p"):
            assert gen.get(absorber, field) == pytest.approx(
                orig.get(absorber, field), rel=1e-6), field


class TestCollectOnDescendingOutput:
    """collect must give the right numbers from the real descending file."""

    def test_collected_values(self, tmp_path):
        d = _copy("cspbi3_validation", tmp_path)
        p = workbook.load(d / "project.xlsx")
        _, work = generate(p, verbose=False)
        row = read_rows(work / "manifest.csv")[0]
        (d / "results").mkdir()
        shutil.copy(Path(__file__).parent / "fixtures" / "descending_sweep.iv",
                    d / "results" / row["iv_file"])
        _, counts = collect(p, verbose=False)
        rows = read_rows(work / "dataset.csv")
        r0 = next(r for r in rows if float(r["Rs"]) == 0)
        assert r0["status"] == "OK"
        assert float(r0["Jsc"]) == pytest.approx(16.395, abs=1e-2)
        assert float(r0["PCE"]) == pytest.approx(18.39, abs=0.05)
        assert "SUSPECT" not in counts
        pce = {float(r["Rs"]): float(r["PCE"]) for r in rows}
        assert pce[0] > pce[2] > pce[5]
