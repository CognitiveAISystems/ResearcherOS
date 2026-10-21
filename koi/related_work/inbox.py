"""ResearcherOS Literature Inbox: watcher wake lines for Related Work (literature.html)."""

from __future__ import annotations

import json
import os
import shutil
import signal
import sys
import time
from pathlib import Path

from koi.adapters.related_work_queue import QUEUE_PATH
from koi.adapters.related_work_queue import list_pending as list_related_work_pending
from koi.adapters.workspace import get_workspace

_ws = get_workspace()
RUN_DIR = _ws.run_dir
LOG_DIR = RUN_DIR / "logs"
WATCH_PID = RUN_DIR / "koi-related-work-inbox-watch.pid"
WAKE_PREFIX = "RELATED_WORK_WAKE"
WATCH_LOG = LOG_DIR / "related-work-watch.log"
POLL_INTERVAL_S = 2.0
DEBOUNCE_S = 1.0

ENGINE_ROOT = _ws.engine_root
INBOX_SCRIPT = "-m koi.related_work.inbox_cli"
CONFIGURED_FLAG = RUN_DIR / "literature-inbox-configured.json"
VENV_PYTHON = _ws.venv_python
LOOP_POLL_INTERVAL_S = 3


def inotify_available() -> bool:
    return shutil.which("inotifywait") is not None


def _python_bin() -> str:
    if VENV_PYTHON.is_file():
        return str(VENV_PYTHON)
    return sys.executable


def _pending_related_work() -> list[dict]:
    try:
        return list_related_work_pending()
    except Exception:
        return []


def pending_count() -> int:
    return len(_pending_related_work())


def processing_instructions(*, focus_related_work_id: str | None = None) -> str:
    py = _python_bin()
    rw = "-m koi.related_work.cli"
    if focus_related_work_id:
        return (
            "Related Work (literature.html): скилл **koi-related-work** — "
            f"новая задача `{focus_related_work_id}`. "
            f"`{py} {rw} claim {focus_related_work_id}` → context → answer -f draft.md."
        )
    pending = _pending_related_work()
    if not pending:
        return "Очередь Related Work пуста."
    ids = ", ".join(item["id"] for item in pending[:3])
    return (
        "Related Work: скилл **koi-related-work** — "
        f"pending ids: {ids}. "
        f"`{py} {rw} claim <id>` → context → answer -f draft.md."
    )


def pending_signature() -> tuple[str, ...]:
    return tuple(f"rw:{item['id']}" for item in _pending_related_work())


def format_wake_line(*, focus_related_work_id: str | None = None) -> str:
    payload: dict[str, object] = {
        "prompt": processing_instructions(focus_related_work_id=focus_related_work_id),
    }
    if focus_related_work_id:
        payload["related_work_id"] = focus_related_work_id
    return f"{WAKE_PREFIX} {json.dumps(payload, ensure_ascii=False)}"


def notify_literature_inbox_wake(*, related_work_id: str | None = None) -> None:
    """Append RELATED_WORK_WAKE to related-work-watch.log for the Literature Inbox chat."""
    if not pending_signature() and not related_work_id:
        return
    line = format_wake_line(focus_related_work_id=related_work_id)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with WATCH_LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def is_literature_inbox_configured() -> bool:
    if not CONFIGURED_FLAG.is_file():
        return False
    try:
        data = json.loads(CONFIGURED_FLAG.read_text(encoding="utf-8"))
        return bool(data.get("configured", True))
    except (OSError, json.JSONDecodeError):
        return False


def set_literature_inbox_configured(configured: bool = True) -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    if configured:
        CONFIGURED_FLAG.write_text(
            json.dumps({"configured": True}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    else:
        CONFIGURED_FLAG.unlink(missing_ok=True)


def _loop_task_prompt() -> str:
    py = _python_bin()
    pending_cmd = f"{py} {INBOX_SCRIPT} pending"
    return (
        "ResearcherOS Literature Inbox: проверь Related Work pending "
        f"(`{pending_cmd}`) и обработай по скиллу koi-related-work "
        "(claim → context → answer -f draft.md)."
    )


def agent_loop_shell_command() -> str:
    payload = json.dumps({"prompt": _loop_task_prompt()}, ensure_ascii=False)
    return (
        f"while true; do sleep {LOOP_POLL_INTERVAL_S}; "
        f"echo 'AGENT_LOOP_TICK_RELATED_WORK {payload}'; done"
    )


def loop_prompt() -> str:
    """Cursor /loop shorthand — same cadence as agent_loop_shell_command()."""
    return f"/loop {LOOP_POLL_INTERVAL_S}s {_loop_task_prompt()}"


def bootstrap_prompt() -> str:
    py = _python_bin()
    watch = INBOX_SCRIPT
    log_rel = ".run/logs/related-work-watch.log"
    loop_shell = agent_loop_shell_command()
    return f"""Ты **ResearcherOS Literature Inbox** — фоновый агент для Related Work (literature.html).

**Настройка один раз.** Кнопка Related Work кладёт задачи в JSON-очередь; системный watcher пишет `{WAKE_PREFIX}` в лог (~1–3 с).

## Сделай сейчас (всё из этого сообщения)

1. Назови этот чат **ResearcherOS Literature Inbox**.

2. Подними сервер и **watcher литературы**:
   ```
   cd {ENGINE_ROOT}
   ./scripts/koi-serve.sh start
   {py} {watch} status
   ```
   В status должно быть `"literature_inbox_watcher_running": true`. Если `false` — повтори `koi-serve.sh start`.

3. **Автоподхват (критично):** запусти **два фоновых shell** через Shell tool с `block_until_ms: 0` и **`notify_on_output`** — без notify агент не просыпается на новые задачи.

   Сначала проверь терминалы и останови старые дубликаты (`tail …related-work-watch.log`, `AGENT_LOOP_TICK_RELATED_WORK`).

   **A) Мониторинг лога watcher** (основной wake, ~1–3 с):
   - command: `cd {ENGINE_ROOT} && tail -n 0 -f {log_rel}`
   - `notify_on_output`: pattern `^{WAKE_PREFIX}`, reason `Related Work wake`

   **B) Fallback — опрос очереди каждые {LOOP_POLL_INTERVAL_S} с**:
   - command: `{loop_shell}`
   - `notify_on_output`: pattern `^AGENT_LOOP_TICK_RELATED_WORK`, reason `Related Work queue poll`

   Оба процесса оставь работать. Не используй голый `tail`/`while` без `notify_on_output`.

4. Сразу обработай накопленное: `{py} {watch} pending` → по скиллу **koi-related-work**: `claim` → `context` → `answer -f draft.md`.

5. На каждый wake из п.3 — снова `pending` и обработай все новые id.

6. Не останавливай мониторинг, пока я явно не попрошу."""


def format_pending_report() -> str:
    related = _pending_related_work()
    if not related:
        return "Очередь Related Work пуста (pending: 0)."
    lines = [f"Pending related-work: {len(related)}", ""]
    for item in related:
        project = item.get("project_id") or "?"
        lines.append(f"  related-work {item['id']}  project={project}")
    lines.append("")
    lines.append(processing_instructions())
    return "\n".join(lines)


def pending_snapshot() -> dict:
    related = _pending_related_work()
    return {
        "counts": {"related_work": len(related)},
        "related_work": [{"id": i["id"], "project_id": i.get("project_id")} for i in related],
        "instructions": processing_instructions(),
    }


def inbox_task_message(*, related_work_id: str | None = None, setup: bool = False) -> str:
    if setup:
        return bootstrap_prompt()
    py = _python_bin()
    inbox = INBOX_SCRIPT
    rw = "-m koi.related_work.cli"
    if related_work_id:
        return (
            f"ResearcherOS Literature Inbox — Related Work `{related_work_id}`.\n\n"
            f"Проверь очередь:\n`{py} {inbox} pending`\n\n"
            f"Обработай по скиллу **koi-related-work**:\n"
            f"1. `{py} {rw} claim {related_work_id}`\n"
            f"2. `{py} {rw} context {related_work_id}`\n"
            f"3. `{py} {rw} answer {related_work_id} -f draft.md`"
        )
    return (
        f"Проверь pending Related Work:\n`{py} {inbox} pending`\n\n"
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
    print(format_wake_line(focus_related_work_id=focus_id), flush=True)
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
    """Foreground watcher; prints RELATED_WORK_WAKE lines to stdout."""
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


def literature_inbox_settings() -> dict:
    py = _python_bin()
    return {
        "literature_inbox_configured": is_literature_inbox_configured(),
        "literature_inbox_bootstrap_prompt": bootstrap_prompt(),
        "literature_inbox_loop_prompt": loop_prompt(),
        "literature_inbox_loop_interval_s": LOOP_POLL_INTERVAL_S,
        "literature_inbox_loop_shell": agent_loop_shell_command(),
        "literature_inbox_wake_prefix": WAKE_PREFIX,
        "literature_inbox_watch_command": f"{py} {INBOX_SCRIPT} watch",
        "literature_inbox_watch_log": ".run/logs/related-work-watch.log",
        "literature_inbox_watcher_running": watcher_running(),
        "literature_inbox_pending_command": f"{py} {INBOX_SCRIPT} pending",
        "literature_inbox_pending_count": pending_count(),
    }
