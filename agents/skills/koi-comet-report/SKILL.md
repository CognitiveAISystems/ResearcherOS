---
name: koi-comet-report
description: Export Comet ML experiment metrics, compare runs, calculate tail summaries, and generate unsmoothed report-ready charts. Use when a researcher asks to inspect a Comet run, download its metrics, compare experiments, update report graphs, or package Comet artifacts for ResearchOS.
---

# Build reports from Comet ML

Use `scripts/comet_report.py` instead of writing a new one-off Comet parser.

## Workflow

1. Resolve the workspace, project, experiment ids, comparison cutoff, and desired panels from the request or existing report.
2. Require `COMET_API_KEY` in the environment. Never print, copy, commit, or embed it.
3. Copy and adapt `references/example-config.json`. Preserve raw metric names in configuration and use human-readable chart labels separately.
4. Run `inspect` when metric names are uncertain. Run `build` to export raw data, create summaries, and render charts.
5. Inspect generated PNGs before adding them to a report. Check titles, legends, clipping, axis ranges, and whether sparse or degenerate series make a statistic misleading.
6. Report the experiment ids, maximum observed step, cutoffs, output paths, and missing metrics. Do not interpret a value-function loss as an environment cost or violation count.

## Commands

```bash
python scripts/comet_report.py inspect \
  --workspace WORKSPACE --project PROJECT --run EXPERIMENT_ID

python scripts/comet_report.py build \
  --config references/example-config.json --out artifacts/comet-report

python scripts/comet_report.py build \
  --config references/example-config.json --out artifacts/comet-report \
  --all-metrics
```

`build` writes `metrics.csv`, `summary.json`, `manifest.json`, configured panel PNGs, and—when requested—one PNG for every numeric metric.

Read [references/config.md](references/config.md) when creating or changing a configuration. Read [references/integration.md](references/integration.md) when installing the skill or connecting its artifacts to a ResearchOS report.

## Invariants

- Plot raw values by default; do not silently smooth, interpolate, truncate, or clamp them.
- Every explicit cutoff and `ylim` must be visible in `manifest.json` and disclosed in the report caption.
- Use equal cutoffs for direct run comparisons unless the requested comparison explicitly concerns different training horizons.
- Treat absent metrics as missing data: record them in the manifest and continue other panels unless `--strict` is set.
- Use `cost_critic/vf_loss` labels such as “cost critic loss”, not “environment violations”. Use episodic cost metrics for actual violations.
- Keep exported raw points so every chart can be reproduced.
