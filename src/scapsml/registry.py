"""
registry -- where every sweepable parameter lives, and in what units.

This is what makes the package independent of any particular cell. A user
names a parameter in the workbook -- "Eg", "NA", "thickness", "BCM", "Rs" --
and the registry knows:

  * WHERE it goes. Some parameters exist only in the .def (bandgap, affinity,
    permittivity, DOS, mobility): SCAPS offers script keywords for several of
    them but they do not take effect, verified across byte-identical runs, so
    each value needs its own definition file. Others are settable from a
    script (doping, thickness, defect density, contact work function), which
    costs nothing extra. Series and shunt resistance are neither: SCAPS applies
    them as a lumped post-process on the finished IV curve, so they are
    computed exactly afterwards and cost no simulations at all.

  * WHAT UNITS. The workbook uses the units papers use (cm^-3, cm^2/Vs, nm).
    The .def stores SI (m^-3, m^2/Vs, m). SCAPS scripts use a mixture --
    cm^-3 for doping but micrometres for thickness. Getting any of these wrong
    produces a result that runs cleanly and is wrong, so each conversion is
    declared once, here, and tested.

  * HOW TO SAMPLE IT. Doping and defect densities span decades and are
    sampled on a log scale; band energies are linear.

Unknown parameters raise immediately with the list of known ones, rather
than being silently ignored.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Param", "REGISTRY", "lookup", "DEF", "SCRIPT", "POST"]

DEF, SCRIPT, POST = "def", "script", "post"


@dataclass(frozen=True)
class Param:
    name: str
    target: str                  # DEF, SCRIPT or POST
    unit: str                    # the unit the WORKBOOK uses
    scope: str = "layer"         # layer | interface | back contact | front contact
    field: str | None = None     # .def field name
    to_si: float = 1.0           # workbook value * to_si = .def value
    script: str | None = None    # command template; {L}/{I} layer/interface no.
    script_scale: float = 1.0    # workbook value * scale = script value
    log: bool = False
    doc: str = ""

    def def_value(self, v):
        return v * self.to_si

    def script_line(self, v, layer_no=None, interface_no=None):
        return self.script.format(L=layer_no, I=interface_no,
                                  v=v * self.script_scale)


_P = [
    # ---- material properties: .def only -------------------------------
    Param("Eg", DEF, "eV", field="Eg", doc="bandgap"),
    Param("chi", DEF, "eV", field="chi", doc="electron affinity"),
    Param("eps", DEF, "-", field="eps", doc="relative permittivity"),
    Param("Nc", DEF, "cm^-3", field="Nc", to_si=1e6, log=True,
          doc="conduction band effective density of states"),
    Param("Nv", DEF, "cm^-3", field="Nv", to_si=1e6, log=True,
          doc="valence band effective density of states"),
    Param("mun", DEF, "cm^2/Vs", field="mu_n", to_si=1e-4,
          doc="electron mobility"),
    Param("mup", DEF, "cm^2/Vs", field="mu_p", to_si=1e-4,
          doc="hole mobility"),
    Param("vthn", DEF, "cm/s", field="v_th_n", to_si=1e-2,
          doc="electron thermal velocity"),
    Param("vthp", DEF, "cm/s", field="v_th_p", to_si=1e-2,
          doc="hole thermal velocity"),
    Param("Krad", DEF, "cm^3/s", field="K_rad", to_si=1e-6, log=True,
          doc="radiative recombination coefficient"),
    Param("sigma_bulk", DEF, "cm^2", field="sigma_n", to_si=1e-4, log=True,
          doc="bulk capture cross section (sets sigma_n and sigma_p)"),

    # ---- device parameters: settable from a script --------------------
    Param("NA", SCRIPT, "cm^-3", field="Na(uniform)", to_si=1e6,
          script="set layer{L}.NA {v:.6e}", log=True,
          doc="shallow acceptor density"),
    Param("ND", SCRIPT, "cm^-3", field="Nd(uniform)", to_si=1e6,
          script="set layer{L}.ND {v:.6e}", log=True,
          doc="shallow donor density"),
    # SCAPS scripts take thickness in MICROMETRES while the .def stores
    # METRES. The keyword is 'thickness' -- 'd' appears valid and is
    # silently ignored, which once produced five identical thickness blocks.
    Param("thickness", SCRIPT, "nm", field="d", to_si=1e-9,
          script="set layer{L}.thickness {v:.6f}", script_scale=1e-3,
          doc="layer thickness"),
    Param("Nt_bulk", SCRIPT, "cm^-3", script="set layer{L}.defect1.ntotal {v:.6e}",
          log=True, doc="bulk defect density"),
    # 'ifdefect1', not 'defect1' -- the latter is accepted and does nothing.
    Param("Nt_interface", SCRIPT, "cm^-2", scope="interface",
          script="set interface{I}.ifdefect1.ntotal {v:.6e}", log=True,
          doc="interface defect density (areal)"),
    # 'contactright', not 'rightcontact' as some manuals say.
    Param("BCM", SCRIPT, "eV", scope="front contact", field="Fi_m",
          script="set contactright.workfunction {v:.4f}",
          doc="back-contact metal work function (right contact)"),
    Param("FCM", SCRIPT, "eV", scope="back contact", field="Fi_m",
          script="set contactleft.workfunction {v:.4f}",
          doc="front-contact work function (left contact)"),
    Param("T", SCRIPT, "K", scope="device",
          script="action workingpoint.temperature {v:.2f}",
          doc="temperature"),

    # ---- computed after the fact: no simulations ----------------------
    Param("Rs", POST, "ohm.cm^2", doc="lumped series resistance"),
    Param("Rsh", POST, "ohm.cm^2", log=True, doc="lumped shunt resistance"),
]

REGISTRY: dict[str, Param] = {p.name.lower(): p for p in _P}

# common spellings people will type into a spreadsheet
_ALIASES = {
    "bandgap": "Eg", "band gap": "Eg", "eg (ev)": "Eg",
    "affinity": "chi", "electron affinity": "chi", "x": "chi",
    "permittivity": "eps", "epsilon": "eps", "dielectric": "eps",
    "mu_n": "mun", "mu_p": "mup", "electron mobility": "mun",
    "hole mobility": "mup", "na": "NA", "nd": "ND",
    "acceptor": "NA", "donor": "ND", "d": "thickness",
    "nt": "Nt_bulk", "defect density": "Nt_bulk", "nt_if": "Nt_interface",
    "interface defect": "Nt_interface", "work function": "BCM",
    "wf": "BCM", "series resistance": "Rs", "shunt resistance": "Rsh",
    "temperature": "T",
}


def lookup(name: str) -> Param:
    key = str(name).strip().lower()
    if key in REGISTRY:
        return REGISTRY[key]
    if key in _ALIASES:
        return REGISTRY[_ALIASES[key].lower()]
    raise KeyError(f"unknown parameter {name!r}. Known: "
                   + ", ".join(sorted(p.name for p in _P)))


def describe() -> str:
    """A table of every parameter, for the template's reference sheet."""
    rows = [f"{'name':<14} {'where':<7} {'unit':<10} description"]
    for p in _P:
        rows.append(f"{p.name:<14} {p.target:<7} {p.unit:<10} {p.doc}")
    return "\n".join(rows)
