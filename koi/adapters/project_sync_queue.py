"""Queue of significant project changes that should be committed and pushed."""

from __future__ import annotations

import json
import logging
import os
import threading
from functools import wraps
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from koi.adapters.workspace import get_workspace

_ws = get_workspace()
QUEUE_PATH = _ws.run_dir / "sync-push-queue.json"
STATE_PATH = _ws.run_dir / "sync-state.json"
PULL_INTERVAL_SEC = 30 * 60
_LOCK = threading.RLock()


def _locked(fn):
    @wraps(fn)
    def call(*args, **kwargs):
        with _LOCK:
            return fn(*args, **kwargs)
    return call


class SyncPushItem(TypedDict):
    project_id: str
    reason: str
    detail: str
    enqueued_at: str


class SyncState(TypedDict, total=False):
    last_pull_at: str
    last_pull_check_at: str
    last_pull_result: str
    last_rq_head: str
    last_rq_heads: dict[str, str]
    last_rq_sigs: dict[str, str]
    rq_sigs_initialized: bool


def _load_queue() -> list[SyncPushItem]:
    if not QUEUE_PATH.exists():
        return []
    try:
        data = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [item for item in data if _valid_item(item)]
    except (ValueError, UnicodeError, OSError):
        logging.getLogger(__name__).warning("Cannot read Git push queue; original file preserved")
        pass
    return []


def _save_queue(items: list[SyncPushItem]) -> None:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if QUEUE_PATH.exists():
        raw = QUEUE_PATH.read_bytes()
        try:
            json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError):
            backup = QUEUE_PATH.with_name(QUEUE_PATH.name + ".invalid-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f"))
            backup.write_bytes(raw)
    temp = QUEUE_PATH.with_suffix(".tmp")
    temp.write_text(
        json.dumps(items, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, QUEUE_PATH)


def _valid_item(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    return all(
        isinstance(item.get(k), str) and item[k]
        for k in ("project_id", "reason", "detail", "enqueued_at")
    )


def _item_key(item: SyncPushItem) -> tuple[str, str, str]:
    return (item["project_id"], item["reason"], item["detail"])


def load_state() -> SyncState:
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def save_state(state: SyncState) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def touch_pull_check(*, result: str | None = None) -> SyncState:
    now = datetime.now(timezone.utc).isoformat()
    state = load_state()
    state["last_pull_check_at"] = now
    if result is not None:
        state["last_pull_at"] = now
        state["last_pull_result"] = result
    save_state(state)
    return state


def get_last_rq_head() -> str | None:
    """Legacy single-repo head (engine git)."""
    state = load_state()
    heads = state.get("last_rq_heads")
    if isinstance(heads, dict) and heads:
        from koi.adapters.workspace import get_workspace

        engine = str(get_workspace().git_root().resolve())
        if engine in heads:
            return heads[engine]
    return state.get("last_rq_head") or None


def get_last_rq_heads() -> dict[str, str]:
    state = load_state()
    heads = state.get("last_rq_heads")
    if isinstance(heads, dict):
        return {str(k): str(v) for k, v in heads.items() if k and v}
    legacy = state.get("last_rq_head")
    if legacy:
        from koi.adapters.workspace import get_workspace

        return {str(get_workspace().git_root().resolve()): str(legacy)}
    return {}


def get_last_rq_sigs() -> dict[str, str]:
    state = load_state()
    sigs = state.get("last_rq_sigs")
    if isinstance(sigs, dict):
        return {str(k): str(v) for k, v in sigs.items() if k and v}
    return {}


def rq_sigs_initialized() -> bool:
    return bool(load_state().get("rq_sigs_initialized"))


def set_last_rq_head(ref: str) -> SyncState:
    """Legacy ack — prefer set_rq_discovery_state."""
    from koi.adapters.workspace import get_workspace

    state = load_state()
    state["last_rq_head"] = ref
    heads = dict(get_last_rq_heads())
    heads[str(get_workspace().git_root().resolve())] = ref
    state["last_rq_heads"] = heads
    save_state(state)
    return state


def set_rq_discovery_state(
    *,
    heads: dict[str, str] | None = None,
    sigs: dict[str, str] | None = None,
) -> SyncState:
    state = load_state()
    if heads is not None:
        state["last_rq_heads"] = heads
        from koi.adapters.workspace import get_workspace

        engine = str(get_workspace().git_root().resolve())
        if engine in heads:
            state["last_rq_head"] = heads[engine]
    if sigs is not None:
        state["last_rq_sigs"] = sigs
        state["rq_sigs_initialized"] = True
    save_state(state)
    return state


def should_periodic_pull() -> bool:
    state = load_state()
    last = state.get("last_pull_check_at")
    if not last:
        return True
    try:
        dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        return age >= PULL_INTERVAL_SEC
    except ValueError:
        return True


@_locked
def enqueue_push(project_id: str, reason: str, detail: str) -> None:
    items = _load_queue()
    key = (project_id, reason, detail)
    if any(_item_key(i) == key for i in items):
        return
    items.append(
        {
            "project_id": project_id,
            "reason": reason,
            "detail": detail,
            "enqueued_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _save_queue(items)


def list_pending_push() -> list[SyncPushItem]:
    return _load_queue()


@_locked
def clear_push_queue() -> None:
    _save_queue([])


@_locked
def dequeue_push(project_id: str | None = None) -> int:
    items = _load_queue()
    if project_id is None:
        removed = len(items)
        _save_queue([])
        return removed
    next_items = [i for i in items if i["project_id"] != project_id]
    removed = len(items) - len(next_items)
    _save_queue(next_items)
    return removed
