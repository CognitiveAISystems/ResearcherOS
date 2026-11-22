"""Lifecycle and command-line entrypoint for the agent-chat worker."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from koi.adapters.agent_process import pid_alive
from koi.adapters.settings_store import has_cursor_api_key, is_api_agent_mode, load_env_file
from koi.adapters.workspace import get_workspace
from koi.agent_chat.runner import process_all_pending, process_item

_ws = get_workspace()
RUN_DIR = _ws.run_dir
WORKER_PID = RUN_DIR / "koi-agent-chat-worker.pid"
LOG_DIR = RUN_DIR / "logs"
VENV_PYTHON = _ws.venv_python
ENGINE_ROOT = _ws.engine_root


def worker_running() -> bool:
    if not WORKER_PID.exists():
        return False
    try:
        pid = int(WORKER_PID.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    return pid_alive(pid)


def cursor_sdk_available() -> bool:
    try:
        import cursor_sdk  # noqa: F401
    except ImportError:
        return False
    return True


def stop_agent_worker() -> None:
    if not WORKER_PID.exists():
        return
    try:
        pid = int(WORKER_PID.read_text(encoding="utf-8").strip())
        os.kill(pid, signal.SIGTERM)
    except (OSError, ValueError):
        pass
    WORKER_PID.unlink(missing_ok=True)


def ensure_agent_worker() -> bool:
    """Start worker if API mode, key and cursor-sdk are available. Returns True if running."""
    load_env_file()
    if not is_api_agent_mode() or not has_cursor_api_key() or not cursor_sdk_available():
        stop_agent_worker()
        return False
    if worker_running():
        return True
    if not VENV_PYTHON.is_file():
        return False
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "agent-chat-worker.log"
    with log_path.open("a", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [str(VENV_PYTHON), "-m", "koi.agent_chat.worker"],
            cwd=str(ENGINE_ROOT),
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    WORKER_PID.write_text(f"{proc.pid}\n", encoding="utf-8")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Background worker for pending agent-chat items"
    )
    parser.add_argument("--once", action="store_true", help="Process the queue once")
    parser.add_argument("--id", help="Process one queue item")
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()

    if args.id:
        print("answered" if process_item(args.id) else "skipped")
        return
    if args.once:
        print(f"answered {process_all_pending()}")
        return

    print("agent-chat worker: polling…", flush=True)
    while True:
        try:
            count = process_all_pending()
            if count:
                print(f"answered {count}", flush=True)
        except KeyboardInterrupt:
            break
        except Exception as exc:  # noqa: BLE001
            print(f"error: {exc}", file=sys.stderr, flush=True)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
