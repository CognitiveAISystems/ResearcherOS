# Tool Mapping

Use this reference when native Arbor tools are unavailable.

| Native Arbor behavior | Helper command |
|---|---|
| Create session and root tree | `arbor_state.py init` |
| `TreeView(format="compact")` | `arbor_state.py view --format compact` |
| `TreeView(format="full")` | `arbor_state.py view --format full` |
| `TreeView(format="node", node_id=...)` | `arbor_state.py view --format node --node-id ...` |
| `TreeView(format="pending")` | `arbor_state.py view --format pending` |
| `TreeView(format="constraints")` | `arbor_state.py view --format constraints` |
| `TreeAddNode` | `arbor_state.py add --parent-id ... --hypothesis ...` |
| `TreeUpdateNode` | `arbor_state.py update --node-id ...` |
| `TreeSetMeta` | `arbor_state.py meta --set key=value` |
| `TreePrune` | `arbor_state.py prune --node-id ... --reason ...` |
| `TreePropagate` | `arbor_state.py propagate --node-id ...` |
| B_dev/B_test eval capture | `arbor_state.py eval --split dev/test --cmd ...` |
| Cached metric extraction from logs | `arbor_state.py parse-log --log ... --metric ...` |
| Build executor prompt | `arbor_state.py prompt-executor --node-id ...` |
| Build smoke-only executor prompt | `arbor_state.py prompt-executor --node-id ... --smoke` |
| Record executor result | `arbor_state.py record --node-id ...` |
| Create a worktree | `arbor_state.py worktree --node-id ...` |
| Merge with B_test guard | `arbor_state.py merge --source-branch ... --node-id ...` |
| Validate tree file | `arbor_state.py check` |
| Generate `REPORT.md` | `arbor_state.py report` |

The helper intentionally does not replace the real multi-agent runtime. It
provides durable state and deterministic guardrails so a host agent can emulate
the open-source behavior during smoke tests and skill-driven runs.
