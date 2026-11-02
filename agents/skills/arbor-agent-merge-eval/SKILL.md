---
name: arbor-agent-merge-eval
description: "Merge and evaluation discipline for Arbor. Use for TreeSetMeta metadata, B_dev/B_test separation, eval command templates, score parsing, GitMergeBranch behavior, protected paths, required outputs, metric_direction, trunk/test score updates, medal detection, and final evaluation before stopping."
---

# Arbor Merge And Eval

Use this whenever scores, metadata, merge decisions, or final validation are
involved.

## Dataset Discipline

- B_dev is for routine iteration, executor experiments, score tracking, and
  idea selection.
- B_test is for milestone checks only: before merging a branch and at final
  report time.
- If B_test diverges from B_dev, do not hand-wave it. Investigate overfitting,
  noise, data split mismatch, or eval contamination.

## Tree Metadata

Persist evaluation metadata early and update it after merges:

- `baseline_score`: unmodified B_dev score.
- `trunk_score`: current trunk B_dev score.
- `test_baseline_score`: unmodified B_test score.
- `test_trunk_score`: current trunk B_test score.
- `eval_cmd`: B_dev command.
- `eval_cmd_test`: B_test command.
- `eval_timeout`, `eval_retries`, `eval_retry_base_delay`,
  `eval_retry_max_delay`.
- `dataset_info`: paths and split descriptions.
- `metric_direction`: `maximize` or `minimize`.
- `trunk_branch`: non-protected branch that receives verified merges.
- `submission_path`, `sample_submission_path`.

Use `{cwd}` and `{node_id}` placeholders. Example:

```text
cd {cwd} && uv run python run_eval.py --split dev --run-name {node_id}
```

## Score Semantics

- Tree node `score` is an absolute B_dev metric value.
- Merge verification uses B_test.
- `metric_direction` controls improvement:
  - maximize: higher is better.
  - minimize: lower is better.
- Do not compare deltas with absolutes.
- If output has JSON with `score`, prefer it. Otherwise extract the primary
  metric from text (`primary_score`, `score`, `accuracy`, `acc`, etc.).

## Merge Procedure

Native `GitMergeBranch`:

1. Refuses target `main` or `master`.
2. Resolves target to configured `trunk_branch`. `main`/`master` are base
   branches, not merge targets.
3. Creates an isolated worktree at `source_branch`.
4. Runs `eval_cmd_test` with `{cwd}` and `{node_id}` substituted.
5. Retries transient failures if configured.
6. Extracts verified B_test score.
7. Rejects the merge if B_test does not improve over `test_trunk_score` or
   `test_baseline_score`.
8. Checks plugin protected paths and required outputs.
9. Merges source into trunk with `--no-ff`.
10. Reports the verified test score and instructs the coordinator to update
    tree metadata and node status.

After success:

- `TreeSetMeta(test_trunk_score=<verified score>)`.
- If needed, re-run B_dev on trunk and `TreeSetMeta(trunk_score=<dev score>)`.
- `TreeUpdateNode(node_id=<id>, status="merged")`.

## Protected Paths And Required Outputs

For plugins such as MLE/Kaggle:

- Reject branches modifying protected globs such as `data/**`, `private/**`,
  or `evaluation/**`.
- Reject merge if required outputs such as `submission.csv` do not exist on
  the branch.
- Snapshot outputs in the workspace so finalization can recover the best one.

## Merge Threshold

`merge_threshold` is a soft coordinator guideline, not a substitute for B_test.
A small improvement can merge when performance-first mode says every gain
counts and B_test verifies it. A large B_dev improvement must still be rejected
if B_test fails.

## Final Stop

Before stopping:

1. Ensure the best available branch is either merged or explicitly rejected.
2. Run final B_test on trunk only if it is available, contract-authorized, and
   the run is not smoke-only.
3. Record `test_trunk_score`.
4. If `test_baseline_score` is missing and a baseline test run is feasible,
   record it.
5. Hand off to `arbor-agent-resume-report`.

For smoke/forward tests, do not run B_test or merge verification unless the
user explicitly requested a real run. Record `test_trunk_score` as unavailable,
state that no separate B_test was used, run `arbor_state.py check`, and hand
off to report generation.

## Manual Emulation

If native `GitMergeBranch` is unavailable, use `arbor-agent-tools`:

```bash
python <tools>/arbor_state.py eval --cwd <project> --run-name <run> \
  --split dev --cmd "<eval_cmd>" --set-meta baseline

python <tools>/arbor_state.py meta --cwd <project> --run-name <run> \
  --set "trunk_branch=<trunk_branch>"

python <tools>/arbor_state.py merge --cwd <project> --run-name <run> \
  --source-branch <branch> --node-id <id>
```

Pass `--target-branch <trunk_branch>` explicitly only when metadata is not set.
If a manual merge would touch live work, prefer `--dry-run` first.
