# Changelog

## 0.2.3

- New `fig_system`: a software-architecture figure in the idiom used by
  architecture papers -- one boundary box that IS the system, modules grouped
  into labelled rows with the group name down the right edge, the third-party
  engine drawn as a foundation bar because it is depended on rather than
  contained, cross-cutting services as a bar spanning every stage, and the
  boundary crossed in only two places (inputs left, artefacts bottom).
  Distinct from `fig_workflow`, which shows the order things happen in: a
  paper usually needs both, and conflating them answers neither question.

## 0.2.2

- New `fig_workflow`: the project pipeline as a methods figure -- what the
  user writes, what the tool generates, what SCAPS produces, what the analysis
  yields -- carrying the real counts for the project it is generated from, and
  marking the one manual step. Arrows are routed so none cross, since
  crossings read as complexity that is not there.

## 0.2.1

- New `fig_architecture`: device cross-section with layer names, thicknesses,
  roles, contacts and the illumination direction. Heights follow a cube root
  so a 25 nm ETL stays legible beside a 350 nm absorber while the ordering is
  preserved, and the true thickness is printed on every layer.
- `fig_validation` now splits across figures (Voc/Jsc, then FF/PCE) so each can
  be placed and captioned separately.
- Bar-chart typography: labels horizontal and never rotated, panel width
  derived from the label lengths INCLUDING the y-axis furniture, consistent
  significant figures per panel, no orphaned ticks on removed spines.

## 0.2.0

- New `scapsml figures`: publication-ready figures from a project's own
  outputs, as vector PDF (editable text, fonttype 42) and 600 dpi PNG.
  Band line-up, J-V with the series-resistance family, bandgap against
  composition with leave-one-out markers, measured-against-simulated panels,
  absorption overlay, and a contact map over two swept parameters.
  Only figures the available data supports are produced.
- J-V axes are bounded by Voc and Jsc, never by the raw arrays: past Voc the
  current reverses and the series-resistance shifted voltage runs far beyond
  the device, leaving most of the axis empty.

## 0.1.2

- `scapsml check` now reports BAND ALIGNMENT at the absorber's two contacts
  and refuses to pass a stack that cannot extract carriers. A blocked device
  produces no current however good the absorber, and SCAPS is slow to fail:
  one run spent an hour producing 34 results, none of them usable.
- The BaTiO3 example shipped with exactly that fault. With the corrected
  electron affinity the absorber sits at chi 4.79-5.09 eV and Ev 6.18-6.46 eV,
  so TiO2 (chi 4.20) and spiro (Ev 5.10) gave a +0.75 eV electron spike and a
  +1.22 eV hole barrier. The example now SWEEPS the ETL affinity and HTL
  valence band, which is the open question that correction raised, and the
  back-contact work function was deepened to match the HTL -- at 5.1-5.4 eV it
  was a third barrier.
- The example is trimmed to 2,916 simulations so it can be run in an evening;
  the two cells to widen it are marked in `make_workbook.py`.

## 0.1.1

Fixes wrong Jsc, FF and PCE from sweeps that start below 0 V. Raw `.iv` files
were always correct; rerun `scapsml collect` and every number is repaired. No
simulation needs repeating.

- SCAPS writes some sweeps in DESCENDING voltage order (a -0.5 to 1.85 V sweep
  came back 1.85 V first). Extraction walked the file in order, took Voc as the
  first zero crossing, discarded the working curve and reported Jsc 56.6 mA/cm2
  and PCE 3.75 % for a cell with Jsc 16.40 and PCE 18.39 %. Curves are now put
  in ascending voltage where the file is read.
- The Jsc fallback no longer extrapolates from far forward bias. It extends a
  curve only if it starts within 0.10 V of short circuit; otherwise the value
  is reported missing rather than invented.
- New physical check: a Jsc above SCAPS's own generation current, or an FF
  outside (0, 1], is marked SUSPECT and excluded from modelling. This would
  have caught the fault above immediately.
- Regression tests use the real descending SCAPS output.

## 0.1.0

First release.

- Excel workbook as the single input: project, anchors, interpolation, sweep,
  layers, experiment, with dropdown validation and a generated reference sheet.
- Generic `.def` reader/writer addressing blocks by name, byte-exact round trips
  including CRLF, position-safe absorption model/file switching.
- Parameter registry: location (`def` / `script` / `post`), unit conversion and
  sampling scale for every sweepable parameter, with verified SCAPS keywords.
- Interpolation: linear, log and monotonic PCHIP; clamped, never extrapolated.
  Electron affinity direct or derived from ionisation potential.
- Absorption spectra aligned at their own measured edges, blended in log alpha,
  placed at each design's bandgap and zeroed below it.
- Every trap pinned to midgap by construction (bulk: above Ei; interface: above
  the middle of the interface gap).
- Exact lumped series/shunt resistance, parametric metric extraction robust to
  folded curves, sweep start voltage derived from the largest Rs.
- Resumable SCAPS GUI runner with Win32 dialog handling, button calibration,
  and actionable UAC errors.
- Validation against measurements at material level (with automatic
  leave-one-out) and device level.
- ML: discovered features, eight algorithms, random / grouped / blocked
  validation, dual-pass SHAP, inverse design with prediction intervals.
- `init --def` writes a working baseline read from the .def, so check passes
  and generate reproduces the original cell. Absorber identified from the
  file's evidence (absorption source, bulk defects) rather than bandgap alone.
- Warning filters are scoped to the third-party calls that need them. The
  package never changes process-wide warning state on import.
