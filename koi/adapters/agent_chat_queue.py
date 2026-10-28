"""Queue of user questions from ResearchOS UI — for Cursor agent."""

from __future__ import annotations

import json
import os
import threading
from functools import wraps

_QUEUE_LOCK = threading.RLock()

def _locked(fn):
    @wraps(fn)
    def call(*args, **kwargs):
        with _QUEUE_LOCK:
            return fn(*args, **kwargs)
    return call
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
    project_id: Optional[str]
    question: str
    enqueued_at: str
    method_id: Optional[str]
    node_id: Optional[str]
    status: AgentChatStatus
    answer: Optional[str]
    processing_at: Optional[str]
    processing_pid: Optional[int]
    answered_at: Optional[str]
    answer_kind: Optional[AnswerKind]
    purpose: str
    board_id: Optional[str]
    card_id: Optional[str]
    report_markdown: str
    proposal: Optional[dict[str, str]]
    review_passed: bool
    cli_agent: Optional[str]
    conversation_id: Optional[str]
    context_suggestions: Optional[dict]
    card_links: list[dict]
    git_snapshot: Optional[str]
    git_notice_version: Optional[int]


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
    temp = QUEUE_PATH.with_suffix(".tmp")
    temp.write_text(
        json.dumps(items, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, QUEUE_PATH)


def _normalize(item: dict) -> AgentChatItem:
    out: AgentChatItem = {
        "id": str(item["id"]),
        "project_id": str(item["project_id"]) if item["project_id"] is not None else None,
        "question": str(item["question"]),
        "enqueued_at": str(item["enqueued_at"]),
        "method_id": item.get("method_id") or None,
        "node_id": item.get("node_id") or None,
        "status": item.get("status") or "pending",
        "answer": item.get("answer") or None,
        "processing_at": item.get("processing_at") or None,
        "processing_pid": item.get("processing_pid"),
        "answered_at": item.get("answered_at") or None,
        "answer_kind": item.get("answer_kind") or None,
        "purpose": item.get("purpose", "agent"),
        "board_id": item.get("board_id"),
        "card_id": item.get("card_id"),
        "report_markdown": item.get("report_markdown", ""),
        "proposal": item.get("proposal"),
        "review_passed": bool(item.get("review_passed", False)),
        "conversation_id": item.get("conversation_id"),
        "context_suggestions": item.get("context_suggestions"),
        "card_links": item.get("card_links", []),
        "git_snapshot": item.get("git_snapshot"),
        "git_notice_version": item.get("git_notice_version"),
    }
    cli_agent = item.get("cli_agent") or None
    if cli_agent:
        out["cli_agent"] = str(cli_agent)
    if out["status"] == "answered" and not out.get("answer"):
        out["status"] = "pending"
        out["answered_at"] = None
    return out


def _valid_item(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    return all(
        isinstance(item.get(k), str) and item[k]
        for k in ("id", "question", "enqueued_at")
    ) and (isinstance(item.get("project_id"), str) and bool(item["project_id"])
           or item.get("project_id") is None and bool(item.get("conversation_id")))


def _prune_project(items: list[AgentChatItem], project_id: str) -> list[AgentChatItem]:
    # Interviews are durable card history, not disposable Q&A entries.
    card_items = [i for i in items if i["project_id"] == project_id and (i.get("card_id") or i.get("conversation_id"))]
    project_items = [i for i in items if i["project_id"] == project_id and not (i.get("card_id") or i.get("conversation_id"))]
    other = [i for i in items if i["project_id"] != project_id]
    if len(project_items) <= MAX_ITEMS_PER_PROJECT:
        return other + card_items + project_items
    project_items.sort(key=lambda i: i.get("answered_at") or i["enqueued_at"])
    return other + card_items + project_items[-MAX_ITEMS_PER_PROJECT:]


@_locked
def enqueue_question(
    project_id: str | None,
    question: str,
    *,
    method_id: Optional[str] = None,
    node_id: Optional[str] = None,
    purpose: str = "agent",
    board_id: Optional[str] = None,
    card_id: Optional[str] = None,
    report_markdown: str = "",
    cli_agent: Optional[str] = None,
    conversation_id: Optional[str] = None,
    git_snapshot: Optional[str] = None,
    git_notice_version: Optional[int] = None,
) -> AgentChatItem:
    text = question.strip()
    if not text:
        raise ValueError("Question is empty")
    items = _load()
    item: AgentChatItem = {
        "id": f"aq-{uuid4().hex[:10]}",
        "project_id": project_id,
        "conversation_id": conversation_id,
        "git_snapshot": git_snapshot,
        "git_notice_version": git_notice_version,
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
    if cli_agent:
        item["cli_agent"] = cli_agent
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


@_locked
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
            _note_inbox(item_id, "Агент взял вопрос в работу.")
        item["processing_pid"] = os.getpid()
        _save(items)
        return item
    raise KeyError(f"Queue item not found: {item_id}")


@_locked
def clear_processing_pid(item_id: str) -> None:
    items = _load()
    for item in items:
        if item["id"] == item_id and item.get("processing_pid") == os.getpid():
            item.pop("processing_pid", None)
            _save(items)
            return


def agent_active(item: AgentChatItem) -> bool:
    pid = item.get("processing_pid")
    if item["status"] != "processing" or not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


@_locked
def submit_answer(
    item_id: str,
    answer: str,
    *,
    answer_kind: AnswerKind = "normal",
    review_passed: bool = False,
) -> AgentChatItem:
    text = answer.strip()
    if not text:
        raise ValueError("Answer is empty")
    items = _load()
    for item in items:
        if item["id"] != item_id:
            continue
        item["status"] = "answered"
        if answer_kind == "normal":
            from koi.agent_chat.card_links import parse_reply as parse_card_links
            text, item["card_links"] = parse_card_links(text, item)
        if item["project_id"] is None and answer_kind == "normal":
            from koi.agent_chat.context_routing import parse_reply
            from koi.agent_chat.conversations import find
            chat = find(item.get("conversation_id")) or {}
            text, suggestions = parse_reply(text, program_id=chat.get("program_id"))
            item["context_suggestions"] = None if chat.get("context_suggestions_dismissed") else suggestions
        if item.get("purpose") in ("report_grill", "grill_me"):
            from koi.adapters.report_grill_reply import parse_reply
            item["review_passed"] = review_passed
            text, proposal = parse_reply(text)
            item["proposal"] = proposal if item["review_passed"] else None
        item["answer"] = text
        item["answer_kind"] = answer_kind
        item["answered_at"] = datetime.now(timezone.utc).isoformat()
        _save(items)
        _note_inbox(item_id, "Ответ опубликован в чате.")
        return item
    raise KeyError(f"Queue item not found: {item_id}")


@_locked
def resolve_context_suggestions(item_id: str) -> None:
    items = _load()
    for item in items:
        if item["id"] == item_id and item.get("context_suggestions"):
            item["context_suggestions"]["resolved"] = True
            _save(items)
            return
    raise KeyError(item_id)


def _note_inbox(item_id: str, message: str) -> None:
    from koi.adapters.settings_store import get_agent_chat_mode
    if get_agent_chat_mode() != "cursor_inbox":
        return
    from koi.adapters.agent_chat_activity import record
    record(item_id, message)


@_locked
def dequeue(item_id: str) -> bool:
    """Remove item from the queue (used by DELETE /agent-chat/{id})."""
    items = _load()
    next_items = [i for i in items if i["id"] != item_id]
    if len(next_items) == len(items):
        return False
    _save(next_items)
    return True
