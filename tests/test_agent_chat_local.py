"""The local chat path launches without a visible terminal and reports progress."""

from pathlib import Path
from types import SimpleNamespace
import json

from fastapi import BackgroundTasks

from koi.agent_chat import runner


def test_local_agent_uses_cursor_print_mode(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner, "find_agent_bin", lambda: Path("/usr/bin/agent"))
    monkeypatch.setattr(runner, "_ws", SimpleNamespace(agent_cwd=lambda: tmp_path))
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdin=SimpleNamespace(write=lambda text: calls.append(text), close=lambda: None),
            stdout=[json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Готовый ответ"}]}})],
            wait=lambda: None,
            poll=lambda: 0,
            kill=lambda: None,
        )

    monkeypatch.setattr(runner.subprocess, "Popen", fake_run)
    monkeypatch.setattr(runner, "record", lambda *_args: None)
    assert runner._run_local_agent("Вопрос", "aq-abc123") == ("Готовый ответ", "Cursor CLI")
    assert calls[0][0] == [
        "/usr/bin/agent", "--print", "--trust", "--mode", "ask", "--output-format", "stream-json"
    ]
    assert calls[0][1]["cwd"] == str(tmp_path)
    assert calls[1] == "Вопрос"


def test_local_agent_write_mode_omits_ask(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner, "find_agent_bin", lambda: Path("/usr/bin/agent"))
    monkeypatch.setattr(runner, "_ws", SimpleNamespace(agent_cwd=lambda: tmp_path))
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(
            returncode=0,
            stdin=SimpleNamespace(write=lambda text: None, close=lambda: None),
            stdout=[json.dumps({"type": "result", "result": "done"})],
            wait=lambda: None,
            poll=lambda: 0,
            kill=lambda: None,
        )

    monkeypatch.setattr(runner.subprocess, "Popen", fake_run)
    assert runner._run_local_agent("Paper review", "proj/slug/c_1", mode=None, force=True)[0] == "done"
    assert calls[0] == [
        "/usr/bin/agent", "--print", "--trust", "--force", "--output-format", "stream-json"
    ]


def test_local_process_records_progress_and_answer(monkeypatch) -> None:
    item = {"id": "aq-abc123", "project_id": "demo", "question": "Что известно?", "status": "pending"}
    events = []
    answers = []
    monkeypatch.setattr(runner, "find_item", lambda _id: item)
    monkeypatch.setattr(runner, "try_auto_answer", lambda *_args: (_ for _ in ()).throw(AssertionError("local mode must use agent")))
    monkeypatch.setattr(runner, "is_cursor_manual_agent_mode", lambda: False)
    monkeypatch.setattr(runner, "is_api_agent_mode", lambda: False)
    monkeypatch.setattr(runner, "find_agent_bin", lambda: Path("/usr/bin/agent"))
    monkeypatch.setattr(runner, "mark_processing", lambda _id: events.append("processing"))
    monkeypatch.setattr(runner, "record", lambda _id, message: events.append(message))
    monkeypatch.setattr(runner, "_sdk_prompt", lambda _id: "prompt")
    monkeypatch.setattr(runner, "_run_local_agent", lambda _prompt, _id: ("Ответ", "Cursor CLI"))
    monkeypatch.setattr(runner, "submit_answer", lambda _id, answer, **_kw: answers.append(answer))

    assert runner.process_item(item["id"])
    assert events[0] == "processing"
    assert answers == ["Ответ"]
    assert events[-1] == "Ответ опубликован в чате."


def test_post_question_schedules_local_agent_without_waiting(monkeypatch) -> None:
    from api.routers import agents

    item = {"id": "aq-abc123", "project_id": "demo", "question": "Что известно?", "status": "pending"}
    monkeypatch.setattr(agents, "load_project", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(agents, "enqueue_question", lambda *_args, **_kwargs: item)
    monkeypatch.setattr(agents, "find_item", lambda _id: item)
    monkeypatch.setattr(agents, "try_auto_answer", lambda *_args: (_ for _ in ()).throw(AssertionError("local mode must use agent")))
    monkeypatch.setattr(agents, "get_agent_chat_mode", lambda: "local")
    tasks = BackgroundTasks()

    response = agents.post_agent_chat(
        SimpleNamespace(project_id="demo", question="Что известно?", method_id=None, node_id=None),
        tasks,
    )

    assert response["item"] == item
    assert response["answered"] is False
    assert len(tasks.tasks) == 1
