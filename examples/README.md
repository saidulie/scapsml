# Examples

| folder | shows |
|---|---|
| `cspbi3_validation/` | reproducing one published device, with the real SCAPS output of simulating it |
| `batio3xsx/` | a composition study with bandgaps anchored to measured thin films |

Each has a `project.xlsx` (the only file to edit), a `base.def`, and a
`make_workbook.py` that regenerates the workbook from documented sources, so
every number in it can be traced.

```bash
cd examples/batio3xsx
scapsml check    project.xlsx
scapsml generate project.xlsx
scapsml validate project.xlsx
```

`cspbi3_validation/reference_run.iv` is genuine SCAPS 3.3.12 output. To see the
collection and validation stages without SCAPS, generate, then copy it into
`results/` under the filename the manifest expects -- which is exactly what
`tests/test_pipeline.py` does.
