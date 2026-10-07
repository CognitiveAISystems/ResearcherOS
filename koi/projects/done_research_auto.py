"""Run done-research with the same headless agent as in-app chat.

The IDE hook still works. This path does not need Cursor to be open:
the API starts it when a card moves to done, and again on server startup
for cards queued in the last few hours.
"""

from __future__ import annotations

import json
import hashlib
import os
import subprocess
import threading
from datetime import datetime, timezone
from uuid import uuid4

from koi.adapters.agent_backends import run_agent
from koi.adapters.done_research_queue import dequeue, list_pending
from koi.adapters.rq_discoveries_feed import append_discoveries
from koi.adapters.settings_store import load_env_file
from koi.adapters.workspace import get_workspace
from koi.literature.cursor_agent_terminal import find_agent_bin
from koi.core.models import ResearchQuestionCertainty
from koi.projects.commands import ResearchQuestionInput, UpdateNodeCommand, update_node
from koi.projects.done_research_cli import build_context

_lock = threading.Lock()
_MAX_AGE_S = 6 * 3600
_MAX_REPORT = 12000


def _log(message: str) -> None:
    line = f"done-research: {message}"
    print(line, flush=True)
    try:
        path = get_workspace().run_dir / "logs" / "done-research.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


def _recent(items: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc)
    fresh = []
    for item in items:
        try:
            stamp = datetime.fromisoformat(item["enqueued_at"])
        except (KeyError, ValueError):
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        if (now - stamp).total_seconds() <= _MAX_AGE_S:
            fresh.append(item)
    fresh.sort(key=lambda item: item["enqueued_at"], reverse=True)
    return fresh


def _parse_payload(text: str) -> dict | None:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _prompt(ctx: dict) -> str:
    report = ctx.get("report_markdown") or ""
    if len(report) > _MAX_REPORT:
        ctx = {**ctx, "report_markdown": report[:_MAX_REPORT] + "\n…[truncated]"}
    return (
        "Сформулируй один исследовательский вывод по карточке, перенесённой в done.\n"
        "question и narrative — обычным языком, без аббревиатур и названий метрик. "
        "Сырые числа только в answer.\n"
        "certainty: definite, если в отчёте есть ясный результат; иначе tentative.\n"
        "importance: целое 1–5.\n"
        "Если вывода нет (пустой отчёт и пустое описание), верни {\"skip\": true}.\n"
        "Иначе верни только JSON без пояснений:\n"
        '{"question":"...","narrative":"...","answer":"...","certainty":"definite","importance":3}\n\n'
        f"Контекст:\n{json.dumps(ctx, ensure_ascii=False)}"
    )


def _save(ctx: dict, payload: dict) -> ResearchQuestionInput:
    method = ctx["method"]
    card_id = ctx["card_id"]
    certainty = payload.get("certainty")
    if certainty not in ("definite", "tentative"):
        certainty = "tentative"
    importance = payload.get("importance", 3)
    try:
        importance = int(importance)
    except (TypeError, ValueError):
        importance = 3
    importance = min(5, max(1, importance))
    fresh = ResearchQuestionInput(
        id=f"rq-{uuid4().hex[:8]}",
        question=str(payload.get("question") or "").strip(),
        narrative=str(payload.get("narrative") or "").strip(),
        answer=str(payload.get("answer") or "").strip(),
        certainty=ResearchQuestionCertainty(certainty),
        importance=importance,
        card_id=card_id,
    )
    if not fresh.question or not fresh.narrative:
        raise ValueError("question and narrative are required")
    existing = []
    replaced = False
    for item in method["research_questions"]:
        if item.get("card_id") == card_id:
            existing.append(
                ResearchQuestionInput(
                    id=item["id"],
                    question=fresh.question,
                    narrative=fresh.narrative,
                    answer=fresh.answer,
                    certainty=fresh.certainty,
                    importance=fresh.importance,
                    card_id=card_id,
                )
            )
            replaced = True
        else:
            existing.append(
                ResearchQuestionInput(
                    id=item.get("id"),
                    question=item.get("question") or "",
                    narrative=item.get("narrative") or "",
                    answer=item.get("answer") or "",
                    certainty=ResearchQuestionCertainty(item.get("certainty") or "definite"),
                    importance=item.get("importance") or 3,
                    card_id=item.get("card_id"),
                )
            )
    if not replaced:
        if len(existing) >= 3:
            worst = min(range(len(existing)), key=lambda i: existing[i].importance)
            existing[worst] = fresh
        else:
            existing.append(fresh)
    update_node(
        ctx["project_id"],
        method["id"],
        UpdateNodeCommand(research_questions=existing),
    )
    return next(item for item in existing if item.card_id == card_id)


def _cursor_cli(prompt: str) -> str | None:
    agent_bin = find_agent_bin()
    if agent_bin is None:
        return None
    models = [None, os.environ.get("KOI_DONE_RESEARCH_FALLBACK_MODEL", "gemini-3.8-flash-low")]
    for model in models:
        command = [
            str(agent_bin), "--print", "--trust", "--mode", "ask",
            "--output-format", "text",
        ]
        if model:
            command += ["--model", model]
        process = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(get_workspace().agent_cwd()),
        )
        if process.returncode == 0 and (process.stdout or "").strip():
            return process.stdout.strip()
        _log((process.stderr or process.stdout or "agent failed").strip()[:500])
    return None


def process_card(project_id: str, board_id: str, card_id: str) -> bool:
    """Write one research question and drop the card from the queue."""
    load_env_file()
    ctx = build_context(project_id, board_id, card_id)
    prompt = _prompt(ctx)
    text = _cursor_cli(prompt)
    backend = "Cursor CLI"
    if not text:
        text, backend = run_agent(prompt, timeout=600)
    if not text:
        _log(f"агент не ответил для {card_id}")
        return False
    payload = _parse_payload(text)
    if payload is None:
        _log(f"не JSON ({backend}) для {card_id}")
        return False
    if payload.get("skip"):
        dequeue(project_id, board_id, card_id)
        _log(f"пропуск {card_id}")
        return True
    try:
        question = _save(ctx, payload)
    except Exception as exc:  # noqa: BLE001
        _log(f"не сохранилось {card_id}: {exc}")
        return False
    dequeue(project_id, board_id, card_id)
    signature = hashlib.sha256(
        (question.narrative or question.answer).encode("utf-8")
    ).hexdigest()[:16]
    append_discoveries(
        [
            {
                "project_id": project_id,
                "question_id": question.id,
                "card_id": card_id,
                "question": question.question,
                "answer": question.narrative or question.answer,
                "author": os.environ.get("USER", "ResearcherOS"),
                "signature": signature,
                "key": f"{project_id}:{question.id}:{signature}",
            }
        ]
    )
    _log(f"вывод записан для {card_id} через {backend}")
    return True


def process_recent() -> int:
    """Headless pass over cards queued in the last six hours. Newest first."""
    if not _lock.acquire(blocking=False):
        return 0
    done = 0
    try:
        for item in _recent(list_pending())[:3]:
            try:
                ok = process_card(item["project_id"], item["board_id"], item["card_id"])
            except Exception as exc:  # noqa: BLE001
                _log(f"сбой {item.get('card_id')}: {exc}")
                ok = False
            if ok:
                done += 1
    finally:
        _lock.release()
    return done


def kick_recent() -> None:
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("KOI_DONE_RESEARCH_AUTO") == "0":
        return
    threading.Thread(target=process_recent, name="done-research", daemon=True).start()
