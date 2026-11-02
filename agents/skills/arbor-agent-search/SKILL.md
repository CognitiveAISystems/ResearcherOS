---
name: arbor-agent-search
description: "Related-work and novelty annotation phase for Arbor. Use after a node has been experimentally validated, especially before merge decisions, to emulate SearchIdeaContext/SearchIdeaContextParallel/SearchStatus, validated-node gating, background SearchAgent behavior, and structured prior-art summaries."
---

# Arbor Search Agent

Use this for post-experiment related-work annotation. It is not for internal
codebase search; use normal file tools for that.

## Eligibility Gate

By default, only search nodes that are validated and effective:

- node status is `done` or `merged`;
- node has a numeric score;
- score improves over current `trunk_score`, or over `baseline_score` if trunk
  is unavailable.

Skip pending, running, unscored, and below-trunk nodes. This keeps novelty cost
tied to merge candidates.

## When To Search

- After `RunExecutor` returns a node with `score > trunk_score`.
- Before `GitMergeBranch` when novelty or related work affects the decision.
- After parallel executor results, annotate all sibling winners with
  `SearchIdeaContextParallel`.

Do not search trivial parameter tweaks, pure scale-ups, or internal codebase
questions.

## SearchAgent Task

The SearchAgent is a novelty scout. It does not implement, critique, or change
the idea. It surveys prior work and writes a Markdown annotation to
`node.related_work`.

Use 2-3 query angles:

- technique class;
- application domain;
- key mechanism.

For ML/NLP literature, use English academic queries with words such as
`paper`, `arxiv`, or `survey`; include one original-language query when useful.

## Hard Caps

- At most 2 search rounds.
- Visit up to 5 pages total.
- Keep the result short enough for a researcher to judge novelty quickly.

## Final JSON Schema

When running an isolated SearchAgent, ask it to emit only:

```json
{
  "summary": "2-4 sentences describing prior work.",
  "related_papers": [
    {
      "title": "Paper title",
      "url": "https://...",
      "one_line_relevance": "Why this is relevant."
    }
  ],
  "novelty_assessment": "novel | partial-overlap | prior-art-exists",
  "overlap_risks": "What specifically overlaps, or 'none'."
}
```

Render it into:

```text
### Summary
...

### Related Papers
- [Title](url) - relevance

### Novelty
novel | partial-overlap | prior-art-exists - justification

### Overlap Risks
...
```

## Background Behavior

Native Arbor usually runs SearchAgent in the background:

- `SearchIdeaContext` returns a dispatch message immediately.
- The coordinator continues IDEATE/DISPATCH work.
- The result lands on `node.related_work` later.
- `SearchStatus` reports in-flight searches.
- Shutdown waits for pending searches to flush.

When emulating in a host that lacks background tasks, run search synchronously
and update `related_work` before merging.

## Failure Handling

Failures are non-blocking. Write a marker such as:

```text
[search-failed: <reason>]
```

Treat it as no information, not evidence of novelty.
