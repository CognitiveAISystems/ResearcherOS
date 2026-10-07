"""Queue of user questions from ResearchOS UI — for Cursor agent."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional, TypedDict
from uuid import uuid4

from koi.adapters.workspace import get_workspace

_ws = get_workspace()
QUEUE_PATH = _ws.run_dir / "agent-chat-queue.json"
MAX_ITEMS_PER_PROJECT = 50

AgentChatStatus = Literal["pending", "processing", "answered"]
AnswerKind = Literal["normal", "warning"]


class AgentChatItem(TypedDict, total=False):
    id: str
    project_id: str
    question: str
    enqueued_at: str
    method_id: Optional[str]
    node_id: Optional[str]
    status: AgentChatStatus
    answer: Optional[str]
    processing_at: Optional[str]
    answered_at: Optional[str]
    answer_kind: Optional[AnswerKind]
    purpose: str
    board_id: Optional[str]
    card_id: Optional[str]
    report_markdown: str
    proposal: Optional[dict[str, str]]


def _load() -> list[AgentChatItem]:
    if not QUEUE_PATH.exists():
        return []
    try:
        data = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [_normalize(item) for item in data if _valid_item(item)]
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save(items: list[AgentChatItem]) -> None:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUEUE_PATH.write_text(
        json.dumps(items, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _normalize(item: dict) -> AgentChatItem:
    out: AgentChatItem = {
        "id": str(item["id"]),
        "project_id": str(item["project_id"]),
        "question": str(item["question"]),
        "enqueued_at": str(item["enqueued_at"]),
        "method_id": item.get("method_id") or None,
        "node_id": item.get("node_id") or None,
        "status": item.get("status") or "pending",
        "answer": item.get("answer") or None,
        "processing_at": item.get("processing_at") or None,
        "answered_at": item.get("answered_at") or None,
        "answer_kind": item.get("answer_kind") or None,
        "purpose": item.get("purpose", "question"),
        "board_id": item.get("board_id"),
        "card_id": item.get("card_id"),
        "report_markdown": item.get("report_markdown", ""),
        "proposal": item.get("proposal"),
    }
    if out["status"] == "answered" and not out.get("answer"):
        out["status"] = "pending"
        out["answered_at"] = None
    return out


def _valid_item(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    return all(
        isinstance(item.get(k), str) and item[k]
        for k in ("id", "project_id", "question", "enqueued_at")
    )


def _prune_project(items: list[AgentChatItem], project_id: str) -> list[AgentChatItem]:
    # Interviews are durable card history, not disposable Q&A entries.
    card_items = [i for i in items if i["project_id"] == project_id and i.get("card_id")]
    project_items = [i for i in items if i["project_id"] == project_id and not i.get("card_id")]
    other = [i for i in items if i["project_id"] != project_id]
    if len(project_items) <= MAX_ITEMS_PER_PROJECT:
        return other + card_items + project_items
    project_items.sort(key=lambda i: i.get("answered_at") or i["enqueued_at"])
    return other + card_items + project_items[-MAX_ITEMS_PER_PROJECT:]


def enqueue_question(
    project_id: str,
    question: str,
    *,
    method_id: Optional[str] = None,
    node_id: Optional[str] = None,
    purpose: str = "question",
    board_id: Optional[str] = None,
    card_id: Optional[str] = None,
    report_markdown: str = "",
) -> AgentChatItem:
    text = question.strip()
    if not text:
        raise ValueError("Question is empty")
    items = _load()
    item: AgentChatItem = {
        "id": f"aq-{uuid4().hex[:10]}",
        "project_id": project_id,
        "question": text,
        "purpose": purpose,
        "board_id": board_id,
        "card_id": card_id,
        "report_markdown": report_markdown,
        "enqueued_at": datetime.now(timezone.utc).isoformat(),
        "method_id": method_id or None,
        "node_id": node_id or None,
        "status": "pending",
        "answer": None,
        "processing_at": None,
        "answered_at": None,
        "answer_kind": None,
    }
    items.append(item)
    items = _prune_project(items, project_id)
    _save(items)
    return item


def list_pending() -> list[AgentChatItem]:
    return [i for i in _load() if i.get("status", "pending") == "pending"]


def list_for_project(project_id: str, *, limit: int = 30, board_id: str | None = None, card_id: str | None = None) -> list[AgentChatItem]:
    items = [i for i in _load() if i["project_id"] == project_id]
    if card_id is not None:
        items = [i for i in items if i.get("board_id") == board_id and i.get("card_id") == card_id]
    items.sort(key=lambda i: i["enqueued_at"], reverse=True)
    return items[:limit]


def find_item(item_id: str) -> Optional[AgentChatItem]:
    return next((i for i in _load() if i["id"] == item_id), None)


def mark_processing(item_id: str) -> AgentChatItem:
    items = _load()
    for item in items:
        if item["id"] != item_id:
            continue
        status = item.get("status") or "pending"
        if status == "answered":
            return item
        if status != "processing":
            item["status"] = "processing"
            item["processing_at"] = datetime.now(timezone.utc).isoformat()
            _save(items)
            _note_inbox(item_id, "Агент взял вопрос в работу.")
        return item
    raise KeyError(f"Queue item not found: {item_id}")


def submit_answer(
    item_id: str,
    answer: str,
    *,
    answer_kind: AnswerKind = "normal",
) -> AgentChatItem:
    text = answer.strip()
    if not text:
        raise ValueError("Answer is empty")
    items = _load()
    for item in items:
        if item["id"] != item_id:
            continue
        item["status"] = "answered"
        if item.get("purpose") in ("report_grill", "grill_me"):
            from koi.adapters.report_grill_reply import parse_reply
            text, proposal = parse_reply(text)
            item["proposal"] = proposal
        item["answer"] = text
        item["answer_kind"] = answer_kind
        item["answered_at"] = datetime.now(timezone.utc).isoformat()
        _save(items)
        _note_inbox(item_id, "Ответ опубликован в чате.")
        return item
    raise KeyError(f"Queue item not found: {item_id}")


def _note_inbox(item_id: str, message: str) -> None:
    from koi.adapters.settings_store import get_agent_chat_mode
    if get_agent_chat_mode() != "cursor_inbox":
        return
    from koi.adapters.agent_chat_activity import record
    record(item_id, message)


def dequeue(item_id: str) -> bool:
    """Remove item from the queue (used by DELETE /agent-chat/{id})."""
    items = _load()
    next_items = [i for i in items if i["id"] != item_id]
    if len(next_items) == len(items):
        return False
    _save(next_items)
    return True
