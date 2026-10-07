#!/usr/bin/env python3
"""Context and queue helpers for ResearchOS UI → Cursor agent chat."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from koi.adapters.paths import koi_root, research_json
from koi.adapters.workspace import get_workspace

_ws = get_workspace()

from koi.agent_chat.formatting import ANSWER_FORMAT_INSTRUCTIONS
from koi.adapters.agent_chat_queue import list_for_project, find_item, list_pending, mark_processing, submit_answer
from koi.adapters.card_reports import read_report
from koi.core.models import NodeType
from koi.adapters.repository import load_project
from koi.adapters.research_store import research_path


def _card_meta(project, board_id: str, card_id: str) -> dict | None:
    board = next((b for b in project.boards if b.id == board_id), None)
    if board is None:
        return None
    card = next((c for c in board.cards if c.id == card_id), None)
    if card is None:
        return None
    report = ""
    report_path = ""
    try:
        meta = read_report(project, board_id, card_id, card.title)
        report = meta.get("content", "")
        report_path = f"projects/{project.id}/{meta.get('relative_path', '')}"
    except Exception:
        pass
    return {
        "board_id": board_id,
        "card_id": card_id,
        "title": card.title,
        "description": card.description,
        "column_id": card.column_id,
        "report_path": report_path,
        "report_markdown": report.strip(),
    }


def _board_for_method(project, method_id: str):
    return next(
        (b for b in project.boards if b.owner_node_id == method_id),
        None,
    )


def build_research_database(project) -> list[dict]:
    """All research questions in the project — primary answer source for the agent."""
    records: list[dict] = []
    for node in project.nodes:
        if node.node_type != NodeType.METHOD or not node.research_questions:
            continue
        board = _board_for_method(project, node.id)
        board_id = board.id if board else None
        for q in node.research_questions:
            entry = {
                "id": q.id,
                "method_id": node.id,
                "method_title": node.title,
                "question": q.question,
                "narrative": q.narrative,
                "answer": q.answer,
                "certainty": q.certainty.value,
                "importance": q.importance,
                "card_id": q.card_id,
            }
            if q.card_id and board_id:
                card = _card_meta(project, board_id, q.card_id)
                if card:
                    entry["experiment"] = {
                        "card_title": card["title"],
                        "board_id": board_id,
                        "report_path": card["report_path"],
                    }
            records.append(entry)
    return records


def build_context(item_id: str) -> dict:
    item = find_item(item_id)
    if item is None:
        raise SystemExit(f"Queue item not found: {item_id}")

    project = load_project(item["project_id"], sync_reports=False)
    if project is None:
        raise SystemExit(f"Project not found: {item['project_id']}")

    research_db = build_research_database(project)
    scope_method = None
    scope_node = None

    method_id = item.get("method_id")
    if method_id:
        method = next((n for n in project.nodes if n.id == method_id), None)
        if method:
            scope_method = {
                "id": method.id,
                "title": method.title,
                "description": method.description,
            }

    node_id = item.get("node_id")
    if node_id:
        node = next((n for n in project.nodes if n.id == node_id), None)
        if node:
            scope_node = {
                "id": node.id,
                "title": node.title,
                "description": node.description,
                "node_type": node.node_type.value,
            }

    interview = {}
    purpose = item.get("purpose") or "question"
    skills = {
        "report_grill": "koi-grill-experiment/SKILL.md",
        "grill_me": "koi-grill-experiment/SKILL.md",
        "make_report": "koi-execute-card/SKILL.md",
    }
    if item.get("card_id"):
        history = list_for_project(project.id, limit=10000, board_id=item.get("board_id"), card_id=item.get("card_id"))
        interview = {
            "purpose": purpose,
            "card": _card_meta(project, item.get("board_id"), item.get("card_id")),
            "current_document": item.get("report_markdown", ""),
            "history": [{"user": h["question"], "assistant": h.get("answer"), "proposal": h.get("proposal")} for h in reversed(history) if h["enqueued_at"] < item["enqueued_at"]],
        }
        skill = skills.get(purpose)
        if skill:
            interview["skill"] = str(_ws.engine_root / "agents/skills" / skill)
        if purpose in ("report_grill", "grill_me"):
            from koi.agent_chat.report_grill import UI_POLICY
            interview["research_root"] = str(koi_root(project.id))
            interview["project_document_path"] = str(koi_root(project.id) / "project.md")
            interview["interview_policy"] = UI_POLICY
        elif purpose == "make_report":
            interview["task"] = "Собери отчёт по этой задаче, следуя скиллу koi-execute-card."
    return {
        **interview,
        "queue_id": item["id"],
        "enqueued_at": item["enqueued_at"],
        "user_question": item["question"],
        "project_id": project.id,
        "project_title": project.title,
        "scope_method": scope_method,
        "scope_node": scope_node,
        "research_database_path": str(
            research_path(project.id).relative_to(koi_root(project.id))
        ),
        "research_database": research_db,
        "answer_policy": interview.get("interview_policy", ANSWER_FORMAT_INSTRUCTIONS),
    }


def cmd_pending(_: argparse.Namespace) -> None:
    print(json.dumps(list_pending(), ensure_ascii=False, indent=2))


def cmd_context(args: argparse.Namespace) -> None:
    print(json.dumps(build_context(args.queue_id), ensure_ascii=False, indent=2))


def cmd_claim(args: argparse.Namespace) -> None:
    try:
        item = mark_processing(args.queue_id)
    except KeyError as e:
        raise SystemExit(str(e)) from e
    print(json.dumps(item, ensure_ascii=False, indent=2))


def cmd_answer(args: argparse.Namespace) -> None:
    text = args.text
    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    if not text or not text.strip():
        raise SystemExit("Answer text is empty")
    try:
        item = submit_answer(args.queue_id, text)
    except KeyError as e:
        raise SystemExit(str(e)) from e
    print(json.dumps(item, ensure_ascii=False, indent=2))


def cmd_complete(args: argparse.Namespace) -> None:
    """Deprecated alias: marks answered with a stub (use answer instead)."""
    raise SystemExit(
        "Use `answer` subcommand with full text — answers must appear in the UI."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_pending = sub.add_parser("pending", help="List queued questions")
    p_pending.set_defaults(func=cmd_pending)

    p_ctx = sub.add_parser("context", help="JSON context for one queue item")
    p_ctx.add_argument("queue_id")
    p_ctx.set_defaults(func=cmd_context)

    p_claim = sub.add_parser("claim", help="Mark question as processing (UI shows agent typing)")
    p_claim.add_argument("queue_id")
    p_claim.set_defaults(func=cmd_claim)

    p_answer = sub.add_parser("answer", help="Save agent answer (shown in UI)")
    p_answer.add_argument("queue_id")
    p_answer.add_argument("text", nargs="?", default="")
    p_answer.add_argument("--file", "-f", help="Read answer from file")
    p_answer.set_defaults(func=cmd_answer)

    p_done = sub.add_parser("complete", help=argparse.SUPPRESS)
    p_done.add_argument("queue_id")
    p_done.set_defaults(func=cmd_complete)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
