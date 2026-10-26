"""ACP v1 subprocess client using the official SDK; one loaded session per turn."""
from __future__ import annotations

import asyncio
import threading
from contextlib import suppress
from uuid import uuid4

from acp import Client, RequestError, connect_to_agent
from acp.schema import ClientCapabilities, Implementation, TextContentBlock, RequestPermissionResponse
from koi.agent_chat import conversations
from koi.agent_chat.activity import record

ACTIVE = {}
LOCK = threading.RLock()


from koi.adapters.acp_agents import agents


def snapshot(cid):
    with LOCK:
        state = ACTIVE.get(cid)
        if not state:
            return None
        return {"item_id": state["item_id"], "text": state["text"],
                "permission": state.get("permission"), "cancelled": state.get("cancelled", False)}


def decide(cid, permission_id, option_id):
    with LOCK:
        state = ACTIVE.get(cid)
        permission = state.get("permission") if state else None
        if not permission or permission["id"] != permission_id:
            raise ValueError("Запрос разрешения уже закрыт")
        if option_id not in {o["optionId"] for o in permission["options"]}:
            raise ValueError("Неизвестный вариант разрешения")
        future = state["permission_future"]
        state["permission"] = None
        def resolve():
            if not future.done():
                future.set_result({"outcome": "selected", "optionId": option_id})
        state["loop"].call_soon_threadsafe(resolve)


def cancel(cid):
    with LOCK:
        state = ACTIVE.get(cid)
        if not state:
            return False
        state["cancelled"] = True
        def stop():
            future = state.get("permission_future")
            if future and not future.done():
                future.set_result({"outcome": "cancelled"})
            state["permission"] = None
            if state.get("session_id"):
                asyncio.create_task(state["conn"].cancel(session_id=state["session_id"]))
            # A non-cooperative agent must not leave a conversation blocked forever.
            state["loop"].call_later(3, state["task"].cancel)
        state["loop"].call_soon_threadsafe(stop)
        return True


class UIClient(Client):
    def __init__(self, state):
        self.state = state
        self.replaying = False

    async def session_update(self, session_id, update, **kwargs):
        if self.replaying:
            return
        event = update.model_dump(by_alias=True, exclude_none=True)
        kind = event.get("sessionUpdate")
        if kind == "agent_message_chunk":
            content = event.get("content", {})
            if content.get("type") == "text":
                with LOCK:
                    self.state["text"] += content.get("text", "")
        elif kind in ("tool_call", "tool_call_update"):
            record(self.state["item_id"], event.get("title") or "Инструмент: " + event.get("status", "в работе"))
        elif kind == "plan":
            record(self.state["item_id"], "План: " + "; ".join(e["content"] for e in event.get("entries", [])))

    async def request_permission(self, session_id, tool_call, options, **kwargs):
        state = self.state
        if state.get("cancelled"):
            return RequestPermissionResponse(outcome={"outcome": "cancelled"})
        future = asyncio.get_running_loop().create_future()
        with LOCK:
            state["permission_future"] = future
            state["permission"] = {"id": uuid4().hex,
                "title": tool_call.title or "Агент запрашивает разрешение",
                "tool_call": tool_call.model_dump(by_alias=True, exclude_none=True),
                "options": [o.model_dump(by_alias=True) for o in options]}
        record(state["item_id"], "Агент ожидает вашего разрешения.")
        try:
            return RequestPermissionResponse(outcome=await future)
        finally:
            with LOCK:
                state["permission"] = None

    async def ext_method(self, method, params):
        raise RequestError.method_not_found(method)

    async def ext_notification(self, method, params):
        return None


async def _run(cid, item_id, prompt, cwd, backend, timeout):
    command = next((r["command"] for r in agents() if r["id"] == backend and r["available"]), None)
    if not command:
        raise ValueError("ACP-агент не установлен или не настроен")
    state = {"loop": asyncio.get_running_loop(), "task": asyncio.current_task(),
             "item_id": item_id, "text": "", "permission": None}
    with LOCK:
        if cid in ACTIVE:
            raise ValueError("Дождитесь ответа в этом чате")
        ACTIVE[cid] = state
    proc = None
    conn = None
    try:
        async with asyncio.timeout(timeout):
            proc = await asyncio.create_subprocess_exec(*command, cwd=str(cwd),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, limit=4 * 1024 * 1024)
            client = UIClient(state)
            conn = connect_to_agent(client, proc.stdin, proc.stdout)
            state["conn"] = conn
            init = await conn.initialize(protocol_version=1, client_capabilities=ClientCapabilities(),
                client_info=Implementation(name="researcheros", version="0.1.0"))
            if init.protocol_version != 1:
                raise ValueError("Агент не поддерживает ACP v1")
            row = conversations.find(cid)
            sid = row.get("acp_session_id") if row and row.get("acp_backend") == backend else None
            if sid and init.agent_capabilities.load_session:
                client.replaying = True
                try:
                    await conn.load_session(cwd=str(cwd), session_id=sid, mcp_servers=[])
                except RequestError:
                    sid = None
                    record(item_id, "Сессия агента недоступна; восстановлю контекст из истории чата.")
                finally:
                    client.replaying = False
            else:
                sid = None
            if not sid:
                session = await conn.new_session(cwd=str(cwd), mcp_servers=[])
                sid = session.session_id
            state["session_id"] = sid
            conversations.update(cid, acp_session_id=sid, acp_backend=backend)
            if state.get("cancelled"):
                return state["text"] or "Остановлено пользователем."
            record(item_id, "ACP-сессия подключена.")
            result = await conn.prompt(session_id=sid, prompt=[TextContentBlock(type="text", text=prompt)])
            if result.stop_reason == "cancelled":
                return state["text"] + "\n\nОстановлено пользователем."
            return state["text"] or "Агент завершил работу без текстового ответа."
    except asyncio.CancelledError:
        return state["text"] + "\n\nОстановлено пользователем."
    finally:
        with LOCK:
            ACTIVE.pop(cid, None)
        if conn:
            with suppress(Exception):
                await conn.close()
        if proc:
            if proc.returncode is None:
                with suppress(ProcessLookupError):
                    proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), 3)
                except asyncio.TimeoutError:
                    with suppress(ProcessLookupError):
                        proc.kill()
                    await proc.wait()


def run(cid, item_id, prompt, cwd, backend, timeout=1800):
    return asyncio.run(_run(cid, item_id, prompt, cwd, backend, timeout))
