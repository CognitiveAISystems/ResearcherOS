"""The local chat path launches without a visible terminal and reports progress."""

from pathlib import Path
from types import SimpleNamespace
import json

import pytest
from fastapi import BackgroundTasks, HTTPException

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
    monkeypatch.setattr(runner, "_run_local_agent", lambda _prompt, _id, **kwargs: ("Ответ", "Cursor CLI") if kwargs == {"mode": None, "force": True} else None)
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


def test_general_chat_prompt_accepts_work_and_includes_project_paths(monkeypatch) -> None:
    monkeypatch.setattr(runner, "build_context", lambda _id: {
        "purpose": "agent", "user_question": "Исправь описание",
        "research_root": "/tmp/tree/demo/koi-structure", "code_root": "/tmp/demo",
    })
    prompt = runner._sdk_prompt("aq-work")
    assert "правка файла" in prompt
    assert "/tmp/tree/demo/koi-structure" in prompt
    assert "скилл koi-agent-chat" not in prompt


def test_api_chat_does_not_short_circuit_work_as_a_knowledge_answer(monkeypatch) -> None:
    from api.routers import agents

    item = {"id": "aq-work", "project_id": "demo", "question": "Исправь описание", "status": "pending"}
    monkeypatch.setattr(agents, "load_project", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(agents, "enqueue_question", lambda *_args, **_kwargs: item)
    monkeypatch.setattr(agents, "find_item", lambda _id: item)
    monkeypatch.setattr(agents, "get_agent_chat_mode", lambda: "api")
    monkeypatch.setattr(agents, "try_auto_answer", lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected summary answer")))
    result = agents.post_agent_chat(SimpleNamespace(project_id="demo", question="Исправь описание", method_id=None, node_id=None), BackgroundTasks())
    assert result["answered"] is False


def test_cli_agents_report_only_installed_bins(monkeypatch) -> None:
    from koi.adapters import agent_backends
    from koi.literature import cursor_agent_terminal

    monkeypatch.setattr(cursor_agent_terminal, "find_agent_bin", lambda: Path("/usr/bin/agent"))
    monkeypatch.setattr(agent_backends, "_codex_ready", lambda: False)
    monkeypatch.setattr(agent_backends, "_claude_bin", lambda: None)
    from koi.adapters import acp_agents
    monkeypatch.setattr(acp_agents, "agents", lambda: [])
    listed = {row["id"]: row["available"] for row in agent_backends.cli_agents()}
    assert listed == {"cursor": True, "codex": False, "claude": False}


def test_chosen_cli_does_not_fall_back(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner, "find_agent_bin", lambda: Path("/usr/bin/agent"))
    monkeypatch.setattr(runner, "_ws", SimpleNamespace(agent_cwd=lambda: tmp_path))
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("cursor")))
    calls = []
    monkeypatch.setattr(runner, "run_agent", lambda _prompt, **kwargs: calls.append(kwargs) or ("Готово", "codex"))
    assert runner._run_local_agent("Вопрос", "aq-1", cli_agent="codex") == ("Готово", "codex")
    assert calls[0]["backend"] == "codex"
    monkeypatch.setattr(runner, "find_agent_bin", lambda: None)
    monkeypatch.setattr(runner, "run_agent", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("fallback")))
    assert runner._run_local_agent("Вопрос", "aq-1", cli_agent="cursor") == (None, None)


def test_post_rejects_unavailable_cli(monkeypatch) -> None:
    from api.routers import agents
    from api.schemas import AgentChatBody

    monkeypatch.setattr(agents, "load_project", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(agents, "cli_agents", lambda: [{"id": "codex", "label": "Codex", "available": False}])
    with pytest.raises(HTTPException) as exc:
        agents.post_agent_chat(
            AgentChatBody(project_id="demo", question="Что известно?", cli_agent="codex"),
            BackgroundTasks(),
        )
    assert exc.value.status_code == 400


def test_queue_keeps_chosen_cli(monkeypatch, tmp_path: Path) -> None:
    from koi.adapters import agent_chat_queue as queue

    monkeypatch.setattr(queue, "QUEUE_PATH", tmp_path / "chat.json")
    item = queue.enqueue_question("demo", "Что известно?", cli_agent="claude")
    assert queue.find_item(item["id"])["cli_agent"] == "claude"
