"""Paper Inbox watcher and wake messages for the paper capability."""

from __future__ import annotations

import json
import os
import shutil
import signal
import sys
import time
from pathlib import Path

from koi.adapters.paper_queue import QUEUE_PATH
from koi.adapters.paper_queue import list_pending as list_paper_pending
from koi.adapters.workspace import get_workspace

_ws = get_workspace()
RUN_DIR = _ws.run_dir
LOG_DIR = RUN_DIR / "logs"
WATCH_PID = RUN_DIR / "koi-paper-inbox-watch.pid"
WAKE_PREFIX = "PAPER_WAKE"
WATCH_LOG = LOG_DIR / "paper-watch.log"
POLL_INTERVAL_S = 2.0
DEBOUNCE_S = 1.0

ENGINE_ROOT = _ws.engine_root
INBOX_SCRIPT = "-m koi.paper.inbox_cli"
CONFIGURED_FLAG = RUN_DIR / "paper-inbox-configured.json"
VENV_PYTHON = _ws.venv_python
LOOP_POLL_INTERVAL_S = 5


def inotify_available() -> bool:
    return shutil.which("inotifywait") is not None


def _python_bin() -> str:
    if VENV_PYTHON.is_file():
        return str(VENV_PYTHON)
    return sys.executable


def _pending_paper() -> list[dict]:
    try:
        return list_paper_pending()
    except Exception:
        return []


def pending_count() -> int:
    return len(_pending_paper())


def processing_instructions(*, focus_paper_id: str | None = None) -> str:
    py = _python_bin()
    paper = "-m koi.paper.cli"
    if focus_paper_id:
        return (
            "Paper (статья NeurIPS): скилл **koi-paper** — "
            f"новая задача `{focus_paper_id}`. "
            f"`{py} {paper} claim {focus_paper_id}` → context → answer -f paper-body.txt."
        )
    pending = _pending_paper()
    if not pending:
        return "Очередь Paper пуста."
    ids = ", ".join(item["id"] for item in pending[:3])
    return (
        "Paper: скилл **koi-paper** — "
        f"pending ids: {ids}. "
        f"`{py} {paper} claim <id>` → context → answer -f paper-body.txt."
    )


def pending_signature() -> tuple[str, ...]:
    return tuple(f"paper:{item['id']}" for item in _pending_paper())


def format_wake_line(*, focus_paper_id: str | None = None) -> str:
    payload: dict[str, object] = {
        "prompt": processing_instructions(focus_paper_id=focus_paper_id),
    }
    if focus_paper_id:
        payload["paper_id"] = focus_paper_id
    return f"{WAKE_PREFIX} {json.dumps(payload, ensure_ascii=False)}"


def notify_paper_inbox_wake(*, paper_id: str | None = None) -> None:
    """Append PAPER_WAKE to paper-watch.log for the Paper Inbox chat."""
    if not pending_signature() and not paper_id:
        return
    line = format_wake_line(focus_paper_id=paper_id)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with WATCH_LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def is_paper_inbox_configured() -> bool:
    if not CONFIGURED_FLAG.is_file():
        return False
    try:
        data = json.loads(CONFIGURED_FLAG.read_text(encoding="utf-8"))
        return bool(data.get("configured", True))
    except (OSError, json.JSONDecodeError):
        return False


def set_paper_inbox_configured(configured: bool = True) -> None:
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
        "ResearcherOS Paper Inbox: проверь Paper pending "
        f"(`{pending_cmd}`) и обработай по скиллу koi-paper "
        "(claim → context → answer -f paper-body.txt)."
    )


def agent_loop_shell_command() -> str:
    payload = json.dumps({"prompt": _loop_task_prompt()}, ensure_ascii=False)
    return (
        f"while true; do sleep {LOOP_POLL_INTERVAL_S}; "
        f"echo 'AGENT_LOOP_TICK_PAPER {payload}'; done"
    )


def loop_prompt() -> str:
    return f"/loop {LOOP_POLL_INTERVAL_S}s {_loop_task_prompt()}"


def bootstrap_prompt() -> str:
    py = _python_bin()
    watch = INBOX_SCRIPT
    log_rel = ".run/logs/paper-watch.log"
    loop_shell = agent_loop_shell_command()
    return f"""Ты **ResearcherOS Paper Inbox** — фоновый агент для генерации статей NeurIPS (index.html → «Статья»).

**Настройка один раз.** Кнопка «Сгенерировать статью» кладёт задачи в JSON-очередь; watcher пишет `{WAKE_PREFIX}` в лог (~1–3 с).

## Сделай сейчас (всё из этого сообщения)

1. Назови этот чат **ResearcherOS Paper Inbox**.

2. Подними сервер и **watcher статей**:
   ```
   cd {ENGINE_ROOT}
   ./scripts/koi-serve.sh start
   {py} {watch} status
   ```
   В status должно быть `"paper_inbox_watcher_running": true`. Если `false` — повтори `koi-serve.sh start`.

3. **Автоподхват (критично):** запусти **два фоновых shell** через Shell tool с `block_until_ms: 0` и **`notify_on_output`** — без notify агент не просыпается на новые задачи.

   Сначала проверь терминалы и останови старые дубликаты (`tail …paper-watch.log`, `AGENT_LOOP_TICK_PAPER`).

   **A) Мониторинг лога watcher** (основной wake, ~1–3 с):
   - command: `cd {ENGINE_ROOT} && tail -n 0 -f {log_rel}`
   - `notify_on_output`: pattern `^{WAKE_PREFIX}`, reason `Paper wake`

   **B) Fallback — опрос очереди каждые {LOOP_POLL_INTERVAL_S} с**:
   - command: `{loop_shell}`
   - `notify_on_output`: pattern `^AGENT_LOOP_TICK_PAPER`, reason `Paper queue poll`

   Оба процесса оставь работать. Не используй голый `tail`/`while` без `notify_on_output`.

4. Сразу обработай накопленное: `{py} {watch} pending` → по скиллу **koi-paper**: `claim` → `context` → `answer -f paper-body.txt`.

5. На каждый wake из п.3 — снова `pending` и обработай все новые id.

6. Не останавливай мониторинг, пока я явно не попрошу."""


def format_pending_report() -> str:
    paper = _pending_paper()
    if not paper:
        return "Очередь Paper пуста (pending: 0)."
    lines = [f"Pending paper: {len(paper)}", ""]
    for item in paper:
        title = item.get("project_title") or item["project_id"]
        lines.append(f"  paper {item['id']}  project={item['project_id']}  {title}")
    lines.append("")
    lines.append(processing_instructions())
    return "\n".join(lines)


def pending_snapshot() -> dict:
    paper = _pending_paper()
    return {
        "counts": {"paper": len(paper)},
        "paper": [
            {
                "id": i["id"],
                "project_id": i["project_id"],
                "project_title": i.get("project_title"),
            }
            for i in paper
        ],
        "instructions": processing_instructions(),
    }


def inbox_task_message(*, paper_id: str | None = None, setup: bool = False) -> str:
    if setup:
        return bootstrap_prompt()
    py = _python_bin()
    inbox = INBOX_SCRIPT
    paper = "-m koi.paper.cli"
    if paper_id:
        return (
            f"ResearcherOS Paper Inbox — статья `{paper_id}`.\n\n"
            f"Проверь очередь:\n`{py} {inbox} pending`\n\n"
            f"Обработай по скиллу **koi-paper**:\n"
            f"1. `{py} {paper} claim {paper_id}`\n"
            f"2. `{py} {paper} context {paper_id}`\n"
            f"3. `{py} {paper} answer {paper_id} -f paper-body.txt`"
        )
    return (
        f"Проверь pending Paper:\n`{py} {inbox} pending`\n\n"
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
    print(format_wake_line(focus_paper_id=focus_id), flush=True)
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
    """Foreground watcher; prints PAPER_WAKE lines to stdout."""
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


def paper_inbox_settings() -> dict:
    py = _python_bin()
    return {
        "paper_inbox_configured": is_paper_inbox_configured(),
        "paper_inbox_bootstrap_prompt": bootstrap_prompt(),
        "paper_inbox_loop_prompt": loop_prompt(),
        "paper_inbox_loop_interval_s": LOOP_POLL_INTERVAL_S,
        "paper_inbox_loop_shell": agent_loop_shell_command(),
        "paper_inbox_wake_prefix": WAKE_PREFIX,
        "paper_inbox_watch_command": f"{py} {INBOX_SCRIPT} watch",
        "paper_inbox_watch_log": ".run/logs/paper-watch.log",
        "paper_inbox_watcher_running": watcher_running(),
        "paper_inbox_pending_command": f"{py} {INBOX_SCRIPT} pending",
        "paper_inbox_pending_count": pending_count(),
    }
