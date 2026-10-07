"""Validate prerequisite dependencies between kanban cards."""

from __future__ import annotations


from koi.core.models import ExperimentCard, KanbanBoard



def normalize_dependency_ids(
    raw: list[str] | None,
    valid_ids: set[str],
    self_id: str = "",
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in raw or []:
        dep = str(item or "").strip()
        if not dep or dep == self_id or dep not in valid_ids or dep in seen:
            continue
        seen.add(dep)
        out.append(dep)
    return out


def normalize_depends_on_list(
    deps: list[str] | None,
    board: KanbanBoard,
    *,
    self_id: str = "",
) -> list[str]:
    valid = {c.id for c in board.cards}
    normalized = normalize_dependency_ids(deps, valid, self_id)
    if self_id and would_create_cycle(board.cards, self_id, normalized):
        return []
    return normalized


def normalize_card_depends_on(
    card: ExperimentCard,
    board: KanbanBoard,
    *,
    allow_cycles: bool = False,
) -> list[str]:
    """Keep only valid same-board prerequisite ids."""
    valid = {c.id for c in board.cards}
    deps = normalize_dependency_ids(card.depends_on, valid, card.id)
    if allow_cycles:
        return deps
    if would_create_cycle(board.cards, card.id, deps):
        return list(card.depends_on or [])
    return deps


def would_create_cycle(
    cards: list[ExperimentCard],
    card_id: str,
    new_deps: list[str],
) -> bool:
    graph = {c.id: list(c.depends_on or []) for c in cards}
    graph[card_id] = list(new_deps)

    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for dep in graph.get(node, []):
            if dfs(dep):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    for cid in graph:
        if dfs(cid):
            return True
    return False


# Compatibility aliases for callers using the original private names.
_normalize_dep_ids = normalize_dependency_ids
_would_create_cycle = would_create_cycle
