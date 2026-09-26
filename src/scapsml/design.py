"""
design -- turn a Project into concrete definition files and simulations.

Every swept parameter lands in one of three places, which sets its cost:

  DEF     each distinct value needs its own .def file. Material properties
          live here because SCAPS's script keywords for them do not take
          effect.
  SCRIPT  each value costs one simulation but no new file.
  POST    applied to the finished IV curve. Costs nothing.

So the enumeration is nested: designs (unique .def files) x script-level
combinations per design, and post-level values expand the dataset afterwards.

A Design carries the full, resolved absorber material -- every interpolated
property with any sweep offset or factor already applied -- so there is one
place that decides what a given .def contains.
"""

from __future__ import annotations

import hashlib
import itertools
from dataclasses import dataclass, field

from .interpolate import Interpolator
from .registry import DEF, POST, SCRIPT, lookup

__all__ = ["Design", "Plan", "plan"]


def s_tag(s):
    """Compact, filename-safe composition label: 0.243 -> '0p243'."""
    t = f"{s:.4f}".rstrip("0").rstrip(".")
    return t.replace("-", "m").replace(".", "p")


@dataclass(frozen=True)
class Design:
    index: int
    composition: float
    material: tuple             # ((prop, value), ...) resolved absorber values
    other: tuple                # ((layer, prop, value), ...) other-layer values
    varied: tuple               # ((label, value), ...) the swept def-level axes
    def_name: str
    abs_name: str | None

    def mat(self, prop, default=None):
        return dict(self.material).get(prop, default)


@dataclass
class Plan:
    project: object
    designs: list
    script_axes: list
    post_axes: list
    skipped: list = field(default_factory=list)

    def sims_for(self, design):
        """[{param: value}] script-level combinations for one design."""
        if not self.script_axes:
            return [{}]
        names = [self._label(a) for a in self.script_axes]
        return [dict(zip(names, vals)) for vals in
                itertools.product(*[a.values for a in self.script_axes])]

    @staticmethod
    def _label(axis):
        return axis.name if not axis.layer else f"{axis.name}@{axis.layer}"

    @property
    def n_sims(self):
        per = 1
        for a in self.script_axes:
            per *= len(a.values)
        return per * len(self.designs)

    @property
    def n_post(self):
        per = 1
        for a in self.post_axes:
            per *= len(a.values)
        return per

    @property
    def n_rows(self):
        return self.n_sims * self.n_post

    @property
    def abs_files(self):
        return sorted({d.abs_name for d in self.designs if d.abs_name})

    def summary(self):
        return {
            "compositions": len({d.composition for d in self.designs}),
            "definition_files": len(self.designs),
            "absorption_files": len(self.abs_files),
            "simulations": self.n_sims,
            "post_levels": self.n_post,
            "dataset_rows": self.n_rows,
            "skipped_designs": len(self.skipped),
        }


def _apply(base, axis, value):
    if axis.mode == "offset":
        return base + value
    if axis.mode == "factor":
        return base * value
    return value


def plan(project) -> Plan:
    it = Interpolator(project.anchors, project.interpolation)
    absorber = project.absorber
    comp_axis = project.composition_axis
    compositions = comp_axis.values if comp_axis else [
        a["composition"] for a in project.anchors]

    def_axes = [a for a in project.axes if a.target == DEF]
    abs_def = [a for a in def_axes if a.layer in (None, absorber)]
    other_def = [a for a in def_axes if a.layer not in (None, absorber)]
    script_axes = [a for a in project.axes if a.target == SCRIPT]
    post_axes = [a for a in project.axes if a.target == POST]

    props = [p for p in it.properties() if p != "IP"]
    has_spectra = any(a.get("abs_file") for a in project.anchors)
    prefix = str(project.name).replace(" ", "_")

    designs, skipped = [], []
    idx = 0
    for s in compositions:
        base = {p: it(p, s) for p in props}
        for combo in itertools.product(*[a.values for a in abs_def]) or [()]:
            mat = dict(base)
            varied = []
            for ax, v in zip(abs_def, combo):
                if ax.name not in mat:
                    # a swept property with no anchor: absolute values only
                    if ax.mode != "absolute":
                        raise ValueError(
                            f"sweep {ax.name}: mode {ax.mode!r} needs an anchor "
                            f"column for {ax.name}; add one or use 'absolute'")
                    mat[ax.name] = v
                else:
                    mat[ax.name] = _apply(mat[ax.name], ax, v)
                varied.append((f"{ax.name}_{ax.mode}" if ax.mode != "absolute"
                               else ax.name, v))
            bad = [k for k in ("Eg", "eps", "Nc", "Nv") if k in mat and mat[k] <= 0]
            if bad:
                skipped.append((s, dict(varied), f"non-physical {bad}"))
                continue
            for ocombo in itertools.product(*[a.values for a in other_def]) or [()]:
                other = tuple((a.layer, a.name, v) for a, v in zip(other_def, ocombo))
                ovaried = tuple((f"{a.name}@{a.layer}", v)
                                for a, v in zip(other_def, ocombo))
                eg = round(mat["Eg"], 4)
                abs_name = (f"{prefix}_S{s_tag(s)}_Eg{s_tag(eg)}.abs"
                            if has_spectra else None)
                designs.append(Design(
                    index=idx, composition=float(s),
                    material=tuple(sorted(mat.items())),
                    other=other,
                    varied=tuple(varied) + ovaried,
                    def_name=f"{prefix}_S{s_tag(s)}_{idx:05d}.def",
                    abs_name=abs_name))
                idx += 1
    return Plan(project, designs, script_axes, post_axes, skipped)


def fingerprint(project) -> str:
    """Stable hash of everything that determines the generated files."""
    h = hashlib.sha256()
    h.update(repr(sorted(project.settings.items(), key=str)).encode())
    h.update(repr(project.anchors).encode())
    h.update(repr([(a.name, a.layer, a.mode, a.values) for a in project.axes]).encode())
    h.update(repr(project.layer_overrides).encode())
    return h.hexdigest()[:12]
