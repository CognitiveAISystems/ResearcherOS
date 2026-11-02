---
name: arbor-research-agent
description: "Public entrypoint for the Arbor skill suite. Use when a user wants to run an Arbor-style autonomous research or optimization workflow from a natural-language goal, including initial clarification of objective, target project, data, metric, evaluation, permissions, budget, run mode, and then automatic bootstrapping into arbor-agent-orchestrator and phase skills."
---

# Arbor Research Agent

Use this as the single user-facing entrypoint. The user should be able to say
`$arbor-research-agent` plus a plain-language goal, similar to using `arbor`,
without knowing the internal phase skills.

This skill performs Arbor-style intake and clarification, then hands control to
`arbor-agent-orchestrator`.

## Entry Protocol

1. Treat the launch cwd as the default target project unless the user names a
   different path.
2. Read available local context before asking: README summaries, config/eval
   hints, cached metrics, dataset notes, and git state.
3. Decide whether the request is clear enough to start. If not, ask concise
   Arbor-style clarification questions before optimizing.
4. Once the contract is clear, load `arbor-agent-orchestrator` and continue
   with its phase loading order.

Do not ask for information that can be discovered safely from local files.
Ask only for decisions, permissions, missing objectives, or ambiguous tradeoffs.

## Intake Context Budget

Keep wrapper intake small. Its job is to determine the run contract, not to
fully analyze the target project.

- Start with `pwd`, git branch/status, `rg --files`, and concise slices such as
  README/config/eval metadata.
- Use `rg` to locate metric/eval/data hints before opening files. Prefer
  focused `sed -n` ranges over full-file reads.
- Do not bulk-read long logs, notebooks, lockfiles, generated outputs, or large
  source files during wrapper intake.
- For training logs or progress logs, avoid raw `cat`, raw `grep`, or broad
  `tail`. If `arbor-agent-tools` is available, use `arbor_state.py parse-log`;
  otherwise normalize carriage returns with `tr '\r' '\n'` and inspect only the
  metric lines needed for the contract.
- Defer deep code reading to `arbor-agent-setup-intake`, `arbor-agent-executor`,
  or the relevant phase skill after the orchestrator is loaded.

## Clarification Gate

If any of these are missing or ambiguous after local inspection, ask before
starting the optimization loop:

- **Target**: project directory, repo branch, and whether the current branch is
  acceptable.
- **Objective**: what should improve and whether the run is maximize/minimize.
- **Metric/eval**: command, score field, B_dev/B_test split, and whether cached
  baseline evidence may be used.
- **Data**: data location, protected/private paths, and whether preparation or
  downloads are allowed.
- **Permissions**: whether source edits, worktrees, commits, package installs,
  internet, GPU jobs, long training, and merge attempts are allowed.
- **Budget**: smoke vs real run, max cycles, wall-clock/training budget, and
  stop condition.
- **Scope preference**: novelty-leaning, effect-leaning, performance-first, or
  mixed.
- **Human gates**: auto, direction, review, or collaborative mode.

Ask as one compact checkpoint, not a long interview. Example:

```text
I can start, but I need these defaults confirmed:
- target: <cwd>
- objective/metric: <inferred metric, direction>
- eval: <inferred command or unknown>
- run mode: smoke / real
- permissions: may edit code? may run training/GPU? may install packages?
- budget: <cycles/time>

Reply "yes" to accept, or edit any line.
```

If the user already gave enough information or explicitly says to use defaults,
do not block on extra confirmation. Proceed with the best conservative contract.

## Contract To Pass Down

Before loading the orchestrator, form a concise contract containing:

- target cwd and git branch;
- instruction/task;
- metric name and direction;
- B_dev/B_test policy;
- baseline status;
- eval command or smoke/cached parser;
- protected files and allowed edit surface;
- run mode and budget;
- user interaction mode;
- any unresolved caveats.

Then load `arbor-agent-orchestrator` and pass this contract as the run
instruction. The orchestrator owns phase loading from that point.

## Run Mode Defaults

- If the user asks to "try", "test", "validate", "demo", or "see behavior",
  default to smoke-only.
- If the project eval is known to run training, downloads, GPU jobs, or
  minute-scale work, ask before running it.
- In smoke mode, load `arbor-agent-tools` when native Arbor tools are absent,
  use cached metrics or `arbor_state.py parse-log`, generate
  `prompt-executor --smoke`, then run `check`, `report`, and a final
  artifact-level `check`.
- In real mode, still complete setup and contract confirmation before any long
  eval, training, package install, or merge.

## Bootstrap Sequence

After intake:

1. Load `arbor-agent-orchestrator`.
2. Ensure `arbor-agent-setup-intake` receives the contract.
   - If the target is not eval-ready (no runnable eval, no dev/test split, or a
     dirty/absent git repo), the `arbor-agent-setup-intake` phase scaffolds the
     measurement plumbing via the `scaffold_benchmark` tool and persists
     `ARBOR_CONTRACT.md` + `research_config.yaml`. The entry point stays a thin
     shell — it does not scaffold directly.
3. Let the orchestrator load phase skills as needed:
   - `arbor-agent-coordinator`
   - `arbor-agent-ideate`
   - `arbor-agent-executor`
   - `arbor-agent-merge-eval`
   - `arbor-agent-search`
   - `arbor-agent-plugins-hitl-budget`
   - `arbor-agent-resume-report`
   - `arbor-agent-tools`
4. Keep the user-facing behavior at the Arbor level. Do not expose internal
   skill mechanics unless useful for debugging or reporting.

## Expected User Experience

The user can write:

```text
$arbor-research-agent optimize this repo for leaderboard score overnight
```

or:

```text
$arbor-research-agent try a simplified smoke run on this autoresearch repo
```

Expected behavior:

- inspect project and infer what can be inferred;
- ask a compact clarification/permission checkpoint if needed;
- create or select `.arbor/sessions/<run_name>/`;
- initialize durable Idea Tree state;
- run the Arbor loop through orchestrator and phase skills;
- use executor/worktree/report discipline rather than ad hoc edits;
- keep B_test protected;
- stop according to budget or smoke instruction;
- report durable artifacts and caveats.
- once `REPORT.md` and expected smoke artifacts exist, stop promptly with a
  concise final response instead of continuing to polish reports or run extra
  cycles.

## Hard Rules

- Do not begin optimization when objective, edit permissions, or expensive eval
  permission is genuinely ambiguous.
- Do not run training, data downloads, package installs, GPU jobs, or long eval
  commands before the user has allowed them or the contract clearly permits
  them.
- Do not use B_test for routine iteration.
- Do not modify protected data/eval/private paths.
- Do not bypass the orchestrator after intake; this skill is the public shell,
  not a second coordinator implementation.
- Do not spend wrapper context recreating setup, coordinator, or executor logic;
  once the contract is clear, load the orchestrator.
- Do not continue running after the requested budget is complete and final
  artifacts have been validated. Finalize with artifact paths, scores, and
  caveats.
