"""
figures -- publication-ready figures from a project's own outputs.

    scapsml figures project.xlsx --outdir figs

Every figure is written as both PDF (vector, for submission) and PNG (for
drafts). Styling follows what journals actually ask for: a single sans font at
8-9 pt, 0.8 pt lines, no chart junk, no title inside the axes -- captions go in
the manuscript -- and colours that survive greyscale printing and the common
forms of colour blindness.

Figures are built only from data that exists. A project with one simulated
device gets the J-V and band figures; one with a contact sweep also gets the
map. Nothing is invented to fill a panel.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import numpy as np

__all__ = ["style", "save", "fig_jv", "fig_bands", "fig_validation",
           "fig_bandgap", "fig_absorption", "fig_contact_map"]

# Okabe-Ito: colour-blind safe, distinct in greyscale
C = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#000000"]


def style():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
        "font.size": 8.5, "axes.labelsize": 9, "axes.titlesize": 9,
        "legend.fontsize": 7.5, "xtick.labelsize": 8, "ytick.labelsize": 8,
        "axes.linewidth": 0.8, "lines.linewidth": 1.3,
        "xtick.direction": "in", "ytick.direction": "in",
        "xtick.top": True, "ytick.right": True,
        "xtick.major.width": 0.8, "ytick.major.width": 0.8,
        "legend.frameon": False, "figure.dpi": 150,
        "savefig.bbox": "tight", "savefig.pad_inches": 0.02,
        "pdf.fonttype": 42, "ps.fonttype": 42,     # editable text, not outlines
    })
    return plt


def save(fig, outdir, name):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    made = []
    for ext in ("pdf", "png"):
        p = outdir / f"{name}.{ext}"
        fig.savefig(p, dpi=600 if ext == "png" else None)
        made.append(p)
    import matplotlib.pyplot as plt
    plt.close(fig)
    return made


# --------------------------------------------------------------------------
def fig_jv(curves, outdir, name="jv", annotate=True):
    """
    J-V curves. `curves` is [(label, V, J)] in V and mA/cm2.

    Only the generating quadrant is shown, with the maximum-power point
    marked on the first curve: that is what a reader checks first, and it
    makes the fill factor visible rather than a number in a table.
    """
    plt = style()
    from .series import iv_metrics
    fig, ax = plt.subplots(figsize=(3.4, 2.7))
    vocs, jscs = [], []
    for k, (label, v, j) in enumerate(curves):
        m = iv_metrics(v, j)
        if m["Voc"]:
            vocs.append(m["Voc"])
        if m["Jsc"]:
            jscs.append(m["Jsc"])
        ax.plot(v, j, color=C[k % len(C)], label=label, zorder=3)
        if annotate and k == 0 and m["PCE"]:
            p = v * j
            i = int(np.argmax(np.where((v >= 0) & (j >= 0), p, -np.inf)))
            ax.plot([v[i]], [j[i]], "o", ms=4, color=C[0], zorder=4,
                    markerfacecolor="white", markeredgewidth=1.1)
            ax.add_patch(plt.Rectangle((0, 0), v[i], j[i], facecolor=C[0],
                                       alpha=0.10, zorder=1, linewidth=0))
    # Bound the axes by Voc and Jsc, never by the raw arrays. Past Voc the
    # current reverses, and with series resistance the terminal voltage then
    # runs far beyond the device's operating range -- a curve to 1.85 V became
    # 3.05 V at Rs = 10, leaving two thirds of the axis empty.
    vmax = max(vocs) if vocs else max(float(np.nanmax(v)) for _, v, _ in curves)
    jmax = max(jscs) if jscs else max(float(np.nanmax(j)) for _, _, j in curves)
    ax.set_xlim(0, vmax * 1.06)
    ax.set_ylim(0, jmax * 1.12)
    ax.set_xlabel("Voltage (V)")
    ax.set_ylabel("Current density (mA cm$^{-2}$)")
    if len(curves) > 1:
        ax.legend(loc="lower left")
    return save(fig, outdir, name)


def fig_bands(deffile, outdir, name="bands", absorber=None):
    """
    Flat-band energy diagram across the stack.

    Layer widths are drawn proportional to log thickness, so a 25 nm ETL is
    still visible beside an 800 nm absorber. This is a band LINE-UP, not a
    solved band diagram: it shows the offsets that decide whether carriers can
    leave, which is what the contact argument rests on.
    """
    plt = style()
    fig, ax = plt.subplots(figsize=(3.6, 2.8))
    d = deffile
    widths = [np.log10(max(d.get(n, "d"), 1e-9) / 1e-9) for n in d.layers]
    widths = [max(w, 0.6) for w in widths]
    total = sum(widths)
    # Reserve headroom for the layer labels, which sit above each conduction
    # band: without it the shallowest layer's name is clipped by the axis.
    tops = [-d.get(n, "chi") for n in d.layers]
    bots = [-(d.get(n, "chi") + d.get(n, "Eg")) for n in d.layers]
    span = max(tops) - min(bots)
    ylo, yhi = min(bots) - 0.04 * span, max(tops) + 0.16 * span
    x = 0.0
    for n, w in zip(d.layers, widths):
        w = w / total
        chi, eg = d.get(n, "chi"), d.get(n, "Eg")
        ec, ev = -chi, -(chi + eg)
        is_abs = (absorber and n == absorber)
        col = C[1] if is_abs else "#BBBBBB"
        ax.add_patch(plt.Rectangle((x, ev), w, eg, facecolor=col,
                                   alpha=0.45 if is_abs else 0.30,
                                   edgecolor="none", zorder=1))
        for y in (ec, ev):
            ax.plot([x, x + w], [y, y], color="black", lw=1.1, zorder=3)
        ax.plot([x, x], [ev, ec], color="black", lw=0.5, alpha=0.4, zorder=2)
        ax.text(x + w / 2, ec + 0.03 * span, n, ha="center", va="bottom",
                fontsize=6.5, rotation=0 if w > 0.14 else 90)
        ax.text(x + w / 2, (ec + ev) / 2, f"{eg:.2f} eV", ha="center",
                va="center", fontsize=6.5, color="#333333")
        x += w
    ax.set_xlim(0, 1)
    ax.set_ylim(ylo, yhi)
    ax.set_xticks([])
    ax.set_ylabel("Energy vs vacuum (eV)")
    ax.set_xlabel("Position through the stack")
    return save(fig, outdir, name)


SYSTEM_ROWS = [
    ("Project model", ["Workbook\nreader", "Parameter\nregistry",
                       "Anchor\ninterpolation", "Design\nenumeration"]),
    ("Generation", ["Definition\nwriter", "Absorption\nbuilder",
                    "Script\ngenerator", "Manifest"]),
    ("Execution", ["GUI\nrunner", "Resume &\nstatus", "File\ninstaller"]),
    ("Analysis", ["IV parser", "Resistance\nmodel", "Dataset\nbuilder",
                  "Validation", "Figures"]),
]


def fig_system(outdir, name="system", rows=None, system="scapsml",
               foundation="SCAPS-1D solver  (Burgelman et al.)",
               inputs=("Project workbook", "Base .def", "Reference spectra"),
               outputs=("definitions, spectra, scripts",
                        "current-voltage curves",
                        "dataset, validation, figures"),
               crosscut="manifest · status · provenance"):
    """
    System architecture in the idiom used by software-architecture papers:

      * one boundary box that IS the system, so what is inside and what is
        outside is unambiguous;
      * modules grouped into labelled rows, with the group name down the
        right edge rather than repeated on every box;
      * the third-party engine the system is built on drawn as a foundation
        bar across the bottom, since it is depended upon rather than
        contained;
      * external inputs entering from the left and artefacts leaving at the
        bottom, so the boundary is crossed in only two places;
      * a cross-cutting bar for what every stage uses.

    This is a different figure from `fig_workflow`: that one shows the order
    things happen in, this one shows what the software is made of. Papers
    usually need both, and conflating them produces a diagram that answers
    neither question.

    `rows` is [(group label, [module names])] and defaults to SYSTEM_ROWS.
    """
    plt = style()
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

    rows = rows or SYSTEM_ROWS
    EDGE, MOD, GROUP = "#444444", "#FFFFFF", "#F0F0F0"
    TONE = ["#DCE9F5", "#D9EAD8", "#FDE4CF", "#EADCF2"]

    fig, ax = plt.subplots(figsize=(7.2, 4.5))

    sx0, sx1 = 0.215, 0.965          # system boundary
    sy0, sy1 = 0.085, 0.945
    ax.add_patch(FancyBboxPatch((sx0, sy0), sx1 - sx0, sy1 - sy0,
                                boxstyle="round,pad=0.006,rounding_size=0.012",
                                facecolor="#FCFCFC", edgecolor=EDGE, lw=1.3,
                                zorder=1))
    ax.text((sx0 + sx1) / 2, sy1 - 0.028, system, ha="center", va="center",
            fontsize=10.5, fontweight="bold", zorder=4)

    lab_w = 0.055                     # right-edge group label strip
    cx0, cw = sx0 + 0.013, 0.042      # left cross-cutting service bar
    gx0, gx1 = cx0 + cw + 0.013, sx1 - lab_w - 0.020
    fy0, fy1 = sy0 + 0.020, sy0 + 0.085          # foundation bar
    top = sy1 - 0.062
    avail = top - (fy1 + 0.030)
    gh = avail / len(rows)

    for r, (label, mods) in enumerate(rows):
        y1 = top - r * gh
        y0 = y1 - gh + 0.016
        ax.add_patch(FancyBboxPatch((gx0, y0), gx1 - gx0, y1 - y0,
                                    boxstyle="round,pad=0.004,rounding_size=0.008",
                                    facecolor=GROUP, edgecolor="#CCCCCC",
                                    lw=0.7, zorder=2))
        n = len(mods)
        pad = 0.010
        w = (gx1 - gx0 - pad * (n + 1)) / n
        for k, m in enumerate(mods):
            x = gx0 + pad + k * (w + pad)
            ax.add_patch(FancyBboxPatch((x, y0 + 0.014), w, (y1 - y0) - 0.028,
                                        boxstyle="round,pad=0.004,"
                                        "rounding_size=0.008",
                                        facecolor=TONE[r % len(TONE)],
                                        edgecolor=EDGE, lw=0.8, zorder=3))
            ax.text(x + w / 2, y0 + (y1 - y0) / 2, m, ha="center", va="center",
                    fontsize=7.3, linespacing=1.3, zorder=4)
        ax.add_patch(FancyBboxPatch((sx1 - lab_w - 0.008, y0), lab_w,
                                    y1 - y0, boxstyle="round,pad=0.004,"
                                    "rounding_size=0.008", facecolor="#E4E4E4",
                                    edgecolor="#CCCCCC", lw=0.7, zorder=2))
        # Rotated group names are wrapped: a 13-character label set upright
        # in a row 0.8 in tall runs past both ends of its strip. Wrapped, the
        # lines stack across the strip instead of along it.
        ax.text(sx1 - lab_w / 2 - 0.008, y0 + (y1 - y0) / 2,
                "\n".join(textwrap.wrap(label, 9, break_long_words=False)),
                ha="center", va="center",
                fontsize=7.0, fontweight="bold", rotation=90,
                linespacing=1.25, zorder=4)

    # Cross-cutting services span every stage, drawn as a bar beside them
    # rather than as a caption: the manifest, run status and provenance are
    # used by all four groups, and a floating note does not say that.
    ax.add_patch(FancyBboxPatch((cx0, fy1 + 0.030), cw, top - (fy1 + 0.030),
                                boxstyle="round,pad=0.004,rounding_size=0.008",
                                facecolor="#E4E4E4", edgecolor="#BBBBBB",
                                lw=0.7, zorder=2))
    ax.text(cx0 + cw / 2, (top + fy1 + 0.030) / 2, crosscut, ha="center",
            va="center", fontsize=7.0, rotation=90, color="#333333", zorder=4)

    ax.add_patch(FancyBboxPatch((cx0, fy0), sx1 - 0.018 - cx0, fy1 - fy0,
                                boxstyle="round,pad=0.004,rounding_size=0.008",
                                facecolor="#E9E9E9", edgecolor=EDGE, lw=0.9,
                                zorder=3))
    ax.text((cx0 + sx1 - 0.018) / 2, (fy0 + fy1) / 2, foundation, ha="center",
            va="center", fontsize=8, fontstyle="italic", zorder=4)

    # external inputs on the left, crossing the boundary once
    iy = [0.80, 0.66, 0.52]
    for k, lab in enumerate(inputs[:3]):
        y = iy[k]
        ax.add_patch(FancyBboxPatch((0.012, y - 0.037), 0.165, 0.074,
                                    boxstyle="round,pad=0.005,rounding_size=0.010",
                                    facecolor="#FFFFFF", edgecolor=EDGE,
                                    lw=0.9, zorder=3))
        ax.text(0.094, y, lab, ha="center", va="center", fontsize=7.6, zorder=4)
        ax.add_patch(FancyArrowPatch((0.177, y), (sx0, y), arrowstyle="-|>",
                                     mutation_scale=9, lw=0.9, color=EDGE,
                                     shrinkA=1, shrinkB=1, zorder=4))
    ax.text(0.094, 0.885, "User", ha="center", va="center", fontsize=8.5,
            fontweight="bold")
    ax.add_patch(FancyArrowPatch((0.094, 0.868), (0.094, 0.842),
                                 arrowstyle="-|>", mutation_scale=8, lw=0.9,
                                 color=EDGE, zorder=4))

    ax.text((sx0 + sx1) / 2, sy0 - 0.030, "   →   ".join(outputs),
            ha="center", va="top", fontsize=7.0, color="#333333")
    ax.add_patch(FancyArrowPatch(((sx0 + sx1) / 2, sy0), ((sx0 + sx1) / 2,
                                 sy0 - 0.022), arrowstyle="-|>",
                                 mutation_scale=9, lw=0.9, color=EDGE, zorder=4))

    ax.set_xlim(0, 1)
    ax.set_ylim(-0.02, 1.0)
    ax.axis("off")
    return save(fig, outdir, name)


def fig_workflow(outdir, name="workflow", counts=None, stages=None,
                  show_manual=True):
    """
    The project workflow, for a methods section.

    Four columns: inputs the user writes, what the tool generates, what SCAPS
    produces, and what the analysis yields. `counts` fills the real numbers
    for a given project -- {"defs": 486, "spectra": 27, "sims": 2916,
    "rows": 14580, "compositions": 9} -- so the figure describes the study
    that was actually run rather than a generic pipeline.

    The one manual step (driving the SCAPS GUI, which has no batch mode) is
    marked, because a reader assessing reproducibility needs to know which
    parts are automatic.
    """
    plt = style()
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

    c = dict(defs=None, spectra=None, sims=None, rows=None, compositions=None)
    c.update(counts or {})
    n = lambda k, fmt="{:,}": (fmt.format(c[k]) if c[k] is not None else "N")

    INPUT, TOOL, SCAPS, OUT = "#DCE9F5", "#D9EAD8", "#FDE4CF", "#EADCF2"
    EDGE = "#555555"

    # Columns need a real gap between them or the connecting arrows are drawn
    # underneath the next box and vanish.
    col_x = [0.010, 0.263, 0.516, 0.769]
    w = 0.200
    # A box 0.200 wide on a 7.4 in figure is 1.48 in; at 6.6 pt a character is
    # about 0.045 in, so about 32 fit. Wrapped to 26 for margin, rather than
    # trusted to fit -- untrimmed captions ran outside their boxes.
    WRAP = 22

    def box(ax, x, y, h, text, face, bold_first=True, fs=6.9):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.008,"
                                    "rounding_size=0.012", facecolor=face,
                                    edgecolor=EDGE, lw=0.8, zorder=2))
        lines = text.split("\n")
        detail = []
        for ln in lines[1:]:
            detail += textwrap.wrap(ln, WRAP) or [""]
        ax.text(x + w / 2, y + h / 2 + (0.012 if detail else 0), lines[0],
                ha="center", va="bottom" if detail else "center",
                fontsize=fs + 0.7, fontweight="bold" if bold_first else "normal",
                zorder=3)
        if detail:
            ax.text(x + w / 2, y + h / 2 + 0.004, "\n".join(detail),
                    ha="center", va="top", fontsize=fs - 0.4, color="#333333",
                    linespacing=1.4, zorder=3)

    def arrow(ax, x0, y0, x1, y1, label=None, style="-|>"):
        ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle=style,
                                     mutation_scale=9, lw=0.9, color=EDGE,
                                     shrinkA=1.5, shrinkB=1.5, zorder=4))
        if label:
            ax.text((x0 + x1) / 2, (y0 + y1) / 2 + 0.014, label, ha="center",
                    va="bottom", fontsize=6.4, color="#333333", style="italic")

    fig, ax = plt.subplots(figsize=(7.4, 3.5))

    heads = ["1  Define", "2  Generate", "3  Simulate", "4  Analyse"]
    for x, h in zip(col_x, heads):
        ax.text(x + w / 2, 0.955, h, ha="center", va="bottom", fontsize=8,
                fontweight="bold", color="#222222")
        ax.plot([x, x + w], [0.945, 0.945], color="#AAAAAA", lw=0.8)

    box(ax, col_x[0], 0.70, 0.20,
        f"Project workbook\n{n('compositions')} compositions\n"
        "anchors, sweep, experiment", INPUT)
    box(ax, col_x[0], 0.44, 0.18, "Base .def\none reference cell", INPUT)
    box(ax, col_x[0], 0.20, 0.18, "Reference spectra\nper anchor composition", INPUT)

    box(ax, col_x[1], 0.68, 0.22,
        f"Definition files\n{n('defs')} .def\nmaterial variants", TOOL)
    box(ax, col_x[1], 0.42, 0.20,
        f"Absorption files\n{n('spectra')} .abs\nedge at each bandgap", TOOL)
    box(ax, col_x[1], 0.16, 0.20, "Scripts + manifest\none script per\ncomposition", TOOL)

    box(ax, col_x[2], 0.56, 0.24,
        f"SCAPS-1D\n{n('sims')} simulations\nresumable, GUI-driven", SCAPS)
    box(ax, col_x[2], 0.24, 0.22, "Current-voltage\ncurves (.iv)\nstatus per run", SCAPS)

    box(ax, col_x[3], 0.66, 0.24,
        f"Dataset\n{n('rows')} rows\nRs applied analytically", OUT)
    box(ax, col_x[3], 0.36, 0.22, "Validation\nvs measured\nEg and J-V", OUT)
    box(ax, col_x[3], 0.08, 0.20, "Figures\nbands · J-V\ncontact map", OUT)

    # Arrows follow what actually determines what, and are routed so none
    # cross: crossings in a methods figure read as complexity that is not
    # there. The workbook and the base .def both produce the definition
    # files; the reference spectra become the absorption files; the scripts
    # are written against the definition files, so that link stays inside the
    # column; and it is the scripts that SCAPS is given.
    arrow(ax, col_x[0] + w, 0.80, col_x[1], 0.79)
    arrow(ax, col_x[0] + w, 0.53, col_x[1], 0.74)
    arrow(ax, col_x[0] + w, 0.29, col_x[1], 0.50)
    arrow(ax, col_x[1] + w / 2, 0.42, col_x[1] + w / 2, 0.36)
    arrow(ax, col_x[1] + w / 2, 0.68, col_x[1] + w / 2, 0.62)
    arrow(ax, col_x[1] + w, 0.26, col_x[2], 0.66)
    arrow(ax, col_x[2] + w / 2, 0.56, col_x[2] + w / 2, 0.46)
    arrow(ax, col_x[2] + w, 0.35, col_x[3], 0.78)
    arrow(ax, col_x[3] + w / 2, 0.66, col_x[3] + w / 2, 0.58)
    arrow(ax, col_x[3] + w / 2, 0.36, col_x[3] + w / 2, 0.28)

    if show_manual:
        ax.text(col_x[2] + w / 2, 0.815, "only manual step", ha="center",
                va="bottom", fontsize=6.4, color="#B45309", style="italic")
        ax.annotate("", xy=(col_x[2] + w / 2, 0.805), xytext=(col_x[2] + w / 2, 0.81),
                    arrowprops=dict(arrowstyle="-", lw=0.7, color="#B45309"))

    ax.text(0.5, 0.012, "Series and shunt resistance are applied to the finished "
            "curve, so every value costs no extra simulation.",
            ha="center", va="bottom", fontsize=6.6, color="#444444", style="italic")

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1.03)
    ax.axis("off")
    return save(fig, outdir, name)


def fig_architecture(deffile, outdir, name="architecture", absorber=None,
                     roles=None, contacts=("TCO / front contact", "Back contact")):
    """
    Device cross-section: the layer stack, drawn to a compressed thickness
    scale, with names, thicknesses and roles.

    Thicknesses span more than an order of magnitude in a typical cell (25 nm
    ETL against 800 nm absorber), so drawing them to true scale hides the thin
    layers entirely. Heights follow a cube root, which keeps the ordering and
    the sense of relative thickness while leaving every layer legible -- and
    the true value is printed on each layer, so nothing is misrepresented.

    `roles` optionally maps layer name -> role text ("ETL", "HTL", ...);
    otherwise the role is inferred from position around the absorber.
    """
    plt = style()
    d = deffile
    layers = d.layers
    absorber = absorber or layers[len(layers) // 2]
    ai = layers.index(d.block(absorber).name)
    if roles is None:
        roles = {}
        for k, n in enumerate(layers):
            roles[n] = ("Absorber" if k == ai else
                        "ETL" if k == ai - 1 else
                        "HTL" if k == ai + 1 else
                        "Window / TCO" if k < ai else "Buffer")

    nm = [d.get(n, "d") * 1e9 for n in layers]
    h = [max(v, 1.0) ** (1 / 3) for v in nm]
    total = sum(h)
    h = [x / total for x in h]

    fig, ax = plt.subplots(figsize=(3.5, 3.4))
    grey = ["#E8E8E8", "#D6D6D6", "#C4C4C4", "#B2B2B2"]
    y = 0.0
    # drawn top-down: illumination enters the first layer in the .def
    for k in range(len(layers) - 1, -1, -1):
        n, hh = layers[k], h[k]
        face = C[1] if k == ai else grey[k % len(grey)]
        ax.add_patch(plt.Rectangle((0.06, y), 0.62, hh, facecolor=face,
                                   edgecolor="black", lw=0.7,
                                   alpha=0.9 if k == ai else 0.75, zorder=2))
        ax.text(0.37, y + hh / 2, n, ha="center", va="center", fontsize=8,
                fontweight="bold" if k == ai else "normal", zorder=3)
        ax.text(0.70, y + hh / 2, f"{nm[k]:.0f} nm", ha="left", va="center",
                fontsize=7, color="#333333")
        ax.text(0.045, y + hh / 2, roles[n], ha="right", va="center",
                fontsize=7, color="#555555", style="italic")
        y += hh

    # Contact labels sit BESIDE their bars, in the same column as the
    # thicknesses. Centred above the stack they collided with the
    # illumination arrows.
    for y0, label in ((y, contacts[0]), (-0.030, contacts[1])):
        ax.add_patch(plt.Rectangle((0.06, y0), 0.62, 0.030,
                                   facecolor="#4D4D4D", edgecolor="black",
                                   lw=0.7, zorder=2))
        ax.text(0.70, y0 + 0.015, label, ha="left", va="center", fontsize=7.5)

    top = y + 0.030
    for dx in (0.16, 0.30, 0.44, 0.58):
        ax.annotate("", xy=(dx, top + 0.020), xytext=(dx, top + 0.130),
                    arrowprops=dict(arrowstyle="-|>", lw=0.9, color=C[4]))
    ax.text(0.37, top + 0.150, "Illumination (AM1.5G)", ha="center",
            va="bottom", fontsize=7.5, color=C[4])

    ax.set_xlim(0, 1.06)
    ax.set_ylim(-0.075, y + 0.255)
    ax.axis("off")
    return save(fig, outdir, name)


def fig_validation(rows, outdir, name="validation",
                   groups=(("Voc", "Jsc"), ("FF", "PCE")), panel_labels=True):
    """
    Measured against simulated, split across separate figures.

    `groups` decides the split; the default puts the two quantities set by
    optics and electrostatics (Voc, Jsc) in one figure and the two derived
    from them (FF, PCE) in another, so each can be placed and captioned on its
    own. One file is written per group, suffixed _1, _2, ...

    `rows` is [(label, {metric: value})].

    Typography follows what a journal copy editor would ask for: labels
    horizontal so they read without turning the page, value labels in the same
    number of significant figures within a panel, y axes starting at zero
    because these are magnitudes, and panel letters set outside the axes so
    they never collide with a bar.
    """
    plt = style()
    units = {"Voc": "V", "Jsc": "mA cm$^{-2}$", "FF": "", "PCE": "%"}
    names = {"Voc": "$V_{oc}$", "Jsc": "$J_{sc}$", "FF": "FF", "PCE": "PCE"}
    fmt = {"Voc": "{:.3f}", "Jsc": "{:.2f}", "FF": "{:.3f}", "PCE": "{:.2f}"}
    letters = "abcdefgh"
    made, k = [], 0
    for gi, group in enumerate(groups, start=1):
        metrics = [m for m in group if any(d.get(m) is not None for _, d in rows)]
        if not metrics:
            continue
        # Width is derived from the labels themselves. A 7.5 pt character is
        # roughly 0.052 in wide, each label needs its own slot with a gap, and
        # the y axis furniture takes a further ~0.8 in that is NOT available
        # to the labels -- omitting that term is what let three 10-character
        # labels overlap. Long single words ("Experiment") cannot be wrapped,
        # so the panel must simply be wide enough.
        wrapped = {l: "\n".join(textwrap.wrap(l, 11)) for l, _ in rows}
        longest = max((max(len(p) for p in w.split("\n"))
                       for w in wrapped.values()), default=6)
        per = 0.80 + len(rows) * longest * 0.052 * 1.30
        fig, axes = plt.subplots(1, len(metrics),
                                 figsize=(per * len(metrics), 2.5))
        axes = np.atleast_1d(axes)
        for ax, m in zip(axes, metrics):
            labels = [l for l, d in rows if d.get(m) is not None]
            vals = [d[m] for _, d in rows if d.get(m) is not None]
            bars = ax.bar(range(len(vals)), vals, width=0.60,
                          color=[C[i % len(C)] for i in range(len(vals))],
                          zorder=3, edgecolor="none")
            for b, v in zip(bars, vals):
                ax.text(b.get_x() + b.get_width() / 2, v + max(vals) * 0.025,
                        fmt[m].format(v), ha="center", va="bottom", fontsize=7)
            ax.set_xticks(range(len(labels)))
            # Horizontal, centred labels: rotated tick labels are the commonest
            # typographic fault in a bar chart and are avoidable here. Long
            # labels wrap onto a second line rather than tilting or colliding.
            ax.set_xticklabels([wrapped[l] for l in labels], fontsize=7.5,
                               ha="center", linespacing=1.15)
            ax.set_ylabel(names[m] + (f" ({units[m]})" if units[m] else ""))
            ax.set_ylim(0, max(vals) * 1.20)
            ax.margins(x=0.14)
            ax.grid(axis="y", lw=0.4, alpha=0.30, zorder=0)
            ax.set_axisbelow(True)
            ax.tick_params(axis="x", length=0)
            # The global style puts ticks on all four sides, which leaves
            # orphaned marks floating where a spine has been removed.
            ax.tick_params(top=False, right=False)
            for side in ("top", "right"):
                ax.spines[side].set_visible(False)
            if panel_labels:
                ax.text(-0.20, 1.03, f"({letters[k]})", transform=ax.transAxes,
                        fontsize=9, fontweight="bold", va="bottom", ha="left")
            k += 1
        fig.tight_layout(w_pad=1.6)
        made += save(fig, outdir, f"{name}_{gi}")
    return made


def fig_bandgap(anchors, measured, model, outdir, name="bandgap", loo=None):
    """
    Bandgap against composition: the interpolation, the measurements, and --
    if given -- the leave-one-out predictions.

    The leave-one-out markers are the point of the figure. Reproducing a
    measurement that is also an anchor proves nothing; predicting it from the
    others is the test.
    """
    plt = style()
    fig, ax = plt.subplots(figsize=(3.4, 2.7))
    xs = np.linspace(min(a["composition"] for a in anchors),
                     max(a["composition"] for a in anchors), 400)
    ax.plot(xs, [model(x) for x in xs], color=C[0], zorder=2,
            label="interpolation")
    ax.plot([a["composition"] for a in anchors if "Eg" in a],
            [a["Eg"] for a in anchors if "Eg" in a], "s", ms=4.5,
            color=C[0], markerfacecolor="white", zorder=3, label="anchors")
    if measured:
        ax.plot([m["composition"] for m in measured], [m["Eg"] for m in measured],
                "o", ms=5, color=C[1], zorder=4, label="measured")
    if loo:
        ax.plot([p[0] for p in loo], [p[1] for p in loo], "^", ms=5,
                color=C[2], markerfacecolor="white", zorder=5,
                label="leave-one-out")
    ax.set_xlabel("Composition $x$")
    ax.set_ylabel("Bandgap (eV)")
    ax.legend(loc="best")
    return save(fig, outdir, name)


def fig_absorption(spectra, outdir, name="absorption", eg=None):
    """alpha(lambda) overlay on a log axis. `spectra` is [(label, lam, alpha_cm)]."""
    plt = style()
    fig, ax = plt.subplots(figsize=(3.4, 2.7))
    for k, (label, lam, a) in enumerate(spectra):
        ax.semilogy(lam, np.maximum(a, 1e0), color=C[k % len(C)], label=label)
    ax.set_xlabel("Wavelength (nm)")
    ax.set_ylabel(r"Absorption coefficient (cm$^{-1}$)")
    ax.set_ylim(1e2, 1e6)
    ax.legend(loc="best")
    return save(fig, outdir, name)


def fig_contact_map(x, y, z, xlabel, ylabel, outdir, name="contact_map",
                    zlabel="PCE (%)"):
    """Heatmap of a figure of merit over two swept contact parameters."""
    plt = style()
    fig, ax = plt.subplots(figsize=(3.6, 2.8))
    xu, yu = np.unique(x), np.unique(y)
    grid = np.full((len(yu), len(xu)), np.nan)
    for xi, yi, zi in zip(x, y, z):
        grid[np.where(yu == yi)[0][0], np.where(xu == xi)[0][0]] = zi
    im = ax.imshow(grid, origin="lower", aspect="auto", cmap="viridis",
                   extent=[xu.min(), xu.max(), yu.min(), yu.max()])
    for j, yv in enumerate(yu):
        for i, xv in enumerate(xu):
            if np.isfinite(grid[j, i]):
                ax.text(xv, yv, f"{grid[j, i]:.1f}", ha="center", va="center",
                        fontsize=6, color="white")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    fig.colorbar(im, ax=ax, label=zlabel, pad=0.02)
    return save(fig, outdir, name)
