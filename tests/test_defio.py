"""defio: generic .def parsing, editing and byte-exact round trips."""
from pathlib import Path

import pytest

from scapsml.defio import DefError, DefFile

FIX = Path(__file__).parent / "fixtures"
DEFS = sorted(FIX.glob("*.def"))


@pytest.fixture(params=DEFS, ids=lambda p: p.stem)
def d(request):
    return DefFile.load(request.param)


class TestRoundTrip:
    def test_load_save_is_byte_identical(self, d, tmp_path):
        """An unedited file must come back exactly -- SCAPS is positional."""
        out = tmp_path / "out.def"
        d.save(out)
        assert out.read_bytes() == Path(d.path).read_bytes()

    def test_preserves_line_endings(self, d, tmp_path):
        raw = Path(d.path).read_bytes()
        d.save(tmp_path / "o.def")
        assert (b"\r\n" in raw) == (b"\r\n" in (tmp_path / "o.def").read_bytes())


class TestDiscovery:
    def test_finds_layers(self, d):
        assert len(d.layers) >= 3

    def test_finds_interfaces(self, d):
        assert len(d.interfaces) == len(d.layers) - 1

    def test_layer_index_is_one_based(self, d):
        assert d.layer_index(d.layers[0]) == 1
        assert d.layer_index(d.layers[-1]) == len(d.layers)

    def test_unknown_block_raises_helpfully(self, d):
        with pytest.raises(DefError, match="Layers"):
            d.block("NoSuchLayer")

    def test_contacts_exist(self, d):
        assert d.block("back contact").kind == "back contact"
        assert d.block("front contact").kind == "front contact"


class TestFieldEditing:
    def test_columnar_field_updates_all_active_slots(self, d):
        layer = d.layers[len(d.layers) // 2]
        d.set(layer, "Eg", 1.2345)
        assert d.get(layer, "Eg") == pytest.approx(1.2345)
        line = next(l for l in d.lines if l.strip().startswith("Eg :")
                    and d.lines.index(l) >= d.block(layer).start
                    and d.lines.index(l) < d.block(layer).end)
        cols = line.split(":", 1)[1].split()
        assert float(cols[0]) == float(cols[5]) == float(cols[6]) == \
               pytest.approx(1.2345)

    def test_scalar_field(self, d):
        layer = d.layers[0]
        d.set(layer, "d", 4.2e-7)
        assert d.get(layer, "d") == pytest.approx(4.2e-7)

    def test_exponent_format_is_kept(self, d):
        layer = d.layers[0]
        d.set(layer, "Nc", 3.3e24)
        line = [l for l in d.lines[d.block(layer).start:d.block(layer).end]
                if l.strip().startswith("Nc :")][0]
        assert "e+24" in line

    def test_edit_touches_only_one_line(self, d):
        before = list(d.lines)
        d.set(d.layers[1], "chi", 4.321)
        changed = [i for i, (a, b) in enumerate(zip(before, d.lines)) if a != b]
        assert len(changed) == 1

    def test_editing_one_layer_leaves_others_alone(self, d):
        other = [d.get(n, "Eg") for n in d.layers[1:]]
        d.set(d.layers[0], "Eg", 9.99)
        assert [d.get(n, "Eg") for n in d.layers[1:]] == other

    def test_contact_work_function(self, d):
        d.set("back contact", "Fi_m", 4.55)
        assert d.get("back contact", "Fi_m") == pytest.approx(4.55)

    def test_missing_field_raises(self, d):
        with pytest.raises(DefError):
            d.set(d.layers[0], "NotAField", 1.0)


class TestAbsorption:
    def test_switch_model_to_file_removes_model_lines(self, d):
        """
        The .def is positional. Leaving the three analytical-model lines
        behind after switching to a file shifts every following line and
        SCAPS mis-parses the block silently.
        """
        layer = next(n for n in d.layers
                     if d.absorption_source(n) == "model")
        n_before = len(d.lines)
        d.set_absorption_file(layer, "x.abs")
        assert d.absorption_source(layer) == "file:x.abs"
        blk = d.block(layer)
        body = "\n".join(d.lines[blk.start:blk.end])
        assert "absorption model A, value of parameter 1" not in body
        assert len(d.lines) == n_before - 3 + 1

    def test_file_to_model_restores_model_lines(self, d):
        layer = next(n for n in d.layers
                     if d.absorption_source(n).startswith("file"))
        d.set_absorption_model(layer)
        assert d.absorption_source(layer) == "model"
        blk = d.block(layer)
        body = "\n".join(d.lines[blk.start:blk.end])
        assert "absorptionfile pure A material" not in body
        assert "absorption model A, value of parameter 1" in body

    def test_round_trip_model_file_model(self, d):
        layer = next(n for n in d.layers if d.absorption_source(n) == "model")
        n0 = len(d.lines)
        d.set_absorption_file(layer, "a.abs")
        d.set_absorption_model(layer)
        assert len(d.lines) == n0

    def test_repointing_an_existing_file(self, d):
        layer = next(n for n in d.layers
                     if d.absorption_source(n).startswith("file"))
        n0 = len(d.lines)
        d.set_absorption_file(layer, "other.abs")
        assert d.absorption_source(layer) == "file:other.abs"
        assert len(d.lines) == n0


class TestDefects:
    def test_pin_midgap_sets_self_referencing_levels(self, d):
        n = d.pin_defects_midgap()
        assert n > 0
        text = d.text()
        import re
        refs = re.findall(r"Reference for defect energy\s*:\s*(\d+)", text)
        assert set(refs) <= {"1", "9"}
        for m in re.finditer(r"^\s*Et\s*:\s*(\S+)", text, re.M):
            assert float(m.group(1)) == 0.0

    def test_layer_get_does_not_read_defect_fields(self, d):
        """A layer-level lookup must not collide with a defect sub-block."""
        layer = next((b.name for b in d.blocks
                      if b.kind == "layer" and "srhrecombination" in b.subblocks),
                     None)
        if layer is None:
            pytest.skip("no layer with a defect block")
        assert d.has(layer, "Et", sub="srhrecombination")


class TestInterfacesByPosition:
    """
    Interface names are free text and go stale when layers are renamed. The
    CsPbI3 validation file carried interfaces named after a BaTiO3 stack.
    Resolution must be positional and never consult the names.
    """

    def test_between_adjacent_layers(self, d):
        L = d.layers
        for k in range(len(L) - 1):
            assert d.interface_index(d.interface_between(L[k], L[k + 1])) == k + 1

    def test_order_does_not_matter(self, d):
        L = d.layers
        assert d.interface_between(L[0], L[1]) == d.interface_between(L[1], L[0])

    def test_non_adjacent_raises(self, d):
        L = d.layers
        with pytest.raises(DefError, match="not adjacent"):
            d.interface_between(L[0], L[2])

    def test_works_when_names_are_stale(self):
        d = DefFile.load(FIX / "cspbi3_base.def")
        assert d.interface_names_stale(), "fixture should carry stale names"
        idx = d.interface_index(d.interface_between("CsPbI3", "Spiro-OMeTAD"))
        assert idx == 3
