from concurrent.futures import ThreadPoolExecutor

import pytest

from koi.agent_chat import research
from koi.adapters import agent_chat_activity


def test_parallel_participants_survive_reload_and_keep_chat_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(research, "PATH", tmp_path / "runs.sqlite3")
    monkeypatch.setattr(agent_chat_activity, "ACTIVITY_DIR", tmp_path / "activity")
    run = research.create_run("chat-a", "aq-123", "project", "Develop a method")

    def execute(i):
        agent = research.register(run, f"Executor {i}", "Evaluate hypothesis", "codex")
        research.update(agent, "running", "Started")
        research.update(agent, "completed", "Evaluated", result="Negative result")
        return agent

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(execute, range(8)))
    assert len(research.participants("chat-a")) == 8
    assert research.participants("chat-b") == []
    for agent in ids:
        assert [e["message"] for e in research.events("chat-a", agent)] == ["Started", "Evaluated"]
        with pytest.raises(KeyError):
            research.events("chat-b", agent)
        with pytest.raises(ValueError, match="finished"):
            research.update(agent, "running", "Restart")
    assert len(agent_chat_activity.read("aq-123")) == 16


def test_invalid_state_does_not_change_participant(tmp_path, monkeypatch):
    monkeypatch.setattr(research, "PATH", tmp_path / "runs.sqlite3")
    run = research.create_run("chat-a", "aq-123", "project", "Goal")
    agent = research.register(run, "Coordinator", "Plan", "codex")
    with pytest.raises(ValueError):
        research.update(agent, "invented", "Bad state")
    assert research.participants("chat-a")[0]["status"] == "pending"


def test_missing_process_is_unknown_not_completed(tmp_path, monkeypatch):
    monkeypatch.setattr(research, "PATH", tmp_path / "runs.sqlite3")
    monkeypatch.setattr(agent_chat_activity, "ACTIVITY_DIR", tmp_path / "activity")
    run = research.create_run("chat-a", "aq-123", "project", "Goal")
    agent = research.register(run, "Executor", "Evaluate", "codex")
    research.attach_handle(agent)
    research.update(agent, "running", "Started")
    assert research.owns_live_turn("aq-123")
    monkeypatch.setattr(research, "_process_start", lambda pid: "")
    assert not research.owns_live_turn("aq-123")
    assert research.participants("chat-a")[0]["status"] == "unknown"
    assert research.participants("chat-a")[0]["result"] == ""


def test_explicit_resume_preserves_run_budget_and_results(tmp_path, monkeypatch):
    from koi.agent_chat import research_tools
    monkeypatch.setattr(research, "PATH", tmp_path / "runs.sqlite3")
    monkeypatch.setattr(agent_chat_activity, "ACTIVITY_DIR", tmp_path / "activity")
    item = {'id':'aq-111', 'conversation_id':'chat-a', 'project_id':'demo', 'question':'/koi-arbor-autoresearch Develop method', 'research_scope':'tree'}
    context = {'project_id':'demo'}
    research.coordinator_prompt(item, context)
    original = research.participants('chat-a')[0]
    run_id = original['run_id']
    research_tools.perform(run_id, 'contract', {'max_seconds':60, 'max_executors':2, 'stop_condition':'Compare'})
    research.reserve_executors(run_id, 1, 10)
    research.finish_coordinator(item['id'], 'completed', 'Turn finished')
    resumed = {**item, 'id':'aq-222', 'question':f'/koi-arbor-autoresearch resume {run_id}'}
    prompt = research.coordinator_prompt(resumed, context)
    agents = research.participants('chat-a')
    assert len(agents) == 2
    assert {a['run_id'] for a in agents} == {run_id}
    assert 'Develop method' in prompt
    assert '"launched": 1' in prompt
    assert '"max_executors": 2' in prompt
    with pytest.raises(ValueError, match='ещё работает'):
        research.coordinator_prompt({**resumed, 'id':'aq-333'}, context)
    with pytest.raises(ValueError, match='не найдено'):
        research.coordinator_prompt({**resumed, 'conversation_id':'chat-b'}, context)


def test_only_new_slash_command_routes_to_arbor(monkeypatch):
    from koi.agent_chat import runner
    context = {'project_id':'demo', 'purpose':'agent', 'user_question':'/koi-arbor-autoresearch Develop method'}
    monkeypatch.setattr(runner, 'build_context', lambda item_id: context)
    monkeypatch.setattr(runner, 'find_item', lambda item_id: {'id':item_id})
    monkeypatch.setattr(research, 'coordinator_prompt', lambda item, ctx: 'NEW ARBOR ENTRYPOINT')
    assert runner._base_sdk_prompt('aq-123') == 'NEW ARBOR ENTRYPOINT'
    for command in ('/autoresearch', '/koi-card-autoresearch', '/koi-autoresearch'):
        context['user_question'] = command + ' Original workflow'
        assert runner._base_sdk_prompt('aq-123') != 'NEW ARBOR ENTRYPOINT'


def test_budget_reply_resumes_run_with_host_launcher(tmp_path, monkeypatch):
    from koi.agent_chat import runner, research_runtime, research_tools
    monkeypatch.setattr(research, 'PATH', tmp_path/'runs.sqlite3')
    monkeypatch.setattr(agent_chat_activity, 'ACTIVITY_DIR', tmp_path/'activity')
    initial = {'id':'aq-first', 'conversation_id':'chat-intake','project_id':'demo',
               'question':'/koi-arbor-autoresearch Develop method', 'research_scope':'tree'}
    research.coordinator_prompt(initial, {'project_id':'demo'})
    run = research.participants('chat-intake')[0]['run_id']
    research.finish_coordinator('aq-first','completed','Waiting for budget')
    reply = {**initial, 'id':'aq-budget', 'question':'45 минут и 3 исполнителя'}
    monkeypatch.setattr(runner,'find_item',lambda _:reply)
    monkeypatch.setattr(runner,'build_context',lambda _: {'project_id':'demo','user_question':reply['question']})
    prompt = runner._base_sdk_prompt(reply['id'])
    assert run in prompt
    with research_runtime.broker(reply['id']):
        with research._db() as db:
            assert db.execute('SELECT run_id FROM brokers WHERE run_id=?',(run,)).fetchone()
    research_tools.perform(run, 'contract', {'max_seconds':2700,'max_parallel':3,
        'max_executors':1000,'stop_condition':'Goal or deadline'})
    assert research.continuation_run({**reply,'question':'Какой статус?'}) is None
    assert research.continuation_run({**reply,'question':'Продолжи исследование'}) == run
