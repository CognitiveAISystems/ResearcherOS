"""Cursor Inbox integration for the ResearcherOS agent-chat capability."""

from __future__ import annotations

import json
import os
import shutil
import signal
import sys
import time
from pathlib import Path

from koi.adapters.agent_chat_queue import QUEUE_PATH, list_pending
from koi.adapters.workspace import get_workspace

_ws = get_workspace()
RUN_DIR = _ws.run_dir
LOG_DIR = RUN_DIR / "logs"
WATCH_PID = RUN_DIR / "koi-agent-chat-inbox-watch.pid"
WAKE_PREFIX = "AGENT_CHAT_WAKE"
WATCH_LOG = LOG_DIR / "agent-chat-watch.log"
POLL_INTERVAL_S = 2.0
DEBOUNCE_S = 1.0

ENGINE_ROOT = _ws.engine_root
INBOX_SCRIPT = "-m koi.agent_chat.inbox_cli"
CONFIGURED_FLAG = RUN_DIR / "chat-inbox-configured.json"
VENV_PYTHON = _ws.venv_python
LOOP_POLL_INTERVAL_S = 5

# Legacy combined inbox (pre-split)
LEGACY_WAKE_PREFIX = "AGENT_INBOX_WAKE"
LEGACY_WATCH_LOG = LOG_DIR / "inbox-watch.log"
LEGACY_CONFIGURED_FLAG = RUN_DIR / "inbox-configured.json"


def inotify_available() -> bool:
    return shutil.which("inotifywait") is not None


def _python_bin() -> str:
    if VENV_PYTHON.is_file():
        return str(VENV_PYTHON)
    return sys.executable


def _pending_agent_chat() -> list[dict]:
    try:
        return list_pending()
    except Exception:
        return []


def pending_count() -> int:
    return len(_pending_agent_chat())


def processing_instructions(*, focus_agent_chat_id: str | None = None) -> str:
    py = _python_bin()
    chat = "-m koi.agent_chat.cli"
    if focus_agent_chat_id:
        return (
            "agent-chat: скилл **koi-agent-chat** — "
            f"новая задача `{focus_agent_chat_id}`. "
            f"`{py} {chat} claim {focus_agent_chat_id}` → context → answer."
        )
    pending = _pending_agent_chat()
    if not pending:
        return "Очередь agent-chat пуста."
    ids = ", ".join(item["id"] for item in pending[:3])
    return (
        "agent-chat: скилл **koi-agent-chat** — "
        f"pending ids: {ids}. "
        f"`{py} {chat} claim <id>` → context → answer."
    )


def pending_signature() -> tuple[str, ...]:
    return tuple(f"ac:{item['id']}" for item in _pending_agent_chat())


def format_wake_line(*, focus_agent_chat_id: str | None = None) -> str:
    payload: dict[str, object] = {
        "prompt": processing_instructions(focus_agent_chat_id=focus_agent_chat_id),
    }
    if focus_agent_chat_id:
        payload["agent_chat_id"] = focus_agent_chat_id
    return f"{WAKE_PREFIX} {json.dumps(payload, ensure_ascii=False)}"


def notify_chat_inbox_wake(*, agent_chat_id: str | None = None) -> None:
    """Append AGENT_CHAT_WAKE to agent-chat-watch.log for the Chat Inbox monitor."""
    if not pending_signature() and not agent_chat_id:
        return
    line = format_wake_line(focus_agent_chat_id=agent_chat_id)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with WATCH_LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def notify_inbox_wake(
    *,
    related_work_id: str | None = None,
    agent_chat_id: str | None = None,
) -> None:
    """Backward-compatible wake: routes to the correct split inbox."""
    if agent_chat_id:
        notify_chat_inbox_wake(agent_chat_id=agent_chat_id)
    if related_work_id:
        from koi.related_work.inbox import notify_literature_inbox_wake

        notify_literature_inbox_wake(related_work_id=related_work_id)


def is_chat_inbox_configured() -> bool:
    if not CONFIGURED_FLAG.is_file():
        return False
    try:
        data = json.loads(CONFIGURED_FLAG.read_text(encoding="utf-8"))
        return bool(data.get("configured", True))
    except (OSError, json.JSONDecodeError):
        return True


def is_inbox_configured() -> bool:
    return is_chat_inbox_configured()


def set_chat_inbox_configured(configured: bool = True) -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    if configured:
        CONFIGURED_FLAG.write_text(
            json.dumps({"configured": True}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        CONFIGURED_FLAG.unlink(missing_ok=True)


def set_inbox_configured(configured: bool = True, *, inbox_kind: str = "chat") -> None:
    if inbox_kind == "literature":
        from koi.related_work.inbox import set_literature_inbox_configured

        set_literature_inbox_configured(configured)
        return
    if inbox_kind == "paper":
        from koi.paper.inbox import set_paper_inbox_configured

        set_paper_inbox_configured(configured)
        return
    set_chat_inbox_configured(configured)


def loop_prompt() -> str:
    """Cursor /loop command — fallback when tail+regex on watcher log is unavailable."""
    py = _python_bin()
    watch = INBOX_SCRIPT
    pending_cmd = f"{py} {watch} pending"
    task = (
        "ResearcherOS Chat Inbox: проверь agent-chat pending "
        f"(`{pending_cmd}`) и обработай по скиллу koi-agent-chat "
        "(claim → context → answer)."
    )
    return f"/loop {LOOP_POLL_INTERVAL_S}s {task}"


def bootstrap_prompt() -> str:
    py = _python_bin()
    watch = INBOX_SCRIPT
    log_rel = ".run/logs/agent-chat-watch.log"
    loop_line = loop_prompt()
    return f"""Ты **ResearcherOS Chat Inbox** — фоновый агент для панели «Спросить агента» (localhost:8080).

**Настройка один раз.** UI кладёт вопросы в JSON-очередь; watcher будит этот чат через `{WAKE_PREFIX}` (~1–3 с).

## Сделай сейчас

1. Назови этот чат **ResearcherOS Chat Inbox**.

2. Убедись, что **watcher чата** запущен (`koi-serve.sh start` поднимает его автоматически):
   ```
   cd {ENGINE_ROOT}
   ./scripts/koi-serve.sh start
   {py} {watch} status
   ```
   В status должно быть `"chat_inbox_watcher_running": true`.

3. Запусти **loop-мониторинг** (обязательно, оставь работать):

   **A) Мониторинг лога watcher** (предпочтительно):
   ```
   tail -n 0 -f {log_rel}
   ```
   Regex уведомлений: `^{WAKE_PREFIX}`

   **B) Fallback — loop опроса очереди каждые {LOOP_POLL_INTERVAL_S} с:**
   ```
   {loop_line}
   ```

4. На каждый `{WAKE_PREFIX}` или новый pending из loop — обработай вопрос по скиллу **koi-agent-chat**:
   `claim` → `context` → `answer`

5. Не останавливай мониторинг/loop, пока я явно не попрошу.

Сейчас: `{py} {watch} pending` → обработай всё накопленное."""


def format_pending_report() -> str:
    agent = _pending_agent_chat()
    if not agent:
        return "Очередь agent-chat пуста (pending: 0)."
    lines = [f"Pending agent-chat: {len(agent)}", ""]
    for item in agent:
        question = str(item.get("question") or "").strip()
        if len(question) > 100:
            question = question[:97] + "…"
        lines.append(f"  agent-chat  {item['id']}  {question or '(без текста)'}")
    lines.append("")
    lines.append(processing_instructions())
    return "\n".join(lines)


def pending_snapshot() -> dict:
    agent = _pending_agent_chat()
    return {
        "counts": {"agent_chat": len(agent)},
        "agent_chat": [{"id": i["id"], "question": i.get("question")} for i in agent],
        "instructions": processing_instructions(),
    }


def pending_counts() -> dict[str, int]:
    from koi.paper.inbox import pending_count as paper_pending_count
    from koi.related_work.inbox import pending_count as rw_pending_count

    return {
        "agent_chat": pending_count(),
        "related_work": rw_pending_count(),
        "paper": paper_pending_count(),
    }


def inbox_task_message(
    *,
    related_work_id: str | None = None,
    agent_chat_id: str | None = None,
    setup: bool = False,
) -> str:
    if related_work_id:
        from koi.related_work.inbox import inbox_task_message as rw_message

        return rw_message(related_work_id=related_work_id, setup=setup)
    if setup:
        return bootstrap_prompt()
    py = _python_bin()
    inbox = INBOX_SCRIPT
    chat = "-m koi.agent_chat.cli"
    if agent_chat_id:
        return (
            f"ResearcherOS Chat Inbox — вопрос `{agent_chat_id}`.\n\n"
            f"Проверь очередь:\n`{py} {inbox} pending`\n\n"
            f"Обработай по скиллу **koi-agent-chat**:\n"
            f"1. `{py} {chat} claim {agent_chat_id}`\n"
            f"2. `{py} {chat} context {agent_chat_id}`\n"
            f"3. `{py} {chat} answer {agent_chat_id} \"…\"`"
        )
    return (
        f"Проверь pending agent-chat:\n`{py} {inbox} pending`\n\n"
        f"{processing_instructions()}"
    )


def watcher_running() -> bool:
    if not WATCH_PID.exists():
        return False
    try:
        pid = int(WATCH_PID.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        WATCH_PID.unlink(missing_ok=True)
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        WATCH_PID.unlink(missing_ok=True)
        return False
    return True


def _write_pid() -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    WATCH_PID.write_text(f"{os.getpid()}\n", encoding="utf-8")


def _remove_pid() -> None:
    WATCH_PID.unlink(missing_ok=True)


def _handle_term(*_args: object) -> None:
    _remove_pid()
    raise SystemExit(0)


def _ensure_queue_file() -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not QUEUE_PATH.exists():
        QUEUE_PATH.write_text("[]\n", encoding="utf-8")


def _emit_wake_if_needed(
    *,
    last_sig: tuple[str, ...],
    last_wake_at: float,
    focus_id: str | None = None,
) -> tuple[tuple[str, ...], float]:
    sig = pending_signature()
    if not sig and not focus_id:
        return (), last_wake_at
    now = time.time()
    if sig == last_sig and now - last_wake_at < DEBOUNCE_S:
        return last_sig, last_wake_at
    print(format_wake_line(focus_agent_chat_id=focus_id), flush=True)
    return sig, now


def _watch_inotify() -> None:
    import subprocess

    _ensure_queue_file()
    last_sig: tuple[str, ...] = ()
    last_wake_at = 0.0
    last_sig, last_wake_at = _emit_wake_if_needed(last_sig=last_sig, last_wake_at=last_wake_at)

    proc = subprocess.Popen(
        [
            "inotifywait",
            "-m",
            "-e",
            "modify,create,close_write,move_self",
            "--format",
            "%w%f",
            str(QUEUE_PATH),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    assert proc.stdout is not None
    for _line in proc.stdout:
        last_sig, last_wake_at = _emit_wake_if_needed(
            last_sig=last_sig, last_wake_at=last_wake_at
        )


def _watch_poll() -> None:
    _ensure_queue_file()
    last_sig: tuple[str, ...] = ()
    last_wake_at = 0.0
    last_mtime = 0.0

    while True:
        changed = False
        try:
            mtime = QUEUE_PATH.stat().st_mtime
        except OSError:
            mtime = 0.0
        if last_mtime != mtime:
            last_mtime = mtime
            changed = True
        if changed:
            last_sig, last_wake_at = _emit_wake_if_needed(
                last_sig=last_sig, last_wake_at=last_wake_at
            )
        else:
            sig = pending_signature()
            if sig and sig != last_sig:
                last_sig, last_wake_at = _emit_wake_if_needed(
                    last_sig=(), last_wake_at=0.0
                )
        time.sleep(POLL_INTERVAL_S)


def run_watch() -> None:
    """Foreground watcher; prints AGENT_CHAT_WAKE lines to stdout."""
    signal.signal(signal.SIGTERM, _handle_term)
    signal.signal(signal.SIGINT, _handle_term)
    _write_pid()
    try:
        if inotify_available():
            _watch_inotify()
        else:
            sys.stderr.write(
                "inotifywait not found — polling every "
                f"{POLL_INTERVAL_S}s (install inotify-tools for instant wake)\n"
            )
            sys.stderr.flush()
            _watch_poll()
    finally:
        _remove_pid()


def inbox_settings() -> dict:
    from koi.paper.inbox import paper_inbox_settings
    from koi.related_work.inbox import literature_inbox_settings

    py = _python_bin()
    chat = {
        "chat_inbox_configured": is_chat_inbox_configured(),
        "chat_inbox_bootstrap_prompt": bootstrap_prompt(),
        "chat_inbox_loop_prompt": loop_prompt(),
        "chat_inbox_loop_interval_s": LOOP_POLL_INTERVAL_S,
        "chat_inbox_wake_prefix": WAKE_PREFIX,
        "chat_inbox_watch_command": f"{py} {INBOX_SCRIPT} watch",
        "chat_inbox_watch_log": ".run/logs/agent-chat-watch.log",
        "chat_inbox_watcher_running": watcher_running(),
        "chat_inbox_pending_command": f"{py} {INBOX_SCRIPT} pending",
        "chat_inbox_pending_count": pending_count(),
        # Legacy alias (chat only)
        "inbox_configured": is_chat_inbox_configured(),
        "inbox_bootstrap_prompt": bootstrap_prompt(),
        "inbox_loop_prompt": loop_prompt(),
        "inbox_loop_interval_s": LOOP_POLL_INTERVAL_S,
        "inbox_wake_prefix": WAKE_PREFIX,
        "inbox_watch_command": f"{py} {INBOX_SCRIPT} watch",
        "inbox_watch_log": ".run/logs/agent-chat-watch.log",
        "inbox_watcher_running": watcher_running(),
        "inbox_inotify_available": inotify_available(),
        "inbox_pending_command": f"{py} {INBOX_SCRIPT} pending",
        "inbox_agent_chat_queue": ".run/agent-chat-queue.json",
        "inbox_related_work_queue": ".run/related-work-queue.json",
        "inbox_paper_queue": ".run/paper-queue.json",
        "inbox_pending_counts": pending_counts(),
    }
    chat.update(literature_inbox_settings())
    chat.update(paper_inbox_settings())
    return chat
