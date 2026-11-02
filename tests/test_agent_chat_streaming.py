"""Real subprocesses verify CLI progress, cancellation and child cleanup offline."""
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from koi.adapters import agent_backends as backends, agent_chat_activity as activity, agent_chat_queue as queue
from koi.adapters.agent_process import run_json
from koi.agent_chat import conversations, live, runner
from api.routers import agents


SCRIPT = r'''
import json, pathlib, subprocess, sys, time
backend = pathlib.Path(sys.argv[0]).name
if backend == "codex": assert "--json" in sys.argv
if backend == "claude": assert "--verbose" in sys.argv and "stream-json" in sys.argv
prompt = sys.stdin.read()
def send(text, final=False):
    if backend == "codex":
        print(json.dumps({"type":"item.completed", "item":{"type":"agent_message", "text":text}}), flush=True)
    else:
        print(json.dumps({"type":"assistant", "message":{"id":str(final), "content":[{"type":"text", "text":text}]}}), flush=True)
print('non-json diagnostic', flush=True)
print(json.dumps({"type":"item.completed", "item":{"type":"reasoning", "text":"PRIVATE"}}), flush=True)
send("Проверяю файлы.")
if prompt.split("\n\n")[0] == "wait":
    subprocess.Popen([sys.executable, "-c", "import pathlib,time; time.sleep(1); pathlib.Path('child-survived').touch()"])
    pathlib.Path('child-started').touch()
    time.sleep(20)
else:
    while not pathlib.Path('finish').exists(): time.sleep(.02)
    send("Готово.", True)
    if backend == "codex":
        pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_text("Готово.")
    else:
        print(json.dumps({"type":"result", "result":"Готово."}), flush=True)
'''


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(queue, "QUEUE_PATH", tmp_path / "queue.json")
    monkeypatch.setattr(conversations, "PATH", tmp_path / "chats.json")
    monkeypatch.setattr(activity, "ACTIVITY_DIR", tmp_path / "activity")
    monkeypatch.setattr(runner, "_ws", SimpleNamespace(agent_cwd=lambda: tmp_path))
    monkeypatch.setattr(runner, "is_api_agent_mode", lambda: False)
    monkeypatch.setattr(runner, "is_cursor_manual_agent_mode", lambda: False)
    monkeypatch.setattr(runner, "cli_agents", lambda: [{"id": b, "label": b, "available": True} for b in ("cursor", "codex", "claude")])
    monkeypatch.setattr(runner, "_sdk_prompt", lambda iid: queue.find_item(iid)["question"])
    monkeypatch.setattr(agents, "load_project", lambda *_a, **_kw: SimpleNamespace(boards=[]))
    scripts = {}
    for name in ("cursor", "codex", "claude"):
        script = tmp_path / name
        script.write_text(f"#!{sys.executable}\n" + SCRIPT)
        script.chmod(0o755)
        scripts[name] = script
    monkeypatch.setattr(backends, "_codex_bin", lambda: str(scripts["codex"]))
    monkeypatch.setattr(backends, "_claude_bin", lambda: str(scripts["claude"]))
    monkeypatch.setattr(runner, "find_agent_bin", lambda: scripts["cursor"])
    return tmp_path


def wait_for(check):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(.02)
    pytest.fail("Timed out waiting for subprocess progress")


@pytest.mark.parametrize("backend", ["cursor", "codex", "claude"])
def test_progress_visible_before_completion_and_preserved(state, backend):
    chat = conversations.create("demo")
    item = queue.enqueue_question("demo", "finish", cli_agent=backend, conversation_id=chat["id"])
    with ThreadPoolExecutor() as pool:
        result = pool.submit(runner.process_item, item["id"])
        wait_for(lambda: live.text(item["id"]))
        assert not result.done()
        detail = agents.get_conversation(chat["id"])
        assert detail["live"]["text"] == "Проверяю файлы."
        assert agents.get_agent_chat("demo")["items"][0]["live"]["text"] == "Проверяю файлы."
        (state / "finish").touch()
        assert result.result(timeout=5)
    answer = queue.find_item(item["id"])
    assert answer["status"] == "answered"
    assert "Проверяю файлы." in answer["answer"] and "Готово." in answer["answer"]
    assert "PRIVATE" not in answer["answer"]
    assert agents.get_conversation(chat["id"])["live"] is None


@pytest.mark.parametrize("backend", ["cursor", "codex", "claude"])
def test_cancel_silent_process_and_children_preserves_text_and_releases_chat(state, backend):
    chat, other = conversations.create("demo"), conversations.create("demo")
    item = queue.enqueue_question("demo", "wait", cli_agent=backend, conversation_id=chat["id"])
    untouched = queue.enqueue_question("demo", "other", conversation_id=other["id"])
    with ThreadPoolExecutor() as pool:
        result = pool.submit(runner.process_item, item["id"])
        wait_for(lambda: (state / "child-started").exists())
        assert agents.cancel_conversation(chat["id"])["ok"]
        assert result.result(timeout=3)
    answer = queue.find_item(item["id"])
    assert answer["answer_kind"] == "warning"
    assert answer["answer"] == "Проверяю файлы.\n\nОстановлено пользователем."
    assert not conversations.find(chat["id"])["pending"]
    assert queue.find_item(untouched["id"])["status"] == "pending"
    time.sleep(1.1)
    assert not (state / "child-survived").exists()
    assert not agents.cancel_conversation(chat["id"])["ok"]


def test_pending_cancel_does_not_launch_and_legacy_item_is_supported(state, monkeypatch):
    item = queue.enqueue_question("demo", "wait")
    assert agents.cancel_agent_chat_item(item["id"])["ok"]
    monkeypatch.setattr(runner, "_sdk_prompt", lambda _id: pytest.fail("Cancelled turn launched"))
    assert not runner.process_item(item["id"])
    assert queue.find_item(item["id"])["answer"] == "Остановлено пользователем."
    assert not agents.cancel_agent_chat_item(item["id"])["ok"]


def test_timeout_stops_process_without_stdout(state):
    import subprocess
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_json([sys.executable, "-c", "import time; time.sleep(20)"], "",
                 cwd=state, timeout=.2, on_event=lambda _event: None)
    assert time.monotonic() - started < 2


@pytest.mark.parametrize("backend", ["cursor", "codex", "claude"])
def test_git_analysis_uses_the_same_progress_and_cancel_signals(state, monkeypatch, backend):
    from koi.agent_chat import git_changes
    from koi.adapters.agent_process import AgentCancelled
    monkeypatch.setattr(backends, "_resolve_cwd", lambda _cwd: state)
    monkeypatch.setattr(git_changes, "get_workspace", lambda: SimpleNamespace(agent_cwd=lambda: state))
    monkeypatch.setattr(backends, "cli_agents", runner.cli_agents)
    item = queue.enqueue_question("demo", "wait", cli_agent=backend)
    queue.mark_processing(item["id"])
    with ThreadPoolExecutor() as pool:
        result = pool.submit(git_changes._suggest, "wait", backend, item["id"])
        wait_for(lambda: live.text(item["id"]))
        assert agents.cancel_agent_chat_item(item["id"])["ok"]
        with pytest.raises(AgentCancelled):
            result.result(timeout=3)
