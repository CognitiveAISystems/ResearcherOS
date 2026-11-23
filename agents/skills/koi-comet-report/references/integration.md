# ResearchOS integration

## Architecture

`agents/skills/koi-comet-report/` is the single canonical implementation. Cursor discovers the same directory through the relative `.cursor/skills/koi-comet-report` symlink. Codex installations can expose it with another relative symlink rather than copying the skill.

The CLI is deliberately outside the ResearchOS API and web processes. It reads experiments through the Comet public API and writes ordinary report artifacts:

1. `metrics.csv` preserves every finite numeric point used by the build.
2. `summary.json` records first, last, global range, and final-window statistics.
3. `manifest.json` records run ids, cutoffs, requested metrics, missing metrics, chart definitions, and whether smoothing was applied.
4. PNG files are embedded into a ResearchOS Markdown report with relative paths.

This boundary keeps external credentials and a plotting stack out of the server. It also makes every figure independently reproducible from the exported CSV and manifest.

## Install optional dependencies

From the ResearchOS repository:

```bash
python -m pip install -r agents/skills/koi-comet-report/requirements.txt
cp .env.example .env
```

Set `COMET_API_KEY` in `.env`. Do not commit `.env` or generated artifacts containing private experiment data.

## Build artifacts for a report

Copy the example configuration into the project or a temporary directory, replace run ids and panel definitions, then run:

```bash
set -a
source .env
set +a

python agents/skills/koi-comet-report/scripts/comet_report.py build \
  --config path/to/comet-report.json \
  --out projects/PROJECT/reports/NODE/assets/CARD
```

Reference a generated image from the report:

```markdown
![Динамика качества и безопасности](assets/CARD/quality.png)
```

Keep `metrics.csv`, `summary.json`, and `manifest.json` beside the images when the report must remain auditable. Use a temporary output directory when only visual inspection is required.

## Why this integration is reproducible

- Comet experiment ids identify the remote source.
- `max_step` and visible axis limits are explicit configuration, not hidden plotting state.
- Raw finite points are exported before plotting.
- No smoothing or interpolation is applied by default.
- Missing metrics are recorded and optionally made fatal with `--strict`.
- Metric semantics remain separate: episodic cost represents environment violations, while `cost_critic/vf_loss` represents critic optimization loss.
