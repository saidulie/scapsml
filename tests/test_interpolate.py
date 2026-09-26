"""interpolate: anchors reproduced exactly, no overshoot, no extrapolation."""
import numpy as np
import pytest

from scapsml.interpolate import Interpolator

ANCHORS = [
    {"composition": 0.20, "Eg": 1.67, "IP": 6.46, "Nc": 1e18, "eps": 300},
    {"composition": 0.243, "Eg": 1.51, "IP": 6.38, "Nc": 3e18, "eps": 280},
    {"composition": 0.253, "Eg": 1.45, "IP": 6.35, "Nc": 5e18, "eps": 270},
    {"composition": 0.287, "Eg": 1.35, "IP": 6.30, "Nc": 8e18, "eps": 250},
    {"composition": 0.36, "Eg": 1.09, "IP": 6.18, "Nc": 2e19, "eps": 200},
]


@pytest.fixture(params=["linear", "pchip"])
def it(request):
    return Interpolator(ANCHORS, {"Eg": request.param})


class TestAnchors:
    def test_reproduces_every_anchor_exactly(self, it):
        for a in ANCHORS:
            assert it("Eg", a["composition"]) == pytest.approx(a["Eg"], abs=1e-12)

    def test_no_extrapolation_beyond_the_anchors(self, it):
        """Clamped, not extrapolated: a fit beyond its data is fiction."""
        assert it("Eg", 0.0) == pytest.approx(ANCHORS[0]["Eg"])
        assert it("Eg", 1.0) == pytest.approx(ANCHORS[-1]["Eg"])


class TestMonotonicity:
    def test_pchip_never_overshoots_a_monotonic_anchor_set(self):
        it = Interpolator(ANCHORS, {"Eg": "pchip"})
        xs = np.linspace(0.20, 0.36, 400)
        ys = [it("Eg", x) for x in xs]
        assert all(b <= a + 1e-12 for a, b in zip(ys, ys[1:]))
        assert max(ys) <= ANCHORS[0]["Eg"] + 1e-12
        assert min(ys) >= ANCHORS[-1]["Eg"] - 1e-12


class TestMethods:
    def test_log_interpolation_is_geometric_midpoint(self):
        it = Interpolator([{"composition": 0, "Nc": 1e18},
                           {"composition": 1, "Nc": 1e20}])
        assert it("Nc", 0.5) == pytest.approx(1e19, rel=1e-9)

    def test_densities_default_to_log(self):
        it = Interpolator(ANCHORS)
        assert it.method("Nc") == "log"
        assert it.method("Eg") == "linear"

    def test_log_rejects_non_positive(self):
        it = Interpolator([{"composition": 0, "Nc": 0.0},
                           {"composition": 1, "Nc": 1e20}])
        with pytest.raises(ValueError):
            it("Nc", 0.5)


class TestDerivedAffinity:
    def test_chi_is_ip_minus_eg(self):
        it = Interpolator(ANCHORS)
        for s in (0.20, 0.25, 0.30, 0.36):
            assert it("chi", s) == pytest.approx(it("IP", s) - it("Eg", s),
                                                 abs=1e-9)

    def test_chi_listed_as_available_when_derivable(self):
        assert "chi" in Interpolator(ANCHORS).properties()


class TestNeighbours:
    def test_blend_weight(self):
        it = Interpolator(ANCHORS)
        lo, hi, t = it.neighbours(0.248)
        assert lo["composition"] == 0.243 and hi["composition"] == 0.253
        assert t == pytest.approx(0.5)
