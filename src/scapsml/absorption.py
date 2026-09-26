"""
absorption -- per-design absorption spectra, and a checker for library files.

GENERATION
----------
Each anchor may name a reference spectrum (anchors!abs_file). For a design at
composition s with bandgap Eg:

  1. take the two anchors bracketing s, with blend weight t
  2. shift each spectrum rigidly so its edge sits at the design's Eg. The
     shift uses the ANCHOR'S OWN Eg as the reference point, not a detected
     onset: E' = E - Eg_anchor + Eg_design. That keeps the absorption edge
     consistent with the gap written into the .def by construction, even
     when a digitised spectrum's apparent onset disagrees with it.
  3. blend in log(alpha), which is how absorption actually varies
  4. zero everything below Eg. A sub-gap tail generates carriers that the
     band structure says cannot exist, and shows up as quantum efficiency
     that stays finite past the band edge.

Spectra are read in either SCAPS .abs form (wavelength nm, alpha 1/m) or as
(photon energy eV, alpha 1/m); the domain is detected from the data, since a
file of energies read as wavelengths absorbs nothing across the solar
spectrum and runs without complaint.

CHECKING
--------
check_file() reports where a library file's edge sits, how much sub-gap
absorption it carries, and how much photocurrent it could deliver. Library
spectra are frequently wrong -- mislabelled, or carrying infrared
free-carrier absorption that inflates Jsc. Check before trusting.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

__all__ = ["read_spectrum", "build", "write_abs", "check_file", "verify"]

HC = 1239.841984            # eV nm
Q = 1.602176634e-19
HC_J = 1.98644586e-25


def read_spectrum(path):
    """(energy_eV ascending, alpha_per_m) from a SCAPS-style two-column file."""
    xs, ys = [], []
    for line in Path(path).read_bytes().decode("latin-1").splitlines():
        s = line.strip()
        if not s or s[0] in "/#!;":
            continue
        p = s.replace(",", " ").split()
        if len(p) < 2:
            continue
        try:
            xs.append(float(p[0])); ys.append(float(p[1]))
        except ValueError:
            continue
    if len(xs) < 3:
        raise ValueError(f"{path}: fewer than three data rows")
    x, a = np.array(xs), np.array(ys)
    # SCAPS .abs holds wavelength in nm (hundreds to thousands); photon
    # energies are under ~20 eV. Reading one as the other silently kills
    # absorption, so decide from the data rather than trusting the extension.
    if np.nanmax(x) > 50:
        e = HC / x
    else:
        e = x
    o = np.argsort(e)
    return e[o], np.clip(a[o], 0.0, None)


ONSET_THRESHOLD_CM = 1e4     # a conventional "strongly absorbing" edge
ALPHA_FLOOR = 1.0            # 1/m, keeps log() finite


def measure_onset(e, alpha, threshold_cm=ONSET_THRESHOLD_CM):
    """Lowest photon energy at which alpha exceeds the threshold (cm-1)."""
    idx = np.where(alpha > threshold_cm * 100.0)[0]
    return float(e[idx[0]]) if len(idx) else float(e[0])


def spectrum_onset(anchor, spectra_dir):
    """The spectrum's OWN edge: anchors!abs_onset if given, else measured."""
    e, a = read_spectrum(Path(spectra_dir) / anchor["abs_file"])
    if isinstance(anchor.get("abs_onset"), (int, float)):
        return float(anchor["abs_onset"]), e, a
    return measure_onset(e, a), e, a


def build(lo, hi, t, eg, spectra_dir, u_grid=None):
    """
    Blended spectrum for one design, edge placed at `eg`.

    Each reference is aligned at its OWN edge -- its measured onset, or
    anchors!abs_onset -- and expressed as energy above that edge. The two are
    blended in log(alpha) on that common axis and the result is placed so its
    edge sits at the design bandgap. Aligning at the stated anchor Eg instead
    would leave the absorption edge and the .def gap disagreeing whenever a
    digitised spectrum's apparent onset differs from the gap it is filed
    under, which is common.
    """
    if u_grid is None:
        u_grid = np.linspace(-0.5, 6.0, 1300)
    logs = []
    for anchor in (lo, hi):
        if not anchor.get("abs_file"):
            raise ValueError(f"anchor at composition {anchor['composition']} "
                             f"has no abs_file")
        onset, e, a = spectrum_onset(anchor, spectra_dir)
        u = e - onset
        la = np.log10(np.maximum(a, ALPHA_FLOOR))
        logs.append(np.interp(u_grid, u, la, left=la[0], right=la[-1]))
    la = (1 - t) * logs[0] + t * logs[1]
    e_out = u_grid + eg
    alpha = 10.0 ** la
    alpha[u_grid < 0] = 0.0           # nothing below the gap
    alpha[alpha <= ALPHA_FLOOR] = 0.0
    keep = e_out > 0.05
    return e_out[keep], alpha[keep]


def write_abs(path, e, alpha, header=()):
    """SCAPS .abs: wavelength nm ascending, alpha in 1/m."""
    m = e > 0
    lam = HC / e[m]
    a = alpha[m]
    o = np.argsort(lam)
    lam, a = lam[o], a[o]
    keep = (lam >= 200) & (lam <= 4000)
    with open(path, "w", newline="\r\n") as f:
        for h in header:
            f.write(f"// {h}\n")
        for L, A in zip(lam[keep], a[keep]):
            f.write(f"{L:.4f}\t{A:.6e}\n")


def verify(e, alpha, eg, tail_tol_cm=1e3):
    """[warnings] for a generated spectrum."""
    out = []
    a_cm = alpha / 100.0
    edge_nm = HC / eg
    lam = HC / np.clip(e, 1e-6, None)
    beyond = np.interp(edge_nm + 100, lam[::-1], a_cm[::-1], left=0, right=0)
    if beyond > tail_tol_cm:
        out.append(f"sub-gap tail {beyond:.0f} cm-1 at edge+100 nm")
    if not (alpha > 0).any():
        out.append("absorbs nothing -- check the reference spectra")
    return out


def _flux(spectrum):
    """AM1.5 photon flux per nm, rescaled to 1000 W/m2 whatever the file's units."""
    e, irr = read_spectrum(spectrum)
    lam = HC / e
    o = np.argsort(lam)
    lam, irr = lam[o], irr[o]
    total = np.trapezoid(irr, lam)
    if total > 0:
        irr = irr * 1000.0 / total
    return lam, irr * lam * 1e-9 / HC_J


def check_file(path, eg, thickness_nm=500, spectrum=None, window=False):
    """
    Diagnose a library absorption file against the gap it is meant to have.
    Returns a dict; 'verdict' is the one-line conclusion.
    """
    e, a = read_spectrum(path)
    a_cm = a / 100.0
    lam = HC / e
    edge_nm = HC / eg
    strong = lam[a_cm > 1e4]
    measured_edge = float(strong.max()) if strong.size else float("nan")
    a500 = float(np.interp(500, lam[::-1], a_cm[::-1], left=0, right=0))
    tail = float(np.interp(edge_nm + 100, lam[::-1], a_cm[::-1], left=0, right=0))

    jmax = None
    if spectrum and Path(spectrum).is_file():
        sl, sf = _flux(spectrum)
        al = np.interp(sl, lam[::-1], a[::-1], left=0, right=0)
        jmax = float(Q * np.trapezoid(sf * (1 - np.exp(-al * thickness_nm * 1e-9)),
                                      sl) * 0.1)

    notes = []
    if window:
        if tail > 1e4:
            notes.append(f"UNUSABLE: infrared tail {tail:.0f} cm-1")
        elif tail > 1e3:
            notes.append(f"mild tail {tail:.0f} cm-1 -- check the effect")
        if a500 > 1e4:
            notes.append(f"absorbs strongly in the visible ({a500:.3g} cm-1)")
        if not notes:
            notes.append("transparent -- good window layer")
    else:
        if not np.isnan(measured_edge) and abs(measured_edge - edge_nm) > 60:
            notes.append(f"edge off by {measured_edge - edge_nm:+.0f} nm")
        if tail > 1e3:
            notes.append(f"sub-gap tail {tail:.0f} cm-1")
        if a500 < 1e4 and edge_nm > 500:
            notes.append("weak in the visible")
        if not notes:
            notes.append("consistent with Eg")
    return {"file": str(path), "edge_nm": measured_edge, "expected_edge_nm": edge_nm,
            "alpha_500_cm": a500, "tail_cm": tail, "jmax": jmax,
            "verdict": "; ".join(notes)}
