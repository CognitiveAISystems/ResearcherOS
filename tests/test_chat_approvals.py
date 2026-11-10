import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from koi.agent_chat import approvals, research, research_mcp
from koi.adapters import agent_chat_activity


@pytest.mark.parametrize('decision', ['approve', 'reject', 'cancel'])
def test_consent_blocks_until_user_decision(tmp_path, monkeypatch, decision):
    monkeypatch.setattr(research, 'PATH', tmp_path / 'runs.sqlite3')
    monkeypatch.setattr(agent_chat_activity, 'ACTIVITY_DIR', tmp_path / 'activity')
    run = research.create_run('chat-a', 'aq-123', 'demo', 'Goal')
    agent = research.register(run, 'Coordinator', 'Task', 'codex')
    research.update(agent, 'running', 'Started')
    cancelled = False
    monkeypatch.setattr(research, 'participant_cancelled', lambda *_: cancelled)
    with ThreadPoolExecutor() as pool:
        result = pool.submit(research_mcp.call, run, agent, 'request_approval',
                             {'title': 'Сохранить правки?', 'details': 'Две конкретные правки'})
        try:
            deadline = time.monotonic() + 3
            while not (pending := approvals.snapshot('chat-a')):
                assert time.monotonic() < deadline
                time.sleep(0.01)
            assert not result.done()
            assert approvals.snapshot('other-chat') is None
            permission = pending['permission']
            assert not approvals.decide('other-chat', permission['id'], 'approve')
            with pytest.raises(ValueError):
                approvals.decide('chat-a', permission['id'], 'unknown')
            if decision == 'cancel':
                cancelled = True
            else:
                assert approvals.decide('chat-a', permission['id'], decision)
            assert result.result(timeout=3)['approved'] is (decision == 'approve')
            assert approvals.snapshot('chat-a') is None
            assert not approvals.decide('chat-a', permission['id'], 'approve')
        finally:
            cancelled = True
