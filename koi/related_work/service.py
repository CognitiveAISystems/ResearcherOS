"""Related Work generation — sync agent or Cursor inbox queue."""

from __future__ import annotations

import sys
from pathlib import Path

from koi.adapters.agent_backends import any_agent_available, run_agent
from koi.adapters.related_work_queue import (
    RelatedWorkItem,
    enqueue_related_work,
    find_item,
    list_for_project,
    mark_processing,
    submit_markdown,
)
from koi.adapters.settings_store import get_agent_chat_mode
from koi.adapters.workspace import get_workspace
from koi.related_work.inbox import (
    inbox_task_message as literature_inbox_task_message,
    notify_literature_inbox_wake,
)
from koi.review.related_work import (
    _strip_code_fences,
    prepare_related_work_material,
)

_ws = get_workspace()


def _python_bin() -> str:
    venv = _ws.venv_python
    if venv.is_file():
        return str(venv)
    return sys.executable


def _related_work_script() -> str:
    return "-m koi.related_work.cli"


def cursor_chat_message(item_id: str) -> str:
    py = _python_bin()
    script = _related_work_script()
    return f"""ResearcherOS Literature Inbox — Related Work `{item_id}`.

Скилл **koi-related-work** (или выполни шаги ниже):

0. **Сразу** отметь задачу принятой (UI покажет «Агент работает»):
   `{py} {script} claim {item_id}`

1. Контекст и промпт:
   `{py} {script} context {item_id}`

2. Напиши раздел Related Works в markdown (заголовок `## Related Works`, 2–5 абзацев).

3. **Обязательно** отправь черновик в UI (без этого текст в чате НЕ появится на странице):
   `{py} {script} answer {item_id} -f related-work.md`

Шаг 0 и 3 обязательны — UI опрашивает очередь, а не чат Cursor."""


def _sync_generate(material: dict[str, object]) -> dict[str, object] | None:
    if not any_agent_available():
        return None
    text, backend = run_agent(str(material["prompt"]), cwd=_ws.agent_cwd())
    markdown = _strip_code_fences(text or "").strip()
    if not markdown:
        return None
    return {
        "project_id": material["project_id"],
        "question": material["question"],
        "problem": material["problem"],
        "cluster_keys": material["cluster_keys"],
        "cluster_labels": material["cluster_labels"],
        "paper_count": material["paper_count"],
        "backend": backend,
        "markdown": markdown,
        "status": "answered",
    }


def submit_related_work_request(
    project_id: str,
    *,
    problem: str,
    cluster_keys: list[str],
) -> dict[str, object]:
    material = prepare_related_work_material(project_id, problem, cluster_keys)
    sync = _sync_generate(material)
    if sync is not None:
        return sync

    item = enqueue_related_work(
        project_id=project_id,
        problem=str(material["problem"]),
        question=str(material["question"]),
        cluster_keys=list(material["cluster_keys"]),
        cluster_labels=list(material["cluster_labels"]),
        paper_count=int(material["paper_count"]),
        prompt=str(material["prompt"]),
    )
    mode = get_agent_chat_mode()
    if mode == "cursor_inbox":
        notify_literature_inbox_wake(related_work_id=item["id"])
    inbox_message = (
        literature_inbox_task_message(related_work_id=item["id"])
        if mode == "cursor_inbox"
        else None
    )
    return {
        "project_id": project_id,
        "question": material["question"],
        "problem": material["problem"],
        "cluster_keys": material["cluster_keys"],
        "cluster_labels": material["cluster_labels"],
        "paper_count": material["paper_count"],
        "status": "pending",
        "item_id": item["id"],
        "item": _public_item(item),
        "agent_chat_mode": mode,
        "cursor_message": cursor_chat_message(item["id"]),
        "inbox_message": inbox_message,
        "backend": None,
        "markdown": None,
    }


def _public_item(item: RelatedWorkItem) -> dict[str, object]:
    return {
        "id": item["id"],
        "project_id": item["project_id"],
        "problem": item["problem"],
        "question": item.get("question") or "",
        "cluster_keys": item.get("cluster_keys") or [],
        "cluster_labels": item.get("cluster_labels") or [],
        "paper_count": item.get("paper_count") or 0,
        "status": item.get("status") or "pending",
        "markdown": item.get("markdown") or None,
        "enqueued_at": item["enqueued_at"],
        "processing_at": item.get("processing_at") or None,
        "answered_at": item.get("answered_at") or None,
    }


def list_related_work_for_project(project_id: str) -> list[dict[str, object]]:
    return [_public_item(item) for item in list_for_project(project_id)]


def get_related_work_item(item_id: str) -> dict[str, object]:
    item = find_item(item_id)
    if item is None:
        raise KeyError(f"Related Work queue item not found: {item_id}")
    out = _public_item(item)
    if item.get("status") != "answered":
        out["cursor_message"] = cursor_chat_message(item_id)
        if get_agent_chat_mode() == "cursor_inbox":
            out["inbox_message"] = literature_inbox_task_message(related_work_id=item_id)
    return out


def answer_related_work_item(item_id: str, markdown: str) -> dict[str, object]:
    item = submit_markdown(item_id, markdown)
    return _public_item(item)


def claim_related_work_item(item_id: str) -> dict[str, object]:
    item = mark_processing(item_id)
    return _public_item(item)


def build_related_work_context(item_id: str) -> dict[str, object]:
    item = find_item(item_id)
    if item is None:
        raise KeyError(f"Related Work queue item not found: {item_id}")
    return {
        "queue_id": item["id"],
        "project_id": item["project_id"],
        "problem": item["problem"],
        "question": item.get("question") or "",
        "cluster_keys": item.get("cluster_keys") or [],
        "cluster_labels": item.get("cluster_labels") or [],
        "paper_count": item.get("paper_count") or 0,
        "enqueued_at": item["enqueued_at"],
        "status": item.get("status") or "pending",
        "processing_at": item.get("processing_at") or None,
        "prompt": item["prompt"],
        "claim_command": f"{_python_bin()} {_related_work_script()} claim {item_id}",
        "answer_command": f"{_python_bin()} {_related_work_script()} answer {item_id} -f related-work.md",
    }
