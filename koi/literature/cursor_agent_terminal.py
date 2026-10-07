"""Open an interactive Cursor agent terminal with a prompt on its command line."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def find_agent_bin() -> Path | None:
    found = shutil.which("agent")
    if found:
        return Path(found)
    fallback = Path.home() / ".local" / "bin" / "agent"
    return fallback if fallback.is_file() else None


def agent_terminal_shell(prompt_path: Path, cwd: Path, agent_bin: Path) -> str:
    # ponytail: the shell expands $(cat) into argv so agent keeps a real TTY.
    # Ceiling is ARG_MAX (~1MB on macOS); a subgraph prompt is a few KB.
    return (
        f"cd {shlex.quote(str(cwd))} && "
        f'{shlex.quote(str(agent_bin))} --trust "$(cat {shlex.quote(str(prompt_path))})"'
    )


def explain_note_file(morphology_root: Path, run_id: str, node_id: str) -> Path:
    if not _SAFE_ID.fullmatch(run_id) or not _SAFE_ID.fullmatch(node_id):
        raise ValueError("Некорректный идентификатор.")
    return Path(morphology_root) / run_id / f"explain-{node_id}.txt"


def explain_note_suffix(rel_posix: str) -> str:
    return (
        "\n\n## Куда записать\n"
        "Ответ — один абзац в ритме из задачи. Без заголовка, списков и кавычек вокруг всего текста.\n"
        f"Запиши тот же абзац в файл `{rel_posix}`.\n"
        "В файле только этот абзац.\n"
    )


def read_explain_note(morphology_root: Path, run_id: str, node_id: str) -> str | None:
    path = explain_note_file(morphology_root, run_id, node_id)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def _applescript_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def open_agent_terminal(prompt: str, cwd: Path) -> Path:
    """Write the prompt aside and open Terminal.app running ``agent`` on it.

    The file stays in the temp directory: Terminal reads it after this returns.
    """
    if sys.platform != "darwin":
        raise OSError("Интерактивный терминал агента доступен только на macOS.")
    agent_bin = find_agent_bin()
    if agent_bin is None:
        raise FileNotFoundError("agent")
    cwd = Path(cwd).resolve()
    if not cwd.is_dir():
        raise OSError(f"Каталог проекта не найден: {cwd}")
    fd, name = tempfile.mkstemp(prefix="koi-explain-", suffix=".txt")
    path = Path(name)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(prompt)
    shell = agent_terminal_shell(path, cwd, agent_bin)
    script = (
        'tell application "Terminal"\n'
        "activate\n"
        f"do script {_applescript_string(shell)}\n"
        "end tell\n"
    )
    result = subprocess.run(
        ["osascript", "-"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "osascript failed").strip()
        raise OSError(detail)
    return path
