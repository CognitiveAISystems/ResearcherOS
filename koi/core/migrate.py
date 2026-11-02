"""One-time migrations for loaded projects (e.g. kanban on hypothesis → method)."""

from __future__ import annotations

from koi.core.models import Node, NodeType, Project

_LEGACY_KANBAN_HYPOTHESIS_TYPES = {NodeType.CAUSE_EVIDENCE, NodeType.REMEDIATION}


def default_method_title(hypothesis: Node) -> str:
    """Label for auto-created method under a hypothesis (not generic «Метод проверки»)."""
    title = hypothesis.title.strip()
    if len(title) <= 72:
        return title
    return title[:69].rstrip() + "…"


def migrate_legacy_kanban_owners(project: Project) -> bool:
    """Move boards from hypothesis nodes to child ``method`` nodes. Returns True if changed."""
    nodes_by_id = {n.id: n for n in project.nodes}
    changed = False
    new_nodes: list[Node] = []

    for board in list(project.boards):
        owner = nodes_by_id.get(board.owner_node_id)
        if owner is None or owner.node_type not in _LEGACY_KANBAN_HYPOTHESIS_TYPES:
            continue

        method_id = f"m-{owner.id}"
        if method_id not in nodes_by_id:
            method = Node(
                id=method_id,
                project_id=project.id,
                parent_id=owner.id,
                node_type=NodeType.METHOD,
                title=default_method_title(owner),
                description=owner.description or "",
            )
            new_nodes.append(method)
            nodes_by_id[method_id] = method
            changed = True

        if board.owner_node_id != method_id:
            board.owner_node_id = method_id
            changed = True

    if new_nodes:
        project.nodes.extend(new_nodes)

    return changed


def kanban_md_needs_upgrade(text: str) -> bool:
    """True when project.md still has a legacy kanban column."""
    for line in text.splitlines():
        stripped = line.strip().lower()
        if not stripped.startswith("|"):
            continue
        if "backlog" in stripped and "running" in stripped and "done" in stripped:
            if "successful" in stripped or "planned" in stripped:
                return True
    return False


def ensure_project_structure(project: Project) -> bool:
    """Apply all structural migrations; return True if project was modified."""
    return migrate_legacy_kanban_owners(project)
