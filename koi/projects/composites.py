"""Merge hypothesis trees from multiple projects sharing a ``composite_id``.

Nodes are matched at read time by structural signature
``(node_type, normalized title, canonical parent)``, not only by id.
Shared ancestors created independently in different repos (same title, different
ids) collapse into one vertex; ``parent_id`` / board ``owner_node_id`` are
remapped onto the canonical ids.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

import yaml

from koi.adapters.paths import project_md
from koi.adapters.project_mount import list_mounts
from koi.adapters.repository import load_project
from koi.core.models import ExperimentCard, KanbanBoard, Node, Project
from koi.projects.views import project_to_client


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta = yaml.safe_load(parts[1]) or {}
    return meta, parts[2].lstrip("\n")


def read_composite_id(project_id: str) -> str | None:
    path = project_md(project_id)
    if not path.is_file():
        return None
    meta, _ = _split_frontmatter(path.read_text(encoding="utf-8"))
    raw = meta.get("composite_id")
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


def list_composite_ids() -> list[str]:
    ids: set[str] = set()
    for mount in list_mounts():
        cid = read_composite_id(mount.project_id)
        if cid:
            ids.add(cid)
    return sorted(ids)


def members_for_composite(composite_id: str) -> list[str]:
    out: list[str] = []
    for mount in list_mounts():
        if read_composite_id(mount.project_id) == composite_id:
            out.append(mount.project_id)
    return sorted(out)


@dataclass
class NodeConflict:
    node_id: str
    field: str
    projects: dict[str, str]


@dataclass
class CompositeProject:
    composite_id: str
    title: str
    description: str
    members: list[dict[str, str]]
    project: Project
    conflicts: list[NodeConflict] = field(default_factory=list)
    board_sources: dict[str, str] = field(default_factory=dict)


def normalize_node_title(value: str) -> str:
    """Normalize titles for cross-repo node matching (NFKC, casefold, spaces)."""
    text = unicodedata.normalize("NFKC", value or "").strip().casefold()
    return re.sub(r"\s+", " ", text)


def _node_match_key(
    node_type: str, title: str, parent_canonical_id: str | None
) -> tuple[str, str, str]:
    return (node_type, normalize_node_title(title), parent_canonical_id or "")


def _topo_nodes(nodes: list[Node]) -> list[Node]:
    by_id = {n.id: n for n in nodes}
    depth_cache: dict[str, int] = {}

    def depth(node: Node) -> int:
        if node.id in depth_cache:
            return depth_cache[node.id]
        if not node.parent_id or node.parent_id not in by_id:
            depth_cache[node.id] = 0
        else:
            depth_cache[node.id] = depth(by_id[node.parent_id]) + 1
        return depth_cache[node.id]

    return sorted(nodes, key=lambda n: (depth(n), n.id))


def _conflict(
    existing: Node,
    project_id: str,
    field_name: str,
    existing_value: str,
    incoming_value: str,
) -> NodeConflict:
    return NodeConflict(
        node_id=existing.id,
        field=field_name,
        projects={
            existing.project_id: existing_value,
            project_id: incoming_value,
        },
    )


def _merge_nodes(
    member_projects: list[tuple[str, Project]],
) -> tuple[list[Node], list[NodeConflict], dict[tuple[str, str], str]]:
    """Merge nodes by signature across projects; remap foreign ids onto canonical.

    Match key: ``(node_type, normalized title, canonical parent id)``.
    Same-id nodes still merge (and may emit conflicts). Same-title siblings
    inside one project are kept distinct; only cross-project title matches collapse.
    """
    by_id: dict[str, Node] = {}
    by_sig: dict[tuple[str, str, str], Node] = {}
    id_remap: dict[tuple[str, str], str] = {}
    conflicts: list[NodeConflict] = []

    for project_id, project in member_projects:
        for node in _topo_nodes(project.nodes):
            parent_canonical: str | None = None
            if node.parent_id:
                parent_canonical = id_remap.get(
                    (project_id, node.parent_id), node.parent_id
                )

            sig = _node_match_key(node.node_type.value, node.title, parent_canonical)
            existing_sig = by_sig.get(sig)

            # Cross-project structural match (same type/title/parent, different ids).
            if existing_sig is not None and existing_sig.project_id != project_id:
                id_remap[(project_id, node.id)] = existing_sig.id
                if existing_sig.description.strip() != node.description.strip():
                    conflicts.append(
                        _conflict(
                            existing_sig,
                            project_id,
                            "description",
                            existing_sig.description.strip(),
                            node.description.strip(),
                        )
                    )
                continue

            existing_id = by_id.get(node.id)
            if existing_id is not None:
                id_remap[(project_id, node.id)] = existing_id.id
                for field_name, existing_val, incoming_val in (
                    (
                        "title",
                        existing_id.title,
                        node.title,
                    ),
                    (
                        "description",
                        existing_id.description.strip(),
                        node.description.strip(),
                    ),
                    (
                        "parent_id",
                        existing_id.parent_id or "",
                        parent_canonical or "",
                    ),
                    (
                        "node_type",
                        existing_id.node_type.value,
                        node.node_type.value,
                    ),
                ):
                    if field_name == "title":
                        if normalize_node_title(str(existing_val)) != normalize_node_title(
                            str(incoming_val)
                        ):
                            conflicts.append(
                                _conflict(
                                    existing_id,
                                    project_id,
                                    field_name,
                                    str(existing_val),
                                    str(incoming_val),
                                )
                            )
                            break
                    elif existing_val != incoming_val:
                        conflicts.append(
                            _conflict(
                                existing_id,
                                project_id,
                                field_name,
                                str(existing_val),
                                str(incoming_val),
                            )
                        )
                        break
                continue

            merged_node = node.model_copy(
                update={"parent_id": parent_canonical},
            )
            by_id[merged_node.id] = merged_node
            if sig not in by_sig:
                by_sig[sig] = merged_node
            id_remap[(project_id, node.id)] = merged_node.id

    return list(by_id.values()), conflicts, id_remap


def _remap_card(card: ExperimentCard, project_id: str, id_remap: dict[tuple[str, str], str]) -> ExperimentCard:
    linked = card.linked_node_id
    if not linked:
        return card
    new_linked = id_remap.get((project_id, linked), linked)
    if new_linked == linked:
        return card
    return card.model_copy(update={"linked_node_id": new_linked})


def _merge_boards(
    member_projects: list[tuple[str, Project]],
    id_remap: dict[tuple[str, str], str],
) -> tuple[list[KanbanBoard], dict[str, str]]:
    boards: list[KanbanBoard] = []
    board_sources: dict[str, str] = {}
    seen: set[str] = set()
    for project_id, project in member_projects:
        for board in project.boards:
            if board.id in seen:
                continue
            seen.add(board.id)
            owner = id_remap.get((project_id, board.owner_node_id), board.owner_node_id)
            cards = [_remap_card(card, project_id, id_remap) for card in board.cards]
            if owner != board.owner_node_id or cards != board.cards:
                board = board.model_copy(update={"owner_node_id": owner, "cards": cards})
            boards.append(board)
            board_sources[board.id] = project_id
    return boards, board_sources


def _composite_title(member_projects: list[tuple[str, Project]]) -> str:
    problem_titles: list[str] = []
    for _pid, project in member_projects:
        for node in project.nodes:
            if node.node_type.value == "problem" and node.title.strip():
                problem_titles.append(node.title.strip())
                break
    if problem_titles and len({normalize_node_title(t) for t in problem_titles}) == 1:
        return problem_titles[0]
    titles = [p.title for _, p in member_projects]
    if len(set(titles)) == 1:
        return titles[0]
    return member_projects[0][0].replace("-", " ").title()


def load_composite(composite_id: str) -> CompositeProject | None:
    member_ids = members_for_composite(composite_id)
    if len(member_ids) < 2:
        return None

    member_projects: list[tuple[str, Project]] = []
    for pid in member_ids:
        project = load_project(pid, sync_reports=False)
        if project is None:
            continue
        member_projects.append((pid, project))
    return build_composite(composite_id, member_projects)


def build_composite(
    composite_id: str, member_projects: list[tuple[str, Project]]
) -> CompositeProject | None:
    if len(member_projects) < 2:
        return None

    nodes, conflicts, id_remap = _merge_nodes(member_projects)
    boards, board_sources = _merge_boards(member_projects, id_remap)

    title = _composite_title(member_projects)
    descriptions = [p.description.strip() for _, p in member_projects if p.description.strip()]
    description = descriptions[0] if descriptions else ""

    merged = Project(
        id=f"composite:{composite_id}",
        title=title,
        description=description,
        literature_keywords=[],
        nodes=nodes,
        boards=boards,
    )

    members = [{"project_id": pid, "title": project.title} for pid, project in member_projects]

    return CompositeProject(
        composite_id=composite_id,
        title=title,
        description=description,
        members=members,
        project=merged,
        conflicts=conflicts,
        board_sources=board_sources,
    )


def composite_to_client(composite: CompositeProject) -> dict[str, Any]:
    from koi.projects.views import merge_page_pins

    payload = project_to_client(
        composite.project,
        board_sources=composite.board_sources,
    )
    payload["is_composite"] = True
    payload["composite_id"] = composite.composite_id
    payload["members"] = composite.members
    payload["conflicts"] = [
        {"node_id": c.node_id, "field": c.field, "projects": c.projects}
        for c in composite.conflicts
    ]
    member_ids = [
        str(m.get("project_id") or "")
        for m in composite.members
        if isinstance(m, dict) and m.get("project_id")
    ]
    # Composite id is virtual — page HTML lives in member koi-structure/pages/.
    payload["page_pins"] = merge_page_pins(member_ids)
    payload["card_tag_colors_by_project"] = {
        pid: dict(member.card_tag_colors) for pid in member_ids
        if (member := load_project(pid, sync_reports=False)) is not None
    }
    for node in payload["nodes"]:
        node["source_project_id"] = node.get("project_id")
    for board in payload["boards"].values():
        source = composite.board_sources.get(board["id"])
        if source:
            board["source_project_id"] = source
            continue
        owner_id = board.get("owner_node_id")
        owner = next((n for n in payload["nodes"] if n["id"] == owner_id), None)
        if owner:
            board["source_project_id"] = owner.get("project_id")
    return payload


def list_composites_summary() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for composite_id in list_composite_ids():
        member_ids = members_for_composite(composite_id)
        if len(member_ids) < 2:
            continue
        member_projects: list[tuple[str, Project]] = []
        programs: set[str] = set()
        for pid in member_ids:
            project = load_project(pid, sync_reports=False)
            if project:
                member_projects.append((pid, project))
            mount = next((m for m in list_mounts() if m.project_id == pid), None)
            if mount:
                programs.update(mount.programs)
        if len(member_projects) < 2:
            continue
        out.append(
            {
                "id": composite_id,
                "title": _composite_title(member_projects),
                "member_ids": member_ids,
                "programs": sorted(programs),
            }
        )
    return out
