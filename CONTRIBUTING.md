# Contributing

## Setup

```bash
git clone https://github.com/<you>/scapsml && cd scapsml
pip install -e ".[all]"
pytest -W error
```

CI runs `pytest -W error` on Linux, Windows and macOS. Warnings are failures:
an unclosed file handle is a leak on Linux and a lock on Windows.

## Adding a parameter

Add one `Param` to `_P` in `src/scapsml/registry.py`, then a test in
`tests/test_registry.py` asserting its unit conversion and, for script
parameters, the exact command it produces.

**Verify a new script keyword in SCAPS before adding it.** Several plausible
keywords (`d`, `eps`, `defect1` on an interface, `rightcontact`) are accepted
and silently ignored. The check: type the command into SCAPS's Script set-up
editor and read the Argument dropdowns, then confirm a sweep over it produces
outputs that actually differ. SCAPS is deterministic, so byte-identical results
mean the keyword never reached the solver.

## Reporting a problem

Include the workbook, the base `.def`, and the output of `scapsml check`.
