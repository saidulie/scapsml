"""
bands -- band alignment at the absorber's two contacts.

A cell whose absorber cannot hand carriers to its transport layers produces no
current however good the absorber is, and SCAPS spends a long time failing to
converge before saying so. This is cheap to check on the numbers alone, so
`scapsml check` does it for every design before anything is simulated.

Sign convention, both quoted as BARRIERS (positive is bad):

  electron side   chi(absorber) - chi(ETL)
      positive means the absorber's conduction band lies BELOW the ETL's, so
      electrons must climb to leave: a spike.
  hole side       Ev(absorber) - Ev(HTL)     with Ev = chi + Eg
      positive means the absorber's valence band lies BELOW the HTL's, so
      holes must climb: a barrier.

A small negative value (a cliff) is usually tolerable and can even help
selectivity. A spike beyond roughly 0.3 eV throttles the current, and beyond
0.5 eV usually stops the device working at all.
"""

from __future__ import annotations

__all__ = ["barriers", "verdict", "SPIKE_WARN", "SPIKE_FAIL"]

SPIKE_WARN = 0.30      # eV
SPIKE_FAIL = 0.50      # eV


def _ev(d, layer):
    return d.get(layer, "chi") + d.get(layer, "Eg")


def barriers(d, absorber):
    """
    {"electron": eV or None, "hole": eV or None, "etl": name, "htl": name}

    The ETL is the layer before the absorber and the HTL the layer after,
    which is how a .def is ordered: illumination enters from the left.
    """
    layers = d.layers
    i = layers.index(d.block(absorber).name)
    etl = layers[i - 1] if i > 0 else None
    htl = layers[i + 1] if i + 1 < len(layers) else None
    out = {"etl": etl, "htl": htl, "electron": None, "hole": None}
    if etl:
        out["electron"] = round(d.get(absorber, "chi") - d.get(etl, "chi"), 4)
    if htl:
        out["hole"] = round(_ev(d, absorber) - _ev(d, htl), 4)
    return out


def verdict(b):
    """(level, message) where level is 'ok', 'warn' or 'fail'."""
    worst, where = 0.0, ""
    for key, carrier in (("electron", "electrons into the ETL"),
                         ("hole", "holes into the HTL")):
        v = b.get(key)
        if v is not None and v > worst:
            worst, where = v, carrier
    if worst >= SPIKE_FAIL:
        return "fail", (f"{worst:+.2f} eV barrier to {where} -- this device "
                        f"cannot extract carriers")
    if worst >= SPIKE_WARN:
        return "warn", f"{worst:+.2f} eV barrier to {where} -- current will be throttled"
    return "ok", "both contacts extract"


def report(d, absorber, designs, build, project, limit=6):
    """
    Lines summarising alignment across designs, plus (n_fail, n_warn).

    Every design is checked, because a sweep over affinity or bandgap moves
    the band edges and a stack that works at one composition can block at
    another.
    """
    rows, n_fail, n_warn = [], 0, 0
    worst = []
    for dz in designs:
        dd = build(project, d, dz)
        b = barriers(dd, absorber)
        lvl, msg = verdict(b)
        n_fail += lvl == "fail"
        n_warn += lvl == "warn"
        worst.append((max(v for v in (b["electron"], b["hole"]) if v is not None),
                      dz, b, lvl, msg))
    worst.sort(key=lambda t: -t[0])
    lines = [f"  {'composition':>11} {'variant':<34} {'e- spike':>9} "
             f"{'h+ barrier':>11}  verdict"]
    for _, dz, b, lvl, msg in worst[:limit]:
        var = ", ".join(f"{k.replace('_offset','').replace('_factor','x')}"
                        f"={v:g}" for k, v in dz.varied)
        lines.append(f"  {dz.composition:>11.4g} {var[:34]:<34} "
                     f"{b['electron']:>+9.2f} {b['hole']:>+11.2f}  {lvl.upper()}")
    return lines, n_fail, n_warn, (worst[0][2] if worst else None)
