"""ML on real SCAPS output from an earlier campaign, and runner bookkeeping."""
import csv
import shutil
from pathlib import Path

import numpy as np
import pytest

from scapsml import ml, workbook
from scapsml.generate import generate
from scapsml import runner
from scapsml._io import read_rows, read_json, write_json

FIX = Path(__file__).parent / "fixtures"
EX = Path(__file__).parents[1] / "examples"


@pytest.fixture(scope="module")
def rows():
    return [r for r in read_rows(FIX / "real_dataset.csv")
            if r["status"] == "OK"]


class TestFeatureDiscovery:
    """
    The fixture was written by an OLDER pipeline with different column names
    (S_pct, htl_Ev, eg_offset...). Feature discovery must not depend on names.
    """

    def test_finds_features_without_a_list(self, rows):
        allf, keep, dropped = ml.select_features(rows)
        assert "S_pct" in allf and "Nt_bulk" in allf

    def test_targets_are_never_features(self, rows):
        allf, _, _ = ml.select_features(rows)
        assert not set(allf) & {"PCE", "Voc", "Jsc", "FF", "status"}

    def test_sampling_columns_are_excluded(self, rows):
        allf, _, dropped = ml.select_features(rows)
        for c in allf:
            assert not c.endswith(("_offset", "_factor"))

    def test_exact_functions_of_composition_are_pruned(self, rows):
        """Nc, Nv, mobilities are functions of composition alone here."""
        _, keep, dropped = ml.select_features(rows)
        for c in ("Nc", "Nv", "mun", "mup"):
            if c in dropped:
                assert "|r|" in dropped[c] or "constant" in dropped[c]
        assert "S_pct" in keep

    def test_log_columns_are_logged(self, rows):
        X = ml.matrix(rows[:20], ["Nt_bulk"])
        assert np.allclose(X[:, 0], np.log10([float(r["Nt_bulk"]) for r in rows[:20]]))


class TestModelsOnRealData:
    def test_full_run_produces_outputs(self, tmp_path):
        table = ml.run(FIX / "real_dataset.csv", tmp_path, kfold=3, candidates=3)
        assert (tmp_path / "metrics.json").is_file()
        assert (tmp_path / "candidates.csv").is_file()
        assert (tmp_path / "model_PCE.joblib").is_file()
        # trees must beat a linear model on this non-linear physics
        assert table["random forest"]["r2_kfold"] > table["linear regression"]["r2_kfold"]
        assert table["random forest"]["r2_kfold"] > 0.8

    def test_zoo_has_the_reference_algorithms(self):
        z = ml.model_zoo()
        for k in ("linear regression", "random forest", "SVR", "MLP"):
            assert k in z


class TestRunnerBookkeeping:
    """Everything the runner decides without touching the GUI."""

    @pytest.fixture
    def proj(self, tmp_path):
        d = tmp_path / "cs"
        shutil.copytree(EX / "cspbi3_validation", d,
                        ignore=shutil.ignore_patterns("work", "results"))
        p = workbook.load(d / "project.xlsx")
        generate(p, verbose=False)
        return p

    def test_expected_files_match_the_manifest(self, proj):
        rows = read_rows(proj.resolve("work_dir") / "manifest.csv")
        c = runner.compositions(proj)[0]
        assert runner.expected(proj, c) == [r["iv_file"] for r in rows]

    def test_progress_counts_existing_files(self, proj):
        c = runner.compositions(proj)[0]
        assert runner.progress(proj, c)[0] == 0
        res = proj.resolve("results_dir", "results")
        res.mkdir(parents=True, exist_ok=True)
        for n in runner.expected(proj, c):
            (res / n).write_text("x" * 1000)
        d, t, e = runner.progress(proj, c)
        assert d == t and e == 0

    def test_header_only_files_count_as_done(self, proj):
        """Rerunning a rejected problem cannot change it -- never loop on it."""
        c = runner.compositions(proj)[0]
        res = proj.resolve("results_dir", "results")
        res.mkdir(parents=True, exist_ok=True)
        for n in runner.expected(proj, c):
            (res / n).write_text("header\n" * 4)
        d, t, e = runner.progress(proj, c)
        assert d == t and e == t

    def test_status_names_the_next_step(self, proj):
        out = []
        todo = runner.status(proj, out=out.append)
        assert todo and any("next: scapsml run" in l for l in out)

    def test_settings_read_button_positions_from_the_workbook(self, proj):
        cfg = runner.Settings(proj)
        assert len(cfg.btn_setup) == 2 and all(isinstance(v, int) for v in cfg.btn_setup)

    def test_install_reports_uac_with_the_fix(self, proj, tmp_path, monkeypatch):
        cfg = runner.Settings(proj)
        locked = tmp_path / "locked"
        (locked / "def").mkdir(parents=True)
        (locked / "absorption").mkdir()
        cfg.scaps_dir = locked
        def deny(*a, **k):
            raise PermissionError("denied")
        monkeypatch.setattr(runner.shutil, "copy2", deny)
        with pytest.raises(PermissionError, match="icacls"):
            runner.install(proj, runner.compositions(proj)[0], cfg)

    def test_install_copies_defs(self, proj, tmp_path):
        cfg = runner.Settings(proj)
        dst = tmp_path / "scaps"
        (dst / "def").mkdir(parents=True)
        (dst / "absorption").mkdir()
        cfg.scaps_dir = dst
        n = runner.install(proj, runner.compositions(proj)[0], cfg)
        assert n >= 1 and list((dst / "def").glob("*.def"))


def test_importing_the_package_does_not_silence_warnings():
    """A library must never change the process-wide warning filters."""
    import importlib
    import warnings
    before = list(warnings.filters)
    import scapsml.ml
    importlib.reload(scapsml.ml)
    assert warnings.filters == before


def test_shap_import_is_clean_in_a_fresh_interpreter(tmp_path):
    """
    SHAP warns at import time on recent matplotlib. Within one pytest session
    the module is usually already cached, so only a FRESH interpreter proves
    the import is covered -- which is exactly the case that failed in a clean
    install while passing locally.
    """
    import subprocess
    import sys
    code = ("import warnings; warnings.simplefilter('error'); "
            "from scapsml.ml import _third_party_quiet\n"
            "with _third_party_quiet():\n"
            "    import shap\n"
            "print('ok')")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    if "No module named 'shap'" in r.stderr:
        pytest.skip("shap not installed")
    assert r.returncode == 0 and "ok" in r.stdout, r.stderr[-800:]
