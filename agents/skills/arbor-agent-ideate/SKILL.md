---
name: arbor-agent-ideate
description: "Strict IDEATE-stage skill for Arbor. Use immediately after TreeView(format=\"constraints\") when drafting Idea Tree nodes, enforcing the idea_drafting and first_principles_probe behavior, depth-aware idea levels, four-line TreeAddNode hypotheses, conflict checks, and self-filtering against shallow tweaks."
---

# Arbor Ideation Gate

Load this only during IDEATE. The coordinator must first call
`TreeView(format="constraints")`.

After loading, write a brief visible progress note if useful:

```text
LOAD_RECEIPT: # SKILL: Idea Drafting
```

## Hard Sequence

1. Read constraints: root insight, pruned lessons, validated findings, tree
   shape, and sibling nodes.
2. Run the Probe Block below before listing candidates.
3. Generate candidates using all four idea moves.
4. Apply depth-aware abstraction.
5. Write a five-field scratch declaration for each survivor.
6. Run the pre-submission self-check.
7. Commit each survivor with `TreeAddNode` using exactly the four labelled
   lines specified below.

If any step is skipped, restart IDEATE.

## Probe Block

Answer all four questions with concrete evidence: failure case IDs, log lines,
metrics, source references, or experiment reports.

```text
PROBE BLOCK
Q1 First principles : <bottleneck CLASS> - evidence: <case ids / log refs>
Q2 Hidden assumption: <assumption> - if dropped: <what opens up>
Q3 Elephant         : <ugly problem the trunk currently ignores>
Q4 Hamming          : <yes/no, plus one sentence justification>
```

Q1 must name a failure class, such as wrong retrieval, wrong reasoning over
correct evidence, wrong stopping condition, wrong representation, wrong
objective, wrong action space, or wrong credit assignment. If you cannot cite
at least two concrete pieces of evidence, go back to OBSERVE.

## Mindset

- Think like a principal investigator, not an engineer filing a small PR.
- Ask HOW, not HOW MUCH: change an algorithm, representation, objective,
  control flow, data structure, or reasoning strategy.
- Aim at a class-level bottleneck, not a single example.
- Mechanism is a noun. "Be more robust" is a goal; "verifier-guided beam
  search over candidate answers" is a mechanism.

## Idea Generation Moves

Use all four moves before selecting candidates:

- **Assumption Inversion**: take the Q2 assumption and design a mechanism that
  works when it is false.
- **Backward From Success**: imagine the benchmark solved; identify missing
  pipeline stages, state, or signals.
- **Analogical Transfer**: borrow mechanisms from search, CSP/SAT, debate,
  program synthesis, control theory, or scientific method.
- **Failure-Case Reverse Engineering**: pick 2-3 failures and ask what minimal
  capability would have caught them; cluster the answers.

Apply a diversity rule: candidates must differ by assumption attacked,
mechanism class, or analogy source. Drop duplicates.

## Depth-Aware Level

- **Depth 1**: broad strategy categories or paradigm shifts. These should read
  like research directions, not implementation tickets.
- **Depth 2+**: concrete algorithmic approaches within a parent direction.
  These must be implementable by an executor in one experiment.

If a depth-1 idea names implementation details, zoom out. If a depth-2 idea is
only a theme, zoom in.

## Candidate Declaration

For each surviving candidate, write this scratch block in reasoning. Only
fields 3 and 5 become part of the final node hypothesis.

1. **Assumption challenged**: which Q2 assumption is dropped or replaced.
2. **Mechanism class**: algorithm/method, data-representation,
   search/retrieval, planning/control, verification/feedback, training/data,
   orchestration, or a named new class.
3. **Mechanism + Hypothesis chain**:
   "We believe **X** helps because **Y**, and we will know it worked if **Z**."
   X is the mechanism, Y is causal and tied to Q1, Z is observable on B_dev.
4. **Orthogonality vs siblings**: name the axis that differs for each sibling.
5. **Conflicts with prior insight**: cite pruned/root conflicts and explain
   the counter, or write "none - attacks an axis no prior node touched".

## Self-Check

Kill or rewrite a candidate if any answer is yes:

- Could it be expressed as a single number or config knob?
- Is it only prompt rewording without a named prompting framework?
- Is it "more X" without a new mechanism?
- Does it state a goal instead of a mechanism?
- Does it re-tread a pruned node without a specific counter?
- Is it disconnected from the Probe Block?

For performance-first MLE/Kaggle plugins, parameter tuning, prompt edits,
ensembles, and scaling can be legitimate. In that mode, use
`arbor-agent-plugins-hitl-budget` to decide which filters are relaxed, but
still require evidence, scope, cost awareness, and non-duplicate ideas.

## TreeAddNode Format

Every committed `hypothesis` must contain exactly four labelled lines in this
order:

```text
Mechanism: <X - the new component / pipeline stage / data structure>
Hypothesis: <Y - causal story tied to the named bottleneck>
Observable: <Z - score delta and/or qualitative shift on B_dev>
Conflicts: <none - attacks an unexplored axis, OR pruned [<id>] said <X>; this counters via <Y>>
```

Do not include the scratch declaration, probe, self-check, or long rationale
inside the tool call.
