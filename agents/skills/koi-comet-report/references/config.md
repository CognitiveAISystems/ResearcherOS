# Configuration

The CLI accepts UTF-8 JSON with these fields:

- `workspace`, `project`: Comet location.
- `tail`: number of final points used for tail statistics; defaults to 20.
- `runs`: ordered list of experiments. Each run needs `id` and may define `label`, `color`, and `max_step`.
- `panels`: output figures. Each panel needs `file` and `charts`.
- Each chart needs `metric`; optional fields are `title`, `ylabel`, and `ylim: [min, max]`.

`max_step` is an explicit presentation cutoff. Omit it to use the complete run. `ylim` changes only the displayed range; raw values remain in `metrics.csv` and `summary.json`.

Use `inspect` to discover exact metric names before editing a config. The output directory is intentionally separate from the configuration so the same comparison can be rendered into a temporary QA directory or a report asset directory.
