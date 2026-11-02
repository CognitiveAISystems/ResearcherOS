---
name: arbor-agent-orchestrator
description: "Top-level controller for recreating the open-source AutoResearch workflow as a suite of skills. Use when the user asks to run, emulate, extract, validate, or refine Arbor/AutoResearch behavior, especially when a coordinator must load phase skills for setup, ideation, executors, merge evaluation, novelty search, plugins, resume, and reports."
---

# Arbor Agent Orchestrator

Use this as the first skill for an Arbor-style research run. It is the phase
loader and policy owner; load the smaller skills only when their phase applies.
For normal user-facing use, prefer starting with `arbor-research-agent`; that
wrapper performs Arbor-style intake and then loads this orchestrator.

## Source Model

This suite mirrors the `open-source` branch of `arbor`, not the older
single hypothesis-tree extraction. The product entry point is `arbor`; the run
architecture is:

- Intake/planning agent creates a research contract.
- Coordinator runs one persistent ReAct loop and owns the Idea Tree.
- Executors implement ideas in isolated git worktrees.
- Merge/eval tooling protects B_test and trunk.
- SearchAgent annotates validated nodes with related work.
- Plugins, HITL, budget policy, checkpoint/resume, dashboard, and report are
  first-class behavior, not optional notes.

Read `references/source-map.md` when auditing against the source tree or when
you need exact file origins.
Read `references/compatibility.md` when packaging the suite for another agent
runtime or checking Codex/Claude Code portability.

## Phase Loading Order

1. **Launch and contract**: load `arbor-agent-setup-intake`.
   Establish target cwd, metric, baseline status, budget, scope preference,
   dev/test discipline, config/plugin choice, and session directory.

2. **Coordinator loop**: load `arbor-agent-coordinator`.
   Run INIT, OBSERVE, IDEATE, SELECT, DISPATCH, DECIDE until the cycle cap,
   budget limit, or diminishing returns says to stop.

3. **IDEATE only**: load `arbor-agent-ideate`.
   This is a hard gate for novelty/scientific runs. It must follow
   `TreeView(format="constraints")` and precede every `TreeAddNode`. If a
   plugin disables strict skills for performance-first MLE/Kaggle, use the
   free-form path described by `arbor-agent-plugins-hitl-budget` instead.

4. **Executor dispatch**: load `arbor-agent-executor`.
   Use for `RunExecutor` / `RunExecutorParallel` behavior, worktree lifecycle,
   executor prompts, long `RunTraining` commands, report parsing, artifact
   capture, and tree updates.

5. **Merge and scoring**: load `arbor-agent-merge-eval`.
   Use before baseline metadata changes, merge attempts, B_test verification,
   protected-path checks, and final test scoring.

6. **Related work**: load `arbor-agent-search`.
   Use after a node is `done` or `merged` and beat trunk, especially before
   merge decisions where novelty matters.

7. **Domain adaptation and human gates**: load
   `arbor-agent-plugins-hitl-budget` when config mentions plugins, profiles,
   `mle_kaggle`, lifecycle hooks, convergence, budget policy, or
   interaction modes `direction`, `review`, or `collaborative`.

8. **Resume and finalization**: load `arbor-agent-resume-report` when the run
   is interrupted/resumed, when dashboard/events/checkpoint artifacts matter,
   or when producing `REPORT.md`.

9. **No native Arbor tools**: load `arbor-agent-tools`.
   Use its `scripts/arbor_state.py` helper to emulate `TreeView`,
   `TreeAddNode`, `TreeSetMeta`, `TreeUpdateNode`, `TreePrune`,
   `TreePropagate`, executor prompt generation, eval score capture, merge
   checks, and report generation in a plain Codex/Claude environment.

## Non-Negotiable Invariants

- As coordinator, do not write benchmark code directly. Code changes happen
  through executor branches or clearly separated executor subagents.
- Maintain an Idea Tree as durable memory. Do not rely on transient chat
  reasoning for run state.
- Record `baseline_score`, `trunk_score`, `eval_cmd`, `eval_cmd_test`,
  `dataset_info`, `metric_direction`, and `trunk_branch` as metadata before
  dispatching real executors.
- Use B_dev for iteration. Use B_test only for merge verification and final
  reporting when the contract permits B_test and the run is not smoke-only.
- Use eval command templates with `{cwd}` and `{node_id}`. Do not hardcode the
  main repository path inside executor eval commands.
- Keep main/master protected. Merge only into the configured trunk branch.
- If using `arbor_state.py`, run tree-mutating commands serially. Do not
  parallelize `init`, `meta`, `add`, `update`, `prune`, `propagate`, `eval`,
  `record`, `worktree`, or `merge` against the same run.
- Preserve evidence: experiment reports, metrics, diffs, event logs, tree JSON,
  tree Markdown, run stats, and final report.
- If the real `arbor` CLI is installed and the user wants a real run, prefer
  invoking it. If the user wants a skill-based reconstruction or a smoke test,
  emulate the behavior with this suite and `arbor-agent-tools`.

## Smoke And Forward-Test Mode

When the user asks for a smoke test, forward test, dry run, or validation of
the skill suite, propagate `smoke-only` through the contract, metadata,
executor prompt, raw reports, and final summary.

- Do not execute inherited real eval commands if they run training, data prep,
  downloads, GPU jobs, or minute-scale benchmarks.
- Replace expensive eval commands with `arbor_state.py parse-log`, another
  cached-score parser, a harmless echo, or an explicitly labelled mocked score
  for plumbing validation.
- Do not `cat`, raw `rg`, raw `grep`, or `tail` long training logs. Some logs
  use carriage-return progress updates that make one physical line enormous.
  Use `arbor_state.py parse-log` or normalize with `tr '\r' '\n'` before
  matching; only inspect at most 20 log lines when debugging a failure.
- Generate executor prompts with `arbor_state.py prompt-executor --smoke`.
  Save the generated prompt as `experiments/<node_id>/executor_prompt.md`.
- Do not create real worktrees, edit source, or merge branches unless the user
  explicitly wants a real run.
- Still complete the durable Arbor artifacts: tree JSON/Markdown, experiment
  report/metrics, executor prompt, `check`, and `REPORT.md`.

## Minimal Run Skeleton

Use this skeleton when no native `arbor` runtime is available:

1. Load `arbor-agent-setup-intake`; produce a contract and initialize
   `.arbor/sessions/<run_name>/.coordinator/idea_tree.json`.
2. Load `arbor-agent-coordinator`; complete INIT and metadata.
3. For each cycle:
   - OBSERVE code/results.
   - `TreeView(format="constraints")`.
   - Load `arbor-agent-ideate`; add 1-3 ideas.
   - SELECT pending leaves.
   - Load `arbor-agent-executor`; dispatch one or more executors.
   - Load `arbor-agent-search` for validated winners when useful.
   - Load `arbor-agent-merge-eval`; merge, prune, or continue.
4. Load `arbor-agent-resume-report`; run final B_test only if it is available,
   authorized, and the run is not smoke-only; write `REPORT.md`; summarize
   artifact paths.

## Common Failure Corrections

- If only one monolithic skill exists, split it by the phase list above.
- If ideation starts without constraints and the idea-drafting gate, restart
  IDEATE from `TreeView(format="constraints")`.
- If an executor evaluates in the main repo rather than its worktree, discard
  that score and rerun with `{cwd}` substitution.
- If B_test is used for routine idea selection, mark the run contaminated and
  reset the decision basis to B_dev.
- If reports contain deltas only, convert tree scores to absolute metric
  values.
