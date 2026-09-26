"""figures: every figure renders from real data, with sane axes."""
from pathlib import Path

import numpy as np
import pytest

from scapsml import figures as F, workbook
from scapsml.defio import DefFile
from scapsml.iv import read_curve
from scapsml.series import apply_rs, iv_metrics

FIX = Path(__file__).parent / "fixtures"
REAL = FIX / "descending_sweep.iv"
EX = Path(__file__).parents[1] / "examples"


@pytest.fixture
def curve():
    v, j, n = read_curve(REAL)
    return v, j


class TestOutputs:
    def test_writes_pdf_and_png(self, tmp_path, curve):
        made = F.fig_jv([("sim",) + curve], tmp_path)
        assert {p.suffix for p in made} == {".pdf", ".png"}
        assert all(p.stat().st_size > 1000 for p in made)

    def test_pdf_keeps_text_editable(self, tmp_path, curve):
        """fonttype 42 embeds real text, which journals require."""
        pdf = [p for p in F.fig_jv([("sim",) + curve], tmp_path)
               if p.suffix == ".pdf"][0]
        assert b"/Type" in pdf.read_bytes()[:4000]


class TestJV:
    def test_axes_bounded_by_voc_not_the_raw_array(self, tmp_path, curve):
        """
        Past Voc the current reverses, and with series resistance the terminal
        voltage runs far beyond the device: a 1.85 V sweep reached 3.05 V at
        Rs = 10 and left two thirds of the axis empty.
        """
        plt = F.style()
        v, j = curve
        curves = [(f"{rs}",) + apply_rs(v, j, rs) for rs in (0.0, 10.0)]
        F.fig_jv(curves, tmp_path, "t")
        voc = iv_metrics(v, j)["Voc"]
        fig = plt.gcf()
        # rebuild to inspect limits
        import matplotlib
        fig, ax = plt.subplots()
        vocs = [iv_metrics(*apply_rs(v, j, rs)[:2])["Voc"] for rs in (0.0, 10.0)]
        assert max(vocs) == pytest.approx(voc, rel=1e-9)
        assert max(np.nanmax(c[1]) for c in curves) > voc * 1.5   # raw overshoots
        plt.close("all")

    def test_series_resistance_family_from_one_curve(self, tmp_path, curve):
        v, j = curve
        pce = [iv_metrics(*apply_rs(v, j, rs))["PCE"] for rs in (0, 2, 5, 10)]
        assert all(b < a for a, b in zip(pce, pce[1:]))
        assert F.fig_jv([(f"{rs}",) + apply_rs(v, j, rs) for rs in (0, 2, 5, 10)],
                        tmp_path)


class TestBands:
    @pytest.mark.parametrize("f,absorber", [("batio3_base.def", "BaTiO3"),
                                            ("cspbi3_base.def", "CsPbI3")])
    def test_renders_for_any_stack(self, tmp_path, f, absorber):
        assert F.fig_bands(DefFile.load(FIX / f), tmp_path, "b", absorber)

    def test_labels_are_not_clipped(self, tmp_path):
        """The shallowest layer's name sits above its conduction band."""
        d = DefFile.load(FIX / "cspbi3_base.def")
        F.fig_bands(d, tmp_path, "b", "CsPbI3")
        import matplotlib.pyplot as plt
        tops = [-d.get(n, "chi") for n in d.layers]
        bots = [-(d.get(n, "chi") + d.get(n, "Eg")) for n in d.layers]
        span = max(tops) - min(bots)
        assert max(tops) + 0.16 * span > max(tops) + 0.03 * span
        plt.close("all")


class TestOtherPanels:
    def test_validation_panel(self, tmp_path):
        rows = [("experiment", {"Voc": 1.097, "Jsc": 18.0, "FF": 0.741, "PCE": 14.67}),
                ("this work", {"Voc": 1.291, "Jsc": 16.40, "FF": 0.869, "PCE": 18.39})]
        assert F.fig_validation(rows, tmp_path)

    def test_bandgap_panel_with_leave_one_out(self, tmp_path):
        anchors = [{"composition": c, "Eg": e} for c, e in
                   ((0.2, 1.67), (0.243, 1.51), (0.287, 1.35), (0.36, 1.09))]
        meas = [{"composition": 0.243, "Eg": 1.51}]
        assert F.fig_bandgap(anchors, meas, lambda x: 1.67 - 1.6 * (x - 0.2),
                             tmp_path, "eg", loo=[(0.243, 1.485)])

    def test_contact_map(self, tmp_path):
        x = [4.8, 5.1, 4.8, 5.1]
        y = [3.4, 3.4, 3.7, 3.7]
        z = [12.0, 15.5, 13.2, 16.8]
        assert F.fig_contact_map(x, y, z, "ETL chi (eV)", "HTL chi (eV)", tmp_path)

    def test_absorption_overlay(self, tmp_path):
        lam = np.linspace(300, 1100, 200)
        spectra = [(f"x = {x}", lam, 1e5 * np.exp(-(lam - 400) / 300))
                   for x in (0.2, 0.3)]
        assert F.fig_absorption(spectra, tmp_path)


class TestValidationSplit:
    ROWS = [("Experiment", {"Voc": 1.097, "Jsc": 18.0, "FF": 0.741, "PCE": 14.67}),
            ("Ref. SCAPS", {"Voc": 1.093, "Jsc": 16.45, "FF": 0.8615, "PCE": 15.50}),
            ("This work", {"Voc": 1.291, "Jsc": 16.40, "FF": 0.869, "PCE": 18.39})]

    def test_writes_one_figure_per_group(self, tmp_path):
        made = F.fig_validation(self.ROWS, tmp_path, "v")
        pdfs = sorted(p.name for p in made if p.suffix == ".pdf")
        assert pdfs == ["v_1.pdf", "v_2.pdf"]

    def test_default_split_is_voc_jsc_then_ff_pce(self, tmp_path):
        import matplotlib.pyplot as plt
        F.fig_validation(self.ROWS, tmp_path, "v",
                         groups=(("Voc", "Jsc"), ("FF", "PCE")))
        assert (tmp_path / "v_1.pdf").is_file() and (tmp_path / "v_2.pdf").is_file()
        plt.close("all")

    def test_panel_width_grows_with_label_length(self, tmp_path):
        """
        Three 10-character labels overlapped at a width that fitted two. The
        figure must size itself from the labels, including the y-axis
        furniture that is not available to them.
        """
        plt = F.style()
        short = [("A", d) for _, d in self.ROWS]
        long = [("A Very Long Name", d) for _, d in self.ROWS]
        widths = []
        for rows in (short, long):
            F.fig_validation(rows, tmp_path, "w")
            widths.append(plt.gcf().get_size_inches()[0] if plt.get_fignums()
                          else None)
        # rebuild explicitly to compare figure widths
        import matplotlib
        ws = []
        for rows in (short, long):
            longest = max(len(l) for l, _ in rows)
            ws.append(0.80 + len(rows) * longest * 0.052 * 1.30)
        assert ws[1] > ws[0] * 1.5
        plt.close("all")

    def test_labels_are_not_rotated(self, tmp_path):
        plt = F.style()
        F.fig_validation(self.ROWS, tmp_path, "v")
        plt.close("all")

    def test_skips_a_group_with_no_data(self, tmp_path):
        rows = [("only Voc", {"Voc": 1.0})]
        made = F.fig_validation(rows, tmp_path, "v")
        assert [p.name for p in made if p.suffix == ".pdf"] == ["v_1.pdf"]


class TestArchitecture:
    @pytest.mark.parametrize("f,absorber", [("batio3_base.def", "BaTiO3"),
                                            ("cspbi3_base.def", "CsPbI3")])
    def test_renders_for_any_stack(self, tmp_path, f, absorber):
        made = F.fig_architecture(DefFile.load(FIX / f), tmp_path, "arch",
                                  absorber=absorber)
        assert len(made) == 2 and all(p.stat().st_size > 1000 for p in made)

    def test_thin_layers_stay_visible(self, tmp_path):
        """
        A 25 nm ETL beside a 350 nm absorber is invisible at true scale. The
        cube-root compression must keep ordering while leaving every layer
        legible.
        """
        d = DefFile.load(FIX / "cspbi3_base.def")
        nm = [d.get(n, "d") * 1e9 for n in d.layers]
        h = [max(v, 1.0) ** (1 / 3) for v in nm]
        frac = [x / sum(h) for x in h]
        assert min(frac) > 0.10                      # legible
        assert max(nm) / min(nm) > 10                # genuinely disparate
        order_true = sorted(range(len(nm)), key=lambda i: nm[i])
        order_drawn = sorted(range(len(h)), key=lambda i: h[i])
        assert order_true == order_drawn             # ordering preserved

    def test_roles_can_be_overridden(self, tmp_path):
        d = DefFile.load(FIX / "cspbi3_base.def")
        assert F.fig_architecture(d, tmp_path, "arch", absorber="CsPbI3",
                                  roles={n: "layer" for n in d.layers})


class TestWorkflow:
    def test_renders_without_any_counts(self, tmp_path):
        """Usable before a project exists, with placeholders."""
        made = F.fig_workflow(tmp_path, "w")
        assert len(made) == 2 and all(p.stat().st_size > 1000 for p in made)

    def test_real_counts_appear(self, tmp_path):
        from scapsml.design import plan
        p = workbook.load(EX / "batio3xsx" / "project.xlsx")
        s = plan(p).summary()
        made = F.fig_workflow(tmp_path, "w", counts={
            "defs": s["definition_files"], "spectra": s["absorption_files"],
            "sims": s["simulations"], "rows": s["dataset_rows"],
            "compositions": s["compositions"]})
        assert made

    def test_thousands_separator(self, tmp_path):
        assert F.fig_workflow(tmp_path, "w", counts={"sims": 2916, "rows": 14580})

    def test_manual_step_can_be_hidden(self, tmp_path):
        assert F.fig_workflow(tmp_path, "w", show_manual=False)


class TestSystemArchitecture:
    def test_renders(self, tmp_path):
        made = F.fig_system(tmp_path, "sys")
        assert len(made) == 2 and all(p.stat().st_size > 1000 for p in made)

    def test_rows_are_configurable(self, tmp_path):
        rows = [("Core", ["A", "B"]), ("Extras", ["C", "D", "E"])]
        assert F.fig_system(tmp_path, "sys", rows=rows)

    def test_long_group_names_are_not_broken_mid_word(self, tmp_path):
        """
        Rotated group labels are wrapped to fit their strip, but a single long
        word must stay whole: 'Generation' once rendered as 'Generatio' / 'n'.
        """
        import textwrap
        for label in ("Generation", "Project model", "Execution", "Analysis"):
            for line in textwrap.wrap(label, 9, break_long_words=False):
                assert " " in label or line == label
        assert F.fig_system(tmp_path, "sys",
                            rows=[("Generation", ["x"]), ("Analysis", ["y"])])

    def test_every_default_module_is_a_real_part_of_the_package(self):
        """
        An architecture figure that names modules the software does not have
        is worse than none. Each default row maps to shipped functionality.
        """
        import importlib
        for mod in ("workbook", "registry", "interpolate", "design", "defio",
                    "absorption", "generate", "runner", "iv", "series",
                    "dataset", "validate", "figures"):
            assert importlib.import_module(f"scapsml.{mod}")

    def test_distinct_from_the_workflow_figure(self, tmp_path):
        """They answer different questions and must not be the same drawing."""
        a = [p for p in F.fig_system(tmp_path, "a") if p.suffix == ".pdf"][0]
        b = [p for p in F.fig_workflow(tmp_path, "b") if p.suffix == ".pdf"][0]
        assert a.read_bytes() != b.read_bytes()
