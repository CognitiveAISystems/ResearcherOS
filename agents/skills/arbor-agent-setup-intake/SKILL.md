---
name: arbor-agent-setup-intake
description: "Setup, intake, preflight, and launch-contract phase for open-source Arbor runs. Use when confirming a target project, metric, baseline, dev/test split, config/plugin settings, branch guard, session directory, or when translating a user goal into the precise contract consumed by the coordinator."
---

# Arbor Setup And Intake

Use this before the coordinator starts. The output is a concrete research
contract plus a clean workspace/session ready for the Arbor cycle.

## Fast Path

1. Confirm the target project directory. Treat the launch cwd as the default
   unless evidence says it is wrong.
2. Inspect README/config/eval files yourself. Do not ask the user to recite
   data you can read.
3. Identify the primary metric, direction, and real evaluation command.
4. Determine B_dev and B_test. If only one split exists, call it B_dev and
   record that no separate B_test is available.
5. Run or locate a cheap baseline when feasible. If not feasible, state
   `baseline unknown - measure during INIT`.
6. Propose one complete contract and ask for a single yes/edit confirmation.
7. Initialize or select `.arbor/sessions/<run_name>/` and hand the contract
   to the coordinator.
8. If real merges are allowed, define a non-protected `trunk_branch` such as
   `arbor/trunk/<run_name>`. Treat `main`/`master` as the base branch, not the
   merge target.

For smoke/forward tests, never run expensive setup, data prep, training, GPU
jobs, or the discovered full eval command. Locate an existing score in cached
metadata/logs or use a clearly labelled mocked score, and include
`smoke-only` in the contract.

## Research Contract

The instruction passed to the coordinator must contain all five components:

- **Metric**: exact score name, command that prints it, and maximize/minimize.
- **Baseline anchor**: current value if known, otherwise say it will be
  measured in INIT.
- **Ambition**: beat baseline, reach a target, or push as high as possible
  within the cycle budget.
- **Scope preference**: novelty-leaning, effect-leaning, or mixed. Infer it
  from the repo/task when possible.
- **Hard constraints**: at minimum, B_test is not for iteration, data/eval
  harness must not be modified to game the metric, and project-specific
  protected paths must be respected.

Do not prescribe a specific approach in the contract. The coordinator owns
idea generation.

## Scaffold When Not Eval-Ready

Some targets arrive as code only — no runnable eval, no dev/held-out split, or
no clean git repo. Do not dead-end: scaffold the *measurement plumbing* (never
the solution) so the coordinator has a metric to optimize.

- Prefer the keyless MCP tool `scaffold_benchmark`. `style="light"` produces a
  runnable target (eval entrypoint printing `score:`, a dev/test split, an
  editable `solution.py`); `style="zoo"` additionally writes the README
  front-matter contract + `PROVENANCE.md` and runs the structural verifier.
  Pass `git_init=true` to initialize and commit a baseline.
- Fallback when the MCP server is absent:
  `arbor benchmark scaffold <dir> [--style zoo] [--git-init]`.
- Only scaffold after the user confirms what counts as success. The tool is
  idempotent and non-destructive — report created vs skipped, never overwrite.

## Persist The One-Screen Contract

Once the contract is confirmed, persist it at the target root so it outlives the
chat (the durable upgrade over an ephemeral on-screen contract):

- `ARBOR_CONTRACT.md` — one screen: target dir, metric (name / command /
  direction), baseline anchor, ambition, scope, dev/test discipline, edit
  surface, and budget (suggested max cycles).
- `research_config.yaml` — machine-readable, auto-detected by `arbor`:
  `task` (the contract paragraph), `coordinator.max_cycles`,
  `coordinator.ui.interaction_mode: review` (safest default; change on request).
  Follow `examples/research_config.example.yaml`.

These are written during setup, before handing the contract to the coordinator.

## Preflight Checks

Mirror `arbor run` preflight:

- LLM credentials or provider config exist if using the real CLI.
- `cwd` exists and is non-empty.
- `git` exists. A git repo should be clean before a fresh run.
- An eval entry point exists or can be discovered (`eval.sh`, `run_eval.py`,
  `evaluate.py`, README instructions, Makefile targets, etc.).
- If the repo is on a non-base branch, either switch to the base branch or
  explicitly allow starting from that branch.

For skill-only smoke tests, do not require external API credentials unless an
LLM call will actually be made.

## Session Layout

Use the open-source layout:

```text
<project>/.arbor/sessions/<run_name>/
  REPORT.md
  COORDINATOR_FINAL_REPORT.txt
  events.jsonl
  run_stats.json
  conversation.md
  .coordinator/
    idea_tree.json
    idea_tree.md
    checkpoint.json
    messages.jsonl
    baseline_cache.json
  experiments/<node_id>/
    report.md
    metrics.json
    diff.patch
  submissions/
```

When no native Arbor runtime exists, initialize the same layout with:

```bash
TOOLS="<skill-dir>/arbor-agent-tools/scripts/arbor_state.py"
python "$TOOLS" init \
  --cwd <project> --run-name <run_name> --task "<contract>"
```

## Config And Plugins

Honor this precedence:

```text
pydantic defaults < plugin.config_overrides < profile < project YAML < CLI
```

Recognize auto config names in the target project:

- `research_config.yaml`
- `arbor.yaml`
- `autoresearch.yaml`

If `plugin: mle_kaggle` is selected, load
`arbor-agent-plugins-hitl-budget` before INIT because the plugin pre-fills
eval contract, protected paths, required outputs, time budget, and skill
behavior.

## Baseline Metadata

The setup phase can discover metadata, but the coordinator must persist it:

- `baseline_score`
- `trunk_score`
- `test_baseline_score`
- `test_trunk_score`
- `eval_cmd`
- `eval_cmd_test`
- `eval_timeout`
- `eval_retries`
- `dataset_info`
- `metric_direction`
- `trunk_branch`
- `submission_path`
- `sample_submission_path`

Use command templates:

```text
cd {cwd} && <eval command> --run-name {node_id}
```

Never bake the main checkout path into executor commands.

When using `arbor_state.py meta`, quote any `--set` value that contains
spaces, braces, shell metacharacters, or JSON:

```bash
python "$TOOLS" meta --cwd <project> --run-name <run_name> \
  --set "eval_cmd=cd {cwd} && python eval.py --split dev" \
  --set "trunk_branch=arbor/trunk/<run_name>"
```

In smoke mode, if a cached baseline log exists, parse only metric lines with
`arbor_state.py parse-log` or an equivalent parser that normalizes carriage
returns. Do not `cat`, raw `rg`, raw `grep`, or `tail` long training logs; if
debugging requires context, cap output to 20 lines.

## Launch Commands

Native runtime examples:

```bash
arbor setup
arbor doctor
arbor run "<contract>" --yes --yes-cwd <project> --config <config> --max-cycles 3
arbor report <project>/.arbor/sessions/<run_name>
```

Skill-only smoke tests should use `arbor-agent-tools` and a copied project
directory unless the user explicitly wants to modify the live repo.
