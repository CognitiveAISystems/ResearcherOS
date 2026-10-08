"""Локальные агент-бэкенды KOI: Codex CLI, OpenRouter, Claude Code CLI и Cursor SDK.

Единая точка запуска LLM-агента для авто-задач (ответы agent-chat,
проверка гипотез с генерацией отчёта). Бэкенд выбирается через
`KOI_AGENT_BACKEND` (по умолчанию `codex,openrouter,claude,cursor` — первый доступный):

- **codex** — локальный Codex CLI в non-interactive режиме (`codex exec`).
  Требуется бинарь `codex` в PATH и локальная авторизация Codex. Модель —
  `KOI_CODEX_MODEL`, доп. флаги — `KOI_CODEX_ARGS`.

- **openrouter** — OpenRouter Chat Completions API. Требуется
  `OPENAI_API_KEY` (по договорённости проекта используем его как ключ
  OpenRouter), модель — `KOI_OPENROUTER_MODEL` (по умолчанию
  `openai/gpt-5.4`).

- **claude** — Claude Code CLI (headless: `claude -p`). Требуется бинарь
  `claude` в PATH (или `KOI_CLAUDE_BIN`) и авторизация CLI
  (`claude login` либо `ANTHROPIC_API_KEY`). Модель — `KOI_CLAUDE_MODEL`,
  доп. флаги — `KOI_CLAUDE_ARGS`.
- **cursor** — Cursor SDK (python-пакет `cursor_sdk`). Требуется
  `CURSOR_API_KEY`; модель — `KOI_AGENT_CHAT_MODEL` (по умолчанию
  composer-2.5).

`allow_edits=True` (для эксперимент-агента, который пишет файл отчёта)
у Claude Code включает `--permission-mode acceptEdits` и набор
инструментов из `KOI_CLAUDE_ALLOWED_TOOLS`; Cursor SDK и так работает
в режиме локального агента с правом на правки.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
import json
from pathlib import Path
from typing import Callable, Optional

from koi.adapters.workspace import get_workspace


def _resolve_cwd(cwd: Path | str | None) -> Path | str:
    if cwd is None:
        return get_workspace().agent_cwd()
    return cwd

DEFAULT_BACKEND_ORDER = "codex,openrouter,claude,cursor"
DEFAULT_TIMEOUT_S = 1800
DEFAULT_CLAUDE_TOOLS = "Read,Glob,Grep,Bash,Write,Edit"
DEFAULT_OPENROUTER_MODEL = "openai/gpt-5.4"
DEFAULT_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _codex_bin() -> Optional[str]:
    return shutil.which(os.environ.get("KOI_CODEX_BIN", "codex"))


def _codex_ready() -> bool:
    return _codex_bin() is not None


def _openrouter_api_key() -> str:
    return os.environ.get("OPENAI_API_KEY", "").strip()


def _openrouter_ready() -> bool:
    return bool(_openrouter_api_key())


def _claude_bin() -> Optional[str]:
    return shutil.which(os.environ.get("KOI_CLAUDE_BIN", "claude"))


def _cursor_ready() -> bool:
    if not os.environ.get("CURSOR_API_KEY", "").strip():
        return False
    try:
        import cursor_sdk  # noqa: F401
    except ImportError:
        return False
    return True


def run_codex_exec(
    prompt: str,
    *,
    cwd: Path | str | None = None,
    timeout: int = DEFAULT_TIMEOUT_S,
    allow_edits: bool = False,
) -> Optional[str]:
    """Non-interactive вызов локального Codex CLI; возвращает финальный текст или None."""
    cwd = _resolve_cwd(cwd)
    bin_path = _codex_bin()
    if not bin_path:
        return None

    sandbox_mode = "workspace-write" if allow_edits else "read-only"
    with tempfile.NamedTemporaryFile(prefix="koi-codex-", suffix=".txt", delete=False) as tmp:
        output_path = Path(tmp.name)
    cmd = [
        bin_path,
        "exec",
        "--skip-git-repo-check",
        "--ephemeral",
        "-s",
        sandbox_mode,
        "-C",
        str(cwd),
        "-o",
        str(output_path),
        "-",
    ]
    model = os.environ.get("KOI_CODEX_MODEL", "").strip()
    if model:
        cmd[2:2] = ["-m", model]
    extra = os.environ.get("KOI_CODEX_ARGS", "").split()
    if extra:
        cmd[2:2] = extra
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=timeout,
        )
        if output_path.exists():
            text = output_path.read_text(encoding="utf-8").strip()
            if text:
                return text
        if proc.returncode == 0:
            text = (proc.stdout or "").strip()
            return text or None
        return None
    except (OSError, subprocess.TimeoutExpired):
        return None
    finally:
        try:
            output_path.unlink(missing_ok=True)
        except OSError:
            pass


def run_openrouter(
    prompt: str,
    *,
    cwd: Path | str | None = None,  # noqa: ARG001 — API backend не использует cwd
    timeout: int = DEFAULT_TIMEOUT_S,
    allow_edits: bool = False,  # noqa: ARG001 — backend только текстовый
) -> Optional[str]:
    """Вызов OpenRouter Chat Completions API; возвращает финальный текст или None."""
    _resolve_cwd(cwd)
    api_key = _openrouter_api_key()
    if not api_key:
        return None

    payload = {
        "model": os.environ.get("KOI_OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL).strip() or DEFAULT_OPENROUTER_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": 0.1,
    }
    request = urllib.request.Request(
        os.environ.get("KOI_OPENROUTER_URL", DEFAULT_OPENROUTER_URL).strip() or DEFAULT_OPENROUTER_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": os.environ.get("KOI_OPENROUTER_REFERER", "https://researchos.local"),
            "X-OpenRouter-Title": os.environ.get("KOI_OPENROUTER_TITLE", "ResearchOS"),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except (OSError, TimeoutError, urllib.error.URLError, urllib.error.HTTPError):
        return None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None

    choices = parsed.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    message = first.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        text = content.strip()
        return text or None
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                text_parts.append(item["text"])
        text = "\n".join(part.strip() for part in text_parts if part.strip()).strip()
        return text or None
    return None


def run_claude_code(
    prompt: str,
    *,
    cwd: Path | str | None = None,
    timeout: int = DEFAULT_TIMEOUT_S,
    allow_edits: bool = False,
) -> Optional[str]:
    """Headless-вызов Claude Code; возвращает финальный текст или None."""
    cwd = _resolve_cwd(cwd)
    bin_path = _claude_bin()
    if not bin_path:
        return None
    cmd = [bin_path, "-p", "--output-format", "text"]
    model = os.environ.get("KOI_CLAUDE_MODEL", "").strip()
    if model:
        cmd += ["--model", model]
    if allow_edits:
        cmd += ["--permission-mode", "acceptEdits"]
        tools = os.environ.get("KOI_CLAUDE_ALLOWED_TOOLS", DEFAULT_CLAUDE_TOOLS)
        if tools.strip():
            cmd += ["--allowed-tools", tools]
    extra = os.environ.get("KOI_CLAUDE_ARGS", "").split()
    cmd += extra
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    text = (proc.stdout or "").strip()
    return text or None


def run_cursor_sdk(
    prompt: str,
    *,
    cwd: Path | str | None = None,
    timeout: int = DEFAULT_TIMEOUT_S,  # noqa: ARG001 — SDK сам управляет временем
    allow_edits: bool = False,  # noqa: ARG001 — локальный агент Cursor всегда полный
) -> Optional[str]:
    """Вызов Cursor SDK; возвращает финальный текст или None."""
    cwd = _resolve_cwd(cwd)
    api_key = os.environ.get("CURSOR_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from cursor_sdk import Agent, AgentOptions, LocalAgentOptions
    except ImportError:
        return None
    try:
        result = Agent.prompt(
            prompt,
            AgentOptions(
                api_key=api_key,
                model=os.environ.get("KOI_AGENT_CHAT_MODEL", "composer-2.5"),
                local=LocalAgentOptions(cwd=str(cwd)),
            ),
        )
    except Exception:  # noqa: BLE001 — сетевые/SDK ошибки → попробует другой бэкенд
        return None
    text = (getattr(result, "result", None) or "").strip()
    if not text:
        return None
    if getattr(result, "status", "") not in ("completed", "success", ""):
        return text or None
    return text


_RUNNERS: dict[str, Callable[..., Optional[str]]] = {
    "codex": run_codex_exec,
    "openrouter": run_openrouter,
    "claude": run_claude_code,
    "cursor": run_cursor_sdk,
}


def backend_order() -> list[str]:
    raw = os.environ.get("KOI_AGENT_BACKEND", DEFAULT_BACKEND_ORDER)
    if raw.strip().lower() in ("off", "none", "0"):
        return []
    if raw.strip().lower() == "auto":
        raw = DEFAULT_BACKEND_ORDER
    return [b.strip().lower() for b in raw.split(",") if b.strip() in _RUNNERS]


def backend_status() -> dict:
    """Что доступно на этой машине — для диагностики и эндпоинта."""
    return {
        "order": backend_order(),
        "codex": {
            "available": _codex_ready(),
            "bin": _codex_bin(),
            "model": os.environ.get("KOI_CODEX_MODEL") or None,
        },
        "openrouter": {
            "available": _openrouter_ready(),
            "model": os.environ.get("KOI_OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL),
            "api_key_present": bool(_openrouter_api_key()),
        },
        "claude": {
            "available": _claude_bin() is not None,
            "bin": _claude_bin(),
            "model": os.environ.get("KOI_CLAUDE_MODEL") or None,
        },
        "cursor": {
            "available": _cursor_ready(),
            "model": os.environ.get("KOI_AGENT_CHAT_MODEL", "composer-2.5"),
        },
    }


def any_agent_available() -> bool:
    status = backend_status()
    return any(
        bool(status.get(name, {}).get("available"))
        for name in ("codex", "openrouter", "claude", "cursor")
    )


def run_agent(
    prompt: str,
    *,
    cwd: Path | str | None = None,
    timeout: int = DEFAULT_TIMEOUT_S,
    allow_edits: bool = False,
    backend: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Запустить агента первым доступным бэкендом.

    Возвращает (текст_ответа, имя_бэкенда) либо (None, None), если ни один
    бэкенд не доступен или все вернули пустой результат.
    """
    cwd = _resolve_cwd(cwd)
    order = [backend] if backend else backend_order()
    for name in order:
        if allow_edits and name == "openrouter":
            continue  # Text-only backend cannot carry out project changes.
        runner = _RUNNERS.get(name)
        if runner is None:
            continue
        text = runner(prompt, cwd=cwd, timeout=timeout, allow_edits=allow_edits)
        if text:
            return text, name
    return None, None
