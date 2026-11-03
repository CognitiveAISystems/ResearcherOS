"""Read CLI events while allowing cancellation even when stdout is silent."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time


class AgentCancelled(Exception):
    pass


def run_json(command, prompt, *, cwd, timeout, on_event, is_cancelled=None, on_started=None,
             feed_stdin=True):
    if is_cancelled and is_cancelled():
        raise AgentCancelled
    process = subprocess.Popen(command, cwd=str(cwd), stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        encoding="utf-8", errors="replace", start_new_session=os.name != "nt")
    stdin, stdout = process.stdin, process.stdout
    assert stdin is not None and stdout is not None  # stdin/stdout=subprocess.PIPE
    finished = threading.Event()
    expired = threading.Event()
    deadline = time.monotonic() + timeout

    def kill_group():
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, check=False)
            return
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def watch():
        while not finished.wait(0.1):
            if is_cancelled and is_cancelled():
                kill_group()
                return
            if time.monotonic() >= deadline:
                expired.set()
                kill_group()
                return

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        if on_started is not None:
            on_started(process.pid)
        try:
            if feed_stdin:
                stdin.write(prompt)
            stdin.close()
        except BrokenPipeError:
            pass
        for line in stdout:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                on_event(event)
        process.wait()
        if is_cancelled and is_cancelled():
            raise AgentCancelled
        if expired.is_set():
            raise subprocess.TimeoutExpired(command, timeout)
        return process.returncode
    finally:
        finished.set()
        watcher.join()
        if process.poll() is None:
            kill_group()
            process.wait()
        for stream in (stdin, stdout):
            if getattr(stream, "close", None) and not getattr(stream, "closed", False):
                stream.close()
