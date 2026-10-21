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


def test_chat_accepts_full_large_report(isolated_queue, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    project = SimpleNamespace(boards=[SimpleNamespace(id="b", cards=[SimpleNamespace(id="c")])])
    monkeypatch.setattr(agents, "load_project", lambda *a, **kw: project)
    monkeypatch.setattr(agents, "get_agent_chat_mode", lambda: "local")
    monkeypatch.setattr(agents, "is_cursor_inbox_agent_mode", lambda: False)
    monkeypatch.setattr(agents, "_run_agent_chat_item", lambda _: None)
    app = FastAPI()
    app.include_router(agents.router)
    report = "Строка лога\n" * 40000
    response = TestClient(app).post("/agent-chat", json={
        "project_id": "demo", "board_id": "b", "card_id": "c",
        "question": "Убери логи из отчёта", "purpose": "agent",
        "report_markdown": report,
    })
    assert response.status_code == 200
    assert queue.find_item(response.json()["item"]["id"])["report_markdown"] == report


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
    queue.submit_answer(second["id"], 'Готово\n```report-setup\n' + json.dumps(proposal) + '\n```', review_passed=True)
    saved = queue.find_item(second["id"])
    assert saved["answer"] == "Готово"
    assert saved["proposal"] == proposal
    assert saved["review_passed"] is True
    monkeypatch.setattr(queue, "MAX_ITEMS_PER_PROJECT", 1)
    for _ in range(3):
        queue.enqueue_question("demo", "Обычный вопрос")
    assert len(queue.list_for_project("demo", board_id="b", card_id="c")) == 2


@pytest.mark.parametrize("payload", ['[]', '{"goal":"x"}', '{"goal":"x","setup":"y","tasks":""}', '{bad}'])
def test_invalid_proposal_is_not_applicable(payload):
    text = f"```report-setup\n{payload}\n```"
    assert parse_reply(text) == (text, None)


def test_grill_proposal_requires_review_pass(isolated_queue):
    item = queue.enqueue_question("demo", "Идея", purpose="grill_me", board_id="b", card_id="c")
    queue.submit_answer(item["id"], 'Готово\n```report-setup\n{"goal":"g","setup":"s","tasks":"t"}\n```')
    saved = queue.find_item(item["id"])
    assert saved["proposal"] is None
    assert saved["review_passed"] is False


def test_card_agent_and_explicit_question_modes(monkeypatch):
    assert AgentChatBody(project_id="demo", question="Исправь постановку").purpose == "agent"
    monkeypatch.setattr(runner, "build_context", lambda _: {"purpose": "agent", "card": {"card_id": "c"}})
    assert "skills перед правкой" in runner._sdk_prompt("id")
    monkeypatch.setattr(runner, "build_context", lambda _: {"purpose": "question", "card": {"card_id": "c"}})
    assert "Не меняй файлы" in runner._sdk_prompt("id")


def test_grill_review_checks_setup_then_prose_readonly(monkeypatch):
    calls = []
    def reviewer(prompt, item_id, **kwargs):
        calls.append((prompt, kwargs))
        return "PASS\nПроверено.", "test-agent"
    monkeypatch.setattr(runner, "_run_local_agent", reviewer)
    monkeypatch.setattr(runner, "record", lambda *a: None)
    ok, feedback = runner._review_grill_proposal("aq-test", {"goal": "Цель", "setup": "Протокол", "tasks": "- [ ] Шаг"}, local_mode=True)
    assert ok and not feedback
    assert len(calls) == 1
    assert calls[0][0].index("Сначала проверь, что") < calls[0][0].index("Затем проверь прозу")
    assert "НЕ является причиной FAIL" in calls[0][0]
    assert all(kwargs["mode"] == "ask" and kwargs["force"] is False for _, kwargs in calls)


def test_grill_review_stops_on_fail(monkeypatch):
    monkeypatch.setattr(runner, "_run_local_agent", lambda *a, **kw: ("FAIL\nНет критерия готовности", "test-agent"))
    monkeypatch.setattr(runner, "record", lambda *a: None)
    ok, feedback = runner._review_grill_proposal("aq-test", {"goal": "Цель", "setup": "Протокол", "tasks": "Шаг"}, local_mode=True)
    assert not ok and "Нет критерия готовности" in feedback


def test_auto_answer_only_explicit_questions(isolated_queue, monkeypatch):
    monkeypatch.setattr(agents, "get_agent_chat_mode", lambda: "api")
    monkeypatch.setattr(agents, "try_auto_answer", lambda *a: "Готовый ответ")
    agent = queue.enqueue_question("demo", "Исправь карточку", purpose="agent")
    question = queue.enqueue_question("demo", "Что известно?", purpose="question")
    agents._auto_answer_pending("demo")
    assert queue.find_item(agent["id"])["status"] == "pending"
    assert queue.find_item(question["id"])["status"] == "answered"


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


def test_two_turn_interview_queues_latest_summary_without_exposing_draft(isolated_queue, monkeypatch):
    from koi.agent_chat import setup_pipeline
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
    queued = []
    monkeypatch.setattr(setup_pipeline, "enqueue", queued.append)
    body = AgentChatBody(project_id="demo", board_id="b", card_id="c", purpose="report_grill", question="Идея", report_markdown="## Цель\n")
    first = agents.post_agent_chat(body, BackgroundTasks())["item"]
    assert runner.process_item(first["id"])
    assert queue.find_item(first["id"])["proposal"] is None
    second = agents.post_agent_chat(body.model_copy(update={"question":"Выбираем SR"}), BackgroundTasks())["item"]
    assert runner.process_item(second["id"])
    assert "Какая метрика?" in prompts[1]
    assert "Выбираем SR" in prompts[1]
    response = agents.get_agent_chat("demo", board_id="b", card_id="c")
    assert response["items"][0]["proposal"] is None
    assert "report-setup" not in response["items"][0]["answer"]
    assert queued == [first["id"], second["id"]]
    assert len(response["items"]) == 2


def test_setup_queue_coalesces_to_latest_card_turn(isolated_queue, monkeypatch, tmp_path):
    from koi.agent_chat import setup_pipeline as pipeline
    monkeypatch.setattr(pipeline, "QUEUE_PATH", tmp_path / "setup-queue.json")
    pipeline._active.clear()
    submitted = []
    monkeypatch.setattr(pipeline._pool, "submit", lambda fn, key: submitted.append(key))
    first = queue.enqueue_question("demo", "Первый ответ", purpose="grill_me", board_id="b", card_id="c")
    second = queue.enqueue_question("demo", "Новый ответ", purpose="grill_me", board_id="b", card_id="c")
    pipeline.enqueue(first["id"])
    pipeline.enqueue(second["id"])
    assert submitted == ["demo/b/c"]
    assert pipeline._read() == {"demo/b/c": second["id"]}
    processed = []
    monkeypatch.setattr(pipeline, "_process", lambda key, item_id: processed.append(item_id))
    pipeline._drain("demo/b/c")
    assert processed == [second["id"]]
    assert pipeline._read() == {}


def test_setup_replacement_preserves_results():
    from koi.agent_chat.setup_pipeline import _replace_sections, _contains_process_text
    source = "## Цель\n\nСтарая\n\n## Постановка эксперимента\n\nСтарая\n\n## Задачи\n\nСтарые\n\n## Результаты\n\nИзмерение 42\n"
    updated = _replace_sections(source, {"goal": "Новая цель", "setup": "Новый протокол", "tasks": "- [ ] Проверить"})
    assert "## Результаты\n\nИзмерение 42" in updated
    assert "## Цель\n\nНовая цель" in updated
    assert "## Задачи\n\n- [ ] Проверить" in updated
    assert _contains_process_text({"goal": "Цель", "setup": "Зафиксировано по истории ответов", "tasks": "- [ ] Шаг"})
    assert not _contains_process_text({"goal": "Цель", "setup": "Контроль ещё выбираем", "tasks": "- [ ] Шаг"})


def test_writer_review_updates_report_without_chat_feedback(isolated_queue, monkeypatch):
    from koi.agent_chat import setup_pipeline as pipeline
    item = queue.enqueue_question("demo", "Новые условия", purpose="grill_me", board_id="b", card_id="c")
    queue.submit_answer(item["id"], "```question\nКакой порог?\nРекомендуемый ответ: 0,05\n```")
    project = SimpleNamespace(id="demo", boards=[SimpleNamespace(id="b", cards=[SimpleNamespace(id="c", title="Card")])])
    current = "## Цель\n\n## Постановка эксперимента\n\n## Задачи\n\n## Результаты\n\nНет\n"
    proposal = {"goal": "Измерить долю", "setup": "Основная метрика открыта", "tasks": "- [ ] Посчитать таблицу"}
    written = []
    monkeypatch.setattr(pipeline, "_latest", lambda *a: True)
    monkeypatch.setattr(pipeline, "load_project", lambda *a, **kw: project)
    monkeypatch.setattr(pipeline, "read_report", lambda *a: {"content": current})
    monkeypatch.setattr(pipeline, "build_context", lambda *a: {"history": []})
    writer_prompts = []
    def writer(prompt, _item_id):
        writer_prompts.append(prompt)
        return "```report-setup\n" + json.dumps(proposal) + "\n```"
    monkeypatch.setattr(pipeline, "_run_private_agent", writer)
    review_evidence = []
    def reviewer(*a, **kw):
        review_evidence.append(kw["evidence"])
        return True, ""
    monkeypatch.setattr(runner, "_review_grill_proposal", reviewer)
    monkeypatch.setattr(pipeline, "write_report", lambda *a: written.append(a[-1]))
    monkeypatch.setattr(pipeline, "record", lambda *a: None)
    pipeline._process("demo/b/c", item["id"])
    assert "## Цель\n\nИзмерить долю" in written[0]
    assert "## Результаты\n\nНет" in written[0]
    assert "Какой порог?" in queue.find_item(item["id"])["answer"]
    assert review_evidence[0]["history"][-1] == {"user": "Новые условия", "assistant": None}
    assert "Какой порог?" in review_evidence[0]["pending_question"]
    assert "pending_question" in writer_prompts[0]


def test_stale_writer_does_not_overwrite_newer_turn(isolated_queue, monkeypatch):
    from koi.agent_chat import setup_pipeline as pipeline
    item = queue.enqueue_question("demo", "Старый ответ", purpose="grill_me", board_id="b", card_id="c")
    project = SimpleNamespace(id="demo", boards=[SimpleNamespace(id="b", cards=[SimpleNamespace(id="c", title="Card")])])
    checks = iter((True, True, False))
    monkeypatch.setattr(pipeline, "_latest", lambda *a: next(checks))
    monkeypatch.setattr(pipeline, "load_project", lambda *a, **kw: project)
    monkeypatch.setattr(pipeline, "read_report", lambda *a: {"content": "## Цель\n"})
    monkeypatch.setattr(pipeline, "build_context", lambda *a: {"history": []})
    proposal = {"goal": "Цель", "setup": "Протокол", "tasks": "- [ ] Задача"}
    monkeypatch.setattr(pipeline, "_run_private_agent", lambda *a: "```report-setup\n" + json.dumps(proposal) + "\n```")
    monkeypatch.setattr(runner, "_review_grill_proposal", lambda *a, **kw: (True, ""))
    writes = []
    monkeypatch.setattr(pipeline, "write_report", lambda *a: writes.append(a))
    pipeline._process("demo/b/c", item["id"])
    assert writes == []
