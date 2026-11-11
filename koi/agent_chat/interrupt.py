"""Finalize open chat turns when ResearchOS stops or a runner is already gone."""
from __future__ import annotations

WARNING = (
    "Запуск прерван перезапуском приложения. Продолжите работу новым сообщением."
)


def turn_alive(item) -> bool:
    """True while a local runner, research handle, or ACP session still owns the turn."""
    from koi.adapters.agent_chat_queue import agent_active
    from koi.agent_chat import research

    if agent_active(item):
        return True
    if research.owns_live_turn(item["id"]):
        return True
    cid = item.get("conversation_id")
    if not cid:
        return False
    from koi.agent_chat import acp_client

    return acp_client.snapshot(cid) is not None


def live_for(item):
    """Progress payload for UI: pending always, processing only while an owner is alive."""
    from koi.agent_chat import live

    if item["status"] == "answered":
        return None
    if item["status"] == "processing" and not turn_alive(item):
        return None
    return live.snapshot(item)


def _cancel_owners(item) -> None:
    from koi.agent_chat import live

    live.request_cancel(item["id"])
    cid = item.get("conversation_id")
    if not cid:
        return
    from koi.agent_chat import acp_client, research

    try:
        acp_client.cancel(cid)
    except Exception:
        pass
    try:
        research.request_cancel(cid)
    except Exception:
        pass


def reclaim_dead_turns(*, conversation_id: str | None = None) -> int:
    """Answer processing turns whose owner process is already gone."""
    from koi.adapters.agent_chat_queue import _load, submit_answer
    from koi.agent_chat import live

    count = 0
    for item in _load():
        if item.get("status") != "processing":
            continue
        if conversation_id is not None and item.get("conversation_id") != conversation_id:
            continue
        if turn_alive(item):
            continue
        text = (live.text(item["id"]) + "\n\n" + WARNING).strip()
        submit_answer(item["id"], text, answer_kind="warning")
        count += 1
    return count


def interrupt_open_turns() -> int:
    """Cancel owners and answer every pending/processing turn (startup/shutdown)."""
    from koi.adapters.agent_chat_queue import _load, submit_answer
    from koi.agent_chat import live

    count = 0
    for item in list(_load()):
        if item.get("status") not in ("pending", "processing"):
            continue
        _cancel_owners(item)
        text = (live.text(item["id"]) + "\n\n" + WARNING).strip()
        submit_answer(item["id"], text, answer_kind="warning")
        count += 1
    return count
