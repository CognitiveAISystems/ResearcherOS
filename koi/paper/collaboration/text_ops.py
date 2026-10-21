"""Text diffs and 3-way import for filesystem / stale-client edits.

Does not implement a CRDT. It turns a known base→incoming change into
insert/delete operations that can be applied to the live document.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextSpan:
    """Replace ``old[start:end]`` with ``new_text``."""

    start: int
    end: int
    new_text: str

    @property
    def delete_len(self) -> int:
        return max(0, self.end - self.start)


@dataclass(frozen=True)
class MergeResult:
    ok: bool
    text: str
    changed: bool
    conflict: bool = False
    reason: str = ""
    agent_span: TextSpan | None = None
    human_span: TextSpan | None = None


def prefix_suffix_span(old: str, new: str) -> TextSpan:
    """Minimal replace-span that turns ``old`` into ``new``."""
    start = 0
    limit = min(len(old), len(new))
    while start < limit and old[start] == new[start]:
        start += 1
    old_end = len(old)
    new_end = len(new)
    while old_end > start and new_end > start and old[old_end - 1] == new[new_end - 1]:
        old_end -= 1
        new_end -= 1
    return TextSpan(start, old_end, new[start:new_end])


def apply_span_to_string(text: str, span: TextSpan) -> str:
    start = max(0, min(span.start, len(text)))
    end = max(start, min(span.end, len(text)))
    return text[:start] + span.new_text + text[end:]


def spans_overlap(left: TextSpan, right: TextSpan) -> bool:
    return left.start < right.end and right.start < left.end


def clamp_span(span: TextSpan, length: int) -> TextSpan:
    start = max(0, min(span.start, length))
    end = max(start, min(span.end, length))
    return TextSpan(start, end, span.new_text)


def shift_span(span: TextSpan, other: TextSpan) -> TextSpan:
    """Move ``span`` (defined on a shared base) after ``other`` was applied."""
    if other.end <= span.start:
        delta = len(other.new_text) - other.delete_len
        return TextSpan(span.start + delta, span.end + delta, span.new_text)
    if span.end <= other.start:
        return span
    after = other.start + len(other.new_text)
    return TextSpan(after, after, span.new_text)


def import_relative(base: str, current: str, incoming: str) -> MergeResult:
    """Apply ``diff(base, incoming)`` onto ``current``.

    Silent wholesale replace of ``current`` with ``incoming`` is never used
    when ``current`` has moved past ``base``.
    """
    if incoming == current:
        return MergeResult(ok=True, text=current, changed=False)
    if incoming == base:
        return MergeResult(ok=True, text=current, changed=False)
    if current == base:
        return MergeResult(ok=True, text=incoming, changed=True)

    human = prefix_suffix_span(base, current)
    agent = prefix_suffix_span(base, incoming)

    # Same insertion point: a later keystroke batch is an extension of the
    # earlier one (stale base_revision). Do not insert the longer string
    # *again* in front of the shorter one.
    if human.start == agent.start and human.delete_len == 0 and agent.delete_len == 0:
        if agent.new_text.startswith(human.new_text):
            return MergeResult(ok=True, text=incoming, changed=True, agent_span=agent, human_span=human)
        if human.new_text.startswith(agent.new_text):
            return MergeResult(ok=True, text=current, changed=False, agent_span=agent, human_span=human)

    if not spans_overlap(human, agent):
        shift = 0
        if human.start < agent.start:
            shift = len(human.new_text) - human.delete_len
        start = agent.start + shift
        old_len = agent.delete_len
        if current[start : start + old_len] != base[agent.start : agent.end]:
            return MergeResult(
                ok=False,
                text=current,
                changed=False,
                conflict=True,
                reason="agent region no longer matches base",
                agent_span=agent,
                human_span=human,
            )
        merged = current[:start] + agent.new_text + current[start + old_len :]
        return MergeResult(ok=True, text=merged, changed=True, agent_span=agent, human_span=human)

    return MergeResult(
        ok=False,
        text=current,
        changed=False,
        conflict=True,
        reason="overlapping human and external edits",
        agent_span=agent,
        human_span=human,
    )


def merge_proposal(base: str, current: str, incoming: str) -> MergeResult:
    """Conservative line-wise three-way merge; competing insertions conflict."""
    import difflib

    if incoming == current or incoming == base:
        return MergeResult(ok=True, text=current, changed=False)
    if current == base:
        return MergeResult(ok=True, text=incoming, changed=True)
    lines = base.splitlines(keepends=True)

    def edits(text):
        target = text.splitlines(keepends=True)
        return [(a, b, target[c:d]) for op, a, b, c, d in
                difflib.SequenceMatcher(None, lines, target, autojunk=False).get_opcodes()
                if op != "equal"]

    human, agent = edits(current), edits(incoming)
    combined = list(human)
    for edit in agent:
        if edit in human:
            continue
        a, b, _ = edit
        for c, d, _ in human:
            overlap = max(a, c) < min(b, d)
            if a == b:
                overlap = c <= a <= d
            if c == d:
                overlap = a <= c <= b
            if overlap:
                return MergeResult(ok=False, text=current, changed=False, conflict=True,
                                   reason="Один фрагмент изменён человеком и агентом")
        combined.append(edit)
    for a, b, replacement in sorted(combined, key=lambda edit: edit[:2], reverse=True):
        lines[a:b] = replacement
    merged = "".join(lines)
    return MergeResult(ok=True, text=merged, changed=merged != current)
