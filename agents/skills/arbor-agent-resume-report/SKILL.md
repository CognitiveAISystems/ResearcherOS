---
name: arbor-agent-resume-report
description: "Resume, checkpoint, event, dashboard, finalization, and report phase for Arbor. Use when continuing interrupted sessions, handling running-node requeue, writing checkpoints/messages, consuming events.jsonl/run_stats, recovering best submissions, generating REPORT.md, or summarizing durable artifacts."
---

# Arbor Resume And Report

Use this when a run stops, resumes, times out, or needs a durable report.

## Checkpoint Files

Open-source Arbor stores the run under:

```text
.arbor/sessions/<run_name>/
  .coordinator/
    idea_tree.json
    idea_tree.md
    checkpoint.json
    messages.jsonl
  events.jsonl
  run_stats.json
  REPORT.md
```

`idea_tree.json` is the primary state. `messages.jsonl` restores conversation
history. `checkpoint.json` stores run name, cycle number, phase, git state,
in-flight executors, cache anchors, and pending human gates.

## Resume Procedure

1. Require an existing `.coordinator/idea_tree.json`.
2. Load the tree.
3. Requeue nodes left as `running` by setting them back to `pending`.
4. Replay `messages.jsonl` if available.
5. Seal any dangling tool-use tail with an interrupted-result marker.
6. Append a short resume nudge:
   - do not restart INIT;
   - call `TreeView`;
   - continue the loop from pending nodes.
7. Keep the existing workspace/session directory.

If the tree is corrupt, do not pretend resume is possible. Start a fresh run
in a clean session only after making that explicit.

## Events

Important event families:

- `session.start`, `session.end`, `session.checkpoint`
- `cycle.start`, `cycle.end`, `cycle.phase`
- `idea.proposed`, `idea.completed`, `idea.pruned`, `idea.merged`
- `executor.start`, `executor.end`
- `tool.start`, `tool.end`
- `llm.call`, `llm.error`, `llm.cache_stat`
- `user.await`, `user.input_received`
- `progress.heartbeat`

Events are JSON-serializable and secret-free. The dashboard, WebUI, stats
collector, and reports consume them.

## Shutdown

Before final report:

1. Wait for background SearchAgents to flush if any are pending.
2. Write final checkpoint and messages.
3. Run plugin `on_finalize` hook if present.
4. On emergency timeout, recover best submission:
   - keep trunk `submission.csv` if present;
   - otherwise copy the best scored snapshot from `submissions/`;
   - otherwise copy the most recent snapshot.
5. Write `run_stats.json`.
6. Generate `REPORT.md`.

In smoke/forward tests, finalization is still mandatory even when no real
executor, merge, or B_test ran. Generate `REPORT.md`, make the smoke caveat
explicit, and stop after artifact validation.

After `REPORT.md` is written and expected artifacts validate, do not keep
polishing reports or launching extra checks. Return a concise final response
with paths, scores, and caveats.

## REPORT.md Contents

Include:

- instruction/task;
- exit reason;
- model/provider if known;
- event summary;
- run stats and token scope;
- baseline/final B_dev;
- baseline/final B_test when available;
- merged ideas;
- top ideas by score;
- artifact paths.

Reports must tolerate partial data. Missing stats, events, or tree fields
should produce a partial report, not a crash.

## Manual Report Generation

Native:

```bash
arbor report <project>/.arbor/sessions/<run_name>
```

Skill-only:

```bash
python <tools>/arbor_state.py report --cwd <project> --run-name <run_name>
```

For skill-suite smoke tests, run `python <tools>/arbor_state.py check` before
`report` for tree integrity, then run it again after `report` with artifact
flags:

```bash
python <tools>/arbor_state.py check --cwd <project> --run-name <run_name>
python <tools>/arbor_state.py report --cwd <project> --run-name <run_name>
python <tools>/arbor_state.py check --cwd <project> --run-name <run_name> \
  --require-report --require-experiment --require-executor-prompt
```

Use `--strict-artifacts` only for full sessions that are expected to contain
events and run stats in addition to tree, experiment, prompt, and report
artifacts.

## Final Response To User

Summarize durable evidence, not transient thoughts:

- session directory;
- final dev/test scores;
- best/merged node ids;
- report path;
- important caveats such as no B_test, timeout, failed search, or incomplete
  executor run.
