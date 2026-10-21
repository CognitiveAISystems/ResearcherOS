"""NeurIPS paper generation — Cursor Paper Inbox queue or background agent."""

from __future__ import annotations

import sys

from koi.adapters.paper_queue import (
    PaperItem,
    enqueue_paper,
    find_item,
    list_for_project,
    mark_finished,
    mark_processing,
)
from koi.adapters.repository import load_project
from koi.adapters.settings_store import get_agent_chat_mode
from koi.adapters.workspace import get_workspace
from koi.paper.catalog import DEFAULT_PAPER_SLUG
from koi.paper.generator import (
    build_paper_from_agent_text,
    collect_paper_context,
    paper_status,
    start_paper_generation,
    _build_agent_prompt,
)
from koi.paper.inbox import (
    inbox_task_message as paper_inbox_task_message,
    notify_paper_inbox_wake,
)

_ws = get_workspace()


def _python_bin() -> str:
    venv = _ws.venv_python
    if venv.is_file():
        return str(venv)
    return sys.executable


def _paper_script() -> str:
    return "-m koi.paper.cli"


def cursor_chat_message(item_id: str) -> str:
    py = _python_bin()
    script = _paper_script()
    return f"""ResearcherOS Paper Inbox — статья `{item_id}`.

Скилл **koi-paper** (или выполни шаги ниже):

0. **Сразу** отметь задачу принятой (UI покажет «Агент работает»):
   `{py} {script} claim {item_id}`

1. Контекст и промпт:
   `{py} {script} context {item_id}`

2. Напиши статью на английском в LaTeX (формат TITLE: / ===LATEX=== из промпта).

3. **Обязательно** отправь результат в систему (без этого PDF не появится):
   `{py} {script} answer {item_id} -f paper-body.txt`

Шаг 0 и 3 обязательны — UI опрашивает очередь, а не чат Cursor."""


def _public_item(item: PaperItem) -> dict[str, object]:
    return {
        "id": item["id"],
        "project_id": item["project_id"],
        "project_title": item.get("project_title") or "",
        "status": item.get("status") or "pending",
        "enqueued_at": item["enqueued_at"],
        "processing_at": item.get("processing_at") or None,
        "finished_at": item.get("finished_at") or None,
        "error": item.get("error") or None,
    }


def submit_paper_request(
    project_id: str,
    *,
    paper_slug: str = DEFAULT_PAPER_SLUG,
) -> dict[str, object]:
    """Enqueue for Paper Inbox (cursor_inbox) or signal background generation."""
    project = load_project(project_id, sync_reports=False)
    if project is None:
        raise KeyError(f"Project not found: {project_id}")

    if not start_paper_generation(project_id, paper_slug):
        raise RuntimeError("Генерация статьи уже идёт — дождитесь завершения")

    mode = get_agent_chat_mode()
    if mode != "cursor_inbox":
        return {
            "project_id": project_id,
            "paper_slug": paper_slug,
            "mode": "background",
            "status": paper_status(project_id, paper_slug),
            "agent_chat_mode": mode,
        }

    item = enqueue_paper(project_id=project_id, project_title=project.title)
    notify_paper_inbox_wake(paper_id=item["id"])
    inbox_message = paper_inbox_task_message(paper_id=item["id"])
    return {
        "project_id": project_id,
        "paper_slug": paper_slug,
        "mode": "inbox",
        "status": "pending",
        "item_id": item["id"],
        "item": _public_item(item),
        "agent_chat_mode": mode,
        "cursor_message": cursor_chat_message(item["id"]),
        "inbox_message": inbox_message,
        "paper_status": paper_status(project_id, paper_slug),
    }


def list_paper_for_project(project_id: str) -> list[dict[str, object]]:
    return [_public_item(item) for item in list_for_project(project_id)]


def get_paper_item(item_id: str) -> dict[str, object]:
    item = find_item(item_id)
    if item is None:
        raise KeyError(f"Paper queue item not found: {item_id}")
    out = _public_item(item)
    if item.get("status") not in ("done", "error"):
        out["cursor_message"] = cursor_chat_message(item_id)
        if get_agent_chat_mode() == "cursor_inbox":
            out["inbox_message"] = paper_inbox_task_message(paper_id=item_id)
    return out


def claim_paper_item(item_id: str) -> dict[str, object]:
    item = mark_processing(item_id)
    return _public_item(item)


def build_paper_context(item_id: str) -> dict[str, object]:
    item = find_item(item_id)
    if item is None:
        raise KeyError(f"Paper queue item not found: {item_id}")
    project = load_project(item["project_id"], sync_reports=False)
    if project is None:
        raise KeyError(f"Project not found: {item['project_id']}")
    context = collect_paper_context(project)
    prompt = _build_agent_prompt(context)
    py = _python_bin()
    script = _paper_script()
    return {
        "queue_id": item["id"],
        "project_id": item["project_id"],
        "project_title": project.title,
        "enqueued_at": item["enqueued_at"],
        "status": item.get("status") or "pending",
        "processing_at": item.get("processing_at") or None,
        "prompt": prompt,
        "context": context,
        "claim_command": f"{py} {script} claim {item_id}",
        "answer_command": f"{py} {script} answer {item_id} -f paper-body.txt",
    }


def answer_paper_item(item_id: str, agent_text: str) -> dict[str, object]:
    item = find_item(item_id)
    if item is None:
        raise KeyError(f"Paper queue item not found: {item_id}")
    project_id = item["project_id"]
    try:
        status = build_paper_from_agent_text(
            project_id, agent_text, backend="cursor_inbox"
        )
        finished = mark_finished(item_id, error=None)
        return {
            "item": _public_item(finished),
            "paper_status": status,
        }
    except Exception as e:  # noqa: BLE001
        mark_finished(item_id, error=str(e))
        raise
