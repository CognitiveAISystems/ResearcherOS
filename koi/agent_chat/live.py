"""Per-turn progress and stop signals, shared with separate worker processes."""
from __future__ import annotations

import json
from koi.adapters import agent_chat_activity as activity


def _path(item_id, suffix):
    return activity._path(item_id).with_suffix(suffix)


def publish(item_id, text):
    path = _path(item_id, ".live.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({"text": text}, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def text(item_id):
    try:
        return json.loads(_path(item_id, ".live.json").read_text(encoding="utf-8"))["text"]
    except (OSError, ValueError, KeyError):
        return ""


def cancelled(item_id):
    return _path(item_id, ".cancel").exists()


def request_cancel(item_id):
    path = _path(item_id, ".cancel")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def snapshot(item):
    if item["status"] == "answered":
        return None
    return {"item_id": item["id"], "text": text(item["id"]),
            "cancelled": cancelled(item["id"]), "permission": None}


def delete(item_id):
    for suffix in (".live.json", ".cancel"):
        _path(item_id, suffix).unlink(missing_ok=True)
