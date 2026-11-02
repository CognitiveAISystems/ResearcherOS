# Arbor Source Map

Use this file when auditing the skill suite against the current Arbor source
tree.

## Entry Points

- `README.md`: product behavior, CLI commands, session layout, B_dev/B_test
  discipline, long-running experiment policy.
- `src/cli/commands/run.py`: `arbor run`, intake, preflight,
  Research Contract, session directory, EventBus, dashboard, report, resume.
- `src/cli/intake/system_prompt.py`: planning assistant contract
  and fast-path behavior.
- `src/cli/intake/launch_tool.py`: `LaunchExperiment` schema.
- `src/cli/preflight.py`: LLM/cwd/git/eval checks.
- `src/cli/branch_guard.py`: base-branch guard.

## Coordinator

- `src/coordinator/orchestrator.py`: single persistent ReAct loop,
  gitignore enforcement, dirty repo check, trunk checkout, lifecycle hooks,
  tree init/resume, plugin eval contract, checkpoint writes, final report.
- `src/coordinator/prompts.py`: coordinator identity and full Arbor
  cycle protocol.
- `src/coordinator/config.py`: config, budget policy, search config,
  skill flags, tree paths.
- `src/coordinator/idea_tree.py`: `IdeaTree.VERSION = 3`, node
  fields, metadata defaults, rendering, constraints view.
- `src/coordinator/checkpoint.py`: checkpoint and messages schema.

## Coordinator Tools

- `src/coordinator/tools/tree_ops.py`: `TreeView`, `TreeAddNode`,
  `TreeUpdateNode`, `TreePrune`, `TreeSetMeta`, `TreePropagate`.
- `src/coordinator/tools/executor_run.py`: `RunExecutor`,
  `RunExecutorParallel`, worktree lifecycle, executor prompt, artifact saving,
  report parsing, cycle caps, HITL review gates.
- `src/coordinator/tools/git_ops.py`: `GitMergeBranch`, protected
  branch guard, B_test worktree eval, retry/backoff, protected paths, required
  outputs, medal handling.
- `src/coordinator/tools/search_ctx.py`: `SearchIdeaContext`,
  `SearchIdeaContextParallel`, `SearchStatus`, background SearchAgent tasks,
  validated-node gate.

## Executor

- `src/executor/prompts.py`: executor identity, code discipline,
  workflow, RunTraining policy, report format.
- `src/core/tools/run_training.py`: long command execution, metric
  extraction, idle timeout, partial log handling.
- `src/core/git_artifacts.py`: commit/artifact path filtering.

## Skills And Plugins

- `src/core/skill_registry.py`: built-in and project skill loading.
- `src/core/tools/skill.py`: `LoadSkill` tool.
- `src/skills/idea_drafting.md`: strict IDEATE methodology.
- `src/skills/first_principles_probe.md`: diagnostic probe.
- `src/plugins/base.py`: plugin schema and load/discover logic.
- `src/plugins/mle_kaggle.yaml`: performance-first plugin,
  eval contract, protected paths, required outputs, profiles, lifecycle
  behavior.
- `docs/plugins.md`: user-facing plugin and skill contract.

## Reports And Observability

- `src/events/types.py`: event names.
- `src/events/payloads.py`: typed payload contract.
- `src/report/generator.py`: `REPORT.md` rendering from session
  artifacts.
- `src/cli/run_dashboard.py`, `src/webui/*`: dashboard
  and browser monitor behavior.

## Key Differences From The Wrong Single-Skill Extraction

- The open-source branch uses the `arbor` CLI, intake planning, session
  directories, dashboard, EventBus, checkpoint/resume, plugins, and reports.
- IDEATE is skill-driven through `LoadSkill("idea_drafting")` unless disabled
  by config/plugin.
- Executors are isolated worktree agents with automatic eval metadata
  injection, artifact capture, and insight propagation.
- Related-work search is a background SearchAgent with a validated-node gate.
- Merge is not a shell `git merge`; it auto-runs B_test and enforces guards.
- Long experiments should use `RunTraining`, not polling loops.
