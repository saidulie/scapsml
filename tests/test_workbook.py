"""workbook: values parse correctly and every mistake is caught, with location."""
from pathlib import Path

import pytest

from scapsml.template import write_template
from scapsml.workbook import WorkbookError, load, parse_values

FIX = Path(__file__).parent / "fixtures"


class TestParseValues:
    def test_single(self):
        assert parse_values(1e16) == [1e16]

    def test_list(self):
        assert parse_values("1e15, 1e16, 1e17") == [1e15, 1e16, 1e17]

    def test_semicolon_and_space(self):
        assert parse_values("1; 2 3") == [1.0, 2.0, 3.0]

    def test_range_is_inclusive(self):
        assert parse_values("20:36:1") == [float(x) for x in range(20, 37)]

    def test_fractional_range_has_no_float_drift(self):
        v = parse_values("0.20:0.36:0.01")
        assert len(v) == 17 and v[0] == 0.2 and v[-1] == 0.36
        assert len({round(b - a, 9) for a, b in zip(v, v[1:])}) == 1

    def test_lin(self):
        assert parse_values("lin:1:2:5") == pytest.approx([1, 1.25, 1.5, 1.75, 2])

    def test_log(self):
        assert parse_values("log:1e14:1e18:5") == pytest.approx(
            [1e14, 1e15, 1e16, 1e17, 1e18])

    @pytest.mark.parametrize("bad", ["", "abc", "1:2:0", "log:0:10:3", "lin:1:2:0"])
    def test_bad_input_raises(self, bad):
        with pytest.raises(ValueError):
            parse_values(bad)


def _book(tmp_path, **ex):
    base = {
        "project": {"name": "t", "base_def": str(FIX / "batio3_base.def"),
                    "absorber": "BaTiO3"},
        "anchor_columns": ["composition", "Eg", "chi"],
        "anchors": [{"composition": 0, "Eg": 3.2, "chi": 4.0},
                    {"composition": 1, "Eg": 0.3, "chi": 5.5}],
        "interpolation": [],
        "sweep": [("composition", "", "absolute", "0:1:0.5", "")],
    }
    base.update(ex)
    p = tmp_path / "t.xlsx"
    write_template(p, example=base)
    return p


class TestValidWorkbook:
    def test_loads(self, tmp_path):
        p = load(_book(tmp_path))
        assert p.absorber == "BaTiO3"
        assert p.composition_axis.values == [0.0, 0.5, 1.0]
        assert len(p.anchors) == 2

    def test_paths_resolve_relative_to_the_workbook(self, tmp_path):
        p = load(_book(tmp_path))
        assert p.resolve("work_dir", "work") == (tmp_path / "work").resolve()


class TestErrorsAreCaughtWithLocation:
    def _problems(self, tmp_path, **ex):
        with pytest.raises(WorkbookError) as e:
            load(_book(tmp_path, **ex))
        return "\n".join(e.value.problems)

    def test_unknown_parameter(self, tmp_path):
        msg = self._problems(tmp_path, sweep=[
            ("composition", "", "absolute", "0", ""),
            ("flux", "", "absolute", "1", "")])
        assert "sweep!A" in msg and "flux" in msg and "Known" in msg

    def test_absorber_not_in_def(self, tmp_path):
        msg = self._problems(tmp_path, project={
            "name": "t", "base_def": str(FIX / "batio3_base.def"),
            "absorber": "Perovskite"})
        assert "not a layer" in msg and "BaTiO3" in msg

    def test_missing_base_def(self, tmp_path):
        msg = self._problems(tmp_path, project={
            "name": "t", "base_def": "nope.def", "absorber": "X"})
        assert "not found" in msg

    def test_unreadable_values(self, tmp_path):
        msg = self._problems(tmp_path, sweep=[
            ("composition", "", "absolute", "0", ""),
            ("NA", "", "absolute", "lots", "")])
        assert "cannot read values" in msg

    def test_offset_on_a_script_parameter(self, tmp_path):
        """offset/factor only make sense relative to an interpolated property."""
        msg = self._problems(tmp_path, sweep=[
            ("composition", "", "absolute", "0", ""),
            ("NA", "", "offset", "1", "")])
        assert "material properties" in msg

    def test_device_parameter_in_anchors(self, tmp_path):
        msg = self._problems(tmp_path,
                             anchor_columns=["composition", "Eg", "NA"],
                             anchors=[{"composition": 0, "Eg": 3.2, "NA": 1e16}])
        assert "put it in 'sweep'" in msg

    def test_chi_and_ip_together(self, tmp_path):
        msg = self._problems(tmp_path,
                             anchor_columns=["composition", "Eg", "chi", "IP"],
                             anchors=[{"composition": 0, "Eg": 3.2, "chi": 4, "IP": 7}])
        assert "either 'chi' or 'IP'" in msg

    def test_no_composition_row(self, tmp_path):
        msg = self._problems(tmp_path, sweep=[("NA", "", "absolute", "1e16", "")])
        assert "no 'composition'" in msg

    def test_parameter_swept_twice(self, tmp_path):
        msg = self._problems(tmp_path, sweep=[
            ("composition", "", "absolute", "0", ""),
            ("NA", "", "absolute", "1e15", ""),
            ("NA", "", "absolute", "1e16", "")])
        assert "swept twice" in msg

    def test_all_problems_reported_together(self, tmp_path):
        """Fix them in one pass, not one per run."""
        with pytest.raises(WorkbookError) as e:
            load(_book(tmp_path,
                       project={"name": "t", "base_def": str(FIX / "batio3_base.def"),
                                "absorber": "Nope"},
                       sweep=[("composition", "", "absolute", "0", ""),
                              ("flux", "", "absolute", "1", "")]))
        assert len(e.value.problems) >= 2

    def test_aliases_are_accepted(self, tmp_path):
        p = load(_book(tmp_path, sweep=[
            ("composition", "", "absolute", "0", ""),
            ("acceptor", "", "absolute", "1e16", "")]))
        assert any(a.name == "NA" for a in p.axes)
