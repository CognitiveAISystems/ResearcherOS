from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen

import pytest

from koi.desktop.server import DesktopServer


def test_desktop_server_serves_ui_and_api_on_one_origin() -> None:
    server = DesktopServer()
    try:
        url = server.start()
        assert url.startswith("http://127.0.0.1:")

        with urlopen(url, timeout=3) as response:
            assert response.status == 200
            assert b"<html" in response.read(4096).lower()

        with urlopen(url.rstrip("/") + "/api/health", timeout=3) as response:
            assert json.loads(response.read()) == {
                "status": "ok",
                "storage": "markdown",
            }
    finally:
        server.stop()


def test_desktop_server_rejects_non_loopback_bind() -> None:
    with pytest.raises(ValueError, match="loopback"):
        DesktopServer(host="0.0.0.0")


def test_cli_prints_ready_json_and_stops_on_sigterm() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root)
    process = subprocess.Popen(
        [sys.executable, "-m", "api.desktop_server", "--port", "0"],
        cwd=repo_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        ready_line = process.stdout.readline().strip()
        ready = json.loads(ready_line)
        assert set(ready) == {"url"}
        assert ready["url"].startswith("http://127.0.0.1:")
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=10) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
