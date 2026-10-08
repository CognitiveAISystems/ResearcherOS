import json
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException

from koi.adapters import agent_chat_queue as queue
from koi.agent_chat import cli, runner
from koi.agent_chat.report_grill import parse_reply
from api.routers import agents
from api.schemas import AgentChatBody


@pytest.fixture
def isolated_queue(monkeypatch, tmp_path):
    monkeypatch.setattr(queue, "QUEUE_PATH", tmp_path / "chat.json")


def test_interview_persists_history_proposal_and_card_scope(isolated_queue, monkeypatch):
    first = queue.enqueue_question("demo", "Идея", purpose="report_grill", board_id="b", card_id="c", report_markdown="## Цель\n")
    queue.submit_answer(first["id"], "Как измеряем? Рекомендация: SR.")
    queue.enqueue_question("demo", "Другая карточка", purpose="report_grill", board_id="b", card_id="other")
    second = queue.enqueue_question("demo", "SR", purpose="report_grill", board_id="b", card_id="c", report_markdown="## Цель\n")
    project = SimpleNamespace(id="demo", title="Demo", nodes=[], boards=[])
    monkeypatch.setattr(cli, "load_project", lambda *a, **kw: project)
    monkeypatch.setattr(cli, "research_path", lambda pid: queue.QUEUE_PATH.parent / "research.json")
    monkeypatch.setattr(cli, "koi_root", lambda pid: queue.QUEUE_PATH.parent)
    monkeypatch.setattr(cli, "code_root", lambda pid: queue.QUEUE_PATH.parent)
    ctx = cli.build_context(second["id"])
    assert ctx["purpose"] == "report_grill"
    assert ctx["history"] == [{"user": "Идея", "assistant": "Как измеряем? Рекомендация: SR.", "proposal": None}]
    assert ctx["current_document"] == "## Цель\n"
    proposal = {"goal": "Цель", "setup": "Протокол", "tasks": "- [ ] Проверить"}
    queue.submit_answer(second["id"], 'Готово\n```report-setup\n' + json.dumps(proposal) + '\n```')
    saved = queue.find_item(second["id"])
    assert saved["answer"] == "Готово"
    assert saved["proposal"] == proposal
    monkeypatch.setattr(queue, "MAX_ITEMS_PER_PROJECT", 1)
    for _ in range(3):
        queue.enqueue_question("demo", "Обычный вопрос")
    assert len(queue.list_for_project("demo", board_id="b", card_id="c")) == 2


@pytest.mark.parametrize("payload", ['[]', '{"goal":"x"}', '{"goal":"x","setup":"y","tasks":""}', '{bad}'])
def test_invalid_proposal_is_not_applicable(payload):
    text = f"```report-setup\n{payload}\n```"
    assert parse_reply(text) == (text, None)


def test_interview_prompt_uses_skill_not_knowledge_answer_policy(monkeypatch):
    monkeypatch.setattr(runner, "build_context", lambda _: {"purpose":"report_grill", "history": [{"user":"идея"}]})
    prompt = runner._sdk_prompt("id")
    assert "Один вопрос за ход" in prompt
    assert "koi-report-review" in prompt
    assert "report-setup" in prompt
    assert "идея" in prompt
    assert "эксперименты пока не покрывают вопрос" not in prompt


def test_api_interview_skips_auto_answer_and_blocks_parallel_turns(isolated_queue, monkeypatch):
    project = SimpleNamespace(boards=[SimpleNamespace(id="b", cards=[SimpleNamespace(id="c")])])
    monkeypatch.setattr(agents, "load_project", lambda *a, **kw: project)
    monkeypatch.setattr(agents, "get_agent_chat_mode", lambda: "api")
    monkeypatch.setattr(agents, "is_cursor_inbox_agent_mode", lambda: False)
    monkeypatch.setattr(agents, "try_auto_answer", lambda *a: pytest.fail("Interview must not be auto-answered"))
    body = AgentChatBody(project_id="demo", question="Идея", purpose="report_grill", board_id="b", card_id="c")
    tasks = BackgroundTasks()
    response = agents.post_agent_chat(body, tasks)
    assert len(tasks.tasks) == 1
    assert response["item"]["purpose"] == "report_grill"
    with pytest.raises(HTTPException) as error:
        agents.post_agent_chat(body, BackgroundTasks())
    assert error.value.status_code == 409
    agents._auto_answer_pending("demo")
    with pytest.raises(HTTPException) as error:
        agents.post_agent_chat(body.model_copy(update={"card_id":"missing"}), BackgroundTasks())
    assert error.value.status_code == 404


def test_report_starts_with_empty_human_sections():
    from koi.adapters.card_reports import report_scaffold
    text = report_scaffold(None, "b", "c", "Title")
    assert text.splitlines() == ["## Цель", "", "## Постановка эксперимента", "", "## Задачи", "", "## Эксперименты", "", "## Результаты"]


def test_two_turn_interview_returns_question_then_applicable_setup(isolated_queue, monkeypatch):
    project = SimpleNamespace(id="demo", title="Demo", nodes=[], boards=[SimpleNamespace(id="b", cards=[SimpleNamespace(id="c")])])
    for module in (agents, cli):
        monkeypatch.setattr(module, "load_project", lambda *a, **kw: project)
    monkeypatch.setattr(cli, "_card_meta", lambda *a: {"card_id":"c", "title":"Experiment"})
    monkeypatch.setattr(cli, "research_path", lambda pid: queue.QUEUE_PATH.parent / "research.json")
    monkeypatch.setattr(cli, "koi_root", lambda pid: queue.QUEUE_PATH.parent)
    monkeypatch.setattr(cli, "code_root", lambda pid: queue.QUEUE_PATH.parent)
    monkeypatch.setattr(agents, "get_agent_chat_mode", lambda: "local")
    monkeypatch.setattr(agents, "is_cursor_inbox_agent_mode", lambda: False)
    monkeypatch.setattr(runner, "is_cursor_manual_agent_mode", lambda: False)
    monkeypatch.setattr(runner, "is_api_agent_mode", lambda: False)
    monkeypatch.setattr(runner, "find_agent_bin", lambda: queue.QUEUE_PATH)
    monkeypatch.setattr(runner, "record", lambda *a: None)
    monkeypatch.setattr(runner, "load_env_file", lambda: None)
    proposal = {"goal":"Claim", "setup":"Protocol", "tasks":"- [ ] Evaluate"}
    prompts = []
    def agent(prompt, item_id):
        prompts.append(prompt)
        return (("Q1: Какая метрика? Рекомендация: SR." if len(prompts) == 1 else "Готово\n```report-setup\n" + json.dumps(proposal) + "\n```"), "test-agent")
    monkeypatch.setattr(runner, "_run_local_agent", agent)
    body = AgentChatBody(project_id="demo", board_id="b", card_id="c", purpose="report_grill", question="Идея", report_markdown="## Цель\n")
    first = agents.post_agent_chat(body, BackgroundTasks())["item"]
    assert runner.process_item(first["id"])
    assert queue.find_item(first["id"])["proposal"] is None
    second = agents.post_agent_chat(body.model_copy(update={"question":"Выбираем SR"}), BackgroundTasks())["item"]
    assert runner.process_item(second["id"])
    assert "Какая метрика?" in prompts[1]
    assert "Выбираем SR" in prompts[1]
    response = agents.get_agent_chat("demo", board_id="b", card_id="c")
    assert response["items"][0]["proposal"] == proposal
    assert len(response["items"]) == 2
