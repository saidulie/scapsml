# scapsml

**Workbook-driven SCAPS-1D parameter sweeps and supervised machine learning for solar-cell design.**

Describe your cell and the parameters to vary in an Excel workbook. `scapsml` builds every SCAPS definition file and script, drives the SCAPS GUI through thousands of simulations, collects the results into an ML-ready dataset, and trains and interprets models on it. You never edit a `.py` file.

```
project.xlsx ──► scapsml generate ──► .def / .abs / .script ──► scapsml run ──► .iv
                                                                                  │
            metrics.json · SHAP plots · candidates.csv ◄── scapsml ml ◄── scapsml collect
```

It works for any cell — any number of layers, any absorber, any stack — because the workbook names parameters (`Eg`, `NA`, `thickness`, `BCM`) and a registry knows where each one lives in SCAPS and what unit it needs.

---

## Install

```bash
pip install "scapsml[all] @ git+https://github.com/saidulie/scapsml"
```

or from a clone:

```bash
git clone https://github.com/saidulie/scapsml && cd scapsml
pip install -e ".[all]"
```

| extra | adds | needed for |
|---|---|---|
| *(none)* | numpy, openpyxl, scikit-learn, matplotlib | generating, collecting, validating |
| `ml` | xgboost, shap | the full model comparison and SHAP |
| `gui` | pyautogui, pywin32, … | **driving SCAPS** — Windows only |
| `dev` | pytest | the test suite |

Generation, collection, validation and ML run anywhere. Only `scapsml run` needs Windows, because SCAPS has no batch mode and must be driven through its GUI.

---

## Quick start

```bash
scapsml init my_cell.xlsx --def my_cell.def   # a WORKING baseline read from your .def
# edit my_cell.xlsx: anchors, sweep, experiment
scapsml check    my_cell.xlsx                 # validate everything before running
scapsml generate my_cell.xlsx                 # defs, spectra, scripts, manifest
scapsml run      my_cell.xlsx                 # drive SCAPS; resumable, Ctrl-C safe
scapsml collect  my_cell.xlsx                 # results -> dataset.csv
scapsml validate my_cell.xlsx                 # compare against measurements
scapsml ml       my_cell.xlsx                 # models, SHAP, inverse design
```

`init --def` reads your absorber's properties back out of the `.def`, converts them to workbook units and writes them as the first anchor, so `check` passes immediately and `generate` reproduces your original cell exactly. You start from a baseline that works and edit it, rather than from an empty form. The absorber is identified from evidence in the file — the layer with a measured absorption spectrum and a bulk defect block — not from bandgap alone, which picks the wrong layer whenever the absorber is wider-gap than its transport layers.

Two worked examples ship with the package — see [Examples](#examples).

---

## The workbook

The only file you edit. `scapsml init` writes one with dropdowns on every parameter column, so an invalid name cannot be typed, and a `reference` sheet listing every parameter with its unit.

| sheet | holds |
|---|---|
| **project** | the base `.def`, which layer is the absorber, where files go |
| **anchors** | material properties at known compositions — interpolated in between |
| **interpolation** | optional: `linear`, `log` or `pchip` per property |
| **sweep** | what to vary, and over which values |
| **layers** | optional: fixed changes to any other layer — ETL, HTL, contacts |
| **experiment** | optional: measurements to validate against |
| **reference** | generated: every valid parameter name |

### Anchors

One row per known composition, one column per property. Values between anchors are interpolated; outside them they are **clamped, never extrapolated**.

| composition | Eg | IP | eps | Nc | abs_file |
|---|---|---|---|---|---|
| 0.243 | 1.51 | 6.38 | … | … | |
| 0.287 | 1.35 | 6.30 | … | … | |
| 0.333 | | | | | `ref_x033.abs` |

Give electron affinity either directly (`chi`) or through the ionisation potential (`IP`), in which case χ = IP − Eg. Rows that only name a spectrum are fine: absorption is blended between the spectrum anchors, independently of the property anchors.

### Sweep

| parameter | layer | mode | values |
|---|---|---|---|
| composition | | absolute | `0.20:0.36:0.01` |
| Eg | | offset | `-0.1, 0, 0.1` |
| NA | | absolute | `log:1e15:1e17:3` |
| Nt_interface | Absorber/HTL | absolute | `1e10, 1e12` |
| Rs | | absolute | `0, 2, 5, 8` |

**values** accepts a list (`1e15, 1e16`), an inclusive range (`20:36:1`), `lin:a:b:n` or `log:a:b:n`.

**mode** `offset` adds to the interpolated anchor value and `factor` multiplies it. Use them to sweep a material property *around* its composition value — which is what makes a feature-importance analysis meaningful, since a property that is an exact function of composition cannot be separated from it by any model.

### Where each parameter goes, and what it costs

```
scapsml params
```

| where | examples | cost per value |
|---|---|---|
| `def` | Eg, chi, eps, Nc, Nv, mun, mup | one new definition file |
| `script` | NA, ND, thickness, Nt_bulk, Nt_interface, BCM | one simulation |
| `post` | Rs, Rsh | **nothing** |

Material properties are `def`-only because SCAPS's script keywords for them are accepted and silently ignored. Series and shunt resistance cost nothing: SCAPS applies them as a lumped post-process on the finished IV curve, and `scapsml` reproduces that transformation exactly, so one simulation yields every resistance value.

---

## What it gets right that is easy to get wrong

Each of these cost a full overnight run to find.

**Defect levels cannot fall outside the gap.** A trap outside the band gap makes SCAPS reject the problem before solving and write an empty `.iv`. `scapsml` pins every bulk trap to *above Ei* and every interface trap to *above the middle of the interface gap*, both with Et = 0, so levels follow the band edges wherever they move. Computing Et numerically instead emptied 2,178 of 4,422 runs in one campaign.

**Absorption follows the bandgap.** Each design gets its own spectrum with its edge at that design's gap. Reference spectra are aligned at their own measured edges before blending, so a digitised spectrum whose apparent onset differs from its stated gap still lands correctly.

**Series resistance is exact, and the sweep starts below zero.** Applying R_s shifts the curve by J·R_s. The sweep start voltage is derived from the largest R_s so the shifted curve still contains V = 0 and Jsc is read rather than extrapolated.

**The `.def` is positional, and treated that way.** Switching a layer's absorption from model to file means deleting three lines, not leaving them behind; left in, they shift every following line and SCAPS mis-parses the block silently. Files round-trip byte-for-byte when unedited, including CRLF line endings.

**Interfaces are found by position, not name.** Interface names in a `.def` are free text and go stale when layers are renamed. Interface *k* sits between layers *k* and *k+1*, which is all SCAPS relies on.

**Script keywords are the verified ones.** `thickness` not `d`, `epsilon` not `eps`, `ifdefect1` not `defect1`, `contactright` not `rightcontact`, `startlambda` not `wl1`. Each wrong form runs cleanly and does nothing.

**SCAPS is deterministic.** Byte-identical output means the change never reached the solver. When a sweep axis shows no effect, suspect the keyword before the physics.

---

## Figures

```bash
scapsml figures my_cell.xlsx --outdir figs
```

Vector PDF for submission and 600 dpi PNG for drafts, in a single sans font at
8-9 pt with colour-blind-safe, greyscale-safe colours. System architecture and a
workflow schematic for the methods section, the latter carrying this
project's own counts; device architecture
schematic; band line-up; J-V with
the series-resistance family drawn from one simulation; bandgap against
composition with leave-one-out markers; measured against simulated; absorption
overlay; and a contact map over any two swept parameters
(`--map-x chi@TiO2 --map-y chi@Spiro-OmeTAD`).

Only figures the data supports are produced -- nothing is invented to fill a
panel.

## Validation

```bash
scapsml validate my_cell.xlsx
```

Two levels, reported separately.

**Material** — measured bandgaps against the anchor interpolation. Run this first: an interpolation that misses the measurements makes every device result wrong. Where a measurement is also an anchor it is reproduced by construction, so `scapsml` automatically runs **leave-one-out** as well — dropping each measured anchor and asking whether the rest predict it.

**Device** — measured Voc, Jsc, FF, PCE against simulated results. For a validation project reproducing one published cell, that is a direct comparison. For a sweep, it reports the simulated range and whether the measurement falls inside.

A 1D drift-diffusion model with no reflection, series resistance, grain boundaries or shunt paths is systematically optimistic in FF and Voc. The report says so rather than presenting the gap as a failure.

---

## Machine learning

```bash
scapsml ml my_cell.xlsx --target PCE
```

**Features are discovered, not listed**, so any stack works. Resolved physical values (Eg, χ, ε) are used; the sampling columns that produced them (`Eg_offset`) are not, since value = interpolation + offset makes the three linearly dependent. Remaining exact dependencies are pruned by correlation.

**Eight algorithms** on identical folds: linear, decision tree, random forest, extra trees, gradient boosting, XGBoost, SVR, MLP.

**Three validation schemes.** On a structured grid a random split is optimistic — a held-out row usually sits between two training rows. Grouping by composition asks about an unseen composition; blocking asks about an unseen *region*.

```
random k-fold            R² = 0.99     interpolation inside the grid
grouped by composition   R² = 0.91     a composition never seen
blocked composition      R² < 0        a region never seen
```

Quote the grouped and blocked numbers. A negative blocked score means the surrogate interpolates but does not extrapolate: frame it as an **interpretation** tool, not a predictive one.

**SHAP runs twice** — all features, then the non-correlated subset. A feature whose importance collapses between passes was borrowing signal from a correlated partner.

**Inverse design** proposes candidates with 90% prediction intervals, filtered by a convergence classifier. When the optimum falls outside its own interval the optimiser has left the sampled region, and the report says to quote the best *measured* cell instead.

---

## Running SCAPS

```bash
scapsml run    my_cell.xlsx              # everything outstanding
scapsml run    my_cell.xlsx 0.25 0.29    # named compositions
scapsml run    my_cell.xlsx --next 3     # three at a time
scapsml status my_cell.xlsx              # works on any machine
```

**Resumable.** A composition whose results all exist is skipped, so a plain `run` resumes. Ctrl-C is safe. A header-only `.iv` — SCAPS rejecting a problem — counts as done, since rerunning cannot change it.

**Partial results are usable.** `collect` marks absent runs `MISSING` and writes the rest, so run `ml` after the first few compositions to confirm the dataset is well formed before committing the remaining hours.

**Calibration.** SCAPS button positions depend on screen resolution. The first time on a new machine:

```bash
scapsml calibrate my_cell.xlsx
```

hover over each button when prompted, and paste the four coordinates into the `project` sheet.

**Permissions.** SCAPS lives under `Program Files`, which is UAC-protected. Either run the shell as administrator, or grant write access once:

```powershell
icacls "C:\Program Files (x86)\Scaps3312\def"        /grant "$($env:USERNAME):(OI)(CI)M"
icacls "C:\Program Files (x86)\Scaps3312\absorption" /grant "$($env:USERNAME):(OI)(CI)M"
```

The `$(...)` is required — a bare `$env:USERNAME:` swallows the colon.

---

## Checking absorption files

```bash
scapsml inspect-abs "C:/Program Files (x86)/Scaps3312/absorption/*.abs" --eg 1.6
scapsml inspect-abs FTO.abs --eg 3.5 --window     # judge as a window layer
```

Library spectra are frequently wrong. Of five CsPbI₃ files in one SCAPS installation the edges spanned 429–882 nm against the 711 nm the gap implied; a `TiO2 (1).abs` absorbed strongly into the infrared while `Tio2.abs`, differing only in capitalisation, was clean. Degenerate oxides (ITO, SnO₂) often carry free-carrier absorption that, used as a window layer, pushed generation from 16 to 70 mA/cm². Check before trusting.

---

## Examples

### `examples/cspbi3_validation` — reproducing a published device

ITO / SnO₂ / CsPbI₃ / spiro-OMeTAD, from Rahman et al. (*ChemistrySelect* 2026), replicating the experimental cell of Wang et al. Ships with the real SCAPS output of simulating it.

| | Voc (V) | Jsc (mA/cm²) | FF | PCE (%) |
|---|---|---|---|---|
| experiment | 1.097 | 18.00 | 0.741 | 14.67 |
| reference SCAPS | 1.093 | 16.45 | 0.862 | 15.50 |
| **scapsml** | **1.291** | **16.27** | **0.869** | **18.24** |

Jsc within 1.1% and FF within 0.8% of the reference simulation. Voc differs because the source quotes interface defect density in cm⁻³ where SCAPS requires cm⁻².

### `examples/batio3xsx` — a composition study anchored to measurements

BaTi(O₁₋ₓSₓ)₃ over x = 0.20–0.36, with bandgaps anchored to measured thin films (x = 0.243, 0.253, 0.287 → 1.51, 1.45, 1.35 eV). Leave-one-out predicts each held-out measurement to within 0.045 eV. Sweeps bandgap, affinity and permittivity around their composition values, plus doping, contact work function and series resistance: 17 compositions, 459 definition files, 2,754 simulations, 13,770 dataset rows.

---

## Tests

```bash
pytest                    # 200 tests
pytest -W error           # the CI configuration: warnings are failures
```

CI runs it on Linux, Windows and macOS against Python 3.9–3.12, with a clean install each time. That matters: one failure only appeared in a fresh environment, because SHAP emits a deprecation warning at *import* time that a long-running session had already cached away.

The suite runs against two real `.def` files, real SCAPS output, and a real 600-row dataset from an earlier campaign written by a different pipeline — which is what shows feature discovery does not depend on column names. It asserts the physics of the series-resistance transform against an analytic diode, byte-exact `.def` round trips, every unit conversion, every verified script keyword, and that no generated trap can fall outside its gap.

---

## Citing

If you use `scapsml` in published work, please cite it (see `CITATION.cff`) and **cite SCAPS-1D itself**:

> M. Burgelman, P. Nollet, S. Degrave, *Thin Solid Films* **361–362**, 527–532 (2000).

SCAPS is developed at the University of Gent and is not distributed with this package. Obtain it from the developers.

## License

MIT — see `LICENSE`.
