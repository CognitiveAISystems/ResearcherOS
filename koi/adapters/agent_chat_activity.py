"""Small per-question activity journal for the in-app agent tab."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from koi.adapters.workspace import get_workspace

ACTIVITY_DIR = get_workspace().run_dir / "agent-chat-activity"


def _path(item_id: str) -> Path:
    if not item_id.startswith("aq-") or not item_id[3:].isalnum():
        raise ValueError("Invalid question id")
    return ACTIVITY_DIR / f"{item_id}.jsonl"


def record(item_id: str, message: str) -> None:
    path = _path(item_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {"at": datetime.now(timezone.utc).isoformat(), "message": message}
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")


def read(item_id: str) -> list[dict]:
    path = _path(item_id)
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines()[-100:]:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def delete(item_id: str) -> None:
    _path(item_id).unlink(missing_ok=True)
