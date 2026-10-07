"""Local settings persisted in KOI/.env (gitignored)."""

from __future__ import annotations

import os
import re
from pathlib import Path

from koi.adapters.workspace import get_workspace

_ws = get_workspace()
ENV_PATH = _ws.env_file
ENV_KEY = "CURSOR_API_KEY"
MODE_KEY = "KOI_AGENT_CHAT_MODE"
AGENT_CHAT_MODE_API = "api"
AGENT_CHAT_MODE_CURSOR_IDE = "cursor_ide"
AGENT_CHAT_MODE_CURSOR_INBOX = "cursor_inbox"
AGENT_CHAT_MODE_LOCAL = "local"
AGENT_CHAT_MODES = frozenset(
    {AGENT_CHAT_MODE_API, AGENT_CHAT_MODE_CURSOR_IDE, AGENT_CHAT_MODE_CURSOR_INBOX, AGENT_CHAT_MODE_LOCAL}
)
CURSOR_API_KEY_URL = "https://cursor.com/dashboard/integrations"


def load_env_file() -> None:
    """Load KOI/.env into os.environ (does not override existing vars)."""
    if not ENV_PATH.exists():
        return
    try:
        text = ENV_PATH.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].strip()
        if "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip()
        if value and value[0] in "\"'" and value[-1] == value[0]:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def get_cursor_api_key() -> str:
    return os.environ.get(ENV_KEY, "").strip()


def has_cursor_api_key() -> bool:
    return bool(get_cursor_api_key())


def mask_cursor_api_key() -> str | None:
    key = get_cursor_api_key()
    if not key:
        return None
    if len(key) <= 8:
        return "••••"
    return f"{key[:4]}…{key[-4:]}"


def _read_env_lines() -> list[str]:
    if not ENV_PATH.exists():
        return []
    try:
        return ENV_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def get_agent_chat_mode() -> str:
    """api | cursor_ide (hooks) | cursor_inbox (file watcher + dedicated chat)."""
    load_env_file()
    raw = os.environ.get(MODE_KEY, "").strip().lower()
    if raw in AGENT_CHAT_MODES:
        return raw
    if has_cursor_api_key():
        return AGENT_CHAT_MODE_API
    return AGENT_CHAT_MODE_LOCAL


def is_api_agent_mode() -> bool:
    return get_agent_chat_mode() == AGENT_CHAT_MODE_API


def is_cursor_ide_agent_mode() -> bool:
    return get_agent_chat_mode() == AGENT_CHAT_MODE_CURSOR_IDE


def is_cursor_inbox_agent_mode() -> bool:
    return get_agent_chat_mode() == AGENT_CHAT_MODE_CURSOR_INBOX


def is_cursor_manual_agent_mode() -> bool:
    """IDE hooks or Inbox watcher — no background API worker."""
    return get_agent_chat_mode() in (
        AGENT_CHAT_MODE_CURSOR_IDE,
        AGENT_CHAT_MODE_CURSOR_INBOX,
    )


def set_agent_chat_mode(mode: str) -> None:
    mode = mode.strip().lower()
    if mode not in AGENT_CHAT_MODES:
        raise ValueError(f"agent_chat_mode must be one of: {', '.join(sorted(AGENT_CHAT_MODES))}")
    _write_env_var(MODE_KEY, mode)
    os.environ[MODE_KEY] = mode


def _write_env_var(key: str, value: str | None) -> None:
    """Write or remove one KEY=value line in KOI/.env."""
    value = (value or "").strip()
    lines: list[str] = []
    found = False
    for line in _read_env_lines():
        if re.match(rf"^\s*(?:export\s+)?{re.escape(key)}\s*=", line):
            found = True
            if value:
                lines.append(f"{key}={value}")
            continue
        lines.append(line)
    if value and not found:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"{key}={value}")
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    if lines:
        ENV_PATH.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        ENV_PATH.chmod(0o600)
    elif ENV_PATH.exists():
        ENV_PATH.unlink()
    if value:
        os.environ[key] = value
    else:
        os.environ.pop(key, None)


def set_cursor_api_key(value: str | None) -> None:
    """Write or remove CURSOR_API_KEY in KOI/.env and update os.environ."""
    _write_env_var(ENV_KEY, (value or "").strip() or None)
