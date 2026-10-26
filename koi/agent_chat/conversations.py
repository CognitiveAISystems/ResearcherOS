"""Durable UI conversations, independent of an agent's protocol session."""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from uuid import uuid4
from koi.adapters.workspace import get_workspace
from koi.adapters import agent_chat_queue as queue

PATH = get_workspace().run_dir / "agent-conversations.json"
LOCK = threading.RLock()


def legacy_id(item):
    scope = [item["project_id"], item.get("board_id"), item.get("card_id")]
    return "legacy-" + hashlib.sha256(json.dumps(scope).encode()).hexdigest()[:20]


def item_conversation(item):
    return item.get("conversation_id") or legacy_id(item)


def _load():
    if not PATH.exists():
        return []
    return json.loads(PATH.read_text(encoding="utf-8"))


def _save(rows):
    PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, PATH)


def list_conversations(project_id=None, board_id=None, card_id=None):
    with LOCK:
        rows = {r["id"]: {**r, "pending": False} for r in _load()}
        for item in sorted(queue._load(), key=lambda i: i["enqueued_at"]):
            cid = item_conversation(item)
            if cid not in rows:
                rows[cid] = {"id": cid, "project_id": item["project_id"],
                    "board_id": item.get("board_id"), "card_id": item.get("card_id"),
                    "title": item["question"][:80], "created_at": item["enqueued_at"],
                    "backend": item.get("cli_agent")}
            rows[cid]["updated_at"] = item.get("answered_at") or item["enqueued_at"]
            rows[cid]["pending"] = rows[cid].get("pending", False) or item["status"] != "answered"
        return sorted((r for r in rows.values()
            if (project_id is None or r["project_id"] == project_id)
            and (board_id is None or r.get("board_id") == board_id)
            and (card_id is None or r.get("card_id") == card_id)),
            key=lambda r: r.get("updated_at", r["created_at"]), reverse=True)


def find(cid):
    return next((r for r in list_conversations() if r["id"] == cid), None)


def create(project_id=None, board_id=None, card_id=None, title="Новый чат", backend=None):
    with LOCK:
        rows = _load()
        row = {"id": "chat-" + uuid4().hex, "project_id": project_id,
               "board_id": board_id, "card_id": card_id, "title": title[:80],
               "backend": backend, "created_at": datetime.now(timezone.utc).isoformat()}
        rows.append(row)
        _save(rows)
        return row


def update(cid, **fields):
    with LOCK:
        rows = _load()
        row = next((r for r in rows if r["id"] == cid), None)
        if row is None:
            row = find(cid)
            if row is None:
                raise KeyError(cid)
            rows.append(row)
        row.update(fields)
        _save(rows)


def messages(cid):
    return sorted((i for i in queue._load() if item_conversation(i) == cid),
                  key=lambda i: i["enqueued_at"], reverse=True)


@queue._locked
def delete(cid):
    """Delete one idle conversation and its queue history, including legacy chats."""
    with LOCK:
        if find(cid) is None:
            raise KeyError(cid)
        items = queue._load()
        history = [item for item in items if item_conversation(item) == cid]
        if any(item.get("status") != "answered" for item in history):
            raise ValueError("Дождитесь завершения ответа перед удалением чата")
        queue._save([item for item in items if item_conversation(item) != cid])
        _save([row for row in _load() if row["id"] != cid])
        return [item["id"] for item in history]
