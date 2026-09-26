"""registry: every conversion declared once and checked here."""
import pytest

from scapsml.registry import DEF, POST, SCRIPT, lookup


class TestUnits:
    def test_density_cm3_to_m3(self):
        assert lookup("Nc").def_value(1e18) == pytest.approx(1e24)

    def test_mobility_cm2_to_m2(self):
        assert lookup("mun").def_value(100.0) == pytest.approx(1e-2)

    def test_thickness_nm_to_m_in_def(self):
        assert lookup("thickness").def_value(300) == pytest.approx(3e-7)

    def test_thickness_nm_to_um_in_script(self):
        """SCAPS scripts take micrometres even though the .def stores metres."""
        line = lookup("thickness").script_line(300, layer_no=3)
        assert line == "set layer3.thickness 0.300000"

    def test_doping_script_stays_in_cm3(self):
        line = lookup("NA").script_line(1e16, layer_no=3)
        assert line == "set layer3.NA 1.000000e+16"

    def test_cross_section_cm2_to_m2(self):
        """1e-15 cm^2 is 1e-19 m^2 -- getting this wrong once zeroed Voc."""
        assert lookup("sigma_bulk").def_value(1e-15) == pytest.approx(1e-19)


class TestVerifiedKeywords:
    """Keywords that look plausible, run cleanly, and do nothing."""

    def test_thickness_keyword_is_not_d(self):
        assert ".thickness " in lookup("thickness").script_line(1, layer_no=1)

    def test_interface_uses_ifdefect(self):
        line = lookup("Nt_interface").script_line(1e12, interface_no=2)
        assert line == "set interface2.ifdefect1.ntotal 1.000000e+12"

    def test_contact_is_contactright(self):
        assert lookup("BCM").script_line(5.1).startswith("set contactright.")


class TestTargets:
    def test_material_properties_are_def_only(self):
        for n in ("Eg", "chi", "eps", "Nc", "Nv", "mun", "mup"):
            assert lookup(n).target == DEF, n

    def test_device_parameters_are_scripted(self):
        for n in ("NA", "thickness", "Nt_bulk", "Nt_interface", "BCM"):
            assert lookup(n).target == SCRIPT, n

    def test_resistances_are_post_processed(self):
        assert lookup("Rs").target == POST
        assert lookup("Rsh").target == POST

    def test_log_scaled_axes(self):
        for n in ("NA", "Nt_bulk", "Nt_interface", "Nc"):
            assert lookup(n).log
        for n in ("Eg", "chi", "thickness"):
            assert not lookup(n).log


class TestLookup:
    def test_case_insensitive(self):
        assert lookup("eg") is lookup("EG") is lookup("Eg")

    def test_aliases(self):
        assert lookup("bandgap").name == "Eg"
        assert lookup("series resistance").name == "Rs"
        assert lookup("electron affinity").name == "chi"

    def test_unknown_lists_the_known(self):
        with pytest.raises(KeyError, match="Known"):
            lookup("flux capacitance")
