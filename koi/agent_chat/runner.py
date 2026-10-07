"""Process one agent-chat queue item: research.json auto-answer, then LLM agent.

Порядок: сначала бесплатный авто-ответ из research.json; если база не
покрывает вопрос — локальный агент через koi.adapters.agent_backends (Claude Code
CLI и/или Cursor SDK, см. KOI_AGENT_BACKEND). Если ни один бэкенд не
доступен — в чат уходит предупреждение с инструкцией по настройке ключа.
"""

from __future__ import annotations

import json
import subprocess
import threading
from koi.adapters.agent_backends import backend_status, run_agent
from koi.agent_chat.cli import build_context
from koi.agent_chat.auto import try_auto_answer
from koi.agent_chat.formatting import ANSWER_FORMAT_INSTRUCTIONS, no_cursor_key_warning
from koi.adapters.agent_chat_queue import find_item, list_pending, mark_processing, submit_answer
from koi.agent_chat.activity import record
from koi.adapters.settings_store import is_api_agent_mode, is_cursor_manual_agent_mode, load_env_file
from koi.adapters.workspace import get_workspace
from koi.literature.cursor_agent_terminal import find_agent_bin

_ws = get_workspace()


def _sdk_prompt(item_id: str) -> str:
    ctx = build_context(item_id)
    if ctx.get("purpose") in ("report_grill", "grill_me"):
        from koi.agent_chat.report_grill import build_prompt
        return build_prompt(ctx)
    if ctx.get("purpose") == "make_report" and ctx.get("skill"):
        from pathlib import Path
        skill = Path(ctx["skill"]).read_text(encoding="utf-8")
        return (
            f"{skill}\n\nСобери отчёт по текущей задаче и сохрани его в документе карточки.\n\n"
            f"Контекст:\n{json.dumps(ctx, ensure_ascii=False, indent=2)}"
        )
    return (
        "Ты отвечаешь на вопрос исследователя в ResearchOS (скилл koi-agent-chat).\n"
        "Правила содержания:\n"
        "1. Сначала research_database в JSON (narrative, answer).\n"
        "2. Отчёт (report_path) — только если в базе не хватает деталей.\n"
        "3. Если в базе нет ответа — честно скажи, что эксперименты пока не покрывают вопрос.\n\n"
        f"{ANSWER_FORMAT_INSTRUCTIONS}\n\n"
        "Верни ТОЛЬКО готовый текст ответа для панели UI.\n\n"
        f"Контекст:\n{json.dumps(ctx, ensure_ascii=False, indent=2)}"
    )


def _any_backend_available() -> bool:
    status = backend_status()
    return any(
        status.get(name, {}).get("available") for name in status.get("order", [])
    )


def _cursor_print_command(agent_bin, *, mode: str | None, force: bool, model: str | None = None) -> list[str]:
    command = [str(agent_bin), "--print", "--trust"]
    if mode:
        command.extend(["--mode", mode])
    if force:
        command.append("--force")
    if model:
        command.extend(["--model", model])
    command.extend(["--output-format", "stream-json"])
    return command


def _note_chat(item_id: str, message: str) -> None:
    if not item_id.startswith("aq-"):
        return
    record(item_id, message)


def _run_local_agent(
    prompt: str,
    item_id: str,
    *,
    mode: str | None = "ask",
    force: bool = False,
    cwd=None,
    timeout: int = 1800,
    model: str | None = None,
    fallback: bool = True,
) -> tuple[str | None, str | None]:
    """Prefer the same Cursor CLI used by literature, without opening Terminal.app."""
    workdir = cwd or _ws.agent_cwd()
    agent_bin = find_agent_bin()
    if agent_bin:
        process = subprocess.Popen(
            _cursor_print_command(agent_bin, mode=mode, force=force, model=model),
            cwd=str(workdir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        timer = threading.Timer(timeout, process.kill)
        timer.start()
        answer = ""
        result_text = ""
        try:
            assert process.stdin is not None
            process.stdin.write(prompt)
            process.stdin.close()
            for line in process.stdout or ():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = event.get("type")
                if kind == "assistant":
                    parts = event.get("message", {}).get("content", [])
                    message = "".join(part.get("text", "") for part in parts if part.get("type") == "text").strip()
                    if message:
                        answer = message
                        _note_chat(item_id, f"Агент: {message[:500]}")
                elif kind == "tool_call" and event.get("subtype") == "started":
                    calls = event.get("tool_call") or {}
                    name = next((key.removesuffix("ToolCall") for key in calls if key.endswith("ToolCall")), "tool")
                    _note_chat(item_id, f"Агент использует инструмент: {name}.")
                elif kind == "result":
                    result_text = str(event.get("result") or "").strip()
            process.wait()
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
                process.wait()
        if process.returncode == 0 and (answer or result_text):
            return answer or result_text, "Cursor CLI"
        _note_chat(item_id, "Cursor CLI не вернул ответ; пробую другой локальный агент.")
        if not fallback:
            return None, None
    if agent_bin and not fallback:
        return None, None
    for backend in ("codex", "claude"):
        text, name = run_agent(prompt, cwd=workdir, backend=backend, timeout=timeout, allow_edits=force)
        if text:
            return text, name
    return None, None


def process_item(item_id: str) -> bool:
    """Auto-answer or LLM agent (claude/cursor). Returns True if answer saved."""
    item = find_item(item_id)
    if item is None or item.get("status") == "answered":
        return False

    load_env_file()  # ключи из KOI/.env (настройки UI) — не перетирает уже заданные
    local_mode = not is_api_agent_mode() and not is_cursor_manual_agent_mode()
    if not local_mode and item.get("purpose") not in ("report_grill", "grill_me", "make_report"):
        auto = try_auto_answer(item["project_id"], item["question"])
        if auto:
            submit_answer(item_id, auto)
            return True
    if is_cursor_manual_agent_mode():
        return False

    if local_mode:
        mark_processing(item_id)
        record(item_id, "Вопрос принят. Ищу доступного локального агента.")

    available = (
        bool(find_agent_bin() or any(backend_status()[name]["available"] for name in ("codex", "claude")))
        if local_mode else _any_backend_available()
    )
    if not available:
        if local_mode:
            record(item_id, "Локальный агент не найден. Установите и авторизуйте Cursor, Codex или Claude CLI.")
            submit_answer(item_id, "Локальный агент не найден. Установите и авторизуйте Cursor, Codex или Claude CLI, затем повторите вопрос.", answer_kind="warning")
        else:
            submit_answer(item_id, no_cursor_key_warning(), answer_kind="warning")
        return True

    if local_mode:
        record(item_id, "Агент обрабатывает вопрос и проверяет базу выводов проекта.")
    try:
        text, backend = (
            _run_local_agent(_sdk_prompt(item_id), item_id) if local_mode
            else run_agent(_sdk_prompt(item_id), cwd=_ws.agent_cwd())
        )
    except Exception as exc:
        if local_mode:
            record(item_id, f"Ошибка запуска: {type(exc).__name__}.")
            submit_answer(item_id, "Не удалось запустить агента. Подробности доступны в журнале работы.", answer_kind="warning")
            return True
        raise
    if text:
        if local_mode:
            record(item_id, f"Ответ получен от {backend or 'локального агента'}.")
        submit_answer(item_id, text)
        if local_mode:
            record(item_id, "Ответ опубликован в чате.")
        return True
    if local_mode:
        record(item_id, "Агент не вернул текст ответа.")
        submit_answer(item_id, "Агент не вернул ответ. Проверьте локальную авторизацию и повторите вопрос.", answer_kind="warning")
        return True
    return False


def process_all_pending() -> int:
    done = 0
    for item in list(list_pending()):
        if process_item(item["id"]):
            done += 1
    return done
