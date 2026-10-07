"""Read/write KOI projects as Markdown (AI-friendly, no DB)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from koi.core.models import (
    DEFAULT_KANBAN_COLUMNS,
    LEGACY_COLUMN_PLANNED,
    ExperimentCard,
    KanbanBoard,
    KanbanColumn,
    MethodResearchQuestion,
    Node,
    NodeType,
    Project,
    ResearchQuestionCertainty,
    Verdict,
)


def normalize_kanban_board(board: KanbanBoard) -> KanbanBoard:
    """Drop legacy ``planned`` column; move its cards to backlog."""
    for card in board.cards:
        if card.column_id == LEGACY_COLUMN_PLANNED:
            card.column_id = "backlog"
    default_by_id = {c.id: c for c in DEFAULT_KANBAN_COLUMNS}
    existing = {c.id: c for c in board.columns if c.id != LEGACY_COLUMN_PLANNED}
    board.columns = [
        KanbanColumn(
            id=dc.id,
            title=existing[dc.id].title if dc.id in existing else dc.title,
            order=i,
        )
        for i, dc in enumerate(DEFAULT_KANBAN_COLUMNS)
    ]
    valid_cols = {c.id for c in board.columns}
    for card in board.cards:
        if card.column_id not in valid_cols:
            card.column_id = "backlog"
    return board

HEADING_RE = re.compile(
    r"^(#{1,6})\s+(problem|cause|cause_evidence|remediation|method|experiment):\s*(\S+)\s*$",
    re.IGNORECASE,
)
KANBAN_START_RE = re.compile(r"^<!--\s*koi:kanban\s+(\S+)\s*-->\s*$", re.IGNORECASE)
METHOD_QUESTIONS_START_RE = re.compile(
    r"^<!--\s*koi:method-questions\s*-->\s*$", re.IGNORECASE
)
CARD_META_RE = re.compile(
    r"^(.*?)(?:\s*<!--\s*(.*?)\s*-->)?\s*$",
    re.DOTALL,
)
CARD_TAG_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
VERDICT_RE = re.compile(r"^verdict:\s*(open|supported|refuted)\s*$", re.IGNORECASE)


def normalize_card_tag(raw: str) -> Optional[str]:
    tag = str(raw or "").strip()
    if not tag or not CARD_TAG_NAME_RE.match(tag):
        return None
    return tag


def normalize_card_tags(raw: list[str] | None) -> list[str]:
    if not raw:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        tag = normalize_card_tag(str(item))
        if not tag:
            continue
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(tag)
    return out


def register_project_card_tags(project: Project, tags: list[str]) -> None:
    existing = {t.lower() for t in project.card_tags}
    for tag in normalize_card_tags(tags):
        if tag.lower() not in existing:
            project.card_tags.append(tag)
            existing.add(tag.lower())


def _parse_card_tags(raw: str) -> list[str]:
    parts = re.split(r"[,;]+", raw)
    return normalize_card_tags(parts)


def _encode_card_desc(desc: str) -> str:
    """Keep kanban table rows single-line while preserving multiline descriptions."""
    return desc.replace("\r\n", "\n").replace("\n", r"\n").replace("-->", "→")


def _decode_card_desc(desc: str) -> str:
    return desc.replace(r"\n", "\n")


def _parse_card_deps(raw: str) -> list[str]:
    parts = re.split(r"[,;]+", raw)
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        dep = str(part or "").strip()
        if not dep or dep in seen:
            continue
        seen.add(dep)
        out.append(dep)
    return out


def card_now_iso() -> str:
    """UTC timestamp for ExperimentCard created_at / updated_at."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_card_timestamp(raw: str) -> Optional[str]:
    stamp = str(raw or "").strip()
    if not stamp:
        return None
    # Accept ISO-8601 with optional fractional seconds / offset; normalize to Z form when possible.
    try:
        normalized = stamp.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return stamp if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?", stamp) else None


_PINNED_TRUE = {"1", "true", "yes", "on"}


def _parse_card_comment(
    meta: str,
) -> tuple[Optional[str], str, list[str], list[str], Optional[str], Optional[str], bool]:
    card_id: Optional[str] = None
    desc = ""
    tags: list[str] = []
    depends_on: list[str] = []
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    pinned = False

    id_m = re.search(r"\bid:(\S+)", meta)
    if id_m:
        card_id = id_m.group(1)

    created_m = re.search(r"\bcreated:(\S+)", meta)
    if created_m:
        created_at = _parse_card_timestamp(created_m.group(1))

    updated_m = re.search(r"\bupdated:(\S+)", meta)
    if updated_m:
        updated_at = _parse_card_timestamp(updated_m.group(1))

    deps_m = re.search(r"\bdeps:([^\s]+)", meta)
    if deps_m:
        depends_on = _parse_card_deps(deps_m.group(1).strip())

    # Same token shape as deps — not $-anchored. Writer emits `tags:… deps:…`,
    # so a trailing tags:(.+?)$ would swallow deps and drop/corrupt tags.
    tags_m = re.search(r"\btags:([^\s]+)", meta)
    if tags_m:
        tags = _parse_card_tags(tags_m.group(1).strip())

    pinned_m = re.search(r"\bpinned:([^\s]+)", meta)
    if pinned_m:
        pinned = pinned_m.group(1).strip().lower() in _PINNED_TRUE

    meta_for_desc = meta
    for m in sorted(
        (m for m in (deps_m, tags_m, created_m, updated_m, pinned_m) if m),
        key=lambda m: m.start(),
        reverse=True,
    ):
        meta_for_desc = (meta_for_desc[: m.start()] + meta_for_desc[m.end() :]).rstrip()

    desc_m = re.search(r"\bdesc:(.*)$", meta_for_desc, re.DOTALL)
    if desc_m:
        desc = _decode_card_desc(desc_m.group(1).strip())

    return card_id, desc, tags, depends_on, created_at, updated_at, pinned


def _parse_card_cell(
    raw: str,
) -> tuple[str, Optional[str], str, list[str], list[str], Optional[str], Optional[str], bool]:
    m = CARD_META_RE.match(raw)
    if not m:
        return raw.strip(), None, "", [], [], None, None, False
    title = m.group(1).strip()
    comment = m.group(2)
    if not comment:
        return title, None, "", [], [], None, None, False
    card_id, desc, tags, depends_on, created_at, updated_at, pinned = _parse_card_comment(
        comment
    )
    return title, card_id, desc, tags, depends_on, created_at, updated_at, pinned


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta = yaml.safe_load(parts[1]) or {}
    body = parts[2].lstrip("\n")
    return meta, body


def _parse_method_questions(lines: list[str], start: int) -> tuple[list[MethodResearchQuestion], int]:
    """Parse YAML list after ``<!-- koi:method-questions -->``."""
    block: list[str] = []
    i = start
    while i < len(lines):
        line = lines[i]
        if (
            HEADING_RE.match(line)
            or KANBAN_START_RE.match(line)
            or METHOD_QUESTIONS_START_RE.match(line)
        ):
            break
        if line.strip() == "" and block:
            break
        block.append(line)
        i += 1
    if not block:
        return [], i
    raw = yaml.safe_load("\n".join(block))
    if not raw:
        return [], i
    if not isinstance(raw, list):
        raw = [raw]
    questions: list[MethodResearchQuestion] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        certainty_raw = str(item.get("certainty", "definite")).lower()
        try:
            certainty = ResearchQuestionCertainty(certainty_raw)
        except ValueError:
            certainty = ResearchQuestionCertainty.DEFINITE
        importance_raw = item.get("importance", 3)
        try:
            importance = max(1, min(5, int(importance_raw)))
        except (TypeError, ValueError):
            importance = 3
        card_id_raw = item.get("card_id")
        card_id = str(card_id_raw).strip() if card_id_raw else None
        questions.append(
            MethodResearchQuestion(
                id=str(item.get("id") or f"rq-{len(questions)}"),
                question=str(item.get("question") or "").strip(),
                answer=str(item.get("answer") or "").strip(),
                narrative=str(item.get("narrative") or "").strip(),
                certainty=certainty,
                importance=importance,
                card_id=card_id or None,
            )
        )
    return [q for q in questions if q.question], i


def _parse_kanban_table(lines: list[str], board_id: str, owner_node_id: str) -> KanbanBoard:
    columns: list[KanbanColumn] = []
    cards: list[ExperimentCard] = []
    if len(lines) < 2:
        return KanbanBoard(
            id=board_id,
            owner_node_id=owner_node_id,
            columns=list(DEFAULT_KANBAN_COLUMNS),
            cards=[],
        )

    header_cells = [c.strip().lower() for c in lines[0].strip("|").split("|")]
    columns = [
        KanbanColumn(id=cid, title=cid.replace("_", " ").title(), order=i)
        for i, cid in enumerate(header_cells)
    ]

    for row_line in lines[2:]:
        if not row_line.strip().startswith("|"):
            break
        cells = [c.strip() for c in row_line.strip("|").split("|")]
        for col_id, raw in zip(header_cells, cells):
            if not raw or raw in ("—", "-", ""):
                continue
            title, card_id, desc, tags, depends_on, created_at, updated_at, pinned = (
                _parse_card_cell(raw)
            )
            cards.append(
                ExperimentCard(
                    id=card_id or f"card-{len(cards)}",
                    board_id=board_id,
                    column_id=col_id,
                    title=title,
                    description=desc,
                    tags=tags,
                    depends_on=depends_on,
                    created_at=created_at,
                    updated_at=updated_at,
                    pinned=pinned,
                )
            )

    return KanbanBoard(id=board_id, owner_node_id=owner_node_id, columns=columns, cards=cards)


def _parse_string_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = re.split(r"[,;\n]+", raw)
    elif isinstance(raw, list):
        parts = [str(item) for item in raw]
    else:
        return []
    return [part.strip() for part in parts if part and part.strip()]


def _parse_literature_keywords(raw: Any) -> list[str]:
    return _parse_string_list(raw)


def _parse_card_tag_vocabulary(raw: Any) -> list[str]:
    return normalize_card_tags(_parse_string_list(raw))


def parse_project_md(text: str, project_id: Optional[str] = None) -> Project:
    meta, body = _split_frontmatter(text)
    pid = str(meta.get("id") or project_id or "project")
    project = Project(
        id=pid,
        title=str(meta.get("title") or pid),
        description=str(meta.get("description") or ""),
        literature_keywords=_parse_literature_keywords(meta.get("literature_keywords")),
        card_tags=_parse_card_tag_vocabulary(meta.get("card_tags")),
        card_tag_colors={str(k).lower(): v for k, v in (meta.get("card_tag_colors") or {}).items()
                         if isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v)}
        if isinstance(meta.get("card_tag_colors"), dict) else {},
    )

    lines = body.splitlines()
    stack: list[tuple[int, str]] = []  # (heading_level, node_id)
    nodes: list[Node] = []
    boards: list[KanbanBoard] = []
    i = 0

    while i < len(lines):
        hm = HEADING_RE.match(lines[i])
        if hm:
            level = len(hm.group(1))
            node_type = NodeType(hm.group(2).lower())
            node_id = hm.group(3)

            while stack and stack[-1][0] >= level:
                stack.pop()
            parent_id = stack[-1][1] if stack else None
            stack.append((level, node_id))

            i += 1
            title = ""
            description_lines: list[str] = []
            verdict = Verdict.OPEN

            while i < len(lines):
                if (
                    HEADING_RE.match(lines[i])
                    or KANBAN_START_RE.match(lines[i])
                    or METHOD_QUESTIONS_START_RE.match(lines[i])
                ):
                    break
                line = lines[i]
                vm = VERDICT_RE.match(line.strip())
                if vm and not title:
                    verdict = Verdict(vm.group(1).lower())
                    i += 1
                    continue
                if line.strip() == "" and not title:
                    i += 1
                    continue
                if not title:
                    title = line.strip()
                else:
                    description_lines.append(line)
                i += 1

            nodes.append(
                Node(
                    id=node_id,
                    project_id=pid,
                    parent_id=parent_id,
                    node_type=node_type,
                    title=title or node_id,
                    description="\n".join(description_lines).strip(),
                    verdict=verdict,
                )
            )
            continue

        km = KANBAN_START_RE.match(lines[i])
        if km and stack:
            board_id = km.group(1)
            owner_node_id = stack[-1][1]
            i += 1
            table_lines: list[str] = []
            while i < len(lines) and (
                lines[i].strip().startswith("|") or lines[i].strip() == ""
            ):
                if lines[i].strip().startswith("|"):
                    table_lines.append(lines[i])
                i += 1
            boards.append(_parse_kanban_table(table_lines, board_id, owner_node_id))
            continue

        qm = METHOD_QUESTIONS_START_RE.match(lines[i])
        if qm and stack:
            owner_node_id = stack[-1][1]
            i += 1
            questions, i = _parse_method_questions(lines, i)
            for n in nodes:
                if n.id == owner_node_id:
                    n.research_questions = questions
                    break
            continue

        i += 1

    project.nodes = nodes
    project.boards = [normalize_kanban_board(b) for b in boards]
    return project


def _format_card(cell: ExperimentCard) -> str:
    base = cell.title.replace("|", "\\|")
    parts: list[str] = []
    if cell.id:
        parts.append(f"id:{cell.id}")
    if cell.pinned:
        parts.append("pinned:1")
    if cell.created_at:
        parts.append(f"created:{cell.created_at}")
    if cell.updated_at:
        parts.append(f"updated:{cell.updated_at}")
    if cell.description:
        parts.append(f"desc:{_encode_card_desc(cell.description)}")
    if cell.tags:
        tags = ",".join(t.replace(",", "") for t in cell.tags)
        parts.append(f"tags:{tags}")
    if cell.depends_on:
        deps = ",".join(d.replace(",", "") for d in cell.depends_on)
        parts.append(f"deps:{deps}")
    if parts:
        return f"{base} <!-- {' '.join(parts)} -->"
    return base


def _write_kanban(board: KanbanBoard) -> list[str]:
    cols = board.columns or list(DEFAULT_KANBAN_COLUMNS)
    col_ids = [c.id for c in cols]
    lines = [
        f"<!-- koi:kanban {board.id} -->",
        "| " + " | ".join(col_ids) + " |",
        "| " + " | ".join("---" for _ in col_ids) + " |",
    ]
    rows: dict[str, list[str]] = {cid: [] for cid in col_ids}
    for card in board.cards:
        if card.column_id in rows:
            rows[card.column_id].append(_format_card(card))

    max_rows = max((len(v) for v in rows.values()), default=0)
    for r in range(max_rows):
        cells = []
        for cid in col_ids:
            cards_in_col = rows[cid]
            cells.append(cards_in_col[r] if r < len(cards_in_col) else "")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return lines


def _children_map(nodes: list[Node]) -> dict[Optional[str], list[Node]]:
    children: dict[Optional[str], list[Node]] = {}
    for n in nodes:
        children.setdefault(n.parent_id, []).append(n)
    for key in children:
        children[key].sort(key=lambda x: (x.node_type.value, x.title))
    return children


def serialize_project_md(project: Project) -> str:
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta = {
        "id": project.id,
        "title": project.title,
        "description": project.description,
        "updated": updated,
        "format": "koi/1",
    }
    meta["card_tags"] = list(project.card_tags)
    meta["card_tag_colors"] = dict(project.card_tag_colors)
    boards_by_owner = {b.owner_node_id: b for b in project.boards}
    out: list[str] = [
        "---",
        yaml.dump(meta, allow_unicode=True, sort_keys=False).strip(),
        "---",
        "",
    ]

    root = next((n for n in project.nodes if n.node_type == NodeType.PROBLEM), None)
    if not root:
        return "\n".join(out)

    children = _children_map(project.nodes)

    def walk(node: Node, depth: int) -> None:
        hashes = "#" * depth
        out.append(f"{hashes} {node.node_type.value}: {node.id}")
        out.append("")
        if node.verdict != Verdict.OPEN:
            out.append(f"verdict: {node.verdict.value}")
            out.append("")
        out.append(node.title)
        out.append("")
        if node.description:
            out.append(node.description)
            out.append("")
        board = boards_by_owner.get(node.id)
        if board:
            out.extend(_write_kanban(board))
        for ch in children.get(node.id, []):
            walk(ch, depth + 1)

    walk(root, 1)
    return "\n".join(out).rstrip() + "\n"
