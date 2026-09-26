"""
bands: catching a device that cannot extract carriers, before simulating it.

The BaTiO3 example once shipped with FTO/TiO2/BaTiO3/spiro while the absorber
sat at chi 4.95 eV and Ev 6.32 eV -- a +0.75 eV electron spike and a +1.22 eV
hole barrier. Every run failed, slowly, and nothing in the pipeline said why
until an hour of simulation had been spent.
"""
from pathlib import Path

import pytest

from scapsml import workbook
from scapsml.bands import SPIKE_FAIL, SPIKE_WARN, barriers, verdict
from scapsml.defio import DefFile
from scapsml.design import plan
from scapsml.generate import build_def

FIX = Path(__file__).parent / "fixtures"
EX = Path(__file__).parents[1] / "examples"


class TestBarriers:
    @pytest.fixture
    def d(self):
        return DefFile.load(FIX / "batio3_base.def")

    def test_identifies_the_neighbouring_layers(self, d):
        b = barriers(d, "BaTiO3")
        assert b["etl"] == "TiO2" and b["htl"] == "Spiro-OmeTAD"

    def test_electron_spike_sign(self, d):
        """Positive means the absorber's conduction band is BELOW the ETL's."""
        d.set("BaTiO3", "chi", 5.0)
        d.set("TiO2", "chi", 4.2)
        assert barriers(d, "BaTiO3")["electron"] == pytest.approx(0.8)

    def test_hole_barrier_sign(self, d):
        d.set("BaTiO3", "chi", 4.95)
        d.set("BaTiO3", "Eg", 1.37)          # Ev 6.32
        d.set("Spiro-OmeTAD", "chi", 2.20)
        d.set("Spiro-OmeTAD", "Eg", 2.90)    # Ev 5.10
        assert barriers(d, "BaTiO3")["hole"] == pytest.approx(1.22)

    def test_the_configuration_that_failed_is_reported_as_fail(self, d):
        d.set("BaTiO3", "chi", 4.946)
        d.set("BaTiO3", "Eg", 1.371)
        lvl, msg = verdict(barriers(d, "BaTiO3"))
        assert lvl == "fail" and "cannot extract" in msg

    def test_matched_contacts_pass(self, d):
        d.set("BaTiO3", "chi", 4.946)
        d.set("BaTiO3", "Eg", 1.371)
        d.set("TiO2", "chi", 5.10)                    # no spike
        d.set("Spiro-OmeTAD", "chi", 3.70)            # Ev 6.60
        assert verdict(barriers(d, "BaTiO3"))[0] == "ok"

    def test_a_cliff_is_not_a_failure(self, d):
        """A negative offset costs voltage but still extracts."""
        d.set("BaTiO3", "chi", 4.0)
        d.set("BaTiO3", "Eg", 1.5)                # Ev 5.5
        d.set("TiO2", "chi", 4.6)                 # conduction band above: cliff
        d.set("Spiro-OmeTAD", "chi", 2.8)         # Ev 5.7, above the absorber
        b = barriers(d, "BaTiO3")
        assert b["electron"] < 0 and b["hole"] < 0
        assert verdict(b)[0] == "ok"

    def test_thresholds_are_ordered(self):
        assert 0 < SPIKE_WARN < SPIKE_FAIL


class TestShippedExamples:
    """Neither example may ship a stack that cannot extract carriers."""

    @pytest.mark.parametrize("name", ["batio3xsx", "cspbi3_validation"])
    def test_no_design_is_blocked(self, name):
        p = workbook.load(EX / name / "project.xlsx")
        base = DefFile.load(p.base_def)
        bad = []
        for dz in plan(p).designs:
            lvl, msg = verdict(barriers(build_def(p, base, dz), p.absorber))
            if lvl == "fail":
                bad.append((dz.composition, dz.varied, msg))
        assert not bad, f"{len(bad)} blocked designs, e.g. {bad[:2]}"

    def test_batio3_example_stays_a_few_hours(self):
        """An example nobody can afford to run is not an example."""
        s = plan(workbook.load(EX / "batio3xsx" / "project.xlsx")).summary()
        assert s["simulations"] <= 4000, s
