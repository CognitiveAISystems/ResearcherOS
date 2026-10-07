from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException

from api.schemas import (
    AgentChatAnswerBody,
    AgentChatBody,
    AgentChatSettingsBody,
    CursorApiKeyBody,
    InboxConfiguredBody,
)
from koi.adapters.agent_chat_queue import (
    dequeue as dequeue_agent_chat_item,
    enqueue_question,
    find_item,
    list_for_project,
    list_pending,
    submit_answer,
)
from koi.agent_chat.auto import try_auto_answer
from koi.agent_chat.activity import delete as delete_agent_chat_activity, read as read_agent_chat_activity, record as record_agent_activity
from koi.agent_chat.runner import process_item
from koi.agent_chat.settings import settings_snapshot
from koi.adapters.settings_store import is_cursor_inbox_agent_mode
from koi.agent_chat.inbox import (
    inbox_task_message,
    notify_chat_inbox_wake,
    set_inbox_configured,
)
from koi.agent_chat.worker import (
    cursor_sdk_available,
    ensure_agent_worker,
    stop_agent_worker,
    worker_running,
)
from koi.adapters.agent_backends import backend_status
from koi.adapters.repository import load_project
from koi.adapters.settings_store import (
    AGENT_CHAT_MODES,
    get_agent_chat_mode,
    is_api_agent_mode,
    set_agent_chat_mode,
    set_cursor_api_key,
)

router = APIRouter(tags=["agents"])


def _run_agent_chat_item(item_id: str) -> None:
    process_item(item_id)


def _sync_agent_worker() -> bool:
    if is_api_agent_mode():
        return ensure_agent_worker()
    stop_agent_worker()
    return False


def _auto_answer_pending(project_id: str) -> None:
    if get_agent_chat_mode() == "local":
        return
    for item in list_for_project(project_id, limit=10):
        if item.get("status") == "answered" or item.get("card_id"):
            continue
        auto = try_auto_answer(project_id, item["question"])
        if auto:
            try:
                submit_answer(item["id"], auto)
            except (KeyError, ValueError):
                pass


@router.get("/agent/backends")
def get_agent_backends():
    return backend_status()


@router.post("/agent-chat")
def post_agent_chat(body: AgentChatBody, background_tasks: BackgroundTasks) -> dict:
    if load_project(body.project_id, sync_reports=False) is None:
        raise HTTPException(404, "Project not found")
    if getattr(body, "card_id", None):
        project = load_project(body.project_id, sync_reports=False)
        board = next((b for b in project.boards if b.id == body.board_id), None)
        if board is None or not any(c.id == body.card_id for c in board.cards):
            raise HTTPException(404, "Card not found")
        history = list_for_project(body.project_id, limit=10000, board_id=body.board_id, card_id=body.card_id)
        if any(i.get("status") != "answered" for i in history):
            raise HTTPException(409, "Дождитесь ответа агента на предыдущий вопрос")
    try:
        item = enqueue_question(
            body.project_id,
            body.question,
            method_id=body.method_id,
            node_id=body.node_id,
            purpose=getattr(body, "purpose", "question"),
            board_id=getattr(body, "board_id", None),
            card_id=getattr(body, "card_id", None),
            report_markdown=getattr(body, "report_markdown", ""),
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    auto = try_auto_answer(item["project_id"], item["question"]) if get_agent_chat_mode() != "local" and item.get("purpose") not in ("report_grill", "grill_me", "make_report") else None
    if auto:
        submit_answer(item["id"], auto)
    answered = bool(auto)
    item = find_item(item["id"]) or item

    if not answered:
        if is_cursor_inbox_agent_mode():
            notify_chat_inbox_wake(agent_chat_id=item["id"])
            record_agent_activity(item["id"], "Вопрос отправлен в ResearchOS Chat Inbox.")
        elif get_agent_chat_mode() in ("local", "api"):
            background_tasks.add_task(_run_agent_chat_item, item["id"])

    return {
        "ok": True,
        "item": item,
        "answered": item.get("status") == "answered",
        "inbox_message": (
            inbox_task_message(agent_chat_id=item["id"])
            if get_agent_chat_mode() == "cursor_inbox" and item.get("status") != "answered"
            else None
        ),
    }


@router.get("/agent-chat/pending")
def get_agent_chat_pending() -> dict:
    return {"items": list_pending()}


@router.get("/agent-chat/activity")
def get_agent_chat_activity(project_id: str, board_id: str | None = None, card_id: str | None = None) -> dict:
    if load_project(project_id, sync_reports=False) is None:
        raise HTTPException(404, "Project not found")
    return {"items": [
        {"id": item["id"], "question": item["question"], "events": read_agent_chat_activity(item["id"])}
        for item in list_for_project(project_id, limit=10000 if card_id else 30, board_id=board_id, card_id=card_id)
    ]}


@router.get("/agent-chat")
def get_agent_chat(project_id: str, board_id: str | None = None, card_id: str | None = None) -> dict:
    if load_project(project_id, sync_reports=False) is None:
        raise HTTPException(404, "Project not found")
    _auto_answer_pending(project_id)
    items = list_for_project(project_id, limit=10000, board_id=board_id, card_id=card_id)
    if card_id is None:
        items = [i for i in items if not i.get("card_id")][:30]
    return {"items": items}


@router.patch("/agent-chat/{item_id}")
def patch_agent_chat_answer(item_id: str, body: AgentChatAnswerBody) -> dict:
    try:
        item = submit_answer(item_id, body.answer)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "item": item}


@router.delete("/agent-chat/{item_id}")
def delete_agent_chat_item(item_id: str) -> dict:
    if not dequeue_agent_chat_item(item_id):
        raise HTTPException(404, f"Queue item not found: {item_id}")
    delete_agent_chat_activity(item_id)
    return {"ok": True}


@router.get("/settings")
def get_settings() -> dict:
    snap = settings_snapshot()
    snap["cursor_sdk_installed"] = cursor_sdk_available()
    snap["agent_worker_running"] = worker_running()
    return snap


@router.put("/settings/cursor-api-key")
def put_cursor_api_key(body: CursorApiKeyBody) -> dict:
    key = body.cursor_api_key.strip()
    set_cursor_api_key(key or None)
    running = _sync_agent_worker()
    snap = settings_snapshot()
    snap["agent_worker_running"] = running
    return {"ok": True, **snap}


@router.put("/settings/inbox-configured")
def put_inbox_configured(body: InboxConfiguredBody) -> dict:
    kind = (body.inbox_kind or "chat").strip().lower()
    if kind not in ("chat", "literature", "paper"):
        raise HTTPException(400, "inbox_kind must be 'chat', 'literature', or 'paper'")
    set_inbox_configured(body.configured, inbox_kind=kind)
    snap = settings_snapshot()
    snap["agent_worker_running"] = worker_running()
    return {"ok": True, **snap}


@router.put("/settings/agent-chat")
def put_agent_chat_settings(body: AgentChatSettingsBody) -> dict:
    if body.agent_chat_mode is not None:
        mode = body.agent_chat_mode.strip().lower()
        if mode not in AGENT_CHAT_MODES:
            raise HTTPException(
                400,
                f"agent_chat_mode must be one of: {', '.join(sorted(AGENT_CHAT_MODES))}",
            )
        set_agent_chat_mode(mode)
    if body.cursor_api_key is not None:
        set_cursor_api_key(body.cursor_api_key.strip() or None)
    running = _sync_agent_worker()
    snap = settings_snapshot()
    snap["agent_worker_running"] = running
    return {"ok": True, **snap}
