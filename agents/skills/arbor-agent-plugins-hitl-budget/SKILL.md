---
name: arbor-agent-plugins-hitl-budget
description: "Domain adaptation, human-in-the-loop, and budget policy phase for Arbor. Use when a run mentions plugins, plugin profiles, mle_kaggle, eval_contract, protected_paths, required_outputs, lifecycle hooks, convergence, budget_policy, RunTraining stages, AskUser, or interaction modes auto/direction/review/collaborative."
---

# Arbor Plugins, HITL, And Budget

Use this when run behavior is modified by configuration rather than by code.

## Plugin Contract

A plugin is a YAML domain adapter. It can define:

- Prompt injections:
  `meta_preamble_inject`, `meta_init_inject`, `meta_ideate_inject`,
  `meta_decide_inject`, `sub_preamble_inject`, `sub_workflow_inject`.
- `eval_contract`: prefilled metadata such as `metric_direction`, `eval_cmd`,
  `submission_path`, and `sample_submission_path`.
- `protected_paths`: globs a branch must not modify.
- `required_outputs`: files that must exist for merge.
- `config_overrides` and named `profiles`.
- `lifecycle_hooks`: `on_workspace_setup`, `after_executor`,
  `on_finalize`.
- `convergence`: early stop policy.

Plugin precedence:

```text
defaults < plugin.config_overrides < active profile < project YAML < CLI
```

## MLE/Kaggle Mode

The built-in `mle_kaggle` plugin is performance-first:

- Novelty has zero value; only metric improvement matters.
- `skills_enabled` may be disabled for strict idea drafting because
  parameter tuning, prompt edits, feature engineering, ensembling, and
  scaling can be valid.
- A valid `submission.csv` is a first-class artifact.
- Data/eval directories are protected.
- Merge requires required outputs and verified score.

Priority:

1. Produce and evaluate a valid baseline submission.
2. Establish robust validation.
3. Explore diverse approach families.
4. Refine promising families.
5. Ensemble/blend diverse winners.
6. Reserve finalization time for best submission recovery.

## Budget Policy

Default Arbor behavior favors long real experiments. Do not invent staged
budgets unless configured.

If `budget_policy.stages` exists, use configured stages such as `smoke`,
`pilot`, and `full` with `RunTraining(budget_stage=...)`.

If `require_cost_estimate` is true, every idea needs:

- estimated wall time;
- minimal smoke test;
- promotion gate from cheap to expensive fidelity.

Do not launch a new executor when remaining budget cannot cover the executor
plus finalization buffer.

## Plateau And Convergence

When repeated siblings under a parent fail to improve:

- Stop expanding that parent.
- Summarize the failure class in the parent insight.
- Switch to Combine or Leap:
  - **Exploit**: refine current best pipeline.
  - **Combine**: ensemble/blend diverse candidates.
  - **Leap**: use a fundamentally different approach family.

If convergence policy emits a stop signal, finalize instead of starting new
experiments.

## Human Interaction Modes

- `auto`: no routine human gates.
- `direction`: after `TreeView(format="constraints")`, ask the user for a
  direction before adding ideas.
- `review`: pause before `TreeAddNode` commits and before executor dispatch.
- `collaborative`: both direction and review.

Use `AskUser` only when genuinely blocked, or when interaction mode requires
it. If timeout occurs, proceed on a stated assumption.

Respect review outcomes:

- approved: continue;
- skipped: do not re-add or dispatch the idea;
- edited: continue from the revised hypothesis or review note.

## Lifecycle Hooks

- `on_workspace_setup`: run once before INIT.
- `after_executor`: snapshot plugin outputs such as `submission.csv` into the
  session `submissions/` directory.
- `on_finalize`: run once after STOP or emergency timeout.

Hook scripts run from the project cwd. Do not inline arbitrary shell in a
plugin; use script files.

## Skill Behavior

If a plugin disables strict skills, do not force `arbor-agent-ideate`'s
scientific anti-tweak filter. Still require:

- constraints first;
- evidence-grounded ideas;
- depth-appropriate tree nodes;
- cost awareness;
- no duplicate siblings;
- clear observable on B_dev.
