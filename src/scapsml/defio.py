"""
defio -- read and write SCAPS-1D definition (.def) files generically.

A .def is a positional text format: SCAPS reads it line by line and expects
every field in its block at a fixed position relative to its neighbours. This
module never reorders lines or reformats anything it was not asked to change,
so a file loaded and saved without edits is byte-identical to the original.

Blocks are addressed by name, which is what makes the package work for any
cell rather than one hardcoded stack:

    d = DefFile.load("base.def")
    d.layers                           -> ['FTO', 'TiO2', 'BaTiO3', 'Spiro']
    d.set("BaTiO3", "Eg", 1.55)
    d.set("BaTiO3", "Nc", 2.2e24)      # SI units, as the .def stores them
    d.set("back contact", "Fi_m", 4.4)
    d.set_absorption_file("BaTiO3", "my.abs")
    d.pin_defects_midgap()             # every trap at midgap, by construction
    d.save("out.def")

Units here are the .def's own (SI: m, m^-3, m^2/Vs). Conversion from the
friendlier units used in the workbook happens in registry.py, not here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["DefFile", "Block", "DefError"]

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"

# Lines that open a top-level block.
_BLOCK_OPEN = ("back contact", "front contact", "layer", "interface properties")


class DefError(Exception):
    """A requested block or field does not exist in this definition file."""


@dataclass
class Block:
    kind: str                  # "layer", "interface", "back contact", "front contact"
    name: str                  # layer name, "A / B" for interfaces, or the kind
    start: int                 # line index of the opening line
    end: int                   # one past the last line
    subblocks: dict = field(default_factory=dict)   # e.g. {"srhrecombination": (s, e)}


def _fmt(value, exp):
    if exp:
        return f"{value:.6e}"
    return f"{value:.6f}"


def _is_exp_token(tok):
    return "e" in tok.lower()


class DefFile:
    """A SCAPS .def file held as its original lines, editable by block name."""

    def __init__(self, text: str, path: str | None = None):
        self.path = path
        self._eol = "\r\n" if "\r\n" in text else "\n"
        self.lines = text.replace("\r\n", "\n").split("\n")
        self._index()

    # ---- construction --------------------------------------------------
    @classmethod
    def load(cls, path):
        # Read BYTES and decode, never read_text(): read_text applies
        # universal-newline translation and silently turns CRLF into LF, so
        # the original line endings could never be detected or restored.
        # SCAPS writes CRLF, and a file saved back with LF is not the file
        # that was loaded.
        p = Path(path)
        return cls(p.read_bytes().decode("latin-1"), str(p))

    def text(self) -> str:
        return self._eol.join(self.lines)

    def save(self, path):
        Path(path).write_bytes(self.text().encode("latin-1"))

    def copy(self) -> "DefFile":
        return DefFile(self.text(), self.path)

    # ---- indexing ------------------------------------------------------
    def _index(self):
        opens = [i for i, ln in enumerate(self.lines)
                 if ln.strip() in _BLOCK_OPEN]
        self.blocks: list[Block] = []
        for k, i in enumerate(opens):
            end = opens[k + 1] if k + 1 < len(opens) else len(self.lines)
            head = self.lines[i].strip()
            if head == "layer":
                name = self._first_value(i, end, "name") or f"layer{k}"
                kind = "layer"
            elif head == "interface properties":
                name = self._first_value(i, end, "interfacename") or f"if{k}"
                kind = "interface"
            else:
                name = kind = head
            b = Block(kind, name.strip(), i, end)
            for j in range(i, end):
                s = self.lines[j].strip()
                if s in ("srhrecombination", "interface recombination"):
                    # a sub-block runs to the next blank-line-separated header
                    # or the end of the block
                    k2 = next((x for x in range(j + 1, end)
                               if self.lines[x].strip() in
                               ("srhrecombination", "interface recombination")),
                              end)
                    b.subblocks.setdefault(s, []).append((j, k2))
            self.blocks.append(b)

    def _first_value(self, start, end, key):
        for j in range(start, end):
            m = re.match(rf"^\s*{re.escape(key)}\s*:\s*(.*)$", self.lines[j])
            if m:
                return m.group(1).strip()
        return None

    # ---- discovery -----------------------------------------------------
    @property
    def layers(self) -> list[str]:
        return [b.name for b in self.blocks if b.kind == "layer"]

    @property
    def interfaces(self) -> list[str]:
        return [b.name for b in self.blocks if b.kind == "interface"]

    def block(self, name: str) -> Block:
        """Find a block by layer name, interface name, or kind."""
        want = name.strip().lower()
        for b in self.blocks:
            if b.name.lower() == want or b.kind == want:
                return b
        # interfaces are often truncated in the file ("Spiro-OmeT"); allow a
        # prefix match on either side of the slash
        for b in self.blocks:
            if b.kind == "interface":
                l, _, r = b.name.lower().partition("/")
                w_l, _, w_r = want.partition("/")
                if l.strip().startswith(w_l.strip()) and \
                   r.strip().startswith(w_r.strip()):
                    return b
        raise DefError(f"no block named {name!r}. Layers: {self.layers}; "
                       f"interfaces: {self.interfaces}")

    def layer_index(self, name: str) -> int:
        """1-based layer number, as SCAPS scripts use (set layer3.NA ...)."""
        return self.layers.index(self.block(name).name) + 1

    def interface_index(self, name: str) -> int:
        """1-based interface number, as SCAPS scripts use it."""
        if name in self.interfaces:
            return self.interfaces.index(name) + 1
        return self.interfaces.index(self.block(name).name) + 1

    def interface_between(self, left: str, right: str) -> str:
        """
        The interface separating two ADJACENT layers, found by POSITION.

        Interface k sits between layer k and layer k+1 -- that is how SCAPS
        numbers them, and it is the only thing SCAPS relies on. Interface
        NAMES are free text and go stale: a .def whose layers were renamed
        from FTO/TiO2/BaTiO3 to ITO/SnO2/CsPbI3 still carried interfaces
        called 'TiO2 / BaTiO3', and any lookup by name failed on it. Names
        are never consulted here.
        """
        L = self.layers
        try:
            i, j = L.index(self.block(left).name), L.index(self.block(right).name)
        except (ValueError, DefError) as exc:
            raise DefError(f"no layers {left!r} and {right!r}; layers: {L}") from exc
        if abs(i - j) != 1:
            raise DefError(f"{left!r} and {right!r} are not adjacent "
                           f"(positions {i + 1} and {j + 1} of {len(L)})")
        k = min(i, j)
        if k >= len(self.interfaces):
            raise DefError(f"the .def has {len(self.interfaces)} interfaces "
                           f"for {len(L)} layers")
        return self.interfaces[k]

    def interface_names_stale(self) -> list:
        """Interfaces whose free-text name does not match their layers."""
        out = []
        for k, n in enumerate(self.interfaces):
            if k + 1 >= len(self.layers):
                break
            a, _, b = n.partition("/")
            want_a, want_b = self.layers[k], self.layers[k + 1]
            if not (want_a.lower().startswith(a.strip().lower()[:4]) and
                    want_b.lower().startswith(b.strip().lower()[:4])):
                out.append((k + 1, n, f"{want_a} / {want_b}"))
        return out

    # ---- field access --------------------------------------------------
    def _find(self, blk: Block, key: str, sub: str | None = None):
        rng = [(blk.start, blk.end)]
        if sub:
            rng = blk.subblocks.get(sub) or []
            if not rng:
                raise DefError(f"block {blk.name!r} has no {sub!r} section")
        pat = re.compile(rf"^\s*{re.escape(key)}\s*:")
        hits = []
        for s, e in rng:
            for j in range(s, e):
                if pat.match(self.lines[j]):
                    # outside a sub-block request, skip lines that belong to
                    # a sub-block so layer 'Et' never collides with defect 'Et'
                    if not sub and any(a <= j < b for v in blk.subblocks.values()
                                       for a, b in v):
                        continue
                    hits.append(j)
        return hits

    def get(self, block: str, key: str, sub: str | None = None):
        blk = self.block(block)
        hits = self._find(blk, key, sub)
        if not hits:
            raise DefError(f"{blk.name!r} has no field {key!r}"
                           + (f" in {sub!r}" if sub else ""))
        rest = self.lines[hits[0]].split(":", 1)[1]
        m = re.search(_NUM, rest)
        return float(m.group(0)) if m else rest.strip()

    def has(self, block: str, key: str, sub: str | None = None) -> bool:
        try:
            return bool(self._find(self.block(block), key, sub))
        except DefError:
            return False

    def set(self, block: str, key: str, value: float,
            sub: str | None = None, all_matches: bool = False):
        """
        Set a numeric field. Columnar lines (nine value columns, as SCAPS
        writes graded parameters) get columns 0, 5 and 6 rewritten -- the
        active value and both reference slots -- so a graded layer and a
        uniform one both see the new value. Scalar lines get their single
        number replaced. Everything else on the line is preserved.
        """
        blk = self.block(block)
        hits = self._find(blk, key, sub)
        if not hits:
            raise DefError(f"{blk.name!r} has no field {key!r}"
                           + (f" in {sub!r}" if sub else ""))
        for j in (hits if all_matches else hits[:1]):
            self.lines[j] = self._rewrite(self.lines[j], value)

    @staticmethod
    def _rewrite(line: str, value: float) -> str:
        head, rest = line.split(":", 1)
        toks = rest.split()
        nums = []
        for t in toks:
            if re.fullmatch(_NUM, t):
                nums.append(t)
            else:
                break
        if len(nums) >= 9:
            exp = _is_exp_token(nums[0])
            new = _fmt(value, exp)
            nums[0] = nums[5] = nums[6] = new
            tail = toks[len(nums):]
            out = head + ":\t" + "\t ".join(nums[:7]) + "\t " + \
                "\t ".join(nums[7:])
            return out + ("\t" + " ".join(tail) if tail else "")
        m = re.match(rf"^(\s*[^:]*:\s*)({_NUM})(.*)$", line)
        if not m:
            raise DefError(f"cannot find a number to replace in: {line!r}")
        exp = _is_exp_token(m.group(2))
        return m.group(1) + _fmt(value, exp) + m.group(3)

    def set_text(self, block: str, key: str, text: str, sub: str | None = None):
        """Replace everything after 'key :' with literal text."""
        blk = self.block(block)
        hits = self._find(blk, key, sub)
        if not hits:
            raise DefError(f"{blk.name!r} has no field {key!r}")
        j = hits[0]
        self.lines[j] = self.lines[j].split(":", 1)[0] + ": " + text

    # ---- absorption ----------------------------------------------------
    _ABS_MODEL = "absorptionmodel pure A material (y=0)"
    _ABS_FILE = "absorptionfile pure A material (y=0)"
    _ABS_MODEL_LINES = ("absorption model A, model",
                        "absorption model A, value of parameter 1",
                        "absorption model A, value of parameter 2")

    def absorption_source(self, layer: str) -> str:
        """'file:<name>' or 'model'."""
        blk = self.block(layer)
        for j in range(blk.start, blk.end):
            s = self.lines[j].strip()
            if s.startswith(self._ABS_MODEL) and "compatibility" not in s:
                if s.endswith("from file"):
                    f = self._first_value(j, blk.end, self._ABS_FILE)
                    return f"file:{f}"
                return "model"
        return "model"

    def set_absorption_file(self, layer: str, filename: str):
        """
        Point a layer's absorption at a file.

        A .def is positional: in 'from model' form three analytical-model
        lines follow the selector; in 'from file' form they must be ABSENT and
        a filename line takes their place. Leaving them shifts every
        subsequent line and SCAPS silently mis-parses the rest of the block --
        which in practice produced 70 mA/cm2 of spurious generation. This
        handles the swap in both directions.
        """
        blk = self.block(layer)
        for j in range(blk.start, blk.end):
            s = self.lines[j].strip()
            if not s.startswith(self._ABS_MODEL) or "compatibility" in s:
                continue
            if s.endswith("from file"):
                k = j + 1
                if k < blk.end and self.lines[k].strip().startswith(self._ABS_FILE):
                    self.lines[k] = f"{self._ABS_FILE} : {filename}"
                else:
                    self.lines.insert(k, f"{self._ABS_FILE} : {filename}")
            else:
                self.lines[j] = f"{self._ABS_MODEL} : from file"
                k = j + 1
                drop = 0
                while k + drop < len(self.lines) and any(
                        self.lines[k + drop].strip().startswith(p)
                        for p in self._ABS_MODEL_LINES):
                    drop += 1
                del self.lines[k:k + drop]
                self.lines.insert(k, f"{self._ABS_FILE} : {filename}")
            self._index()
            return
        raise DefError(f"layer {layer!r} has no absorption selector")

    def set_absorption_model(self, layer: str, a: float = 1e5, b: float = 0.0):
        """Switch a layer to SCAPS's analytical sqrt(hv-Eg) model."""
        blk = self.block(layer)
        for j in range(blk.start, blk.end):
            s = self.lines[j].strip()
            if not s.startswith(self._ABS_MODEL) or "compatibility" in s:
                continue
            k = j + 1
            if k < blk.end and self.lines[k].strip().startswith(self._ABS_FILE):
                del self.lines[k]
            self.lines[j] = f"{self._ABS_MODEL} : from model"
            if not (k < len(self.lines) and self.lines[k].strip().startswith(
                    self._ABS_MODEL_LINES[0])):
                self.lines[k:k] = [
                    "absorption model A, model : sqrt(hv-Eg) law (SCAPS traditional)",
                    f"absorption model A, value of parameter 1 : {a:.6e}",
                    f"absorption model A, value of parameter 2 : {b:.6e}",
                ]
            self._index()
            return
        raise DefError(f"layer {layer!r} has no absorption selector")

    # ---- defect levels -------------------------------------------------
    def pin_defects_midgap(self):
        """
        Place every bulk and interface trap at midgap BY CONSTRUCTION.

        Bulk traps get reference 1 (above Ei) with Et = 0. Interface traps
        get reference 9 (above the middle of the interface gap) with Et = 0.
        A level set this way follows the band edges wherever they move and
        can never fall outside the gap -- the failure that makes SCAPS reject
        a problem before solving and write a header-only .iv. Computing Et
        numerically instead is how 2178 of 4422 runs in one campaign came
        back empty: the gap it was computed against was not the gap the
        device had.
        """
        n = 0
        for b in self.blocks:
            for sub, ranges in b.subblocks.items():
                ref = 1 if sub == "srhrecombination" else 9
                for s, e in ranges:
                    for j in range(s, e):
                        ln = self.lines[j]
                        if ln.strip().startswith("Reference for defect energy"):
                            self.lines[j] = re.sub(
                                r"(Reference for defect energy\s*:\s*)\d+",
                                rf"\g<1>{ref}", ln)
                            n += 1
                        elif re.match(r"^\s*Et\s*:", ln):
                            self.lines[j] = self._rewrite(ln, 0.0)
        return n

    # ---- summary -------------------------------------------------------
    def summary(self) -> str:
        out = [f"{len(self.layers)} layers, {len(self.interfaces)} interfaces"]
        for n in self.layers:
            b = self.block(n)
            def g(k):
                try:
                    return self.get(n, k)
                except DefError:
                    return None
            out.append(f"  {n:<16} d={g('d')}  Eg={g('Eg')}  chi={g('chi')}  "
                       f"abs={self.absorption_source(n)}")
        return "\n".join(out)
