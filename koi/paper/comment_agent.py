"""Paper comments use the same durable edit-task workflow as general edits."""
from __future__ import annotations

from pathlib import Path
from koi.paper import edit_tasks


def status(project_id: str, slug: str, comment_id: str) -> dict:
    task = next((t for t in edit_tasks.list_tasks(project_id, slug) if t.get("comment_id") == comment_id), None)
    if task is None:
        return {"status": "idle", "error": None}
    state = task["status"]
    return {**task, "status": "done" if state in {"review", "resolved", "unchanged"} else state}


def launch(project_id: str, slug: str, comment_id: str, prompt: str, slot_dir: Path | None = None) -> dict:
    if slot_dir is None:
        raise ValueError("Paper directory is missing")
    return edit_tasks.launch(project_id, slug, slot_dir, prompt, comment_id=comment_id)
