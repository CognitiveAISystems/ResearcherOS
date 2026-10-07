"""Frontend-facing project read models shared by API and Hub."""

from __future__ import annotations

from typing import Optional

from koi.core.models import ALLOWED_CHILDREN, KANBAN_OWNER_TYPES, NodeType, Project


def _page_pins(project_id: str) -> dict:
    try:
        from koi.adapters.pages import visible_pins

        return visible_pins(project_id)
    except Exception:
        return {}


def merge_page_pins(project_ids: list[str]) -> dict[str, list[dict[str, str]]]:
    """Union visible page pins across member repos (composite view).

    Each pin keeps ``project_id`` so the UI can open the HTML from the owning
    repo — composite ids are not writable storage roots.
    """
    out: dict[str, list[dict[str, str]]] = {}
    seen: dict[str, set[str]] = {}
    for project_id in project_ids:
        if not project_id:
            continue
        for node_id, pins in _page_pins(project_id).items():
            if not isinstance(pins, list):
                continue
            bucket = out.setdefault(str(node_id), [])
            seen_ids = seen.setdefault(str(node_id), set())
            for pin in pins:
                if not isinstance(pin, dict):
                    continue
                page_id = str(pin.get("id") or pin.get("page_id") or "").strip()
                if not page_id or page_id in seen_ids:
                    continue
                seen_ids.add(page_id)
                bucket.append(
                    {
                        "id": page_id,
                        "title": str(pin.get("title") or ""),
                        "project_id": project_id,
                    }
                )
    return out


def project_to_client(
    project: Project,
    *,
    board_sources: Optional[dict[str, str]] = None,
) -> dict:
    boards_by_owner = {board.owner_node_id: board for board in project.boards}
    nodes_out = []
    for node in project.nodes:
        item = node.model_dump()
        item["node_type"] = node.node_type.value
        item["verdict"] = node.verdict.value
        if node.node_type in KANBAN_OWNER_TYPES:
            board = boards_by_owner.get(node.id)
            item["has_kanban"] = board is not None
            item["board_id"] = board.id if board else None
            item["has_research_questions"] = len(node.research_questions) > 0
            counts = {"definite": 0, "tentative": 0}
            for question in node.research_questions:
                counts[question.certainty.value] += 1
            item["research_question_counts"] = counts
            cards_by_id = {card.id: card for card in board.cards} if board else {}
            item["research_questions"] = [
                {
                    "id": question.id,
                    "question": question.question,
                    "answer": question.answer,
                    "narrative": question.narrative,
                    "certainty": question.certainty.value,
                    "importance": question.importance,
                    "card_id": question.card_id,
                    "card_title": (
                        cards_by_id[question.card_id].title
                        if question.card_id and question.card_id in cards_by_id
                        else None
                    ),
                }
                for question in node.research_questions
            ]
        else:
            item["has_kanban"] = False
            item["board_id"] = None
            item["has_research_questions"] = False
            item["research_question_counts"] = {"definite": 0, "tentative": 0}
            item["research_questions"] = []
        if node.node_type in (NodeType.CAUSE_EVIDENCE, NodeType.REMEDIATION):
            item["can_add_method"] = True
        nodes_out.append(item)

    boards_out = {
        board.id: {
            "id": board.id,
            "owner_node_id": board.owner_node_id,
            "source_project_id": (board_sources or {}).get(board.id) or project.id,
            "columns": [column.model_dump() for column in board.columns],
            # Only CRUD-authored created_at/updated_at — never filesystem mtime.
            "cards": [card.model_dump() for card in board.cards],
        }
        for board in project.boards
    }

    return {
        "id": project.id,
        "title": project.title,
        "description": project.description,
        "literature_keywords": list(project.literature_keywords),
        "card_tags": list(project.card_tags),
        "card_tag_colors": dict(project.card_tag_colors),
        "nodes": nodes_out,
        "boards": boards_out,
        "page_pins": _page_pins(project.id),
    }


def allowed_children(parent_type: str | None) -> list[str]:
    key = NodeType(parent_type) if parent_type else None
    return [node_type.value for node_type in ALLOWED_CHILDREN.get(key, [])]
