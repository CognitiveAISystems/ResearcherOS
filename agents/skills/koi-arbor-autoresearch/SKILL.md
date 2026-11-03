---
name: koi-arbor-autoresearch
description: >-
  Develop a method autonomously in an existing ResearcherOS project using Arbor's
  coordinator and parallel CLI executors. Use for /koi-arbor-autoresearch or an
  explicit Arbor research request; keep existing autoresearch workflows separate.
---

# Autonomous research in ResearcherOS

Read the project's AGENTS.md, project.md, research.json and relevant reports.
Keep the main node unchanged. Use at most eight words in node and card titles.
Infer known facts from files before asking.
Establish goal, budget, evaluation protocol, protected paths, permitted compute
and stopping criteria before experiments. Record unresolved assumptions.

## Research scope and confirmation

The launch context determines the initial scope, not the mere presence of a
selected node. A kanban or card starts at its owning METHOD; the tree starts at
TREE level even when a method node is selected on the canvas.

Read `checkpoint.run.metadata.research_scope` (JSON) or
`view.arbor_metadata.research_scope`. Its `level` is `method` or `tree`, and
`method_id` identifies the selected method. A recorded level means the user has
already confirmed it in the launch dialog: do not ask again on continuation or
resume, and never infer a different scope from the current screen.

If `level` is null, no research is authorized yet. Ask the user once before
mutating the tree, planning experiments or dispatching executors. From a method,
ask whether to improve this named method or search ideas and hypotheses across
the tree. From a tree, confirm tree-level research without offering to descend
into a method. Wait for the reply, then record operation `scope` with
`{"level":"method"}` or `{"level":"tree"}`. Cancellation starts no research.
This also covers direct slash invocations outside the UI launch dialog.

- **Method:** investigate mechanisms and improvements of the selected method,
  informed by its existing results. Publish alternative improvement hypotheses
  in that method's description and their decisive experiments on its own kanban.
  Use `phase:"hypotheses"` with `node_ids:[method_id]`; do not create competing
  methods, edit other branches, or promote the investigation to tree level.
  The originating card supplies evidence; it does not restrict the work to one
  card. Preserve the method's existing description and conclusions.
- **Tree:** investigate higher-level ideas, causes and falsifiable hypotheses;
  compare alternative methods, then publish them in the appropriate branches
  and prepare their experiments. Do not silently narrow this to tuning one
  selected implementation. Keep the root unchanged.

These scope rules override the generic method-generation and ancestor-update
instructions below. Continue across waves within the agreed scope. If a broader
question emerges during method research, report it and propose a separate
TREE-level research request; never expand the current run silently.

## Coordinator

Load the sibling `arbor-research-agent` and `arbor-agent-orchestrator` skills,
and always load `arbor-agent-ideate` before generating methods. Load other
phase skills when relevant. The workflow below overrides upstream optional
strict-skills, hidden candidate drafting and performance-first defaults. Preserve Arbor's ideation, selection,
parallel execution, dev/test discipline, evidence propagation and stop policy.
ResearcherOS owns scientific state. Do not initialize a second `.arbor` tree,
run the upstream `arbor_state.py`, or overwrite project.md directly.

Use the provided `tool_commands.project` command with JSON on stdin.
Use `tool_commands.dispatch` for executor dispatch. Run command arrays as argv,
quoting paths if using a shell. In the desktop build these invoke the bundled
server with dedicated flags; do not treat that executable as a Python interpreter.

For a source checkout the equivalent is
`python -m koi.agent_chat.research_tools` from the ResearcherOS engine
with one JSON request on stdin:

```json
{"run_id":"<provided run>","operation":"view","args":{}}
```

Before dispatch, record `contract` with `max_seconds`, `max_parallel`, `max_executors` and
`stop_condition` from the agreed scope. This budget cannot be silently reset.
`max_parallel` is concurrent workers (1–4). `max_executors` is the TOTAL
number of launches across all waves, including idea/review agents; it is NOT
concurrency or the number of hypotheses. If the user grants "30 minutes, two
executors", use max_seconds=1800 and max_parallel=2. Do not translate this into
a two-launch lifetime cap. Unless the user specifies a total launch cap, use
max_executors=1000 as a technical ceiling, with the agreed time/concurrency
bounds controlling actual work. Never raise a previously agreed lifetime cap.
The adapter refuses new launches after the deadline or total launch limit.

Supported operations: `scope`, `phase`, `contract`, `meta`, `view`, `create_node`, `update_node`, `delete_node`,
`create_card`, `update_card`, `read_report`, `write_report`, `conclusion`.
Arguments follow existing ResearcherOS project command fields. Node operations
use `node_id`; cards/reports use `board_id` and `card_id`. Report writing adds
`content`. A new card always starts in backlog. `view` returns nodes and boards
with their real IDs. Reuse existing entities; never manufacture IDs.
TreeView maps to `view`; TreeAddNode/TreeUpdateNode map to node/card commands.
Map strategy levels to existing program/cause branches, preserving each
falsifiable hypothesis in its description and the hypothesis edge where the
domain permits it. Put concrete methods below them and experiments on their
kanbans. Follow the allowed parent/child types returned by the project model.
TreeSetMeta maps to `meta`: persist baseline_score, trunk_score, eval_cmd,
eval_cmd_test, dataset_info, metric_direction, trunk_branch, run_mode and
permissions. `view` returns them under arbor_metadata. These are execution
settings; experiment evidence remains in card reports.
TreePropagate means updating non-root ancestor descriptions from linked report
evidence and saving method conclusions, not duplicating the tree.
Pruning records a reason and preserves evidence; it does not erase history.

## Mandatory visible research phases

Default to developing methods, not tuning the existing implementation. A metric
is evidence for a scientific claim, not a substitute for that claim. Use a
performance-first/tuning-only scope only when the user explicitly requests it.
Never claim novelty without checking relevant prior work; label unverified
novelty as unverified. Read existing evidence before proposing alternatives.
For a new problem, missing baseline runs or two concrete failure examples must
not block provisional method ideation. This overrides the upstream IDEATE
evidence-count gate: publish explicit assumptions and untested hypotheses, then
plan evidence collection as experiments. Never fabricate the missing evidence
or report a hypothesis as validated. Existing observations should inform ideas,
without restricting the search to local modifications of the current code.

1. **Clarification.** Recover known answers from the conversation and project.
   If clarification is already done, acknowledge it and continue without repeating
   the interview. Establish the research question, scope and budget.
2. **Method hypotheses.** Generate alternatives differing in causal assumption,
   algorithm, representation, objective or information flow. Consider assumption
   inversion, a different mechanism, and transfer from another field. Compare
   plausible alternatives openly; one method is acceptable when justified by the
   task/evidence, not merely because it is easiest. A learning-rate sweep, larger
   model, longer training or prompt wording change is not a new method by itself.
   Publish surviving alternatives in the existing tree BEFORE testing them.
   For each, describe the problem/failure, mechanism, why it should work,
   difference from known approaches, falsifiable prediction, decisive test,
   limitations and status (untested/supported/refuted/open). Preserve rejected
   alternatives and reasons in the relevant description/report. Publish concise
   scientific rationale, not private chain-of-thought. Group upper-level claims
   above concrete mechanisms using permitted node types; never change the root.
   Review the set for distinct mechanisms and missing plausible directions.
   Record `phase` with `phase:"hypotheses"` and real `node_ids` of those nodes.
3. **Experiment planning / backlog.** Fill the current wave's backlog BEFORE
   starting any execution. Each card answers one scientific question. Put pilot,
   control, ablation and robustness runs in the SAME card when they jointly answer
   that question; split unrelated questions or independent scales into cards.
   Cover the retained methods or explicitly explain why a method is deferred.
   Prepare every selected card's report §§1–3 using the canonical
   `koi-report-review/report-skeleton.md`, `koi-grill-experiment` and setup review.
   Fix supported/refuted/open decision rules, baselines/controls, dependencies,
   artifacts and completion criteria before runs. Do not invent results.
   The coordinator MUST select the plots for each card's monitor before dispatch
   and record them in report §3: question, metrics/axes, data source, image path
   under metrics_dir, update trigger and intended inclusion in the final report.
   Follow koi-card-autoresearch's “Промежуточные графики и картинки” section.
   Record `phase:"backlog"` with `cards:[{"board_id":"...","card_id":"..."}]`.
   Tell the originating chat which hypotheses and cards are now visible.
4. **Execution.** Record `phase:"execution"`, then execute the prepared wave,
   dispatching independent cards/runs concurrently where permitted. Start each
   card with backlog → running only AFTER setup. Follow koi-execute-card and
   koi-card-autoresearch for execution. Complete subtasks immediately; maintain
   live_note, live_log and metrics_dir; publish real plots as data appears.
   Keep the canonical report headings: §1 purpose; §2 primary metric and rule;
   §3 preparation with one §3.x per experiment; §4, §5, … individual experiments,
   each with results/artifacts FIRST and evidence-based conclusions below.
   §5 is optional for a one-experiment card. Do not replace the report with a
   generic summary or confuse it with the separate ingest-only .run.md format.
   Review results with koi-report-review. Mark done only after all planned runs
   finish or their omission is explicitly resolved; a failed hypothesis may be
   a completed card, a running/queued compute job may not. Apply koi-done-research
   via `conclusion` with board_id, card_id and conclusion containing question,
   narrative, answer, certainty and importance. Keep the visible card conclusion
   brief and understandable without the report (koi-prose-style).

## Continue across waves

The default unit of completion is the USER'S RESEARCH GOAL, not one wave,
two hypotheses, a filled backlog, a fixed candidate pool or an executor reply.
Do not invent "one wave completed" as the run's stop_condition unless the user
explicitly requested a single wave. A wave's fixed experiment plan constrains
that wave; it does not prohibit proposing a new method in the next wave.

After each wave, read the actual remaining deadline and launch budget from the
`view.research_budget` (deadline, launched, max_executors), then compare evidence to the original target. If the
target is unmet and resources remain, continue IN THE SAME COORDINATOR TURN:
review failure mechanisms → publish revised/new hypotheses → plan backlog →
execute the next wave. Negative results are input to new ideas, not a stop.
Keep time for synthesis; do not spend the full lifetime launch cap on planning.
A finite hypothesis list is a first wave, not an exhaustive search space.

Do not use the protected final test after every unsuccessful dev wave. Reserve
it for the selected final candidate according to the fixed evaluation protocol;
never tune on its revealed scores. Do not silently replace R with R² or vice
versa; preserve the user's clarified metric and threshold across waves.

Stop only at verified goal attainment under the agreed protocol, actual resource
exhaustion, user cancellation, or a concrete blocker that prevents useful work.
Report the exact reason, evidence, elapsed/remaining budget and unresolved work.
Do not claim exhaustive impossibility from two unsuccessful hypotheses. If
external input/access is required, preserve state and ask only for that input.
Do not silently extend budgets or start a fresh run to evade a stopping boundary.

At a wave boundary, update parent hypotheses from linked evidence and explain
what was learned, what remains open and why the next wave changes. To revise
methods, return to `hypotheses`, publish the revision and plan a fresh backlog
wave; never perform an unrecorded alternative experiment inside the agent.
The adapter stores phase and entity references only; scientific content lives
in the existing tree/reports. Resume reads `arbor_metadata.research_workflow`:
reuse completed clarification, published methods and existing cards. Never
repeat completed experiments merely to satisfy the phase order.

## Executor dispatch

Call the provided `tool_commands.dispatch` argv with JSON on stdin:

```json
{"run_id":"<provided run>","timeout":1800,"tasks":[{"backend":"codex","role":"Исследователь","cwd":"<isolated absolute workdir>","board_id":"<board>","card_id":"<card>","task":"<bounded experiment and artifact requirements>"}]}
```

Inside a coordinator, this command submits to the existing ResearcherOS host
launcher, which starts CLI processes outside the coordinator sandbox. Do not
launch nested Codex processes yourself or bypass the sandbox. No separate
service is required. One to four tasks run concurrently. Backends: `codex`, `claude`,
`opencode`. Each task needs an existing isolated directory; create Git
worktrees only when explicitly authorized. Otherwise use independent copies
and return diffs for coordinator review. Never apply competing code edits in
one checkout. Search/review agents use the same dispatch and explicit roles.
Include the parent hypothesis, specific scientific question, fixed decision rule,
report sections/artifacts and progress requirements in every executor task.
Include the coordinator's mandatory plot plan: publish and refresh actual image
files in the card monitor as measurements arrive; logs or dashboard links alone
do not suffice. Before closing the card, preserve and embed the key plots in its
report, including material negative results, with conclusions below the evidence.
Idea/review agents may run during planning; experiment executors must wait for
the execution phase. Executors must not recursively dispatch or edit the shared tree. Use the
ResearcherOS virtualenv Python and module path for all adapter commands.

Keep overall milestones in the originating chat: selected hypothesis, evidence,
next decision and budget remaining. Do not invent a completion percentage.
Stop at the budget or goal boundary, preserve state and report what remains.


## Resume

In the same chat, invoke `/koi-arbor-autoresearch resume <run-id>` (or
`продолжи <run-id>`). The adapter returns the original goal, existing budget
and participants. Read the project and card reports again. Never dispatch a
second copy of a running task. An unknown process requires artifact inspection
before retry. Preserve consumed budget; do not silently create a fresh contract.
