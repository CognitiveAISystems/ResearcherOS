"""Agent-chat settings read model composed from persistence and inbox state."""

from __future__ import annotations

from koi.adapters.settings_store import (
    AGENT_CHAT_MODE_API,
    AGENT_CHAT_MODE_CURSOR_IDE,
    AGENT_CHAT_MODE_CURSOR_INBOX,
    AGENT_CHAT_MODE_LOCAL,
    CURSOR_API_KEY_URL,
    get_agent_chat_mode,
    has_cursor_api_key,
    mask_cursor_api_key,
)
from koi.agent_chat.inbox import inbox_settings


def settings_snapshot() -> dict:
    """Return the settings payload exposed by the agent-chat API."""
    mode = get_agent_chat_mode()
    snapshot = {
        "agent_chat_mode": mode,
        "agent_chat_mode_labels": {
            AGENT_CHAT_MODE_API: "Фоновый агент (Cursor API)",
            AGENT_CHAT_MODE_CURSOR_IDE: "Агент в Cursor (hooks)",
            AGENT_CHAT_MODE_CURSOR_INBOX: "Inbox-чат",
            AGENT_CHAT_MODE_LOCAL: "Локальный агент",
        },
        "cursor_api_key_configured": has_cursor_api_key(),
        "cursor_api_key_masked": mask_cursor_api_key(),
        "cursor_api_key_url": CURSOR_API_KEY_URL,
    }
    snapshot.update(inbox_settings())
    return snapshot
