from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException

from api.schemas import (
    AgentChatAnswerBody,
    ConversationCreateBody,
    ConversationScopeBody,
    PermissionBody,
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
from koi.adapters.agent_backends import backend_status, cli_agents
from koi.adapters.repository import load_project
from koi.adapters.settings_store import (
    AGENT_CHAT_MODES,
    get_agent_chat_mode,
    is_api_agent_mode,
    set_agent_chat_mode,
    set_cursor_api_key,
)

from koi.agent_chat import conversations
from koi.adapters.agent_chat_queue import _locked

router = APIRouter(tags=["agents"])


def _check_scope(project_id, board_id=None, card_id=None):
    if not project_id:
        if board_id or card_id:
            raise HTTPException(400, "Project required")
        return None
    project = load_project(project_id, sync_reports=False)
    if project is None:
        raise HTTPException(404, "Project not found")
    if card_id and not board_id:
        raise HTTPException(400, "Укажите доску и карточку вместе")
    if board_id:
        board = next((b for b in project.boards if b.id == board_id), None)
        if board is None or (card_id and not any(c.id == card_id for c in board.cards)):
            raise HTTPException(404, "Card not found")
    return project


@router.get("/agent-conversations")
def get_conversations(project_id: str | None = None, board_id: str | None = None, card_id: str | None = None):
    if (board_id or card_id) and not project_id:
        raise HTTPException(400, "Project required")
    if project_id:
        _check_scope(project_id, board_id, card_id)
    return {"items": conversations.list_conversations(project_id, board_id, card_id)}


@router.post("/agent-conversations")
def create_conversation(body: ConversationCreateBody):
    _check_scope(body.project_id, body.board_id, body.card_id)
    if body.backend and not any(r["id"] == body.backend and r["available"] for r in cli_agents()):
        raise HTTPException(400, "Агент недоступен")
    return {"item": conversations.create(body.project_id, body.board_id, body.card_id, body.title, body.backend)}


def _conversation(cid):
    row = conversations.find(cid)
    if not row:
        raise HTTPException(404, "Chat not found")
    _check_scope(row["project_id"], row.get("board_id"), row.get("card_id"))
    return row


@router.get("/agent-conversations/{cid}")
def get_conversation(cid: str):
    row = _conversation(cid)
    return {"conversation": row, "items": conversations.messages(cid), "live": None}


@router.delete("/agent-conversations/{cid}")
def delete_conversation(cid: str):
    try:
        item_ids = conversations.delete(cid)
    except KeyError:
        raise HTTPException(404, "Chat not found")
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    for item_id in item_ids:
        delete_agent_chat_activity(item_id)
    return {"ok": True}


@router.patch("/agent-conversations/{cid}")
@_locked
def move_conversation(cid: str, body: ConversationScopeBody):
    row = _conversation(cid)
    _check_scope(body.project_id, body.board_id, body.card_id)
    if any(i["status"] != "answered" for i in conversations.messages(cid)):
        raise HTTPException(409, "Дождитесь завершения ответа перед переносом чата")
    conversations.update(cid, project_id=body.project_id, board_id=body.board_id, card_id=body.card_id,
                         acp_session_id=None, acp_backend=None)
    return {"item": conversations.find(cid)}


@router.get("/agent-conversations/{cid}/activity")
def get_conversation_activity(cid: str):
    _conversation(cid)
    return {"items": [{"id": i["id"], "question": i["question"], "events": read_agent_chat_activity(i["id"])} for i in conversations.messages(cid)]}


@router.post("/agent-conversations/{cid}/cancel")
def cancel_conversation(cid: str):
    _conversation(cid)
    return {"ok": False}


@router.post("/agent-conversations/{cid}/permission")
def decide_permission(cid: str, body: PermissionBody):
    _conversation(cid)
    raise HTTPException(409, "Нет активного запроса разрешения")


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
        if item.get("status") == "answered" or item.get("card_id") or item.get("purpose") != "question":
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
@_locked
def post_agent_chat(body: AgentChatBody, background_tasks: BackgroundTasks) -> dict:
    _check_scope(body.project_id, getattr(body, "board_id", None), getattr(body, "card_id", None))
    if not body.project_id and not getattr(body, "conversation_id", None):
        raise HTTPException(400, "Chat required")
    if getattr(body, "purpose", "agent") in ("prose", "run") and not (getattr(body, "card_id", None) and getattr(body, "board_id", None)):
        raise HTTPException(400, "Откройте карточку, чтобы выполнить эту команду.")
    cid = getattr(body, "conversation_id", None)
    conversation = _conversation(cid) if cid else None
    if conversation and (conversation["project_id"], conversation.get("board_id"), conversation.get("card_id")) != (body.project_id, getattr(body, "board_id", None), getattr(body, "card_id", None)):
        raise HTTPException(400, "Чат относится к другому проекту или карточке")
    if cid and any(i["status"] != "answered" for i in conversations.messages(cid)):
        raise HTTPException(409, "Дождитесь ответа в этом чате")
    cli_agent = getattr(body, "cli_agent", None) or (conversation or {}).get("backend") or None
    if cli_agent:
        row = next((agent for agent in cli_agents() if agent["id"] == cli_agent), None)
        if row is None or not row["available"]:
            label = row["label"] if row else cli_agent
            raise HTTPException(400, f"{label} сейчас недоступен. Проверьте, что CLI установлен.")
    if getattr(body, "card_id", None):
        project = load_project(body.project_id, sync_reports=False)
        board = next((b for b in project.boards if b.id == body.board_id), None)
        if board is None or not any(c.id == body.card_id for c in board.cards):
            raise HTTPException(404, "Card not found")
        history = list_for_project(body.project_id, limit=10000, board_id=body.board_id, card_id=body.card_id)
        if not cid and any(i.get("status") != "answered" for i in history):
            raise HTTPException(409, "Дождитесь ответа агента на предыдущий вопрос")
    try:
        item = enqueue_question(
            body.project_id,
            body.question,
            method_id=body.method_id,
            node_id=body.node_id,
            purpose=getattr(body, "purpose", "agent"),
            board_id=getattr(body, "board_id", None),
            card_id=getattr(body, "card_id", None),
            report_markdown=getattr(body, "report_markdown", ""),
            cli_agent=cli_agent,
            **({"conversation_id": cid} if cid else {}),
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    if cid:
        conversations.update(cid, backend=cli_agent, **({"title": body.question[:80]} if conversation["title"] == "Новый чат" else {}))
    answered = False
    item = find_item(item["id"]) or item

    if not answered:
        if is_cursor_inbox_agent_mode():
            notify_chat_inbox_wake(agent_chat_id=item["id"])
            record_agent_activity(item["id"], "Вопрос отправлен в ResearcherOS Chat Inbox.")
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
    existing = find_item(item_id)
    if existing and existing.get("status") != "answered":
        raise HTTPException(409, "Сначала дождитесь завершения или остановите агента")
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
    from koi.adapters.settings_store import _write_env_var
    for scope in ("main", "card"):
        width = getattr(body, f"chat_list_{scope}_width", None)
        if width is not None:
            _write_env_var(f"KOI_CHAT_LIST_{scope.upper()}_WIDTH", str(width))
    if body.chat_panel_width is not None:
        _write_env_var("KOI_CHAT_PANEL_WIDTH", str(body.chat_panel_width))
    running = _sync_agent_worker() if body.agent_chat_mode is not None or body.cursor_api_key is not None else worker_running()
    snap = settings_snapshot()
    snap["agent_worker_running"] = running
    return {"ok": True, **snap}
