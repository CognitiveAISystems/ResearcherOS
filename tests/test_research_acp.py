"""Actual ACP stdio sessions for child agents, without a model service."""
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest
pytest.importorskip("acp", reason="ACP SDK не входит в зависимости: нужен agent-client-protocol")
from koi.agent_chat import acp_client
from test_chat_conversations import FAKE_AGENT


@pytest.fixture
def transport(tmp_path, monkeypatch):
    script = tmp_path / 'agent.py'
    script.write_text(FAKE_AGENT)
    monkeypatch.setattr(acp_client, 'agents', lambda: [{'id':'acp:test', 'available':True, 'command':[sys.executable,str(script)]}])
    def no_sidebar_write(*args, **kwargs):
        raise AssertionError('Child agent must not create or change a sidebar conversation')
    monkeypatch.setattr(acp_client.conversations, 'update', no_sidebar_write)
    return tmp_path


def test_parallel_transient_sessions_have_independent_events(transport):
    events = [[], []]
    def execute(i):
        return acp_client.run_executor(f'agent-{i}', 'aq-123', 'hello', transport, 'acp:test', events[i].append, 5)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(execute, range(2)))
    assert results == ['Поток ответа', 'Поток ответа']
    assert events == [['Поток ', 'ответа'], ['Поток ', 'ответа']]
    assert not acp_client.ACTIVE


def test_child_permission_is_not_silently_approved(transport):
    events=[]
    result = acp_client.run_executor('agent-one', 'aq-123', 'permission', transport, 'acp:test', events.append, 5)
    assert 'cancelled' in result
    assert any('Требуется разрешение' in event for event in events)


def test_parent_session_stream_and_permission_use_existing_chat_api(transport, monkeypatch):
    import time
    from api.routers import agents
    from api.schemas import PermissionBody
    monkeypatch.setattr(acp_client.conversations, 'find', lambda cid: {'id':cid})
    monkeypatch.setattr(acp_client.conversations, 'update', lambda *args, **kwargs: None)
    monkeypatch.setattr(agents, '_conversation', lambda cid: {'id':cid})
    monkeypatch.setattr(agents.conversations, 'messages', lambda cid: [])
    monkeypatch.setattr(acp_client, 'record', lambda *args: None)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(acp_client.run, 'chat-parent', 'aq-123', 'permission', transport, 'acp:test', 5)
        deadline = time.monotonic()+4
        state = None
        while time.monotonic()<deadline:
            state = acp_client.snapshot('chat-parent')
            if state and state.get('permission'):
                break
            time.sleep(.01)
        assert state and state.get('permission')
        visible = agents.get_conversation('chat-parent')
        assert visible['live']['text'] == 'Поток '
        assert visible['live']['permission']['title'] == 'Записать файл'
        agents.decide_permission('chat-parent', PermissionBody(permission_id=state['permission']['id'], option_id='allow'))
        assert future.result(timeout=5) == 'Поток allow'
    assert acp_client.snapshot('chat-parent') is None
