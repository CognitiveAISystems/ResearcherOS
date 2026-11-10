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
- **opencode** — локальный OpenCode CLI (headless: `opencode run`). Бинарь —
  программа, установленная в системе, как `codex` и `claude`; явный путь —
  `KOI_OPENCODE_BIN`. Модель — `KOI_OPENCODE_MODEL`, доп. флаги —
  `KOI_OPENCODE_ARGS`. Без правок файлов запускается встроенный агент `plan`,
  с правками — `--auto`. Ответ собирается из частей `text` потока
  JSON-событий (`--format json`), как `--json` у Codex.
- **Порядок по умолчанию** — `codex,openrouter,claude,cursor,opencode`.

`allow_edits=True` (для эксперимент-агента, который пишет файл отчёта)
у Claude Code включает `--permission-mode acceptEdits` и набор
инструментов из `KOI_CLAUDE_ALLOWED_TOOLS`; Cursor SDK и так работает
в режиме локального агента с правом на правки.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from koi.adapters.agent_process import run_json
from koi.adapters.workspace import get_workspace


def _resolve_cwd(cwd: Path | str | None) -> Path | str:
    if cwd is None:
        return get_workspace().agent_cwd()
    return cwd

DEFAULT_TIMEOUT_S = 1800
DEFAULT_CLAUDE_TOOLS = "Read,Glob,Grep,Bash,Write,Edit"
DEFAULT_OPENROUTER_MODEL = "openai/gpt-5.4"
DEFAULT_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OPENCODE_READONLY_AGENT = "plan"


class AgentBackendError(RuntimeError):
    """A backend reported a user-facing failure rather than an answer."""


def _codex_bin() -> str | None:
    configured = os.environ.get("KOI_CODEX_BIN", "codex")
    found = shutil.which(configured)
    if found:
        return found
    if configured != "codex":
        return None
    # Finder starts the packaged app without the user's shell PATH. Codex may
    # still be installed with ChatGPT or in the user's local bin directory.
    candidates = (
        Path.home() / ".local" / "bin" / "codex",
        Path("/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex"),
        Path.home() / "Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex",
    )
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _codex_ready() -> bool:
    return _codex_bin() is not None


def _openrouter_api_key() -> str:
    return os.environ.get("OPENAI_API_KEY", "").strip()


def _openrouter_ready() -> bool:
    return bool(_openrouter_api_key())


def _claude_bin() -> str | None:
    return shutil.which(os.environ.get("KOI_CLAUDE_BIN", "claude"))


def _claude_ready() -> bool:
    return _claude_bin() is not None


def _cursor_cli_ready() -> bool:
    from koi.literature.cursor_agent_terminal import find_agent_bin

    return find_agent_bin() is not None


def _cursor_available() -> bool:
    """Cursor запускается и через SDK, и через CLI: годится любой из путей."""
    return _cursor_sdk_ready() or _cursor_cli_ready()


def _opencode_bin() -> str | None:
    return shutil.which(os.environ.get("KOI_OPENCODE_BIN", "opencode"))


def _opencode_ready() -> bool:
    return _opencode_bin() is not None


def _cursor_sdk_ready() -> bool:
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
    externally_sandboxed: bool = False,
    on_event=None,
    is_cancelled=None,
    on_started=None,
    mcp_args=(),
    mcp_env=None,
) -> str | None:
    """Non-interactive вызов локального Codex CLI; возвращает финальный текст или None."""
    cwd = _resolve_cwd(cwd)
    bin_path = _codex_bin()
    if not bin_path:
        return None

    # The paper worker already has OS protection; macOS forbids nested Seatbelt.
    sandbox_mode = "danger-full-access" if externally_sandboxed else ("workspace-write" if allow_edits else "read-only")
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
    # Research tasks need APIs and local preview servers inside the workspace.
    extra = ["-c", "sandbox_workspace_write.network_access=true"] if allow_edits and not externally_sandboxed else []
    if allow_edits and not externally_sandboxed:
        # Desktop state lives outside the code workspace. SQLite also needs
        # permission to create its journal beside the registry.
        run_dir = get_workspace().run_dir
        run_dir.mkdir(parents=True, exist_ok=True)
        extra += ["--add-dir", str(run_dir.resolve())]
    extra += os.environ.get("KOI_CODEX_ARGS", "").split()
    extra += list(mcp_args)
    if extra:
        cmd[2:2] = extra
    try:
        if on_event is not None:
            cmd.insert(2, "--json")
            returncode = run_json(cmd, prompt, cwd=cwd, timeout=timeout,
                                  on_event=on_event, is_cancelled=is_cancelled, on_started=on_started, env=mcp_env)
            stdout = ""
        else:
            proc = subprocess.run(cmd, input=prompt, capture_output=True,
                                  text=True, cwd=str(cwd), timeout=timeout, env=mcp_env)
            stdout, returncode = proc.stdout, proc.returncode
        if output_path.exists():
            text = output_path.read_text(encoding="utf-8").strip()
            if text:
                return text
        if returncode == 0:
            text = (stdout or "").strip()
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
    cwd: Path | str | None = None,
    timeout: int = DEFAULT_TIMEOUT_S,
    allow_edits: bool = False,
) -> str | None:
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
    on_event=None,
    is_cancelled=None,
    on_started=None,
    mcp_args=(),
    mcp_env=None,
) -> str | None:
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
        if mcp_args:
            tools = ','.join(filter(None, [tools, 'mcp__researcheros__spawn_agents,mcp__researcheros__list_agents']))
        if tools.strip():
            cmd += ["--allowed-tools", tools]
    elif mcp_args:
        cmd += ['--permission-mode', 'plan', '--allowed-tools',
                'Read,Glob,Grep,mcp__researcheros__spawn_agents,mcp__researcheros__list_agents']
    extra = os.environ.get("KOI_CLAUDE_ARGS", "").split()
    cmd += extra
    cmd += list(mcp_args)
    try:
        if on_event is not None:
            cmd[cmd.index("--output-format") + 1] = "stream-json"
            cmd.append("--verbose")
            answer = ""
            failed = False
            def receive(event):
                nonlocal answer, failed
                on_event(event)
                if event.get("type") == "result":
                    answer = str(event.get("result") or "").strip()
                    failed = bool(event.get("is_error"))
            code = run_json(cmd, prompt, cwd=cwd, timeout=timeout,
                            on_event=receive, is_cancelled=is_cancelled, on_started=on_started, env=mcp_env)
            return answer if code == 0 and not failed and answer else None
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=timeout,
            env=mcp_env,
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
    timeout: int = DEFAULT_TIMEOUT_S,
    allow_edits: bool = False,
    mcp_args=(),
    mcp_env=None,
    on_event=None,
    is_cancelled=None,
    on_started=None,
) -> str | None:
    """Вызов Cursor SDK; возвращает финальный текст или None."""
    cwd = _resolve_cwd(cwd)
    if mcp_args:
        from koi.agent_chat.runner import _cursor_print_command, find_agent_bin
        binary = find_agent_bin()
        if not binary:
            return None
        answer = ''
        def receive(event):
            nonlocal answer
            if on_event:
                on_event(event)
            if event.get('type') == 'result':
                answer = str(event.get('result') or '').strip()
        command = _cursor_print_command(binary, mode=None if allow_edits else 'ask', force=allow_edits)
        command += list(mcp_args)
        code = run_json(command, prompt, cwd=cwd, timeout=timeout, on_event=receive,
                        is_cancelled=is_cancelled, on_started=on_started, env=mcp_env)
        return answer if code == 0 and answer else None
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


def run_opencode(
    prompt: str,
    *,
    cwd: Path | str | None = None,
    timeout: int = DEFAULT_TIMEOUT_S,
    allow_edits: bool = False,
    on_event=None,
    is_cancelled=None,
    on_started=None,
    mcp_args=(),
    mcp_env=None,
) -> str | None:
    """Non-interactive вызов установленного OpenCode CLI; возвращает финальный текст или None."""
    cwd = _resolve_cwd(cwd)
    bin_path = _opencode_bin()
    if not bin_path:
        return None
    cmd = [bin_path, "--standalone", "run"]
    model = os.environ.get("KOI_OPENCODE_MODEL", "").strip()
    if model:
        cmd += ["--model", model]
    cmd += ["--auto"] if allow_edits else ["--agent", DEFAULT_OPENCODE_READONLY_AGENT]
    cmd += os.environ.get("KOI_OPENCODE_ARGS", "").split()
    cmd += list(mcp_args)
    try:
        if on_event is not None:
            cmd += ["--format", "json"]
            answer = ""
            error_message = ""

            def receive(event):
                nonlocal answer, error_message
                on_event(event)
                if event.get("type") == "error" and isinstance(event.get("error"), dict):
                    error_message = str(event["error"].get("message") or "Ошибка провайдера")
                part = event.get("part")
                if event.get("type") == "text" and isinstance(part, dict):
                    answer += str(part.get("text") or "")

            code = run_json(cmd + [prompt], "", cwd=cwd, timeout=timeout, on_event=receive,
                            is_cancelled=is_cancelled, on_started=on_started, feed_stdin=False, env=mcp_env)
            if error_message:
                raise AgentBackendError("OpenCode: " + error_message)
            text = answer.strip()
            return text if code == 0 and text else None
        proc = subprocess.run(cmd + [prompt], capture_output=True, text=True,
                              cwd=str(cwd), timeout=timeout, env=mcp_env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    text = (proc.stdout or "").strip()
    return text or None


# Единственный перечень бэкендов: порядок, подпись, поток событий, запуск, проверка.
# Добавить агента = добавить строку здесь плюс блок в backend_status().
_BACKENDS: tuple[tuple[str, str | None, bool, Callable[..., str | None], str], ...] = (
    ("codex", "Codex", True, run_codex_exec, "_codex_ready"),
    ("openrouter", None, False, run_openrouter, "_openrouter_ready"),
    ("claude", "Claude", True, run_claude_code, "_claude_ready"),
    ("cursor", "Cursor", False, run_cursor_sdk, "_cursor_available"),
    ("opencode", "OpenCode", True, run_opencode, "_opencode_ready"),
)
DEFAULT_BACKEND_ORDER = ",".join(name for name, *_ in _BACKENDS)
CLI_AGENTS: tuple[tuple[str, str], ...] = tuple((name, label) for name, label, *_ in _BACKENDS if label)
STREAMING_BACKENDS = tuple(name for name, _, streams, *_ in _BACKENDS if streams)
_RUNNERS: dict[str, Callable[..., str | None]] = {name: runner for name, _, _, runner, _ in _BACKENDS}


def _ready(name: str) -> bool:
    """Доступность бэкенда на этой машине; проверку ищем в модуле, чтобы её можно было подменить."""
    for backend, _, _, _, probe in _BACKENDS:
        if backend == name:
            return bool(globals()[probe]())
    return False


def known_backend(name: str) -> bool:
    """Может ли этот бэкенд запускать задачи агента."""
    return name in _RUNNERS


def editable_backend(name: str) -> bool:
    """Может ли бэкенд править файлы проекта: текстовая модель — нет."""
    return name in _RUNNERS and name != "openrouter"


def editable_backends() -> list[str]:
    """Бэкенды, которыми можно править проект, в порядке приоритета."""
    return [name for name in DEFAULT_BACKEND_ORDER.split(",") if editable_backend(name)]


def backend_order() -> list[str]:
    raw = os.environ.get("KOI_AGENT_BACKEND", DEFAULT_BACKEND_ORDER)
    if raw.strip().lower() in ("off", "none", "0"):
        return []
    if raw.strip().lower() == "auto":
        raw = DEFAULT_BACKEND_ORDER
    return [b.strip().lower() for b in raw.split(",") if b.strip() in _RUNNERS]


def cli_agents() -> list[dict]:
    """Какие CLI реально есть на этой машине."""
    return [
        {"id": name, "label": label, "available": _ready(name)}
        for name, label in CLI_AGENTS
    ]


def acp_agents() -> list[dict]:
    """Агенты по протоколу ACP: видны только когда есть SDK и их программа."""
    if importlib.util.find_spec("acp") is None:
        return []
    try:
        from koi.adapters.acp_agents import agents as discovered
    except ImportError:
        return []
    return [
        {"id": row["id"], "label": row["label"], "available": bool(row["available"])}
        for row in discovered()
    ]


def backend_status() -> dict:
    """Что доступно на этой машине — для диагностики и эндпоинта."""
    return {
        "order": backend_order(),
        "cli": cli_agents(),
        "codex": {
            "available": _ready("codex"),
            "bin": _codex_bin(),
            "model": os.environ.get("KOI_CODEX_MODEL") or None,
        },
        "openrouter": {
            "available": _ready("openrouter"),
            "model": os.environ.get("KOI_OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL),
            "api_key_present": bool(_openrouter_api_key()),
        },
        "claude": {
            "available": _ready("claude"),
            "bin": _claude_bin(),
            "model": os.environ.get("KOI_CLAUDE_MODEL") or None,
        },
        "cursor": {
            "available": _ready("cursor"),
            "model": os.environ.get("KOI_AGENT_CHAT_MODEL", "composer-2.5"),
        },
        "opencode": {
            "available": _ready("opencode"),
            "bin": _opencode_bin(),
            "model": os.environ.get("KOI_OPENCODE_MODEL") or None,
        },
    }


def any_agent_available() -> bool:
    return any(_ready(name) for name, *_ in _BACKENDS)


def run_agent(
    prompt: str,
    *,
    cwd: Path | str | None = None,
    timeout: int = DEFAULT_TIMEOUT_S,
    allow_edits: bool = False,
    backend: str | None = None,
    externally_sandboxed: bool = False,
    on_event=None,
    is_cancelled=None,
    on_started=None,
    delegation=None,
) -> tuple[str | None, str | None]:
    """Запустить агента первым доступным бэкендом.

    Возвращает (текст_ответа, имя_бэкенда) либо (None, None), если ни один
    бэкенд не доступен или все вернули пустой результат.
    """
    cwd = _resolve_cwd(cwd)
    order = [backend] if backend else backend_order()
    for name in order:
        if is_cancelled and is_cancelled():
            from koi.adapters.agent_process import AgentCancelled
            raise AgentCancelled
        if allow_edits and name == "openrouter":
            continue  # Text-only backend cannot carry out project changes.
        runner = _RUNNERS.get(name)
        if runner is None:
            continue
        extra: dict[str, object] = {"externally_sandboxed": True} if name == "codex" and externally_sandboxed else {}
        if name in STREAMING_BACKENDS or (name == 'cursor' and delegation):
            if on_started is not None:
                extra["on_started"] = on_started
            if on_event is not None:
                extra["on_event"] = on_event
            if is_cancelled is not None:
                extra["is_cancelled"] = is_cancelled
        from koi.agent_chat.research_mcp import configuration
        with configuration(name, delegation) as (mcp_args, mcp_env):
            if delegation and name != 'openrouter':
                extra.update(mcp_args=mcp_args, mcp_env={**os.environ, **mcp_env} if mcp_env else None)
            text = runner(prompt, cwd=cwd, timeout=timeout, allow_edits=allow_edits, **extra)
        if text:
            return text, name
    return None, None
