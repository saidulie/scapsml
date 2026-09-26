"""Tests for the lumped series/shunt resistance transformation."""
import os
import sys

import numpy as np
import pytest


from scapsml.series import apply_rs, iv_metrics, metrics_vs_rs


def ideal_diode(jsc=25.0, j0=1e-12, n=1.0, vt=0.025852, npts=400, overshoot=1.06):
    """
    An analytic single-diode curve in the photocurrent-positive convention,
    swept to just past Voc the way SCAPS does with stopafterVoc.
    """
    voc = n * vt * np.log(jsc / (j0 * 1e3) + 1.0)
    v = np.linspace(0, voc * overshoot, npts)
    j = jsc - j0 * 1e3 * (np.exp(v / (n * vt)) - 1.0)     # mA/cm2
    return v, j


class TestApplyRs:
    def test_zero_rs_is_identity(self):
        v, j = ideal_diode()
        v2, j2 = apply_rs(v, j, rs=0.0)
        assert np.allclose(v, v2)
        assert np.allclose(j, j2)

    def test_voltage_shift_matches_ohms_law(self):
        """
        Series resistance DROPS voltage: V_terminal = V_junction - J*Rs.
        With the sign inverted the transformation adds power and the fill
        factor exceeds 1, which test_ff_below_unity catches independently.
        """
        v, j = ideal_diode()
        rs = 5.0
        v2, _ = apply_rs(v, j, rs=rs)
        assert np.allclose(v2 - v, -j * 1e-3 * rs)
        # Where the cell delivers current (J > 0) the terminal voltage is
        # lower than the junction voltage. Past Voc the current reverses and
        # the drop reverses with it, which is also correct.
        gen = j > 0
        assert (v2[gen] <= v[gen]).all()
        assert (v2[~gen] >= v[~gen]).all()

    def test_ff_never_exceeds_unity(self):
        """A physical guard: no passive resistance can create power."""
        v, j = ideal_diode()
        for rs in (0.0, 1.0, 5.0, 10.0, 20.0):
            ff = iv_metrics(*apply_rs(v, j, rs))["FF"]
            assert 0.0 < ff <= 1.0, (rs, ff)

    def test_voc_is_exactly_preserved(self):
        """At J = 0 there is no drop across Rs, so Voc cannot move at all."""
        v, j = ideal_diode()
        base = iv_metrics(v, j)
        for rs in (1.0, 5.0, 20.0, 50.0):
            m = iv_metrics(*apply_rs(v, j, rs))
            assert m["Voc"] == pytest.approx(base["Voc"], rel=1e-9)

    def test_jsc_is_preserved_at_moderate_rs(self):
        """
        At V_terminal = 0 the junction sits at V_j = J*Rs, forward biased by a
        small amount, so Jsc falls slightly. For Rs well below the cell's
        characteristic resistance Voc/Jsc (~25 ohm.cm2 here) the loss is
        negligible; by Rs = 20 it becomes visible, which is real physics.
        """
        v, j = ideal_diode()
        base = iv_metrics(v, j)["Jsc"]
        for rs in (1.0, 2.0, 5.0):
            assert iv_metrics(*apply_rs(v, j, rs))["Jsc"] == pytest.approx(base, rel=1e-4)
        assert iv_metrics(*apply_rs(v, j, 20.0))["Jsc"] == pytest.approx(base, rel=0.02)

    def test_ff_falls_monotonically_with_rs(self):
        v, j = ideal_diode()
        ffs = [iv_metrics(*apply_rs(v, j, rs))["FF"] for rs in (0, 1, 2, 5, 10, 20)]
        assert all(b < a for a, b in zip(ffs, ffs[1:])), ffs

    def test_pce_falls_monotonically_with_rs(self):
        v, j = ideal_diode()
        p = [iv_metrics(*apply_rs(v, j, rs))["PCE"] for rs in (0, 1, 2, 5, 10, 20)]
        assert all(b < a for a, b in zip(p, p[1:])), p

    def test_shunt_reduces_current_at_forward_bias(self):
        v, j = ideal_diode()
        _, j2 = apply_rs(v, j, rs=0.0, rsh=100.0)
        assert j2[0] == pytest.approx(j[0], abs=1e-9)      # V=0: no shunt loss
        assert j2[-1] < j[-1]                              # high V: leakage

    def test_infinite_shunt_is_identity(self):
        v, j = ideal_diode()
        _, j2 = apply_rs(v, j, rs=0.0, rsh=np.inf)
        assert np.allclose(j, j2)


class TestIVMetrics:
    def test_recovers_known_curve(self):
        v, j = ideal_diode(jsc=25.0)
        m = iv_metrics(v, j)
        assert m["Jsc"] == pytest.approx(25.0, rel=1e-6)
        assert 0.5 < m["Voc"] < 1.2
        assert 0.7 < m["FF"] < 0.92
        assert m["PCE"] == pytest.approx(m["Voc"] * m["Jsc"] * m["FF"], rel=1e-3)

    def test_no_crossing_gives_no_voc(self):
        v = np.linspace(0, 1.0, 50)
        j = np.full_like(v, 20.0)              # never reaches zero
        m = iv_metrics(v, j)
        assert m["Voc"] is None and m["FF"] is None and m["PCE"] is None
        assert m["Jsc"] == pytest.approx(20.0)

    def test_runaway_forward_bias_does_not_break_metrics(self):
        """
        A sweep that continues far past Voc reaches huge negative J. With Rs
        applied that becomes a huge negative terminal voltage and a spurious
        second V = 0 crossing. Metrics must be unaffected.
        """
        v = np.linspace(0, 1.2, 400)
        j = 25.0 - 1e-12 * 1e3 * (np.exp(v / 0.025852) - 1.0)
        short = ideal_diode(jsc=25.0)
        for rs in (0.0, 1.0, 5.0):
            a = iv_metrics(*apply_rs(v, j, rs))
            b = iv_metrics(*apply_rs(*short, rs))
            # tolerances reflect the different voltage grids (400 points over
            # 1.2 V against 400 over 0.66 V), not the transformation
            assert a["Voc"] == pytest.approx(b["Voc"], abs=2e-4)
            assert a["Jsc"] == pytest.approx(b["Jsc"], rel=1e-4)
            assert a["FF"] == pytest.approx(b["FF"], abs=2e-3)

    def test_pce_definition(self):
        v, j = ideal_diode()
        m = iv_metrics(v, j, p_in=100.0)
        pmax = max(vv * jj for vv, jj in zip(v, j) if 0 <= vv <= m["Voc"])
        assert m["PCE"] == pytest.approx(pmax, rel=1e-9)


class TestMetricsVsRs:
    def test_returns_entry_per_rs(self):
        v, j = ideal_diode()
        out = metrics_vs_rs(v, j, [0.0, 2.0, 5.0])
        assert set(out) == {0.0, 2.0, 5.0}
        assert out[0.0]["PCE"] > out[5.0]["PCE"]

    def test_matches_scaps_magnitude(self):
        """
        Sanity against the project's own numbers: the S=33 champion cell had
        Jsc 25.99, Voc 1.105, FF 0.779, PCE 22.35% at Rs = 0. A 5 ohm.cm2
        series resistance should cost a few points of FF, not collapse it.
        """
        v, j = ideal_diode(jsc=25.99, j0=3e-19, n=1.6)
        m0 = iv_metrics(v, j)
        m5 = iv_metrics(*apply_rs(v, j, 5.0))
        assert m0["FF"] > m5["FF"] > 0.5 * m0["FF"]
        assert m5["Jsc"] == pytest.approx(m0["Jsc"], rel=1e-3)
        assert m5["Voc"] == pytest.approx(m0["Voc"], rel=1e-9)


# ---------------------------------------------------------------------------
# Regression: real SCAPS output written in DESCENDING voltage order
# ---------------------------------------------------------------------------
import pathlib

_DESC = pathlib.Path(__file__).parent / "fixtures" / "descending_sweep.iv"


class TestDescendingSweep:
    """
    A sweep requested from -0.5 V to 1.85 V came back from SCAPS written
    1.85 V first. Read in file order, extraction found Voc as the "first"
    zero crossing, discarded the working curve, extrapolated Jsc from two
    points at 1.85 V to report 56.6 mA/cm2, and gave PCE 3.75 %. True values
    are Jsc 16.40 and PCE 18.39. The file is real SCAPS 3.3.12 output.
    """

    def test_file_really_is_descending(self):
        """Guard the fixture: if this ever fails the test below proves nothing."""
        vs = []
        for line in _DESC.read_bytes().decode("latin-1").splitlines():
            t = line.strip().split("\t")
            try:
                vs.append(float(t[0])) if len(t) >= 6 else None
            except ValueError:
                pass
        assert vs[0] > vs[-1] and vs[0] > 1.8 and vs[-1] < -0.4

    def test_metrics_are_correct(self):
        from scapsml.iv import read_metrics
        m = read_metrics(_DESC)
        assert m["status"] == "OK"
        assert m["Voc"] == pytest.approx(1.2910, abs=1e-3)
        assert m["Jsc"] == pytest.approx(16.395, abs=1e-2)
        assert m["FF"] == pytest.approx(0.8687, abs=2e-3)
        assert m["PCE"] == pytest.approx(18.39, abs=0.05)

    def test_reader_returns_ascending_voltage(self):
        from scapsml.iv import read_curve
        v, j, n = read_curve(_DESC)
        assert n == 150 and (np.diff(v) > 0).all()

    def test_order_never_changes_the_answer(self):
        """Ascending, descending or shuffled: identical metrics."""
        from scapsml.iv import read_curve
        v, j, _ = read_curve(_DESC)
        ref = iv_metrics(*apply_rs(v, j, 0.0))
        rng = np.random.default_rng(0)
        for order in (np.arange(len(v))[::-1], rng.permutation(len(v))):
            for rs in (0.0, 5.0):
                a = iv_metrics(*apply_rs(v[order], j[order], rs))
                b = iv_metrics(*apply_rs(v, j, rs))
                for k in ("Voc", "Jsc", "FF", "PCE"):
                    assert a[k] == pytest.approx(b[k], rel=1e-9), (k, rs)
        assert ref["Jsc"] == pytest.approx(16.395, abs=1e-2)

    def test_jsc_never_exceeds_generation(self):
        """A hard physical bound, and the check that would have caught this."""
        from scapsml.iv import read_curve, read_metrics
        m = read_metrics(_DESC)
        assert m["generation"] == pytest.approx(16.486, abs=1e-2)
        assert m["Jsc"] <= m["generation"]

    def test_impossible_jsc_is_flagged_not_reported(self):
        from scapsml.iv import classify
        bad = {"Voc": 1.29, "Jsc": 56.58, "FF": 0.05, "PCE": 3.75}
        assert classify(150, bad, True, generation=16.49) == "SUSPECT"

    def test_ff_outside_unit_interval_is_flagged(self):
        from scapsml.iv import classify
        assert classify(150, {"Jsc": 16, "FF": 1.4, "PCE": 20}, True) == "SUSPECT"


class TestExtrapolationIsBounded:
    def test_refuses_to_extrapolate_from_far_forward_bias(self):
        """
        Two points at 1.85 V are no basis for a value at 0 V. The unbounded
        fallback turned exactly that into Jsc = 56.6. Missing beats invented.
        """
        v = np.array([1.2822, 1.2980, 1.8342, 1.8500])
        j = np.array([2.921, -2.319, -119.02, -120.53])
        m = iv_metrics(v, j)
        assert m["Jsc"] is None and m["PCE"] is None

    def test_still_extends_a_curve_starting_just_above_zero(self):
        v, j = ideal_diode()
        m = iv_metrics(v[3:], j[3:])            # starts ~5 mV above 0
        assert v[3] < 0.1
        assert m["Jsc"] == pytest.approx(25.0, rel=1e-3)
