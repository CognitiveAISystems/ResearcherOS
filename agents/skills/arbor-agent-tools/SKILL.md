---
name: arbor-agent-tools
description: "Deterministic helper layer for emulating Arbor tools in Codex or Claude Code when native TreeView, TreeAddNode, TreeSetMeta, RunExecutor, GitMergeBranch, or report tooling is unavailable. Use for local state management, eval score capture, executor prompt generation, merge checks, and skill forward tests."
---

# Arbor Agent Tools

Use this skill when the host does not provide native Arbor tools. The bundled
script stores state in the same style as open-source Arbor:

```text
<cwd>/.arbor/sessions/<run_name>/.coordinator/idea_tree.json
<cwd>/.arbor/sessions/<run_name>/.coordinator/idea_tree.md
```

## Script

`scripts/arbor_state.py` is stdlib-only.

Common commands:

```bash
TOOLS="<skill-dir>/arbor-agent-tools/scripts/arbor_state.py"
python "$TOOLS" init --cwd <project> --run-name <run> --task "<contract>"
python "$TOOLS" view --cwd <project> --run-name <run> --format constraints
python "$TOOLS" meta --cwd <project> --run-name <run> --set baseline_score=42 --set trunk_score=42
python "$TOOLS" meta --cwd <project> --run-name <run> --set "eval_cmd=cd {cwd} && bash eval.sh"
python "$TOOLS" add --cwd <project> --run-name <run> --parent-id ROOT --hypothesis "<four-line hypothesis>"
python "$TOOLS" update --cwd <project> --run-name <run> --node-id 1 --status done --score 45 --insight "..."
python "$TOOLS" worktree --cwd <project> --run-name <run> --node-id 1 --trunk <trunk_branch>
python "$TOOLS" prompt-executor --cwd <project> --run-name <run> --node-id 1 --workdir <worktree>
python "$TOOLS" prompt-executor --cwd <project> --run-name <run> --node-id 1 --smoke
python "$TOOLS" eval --cwd <project> --run-name <run> --split dev --exec-cwd <worktree> --cmd "bash {cwd}/eval.sh" --set-meta trunk
python "$TOOLS" record --cwd <project> --run-name <run> --node-id 1 --score 45 --insight "..." --result "..."
python "$TOOLS" parse-log --log <project>/run.log --metric val_bpb
python "$TOOLS" report --cwd <project> --run-name <run>
python "$TOOLS" check --cwd <project> --run-name <run> --require-report --require-experiment --require-executor-prompt
```

Read `references/tool-mapping.md` when deciding which script command maps to a
native Arbor tool.

## State Rules

- Keep scores absolute.
- Keep eval commands templated with `{cwd}` and `{node_id}`.
- Do not run B_test during executor iteration.
- Use `record` for executor outcomes so artifacts and tree updates stay in
  one place.
- Use `check` before trusting a hand-edited tree. Add artifact flags such as
  `--require-report`, `--require-experiment`, `--require-executor-prompt`,
  `--require-events`, `--require-run-stats`, or `--strict-artifacts` when
  validating a completed run.
- Serialize tree-mutating commands for the same run. Do not parallelize
  `init`, `meta`, `add`, `update`, `prune`, `propagate`, `eval`, `record`,
  `worktree`, or `merge`.

## Forward Testing

For a smoke test, copy the target project to a disposable directory outside the
Arbor repository, initialize a short run, record metadata, add one idea,
generate an executor prompt, and run only cheap commands. Do not run full long
training unless explicitly requested.

Smoke-specific rules:

- Use `prompt-executor --smoke`.
- If a real eval command invokes training, data prep, downloads, GPU work, or a
  minute-scale benchmark, do not execute it; store a cached-score parser,
  harmless echo, or mocked score instead.
- Parse existing logs with `parse-log`; it normalizes carriage-return progress
  logs before extracting metrics. Avoid full `cat`, raw `rg`, raw `grep`, or
  `tail` output; cap diagnostic log snippets at 20 lines.
- Finish with `check` and `report` so the smoke produces a real `REPORT.md`.
