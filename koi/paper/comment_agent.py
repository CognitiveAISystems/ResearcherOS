"""Run a focused paper-comment fix through a background Cursor CLI job."""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
from pathlib import Path

from koi.agent_chat.runner import _run_local_agent
from koi.paper.collaboration.session import get_or_create_session
from koi.paper.comments import add_reply

_lock = threading.Lock()
_jobs: dict[str, dict] = {}


def _key(project_id: str, slug: str, comment_id: str) -> str:
    return f"{project_id}/{slug}/{comment_id}"


def status(project_id: str, slug: str, comment_id: str) -> dict:
    with _lock:
        job = _jobs.get(_key(project_id, slug, comment_id))
    if not job:
        return {"status": "idle", "error": None}
    return {"status": job["status"], "error": job.get("error"), "answer": job.get("answer")}


def launch(project_id: str, slug: str, comment_id: str, prompt: str, slot_dir: Path | None = None) -> dict:
    text = prompt.strip()
    if not text:
        raise ValueError("Prompt is empty")
    key = _key(project_id, slug, comment_id)
    with _lock:
        job = _jobs.get(key)
        if job and job.get("status") == "running":
            raise RuntimeError("Agent is already fixing this comment")
        _jobs[key] = {"status": "running", "error": None}
    threading.Thread(
        target=_work,
        args=(key, project_id, slug, comment_id, text, slot_dir),
        daemon=True,
        name=f"paper-comment-{comment_id}",
    ).start()
    return {"status": "running"}


def _work(key: str, project_id: str, slug: str, comment_id: str, prompt: str, slot_dir: Path | None) -> None:
    try:
        if slot_dir is None:
            raise ValueError("Paper directory is missing")
        tex_path = slot_dir / "main.tex"
        before = tex_path.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory(prefix="koi-paper-comment-") as temp:
            draft_dir = Path(temp)
            shutil.copy2(tex_path, draft_dir / "main.tex")
            text, _backend = _run_local_agent(
                prompt, key, mode=None, force=True, cwd=draft_dir, timeout=180,
                model=os.environ.get("KOI_PAPER_COMMENT_MODEL", "gpt-5.3-codex-low-fast"),
                fallback=False,
            )
            candidate = (draft_dir / "main.tex").read_text(encoding="utf-8")
        if not text:
            raise RuntimeError("Агент не вернул ответ.")
        if candidate == before:
            raise RuntimeError("Агент не предложил изменений в main.tex.")
        session = get_or_create_session(project_id, slug, tex_path)
        session.import_external(candidate, source="paper-comment-agent")
        if session.proposal is None:
            raise RuntimeError("Предложение не создано: статья изменилась во время работы агента.")
        answer = text.strip()[:2000]
        add_reply(slot_dir, comment_id, body=answer, author="Агент")
    except Exception as exc:
        with _lock:
            _jobs[key] = {"status": "error", "error": str(exc) or type(exc).__name__}
        return
    with _lock:
        _jobs[key] = {"status": "done", "error": None, "answer": answer}
