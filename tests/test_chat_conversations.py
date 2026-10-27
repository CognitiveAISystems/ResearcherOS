from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException
from koi.agent_chat import conversations as chats
from koi.adapters import agent_chat_queue as queue
from koi.adapters import agent_chat_activity as activity


@pytest.fixture
def state(monkeypatch, tmp_path):
    monkeypatch.setattr(chats, "PATH", tmp_path / "chats.json")
    monkeypatch.setattr(queue, "QUEUE_PATH", tmp_path / "queue.json")
    monkeypatch.setattr(activity, "ACTIVITY_DIR", tmp_path / "activity")
    return tmp_path


def test_legacy_history_and_conversation_isolation(state):
    old = queue.enqueue_question("a", "Старое сообщение")
    card = queue.enqueue_question("a", "Карточка", board_id="b", card_id="c")
    legacy = chats.list_conversations()
    assert len(legacy) == 2
    assert chats.messages(chats.legacy_id(old))[0]["id"] == old["id"]
    one = chats.create("a", "b", "c")
    two = chats.create("a", "b", "c")
    queue.enqueue_question("a", "Первый чат", board_id="b", card_id="c", conversation_id=one["id"])
    queue.enqueue_question("a", "Второй чат", board_id="b", card_id="c", conversation_id=two["id"])
    chats.create("other")
    assert len(chats.list_conversations("a", "b", "c")) == 3
    assert [i["question"] for i in chats.messages(one["id"])] == ["Первый чат"]
    chats.update(one["id"], backend="test")
    item = chats.messages(one["id"])[0]
    queue.submit_answer(item["id"], "Ответ")
    assert not chats.find(one["id"])["pending"]
    assert len(chats.list_conversations()) == 5
    assert len(chats.messages(chats.legacy_id(card))) == 1


def test_conversation_history_survives_pruning_and_concurrent_writes(state):
    one = chats.create("a")
    def send(n):
        return queue.enqueue_question("a", str(n), conversation_id=one["id"])
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(send, range(75)))
    assert len(chats.messages(one["id"])) == 75
    assert chats.find(one["id"])["id"] == one["id"]


def test_working_is_separate_from_unread_and_read_state_survives_reload(state):
    chat = chats.create("a")
    item = queue.enqueue_question("a", "Проверка", conversation_id=chat["id"])
    assert not chats.find(chat["id"])["unread"]
    queue.mark_processing(item["id"])
    assert chats.find(chat["id"])["agent_active"]
    assert not chats.find(chat["id"])["unread"]
    queue.submit_answer(item["id"], "Готово")
    row = chats.find(chat["id"])
    assert row["unread"] and not row["agent_active"]
    assert row["latest_answer_id"] == item["id"]
    chats.mark_read(chat["id"], item["id"])
    assert not chats.list_conversations()[0]["unread"]
    assert json.loads(chats.PATH.read_text())[0]["read_through"] == queue.find_item(item["id"])["answered_at"]


def test_read_receipt_does_not_consume_newer_or_other_chat_answer(state):
    one, two = chats.create("a"), chats.create("a")
    first = queue.enqueue_question("a", "Первый", conversation_id=one["id"])
    queue.submit_answer(first["id"], "Первый ответ")
    second = queue.enqueue_question("a", "Второй", conversation_id=one["id"])
    queue.submit_answer(second["id"], "Новый ответ")
    chats.mark_read(one["id"], first["id"])
    assert chats.find(one["id"])["unread"]
    with pytest.raises(ValueError):
        chats.mark_read(two["id"], second["id"])
    chats.mark_read(one["id"], second["id"])
    chats.mark_read(one["id"], first["id"])
    assert not chats.find(one["id"])["unread"]


def test_unread_rollout_baselines_old_history_only_once_including_legacy(state):
    chat = chats.create("a")
    old = queue.enqueue_question("a", "Старое", conversation_id=chat["id"])
    legacy = queue.enqueue_question("a", "Старая переписка")
    queue.submit_answer(old["id"], "Старый ответ")
    queue.submit_answer(legacy["id"], "Старый ответ")
    stored = chats._load()
    stored[0].pop("read_through")
    chats._save(stored)
    assert not any(row["unread"] for row in chats.list_conversations())
    for cid in (chat["id"], chats.legacy_id(legacy)):
        new = queue.enqueue_question("a", "Продолжение", conversation_id=cid)
        queue.submit_answer(new["id"], "Новый ответ")
        assert chats.find(cid)["unread"]


def test_read_api_rejects_answer_from_another_conversation(state, monkeypatch):
    from api.routers import agents
    from api.schemas import ConversationReadBody
    monkeypatch.setattr(agents, "load_project", lambda *_a, **_kw: SimpleNamespace(boards=[]))
    one, two = chats.create("a"), chats.create("a")
    item = queue.enqueue_question("a", "Вопрос", conversation_id=one["id"])
    queue.submit_answer(item["id"], "Ответ")
    with pytest.raises(HTTPException) as error:
        agents.mark_conversation_read(two["id"], ConversationReadBody(answer_id=item["id"]))
    assert error.value.status_code == 400
    assert not agents.mark_conversation_read(one["id"], ConversationReadBody(answer_id=item["id"]))["item"]["unread"]


def test_api_conflict_is_per_chat_and_rejects_cross_scope(state, monkeypatch):
    from api.routers import agents
    from api.schemas import AgentChatBody
    project = SimpleNamespace(boards=[SimpleNamespace(id="b", cards=[SimpleNamespace(id="c")])])
    monkeypatch.setattr(agents, "load_project", lambda *a, **kw: project)
    monkeypatch.setattr(agents, "get_agent_chat_mode", lambda: "local")
    first = chats.create("a", "b", "c")
    second = chats.create("a", "b", "c")
    body = dict(project_id="a", board_id="b", card_id="c", question="Работа")
    agents.post_agent_chat(AgentChatBody(**body, conversation_id=first["id"]), BackgroundTasks())
    with pytest.raises(HTTPException) as error:
        agents.post_agent_chat(AgentChatBody(**body, conversation_id=first["id"]), BackgroundTasks())
    assert error.value.status_code == 409
    agents.post_agent_chat(AgentChatBody(**body, conversation_id=second["id"]), BackgroundTasks())
    with pytest.raises(HTTPException) as error:
        agents.post_agent_chat(AgentChatBody(project_id="other", question="x", conversation_id=first["id"]), BackgroundTasks())
    assert error.value.status_code == 400


FAKE_AGENT = r'''
import json, sys
sid = "session-native"
permission = False
mode = ""
def send(data):
    print(json.dumps({"jsonrpc": "2.0", **data}), flush=True)
def answer(id, result):
    send({"id": id, "result": result})
def chunk(text):
    send({"method": "session/update", "params": {"sessionId": sid, "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}}}})
for line in sys.stdin:
    msg = json.loads(line)
    method = msg.get("method")
    if method == "initialize":
        answer(msg["id"], {"protocolVersion": 1, "agentCapabilities": {"loadSession": True}, "authMethods": []})
    elif method == "session/new":
        answer(msg["id"], {"sessionId": sid})
    elif method == "session/load":
        assert msg["params"]["sessionId"] == sid
        chunk("REPLAY MUST NOT APPEAR")
        answer(msg["id"], {})
    elif method == "session/prompt":
        prompt_id = msg["id"]
        mode = msg["params"]["prompt"][0]["text"]
        if mode == "crash":
            sys.exit(3)
        chunk("Поток ")
        if mode in ("permission", "cancel"):
            send({"id": 99, "method": "session/request_permission", "params": {"sessionId": sid, "toolCall": {"toolCallId": "tool", "title": "Записать файл"}, "options": [{"optionId": "allow", "name": "Разрешить", "kind": "allow_once"}, {"optionId": "deny", "name": "Запретить", "kind": "reject_once"}]}})
        else:
            chunk("ответа")
            answer(prompt_id, {"stopReason": "end_turn"})
    elif method == "session/cancel":
        answer(prompt_id, {"stopReason": "cancelled"})
    elif msg.get("id") == 99:
        if mode != "cancel":
            chunk(msg["result"]["outcome"].get("optionId", "cancelled"))
            answer(prompt_id, {"stopReason": "end_turn"})
'''


@pytest.fixture
def fake_agent(state, monkeypatch):
    pytest.skip("ACP deferred; CLI-only release")
    from koi.agent_chat import acp_client
    script = state / "agent.py"
    script.write_text(FAKE_AGENT)
    monkeypatch.setattr(acp_client, "agents", lambda: [{"id": "acp:test", "available": True, "command": [sys.executable, str(script)]}])
    return state


def wait_permission(cid):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        live = acp_client.snapshot(cid)
        if live and live.get("permission"):
            return live
        time.sleep(0.01)
    raise AssertionError("No permission request")


def test_real_stdio_handshake_stream_load_and_permissions(fake_agent):
    chat = chats.create("a")
    def run(prompt):
        return acp_client.run(chat["id"], "aq-test", prompt, fake_agent, "acp:test", timeout=5)
    assert run("hello") == "Поток ответа"
    assert chats.find(chat["id"])["acp_session_id"] == "session-native"
    assert run("again") == "Поток ответа"  # excludes replayed chunks
    with ThreadPoolExecutor() as pool:
        response = pool.submit(run, "permission")
        live = wait_permission(chat["id"])
        assert live["text"] == "Поток "
        with pytest.raises(ValueError):
            acp_client.decide(chat["id"], live["permission"]["id"], "forged")
        acp_client.decide(chat["id"], live["permission"]["id"], "allow")
        assert response.result(timeout=8) == "Поток allow"
    assert acp_client.snapshot(chat["id"]) is None


def test_cancellation_and_process_failure_release_chat(fake_agent):
    chat = chats.create("a")
    with ThreadPoolExecutor() as pool:
        response = pool.submit(acp_client.run, chat["id"], "aq-test", "cancel", fake_agent, "acp:test", 5)
        wait_permission(chat["id"])
        assert acp_client.cancel(chat["id"])
        assert "Остановлено пользователем" in response.result(timeout=8)
    assert acp_client.snapshot(chat["id"]) is None
    with pytest.raises(Exception):
        acp_client.run(chat["id"], "aq-test", "crash", fake_agent, "acp:test", 1)
    assert acp_client.snapshot(chat["id"]) is None


def test_sidebar_width_persists_in_runtime_settings(monkeypatch, tmp_path):
    from api.routers import agents
    from api.schemas import AgentChatSettingsBody
    from koi.adapters import settings_store
    from koi.agent_chat.settings import settings_snapshot
    import os
    monkeypatch.setattr(settings_store, "ENV_PATH", tmp_path / "settings.env")
    for key in ("KOI_CHAT_LIST_MAIN_WIDTH", "KOI_CHAT_LIST_CARD_WIDTH"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(agents, "worker_running", lambda: False)
    body = AgentChatSettingsBody(chat_list_main_width=320, chat_list_card_width=240)
    agents.put_agent_chat_settings(body)
    os.environ.pop("KOI_CHAT_LIST_MAIN_WIDTH", None)
    os.environ.pop("KOI_CHAT_LIST_CARD_WIDTH", None)
    assert settings_snapshot()["chat_list_main_width"] == 320
    assert settings_snapshot()["chat_list_card_width"] == 240
    with pytest.raises(ValueError):
        AgentChatSettingsBody(chat_list_main_width=900)


def test_global_chat_context_and_move_preserve_history(state, monkeypatch):
    from api.routers import agents
    from api.schemas import AgentChatBody, ConversationCreateBody, ConversationScopeBody
    from koi.agent_chat import cli, runner
    from koi.adapters import repository
    project = SimpleNamespace(boards=[SimpleNamespace(id="b", cards=[SimpleNamespace(id="c")])])
    monkeypatch.setattr(agents, "load_project", lambda pid, **kw: project if pid == "a" else None)
    monkeypatch.setattr(agents, "get_agent_chat_mode", lambda: "local")
    monkeypatch.setattr(repository, "list_projects", lambda: [])
    chat = agents.create_conversation(ConversationCreateBody())["item"]
    assert chat["project_id"] is None
    first = agents.post_agent_chat(AgentChatBody(conversation_id=chat["id"], question="Все исследования"), BackgroundTasks())["item"]
    assert queue.find_item(first["id"])["project_id"] is None
    with pytest.raises(HTTPException) as error:
        agents.move_conversation(chat["id"], ConversationScopeBody(project_id="a"))
    assert error.value.status_code == 409
    queue.submit_answer(first["id"], "Обзор")
    second = queue.enqueue_question(None, "Продолжи", conversation_id=chat["id"])
    context = cli.build_context(second["id"])
    assert context["project_id"] is None
    assert context["history"] == [{"user": "Все исследования", "assistant": "Обзор"}]
    assert "всех исследований" in runner._sdk_prompt(second["id"])
    queue.submit_answer(second["id"], "Продолжение")
    chats.update(chat["id"], acp_session_id="old-session", acp_backend="acp:test")
    moved = agents.move_conversation(chat["id"], ConversationScopeBody(project_id="a", board_id="b", card_id="c"))["item"]
    assert moved["id"] == chat["id"] and moved["card_id"] == "c"
    assert moved["acp_session_id"] is None
    assert len(chats.messages(chat["id"])) == 2
    assert chats.list_conversations("a", "b", "c")[0]["id"] == chat["id"]
    with pytest.raises(HTTPException):
        agents.move_conversation(chat["id"], ConversationScopeBody(project_id="missing"))
    assert chats.find(chat["id"])["project_id"] == "a"
    agents.move_conversation(chat["id"], ConversationScopeBody())
    assert chats.find(chat["id"])["project_id"] is None
    assert not chats.list_conversations("a")
    assert len(agents.get_conversation(chat["id"])["items"]) == 2
    with pytest.raises(HTTPException):
        agents.create_conversation(ConversationCreateBody(board_id="b", card_id="c"))


def test_cli_release_rejects_acp_without_losing_chat(state, monkeypatch):
    from api.routers import agents
    from api.schemas import AgentChatBody, ConversationCreateBody
    from koi.adapters.agent_backends import cli_agents
    monkeypatch.setenv("KOI_ACP_AGENTS", '{"test":["python"]}')
    assert all(not row["id"].startswith("acp:") for row in cli_agents())
    with pytest.raises(HTTPException) as error:
        agents.create_conversation(ConversationCreateBody(backend="acp:test"))
    assert error.value.status_code == 400
    chat = chats.create(backend="acp:test")
    old = queue.enqueue_question(None, "Первый вопрос", conversation_id=chat["id"])
    queue.submit_answer(old["id"], "Ответ")
    with pytest.raises(HTTPException):
        agents.post_agent_chat(AgentChatBody(conversation_id=chat["id"], question="Продолжи"), BackgroundTasks())
    monkeypatch.setattr(agents, "cli_agents", lambda: [{"id": "codex", "available": True}])
    monkeypatch.setattr(agents, "get_agent_chat_mode", lambda: "local")
    item = agents.post_agent_chat(AgentChatBody(conversation_id=chat["id"], cli_agent="codex", question="Продолжи"), BackgroundTasks())["item"]
    assert item["cli_agent"] == "codex"
    assert len(chats.messages(chat["id"])) == 2
    assert agents.get_conversation(chat["id"])["live"] is None


def test_restart_interrupts_cli_turn_and_keeps_history(state, monkeypatch):
    from api import main
    from koi.adapters import project_discovery_watch, settings_store
    from koi.projects import done_research_auto
    from koi.agent_chat import setup_pipeline
    from koi.agent_chat import git_changes
    monkeypatch.setattr(git_changes, "start", lambda: None)
    monkeypatch.setattr(settings_store, "load_env_file", lambda: None)
    monkeypatch.setattr(project_discovery_watch, "start_project_discovery_watch", lambda: None)
    monkeypatch.setattr(done_research_auto, "kick_recent", lambda: None)
    monkeypatch.setattr(setup_pipeline, "resume_pending", lambda: None)
    chat = chats.create()
    answered = queue.enqueue_question(None, "Решение", conversation_id=chat["id"])
    queue.submit_answer(answered["id"], "Согласовано")
    pending = queue.enqueue_question(None, "Продолжи", conversation_id=chat["id"])
    queue.mark_processing(pending["id"])
    main._startup()
    assert queue.find_item(answered["id"])["answer"] == "Согласовано"
    assert queue.find_item(pending["id"])["status"] == "answered"
    assert "перезапуском" in queue.find_item(pending["id"])["answer"]
    assert not chats.find(chat["id"])["pending"]


def test_method_scope_includes_card_chats_but_not_other_methods(state, monkeypatch):
    from api.routers import agents
    board = SimpleNamespace(id="method", cards=[SimpleNamespace(id="card")])
    monkeypatch.setattr(agents, "load_project", lambda *a, **kw: SimpleNamespace(boards=[board]))
    method = chats.create("project", "method")
    card = chats.create("project", "method", "card")
    chats.create("project", "other-method")
    chats.create("project")
    agents._check_scope("project", "method")
    assert {r["id"] for r in chats.list_conversations("project", "method")} == {method["id"], card["id"]}
    assert [r["id"] for r in chats.list_conversations("project", "method", "card")] == [card["id"]]
    with pytest.raises(HTTPException):
        agents._check_scope("project", "missing-method")


def test_delete_conversation_removes_only_its_history_and_legacy_metadata(state):
    one = chats.create("a")
    two = chats.create("a")
    message = queue.enqueue_question("a", "Первый", conversation_id=one["id"])
    queue.submit_answer(message["id"], "Ответ")
    other = queue.enqueue_question("a", "Второй", conversation_id=two["id"])
    queue.submit_answer(other["id"], "Другой ответ")
    assert chats.delete(one["id"]) == [message["id"]]
    assert chats.find(one["id"]) is None
    assert chats.messages(one["id"]) == []
    assert chats.messages(two["id"])[0]["id"] == other["id"]
    legacy = queue.enqueue_question("a", "Старый чат")
    queue.submit_answer(legacy["id"], "Ответ")
    chats.delete(chats.legacy_id(legacy))
    assert chats.find(chats.legacy_id(legacy)) is None
    with pytest.raises(KeyError):
        chats.delete(one["id"])


def test_delete_pending_conversation_is_rejected_without_data_loss(state):
    from api.routers import agents
    chat = chats.create()
    item = queue.enqueue_question(None, "Работа", conversation_id=chat["id"])
    with pytest.raises(HTTPException) as error:
        agents.delete_conversation(chat["id"])
    assert error.value.status_code == 409
    assert chats.find(chat["id"]) is not None
    assert chats.messages(chat["id"])[0]["id"] == item["id"]


@pytest.fixture
def routing(state, monkeypatch):
    from koi.agent_chat import context_routing
    from api.routers import agents
    from koi.core.models import Project, Node, NodeType, KanbanBoard
    project = Project(id='a', title='BP35', nodes=[Node(id='m', project_id='a', node_type=NodeType.METHOD, title='Память агента')], boards=[KanbanBoard(id='b', owner_node_id='m')])
    monkeypatch.setattr(context_routing, 'catalog', lambda: [
        {'project_id': 'a', 'tree_title': 'BP35', 'program_ids': ['agents'], 'program_titles': ['Morpheus'],
         'methods': [{'board_id': 'b', 'method_id': 'm', 'method_title': 'Память агента'}]},
        {'project_id': 'other', 'tree_title': 'Другая игра', 'program_ids': [], 'program_titles': [], 'methods': []}])
    monkeypatch.setattr(agents, 'load_project', lambda pid, **kw: project if pid == 'a' else None)
    monkeypatch.setattr(agents, 'get_agent_chat_mode', lambda: 'local')
    monkeypatch.setattr(agents, 'cli_agents', lambda: [])
    return context_routing


def routing_answer(options=None, awaiting=True):
    return 'Сначала выберите контекст.\n```research_context\n' + json.dumps({
        'awaiting_selection': awaiting,
        'options': options if options is not None else [{'project_id': 'a', 'board_id': 'b'}],
    }) + '\n```'


def test_context_options_validated_persisted_and_private(routing):
    chat = chats.create()
    item = queue.enqueue_question(None, 'Поставь эксперимент BP35', conversation_id=chat['id'])
    reply = queue.submit_answer(item['id'], routing_answer([
        {'project_id': 'a', 'board_id': 'b', 'tree_title': '<script>fake</script>'},
        {'project_id': 'other', 'board_id': 'b'},
    ]))
    assert reply['answer'] == 'Сначала выберите контекст.'
    options = queue.find_item(item['id'])['context_suggestions']['options']
    assert len(options) == 1 and options[0]['tree_title'] == 'BP35'
    assert options[0]['method_title'] == 'Память агента'
    assert chats.find(chat['id'])['project_id'] is None
    assert routing.parse_reply('Обычный общий ответ') == ('Обычный общий ответ', None)
    assert routing.parse_reply('Ответ\n```research_context\n{bad json}\n```') == ('Ответ', None)
    for candidate in [{'project_id': []}, {'project_id': 'missing'}, {'project_id': 'a', 'board_id': 'missing'}]:
        assert routing.parse_reply(routing_answer([candidate]))[1] is None


def test_context_choice_resumes_only_after_explicit_selection(routing):
    from api.routers import agents
    from api.schemas import ConversationContextChoiceBody
    chat = chats.create()
    first = queue.enqueue_question(None, 'Поставь эксперимент BP35', conversation_id=chat['id'])
    queue.submit_answer(first['id'], routing_answer())
    tasks = BackgroundTasks()
    choice = ConversationContextChoiceBody(item_id=first['id'], option=0)
    moved = agents.choose_conversation_context(chat['id'], choice, tasks)['item']
    assert moved['project_id'] == 'a' and moved['board_id'] == 'b'
    history = chats.messages(chat['id'])
    assert len(history) == 2 and history[0]['question'] == first['question']
    assert history[0]['project_id'] == 'a' and history[0]['board_id'] == 'b'
    assert history[0]['method_id'] == 'm' and history[0]['node_id'] == 'm'
    assert history[0]['status'] == 'pending' and len(tasks.tasks) == 1
    assert queue.find_item(first['id'])['context_suggestions']['resolved']
    with pytest.raises(HTTPException) as error:
        agents.choose_conversation_context(chat['id'], choice, BackgroundTasks())
    assert error.value.status_code == 409 and len(chats.messages(chat['id'])) == 2


def test_context_choice_keeps_general_and_does_not_repeat(routing):
    from api.routers import agents
    from api.schemas import ConversationContextChoiceBody
    from koi.agent_chat import cli
    chat = chats.create()
    first = queue.enqueue_question(None, 'Что известно про BP35?', conversation_id=chat['id'])
    queue.submit_answer(first['id'], routing_answer(awaiting=False))
    tasks = BackgroundTasks()
    agents.choose_conversation_context(chat['id'], ConversationContextChoiceBody(item_id=first['id']), tasks)
    assert not tasks.tasks and chats.find(chat['id'])['project_id'] is None
    second = queue.enqueue_question(None, 'Продолжим общий разговор', conversation_id=chat['id'])
    assert cli.build_context(second['id'])['context_suggestions_dismissed'] is True
    assert queue.submit_answer(second['id'], routing_answer())['context_suggestions'] is None


def test_context_choice_rejects_cross_chat_pending_and_invalid(routing):
    from api.routers import agents
    from api.schemas import ConversationContextChoiceBody
    chat, other = chats.create(), chats.create()
    first = queue.enqueue_question(None, 'BP35', conversation_id=chat['id'])
    queue.submit_answer(first['id'], routing_answer(awaiting=False))
    choice = ConversationContextChoiceBody(item_id=first['id'], option=0)
    with pytest.raises(HTTPException) as error:
        agents.choose_conversation_context(other['id'], choice, BackgroundTasks())
    assert error.value.status_code == 404
    with pytest.raises(HTTPException):
        agents.choose_conversation_context(chat['id'], ConversationContextChoiceBody(item_id=first['id'], option=1), BackgroundTasks())
    pending = queue.enqueue_question(None, 'Ещё вопрос', conversation_id=chat['id'])
    with pytest.raises(HTTPException) as error:
        agents.choose_conversation_context(chat['id'], choice, BackgroundTasks())
    assert error.value.status_code == 409
    queue.submit_answer(pending['id'], 'Ответ')
    agents.choose_conversation_context(chat['id'], choice, BackgroundTasks())
    assert len(chats.messages(chat['id'])) == 2  # informational reply only moves, never reruns


def test_context_choice_rolls_back_when_continuation_cannot_start(routing, monkeypatch):
    from api.routers import agents
    from api.schemas import ConversationContextChoiceBody
    chat = chats.create()
    item = queue.enqueue_question(None, 'Поставь эксперимент BP35', conversation_id=chat['id'])
    queue.submit_answer(item['id'], routing_answer())
    def unavailable(*_args, **_kwargs):
        raise HTTPException(400, 'Агент недоступен')
    monkeypatch.setattr(agents, 'post_agent_chat', unavailable)
    with pytest.raises(HTTPException):
        agents.choose_conversation_context(chat['id'], ConversationContextChoiceBody(item_id=item['id'], option=0), BackgroundTasks())
    assert chats.find(chat['id'])['project_id'] is None
    assert len(chats.messages(chat['id'])) == 1
    assert not queue.find_item(item['id'])['context_suggestions'].get('resolved')


def test_program_chat_remembers_program_without_binding_tree(routing, monkeypatch):
    from api.routers import agents
    from api.schemas import ConversationCreateBody, ConversationContextChoiceBody
    from koi.agent_chat import cli
    from koi.adapters import repository
    monkeypatch.setattr(repository, 'list_projects', lambda: [])
    chat = agents.create_conversation(ConversationCreateBody(program_id='agents', focus_project_id='a'))['item']
    assert chat['project_id'] is None and chat['program_id'] == 'agents' and chat['focus_project_id'] == 'a'
    item = queue.enqueue_question(None, 'Эксперимент BP35', conversation_id=chat['id'])
    context = cli.build_context(item['id'])
    assert context['program_id'] == 'agents'
    assert [r['project_id'] for r in context['context_catalog']] == ['a']
    answered = queue.submit_answer(item['id'], routing_answer([{'project_id': 'a', 'board_id': 'b'}, {'project_id': 'other'}]))
    assert len(answered['context_suggestions']['options']) == 1
    tasks = BackgroundTasks()
    moved = agents.choose_conversation_context(chat['id'], ConversationContextChoiceBody(item_id=item['id'], option=0), tasks)['item']
    assert moved['project_id'] == 'a' and moved['program_id'] == 'agents'
    assert moved['focus_project_id'] is None and len(tasks.tasks) == 1


def test_program_chat_rejects_invalid_membership_and_stale_suggestions(routing, monkeypatch):
    from api.routers import agents
    from api.schemas import ConversationCreateBody, ConversationContextChoiceBody
    original_load = agents.load_project
    monkeypatch.setattr(agents, 'load_project', lambda pid, **kw: SimpleNamespace(boards=[]) if pid == 'other' else original_load(pid, **kw))
    for body in [ConversationCreateBody(program_id='missing'),
                 ConversationCreateBody(program_id='agents', focus_project_id='other'),
                 ConversationCreateBody(program_id='agents', project_id='other'),
                 ConversationCreateBody(focus_project_id='a')]:
        with pytest.raises(HTTPException) as error:
            agents.create_conversation(body)
        assert error.value.status_code == 400
    chat = chats.create(program_id='agents')
    item = queue.enqueue_question(None, 'BP35', conversation_id=chat['id'])
    queue.submit_answer(item['id'], routing_answer())
    # A persisted suggestion must still belong to the program when it is chosen.
    chats.update(chat['id'], program_id='ungrouped')
    with pytest.raises(HTTPException) as error:
        agents.choose_conversation_context(chat['id'], ConversationContextChoiceBody(item_id=item['id'], option=0), BackgroundTasks())
    assert error.value.status_code == 400 and chats.find(chat['id'])['project_id'] is None


def test_activity_requires_processing_owner_and_ignores_waiting(state, monkeypatch):
    chat = chats.create('a')
    item = queue.enqueue_question('a', 'Вопрос', conversation_id=chat['id'])
    assert chats.find(chat['id'])['pending']
    assert not chats.find(chat['id'])['agent_active']
    queue.mark_processing(item['id'])
    assert chats.find(chat['id'])['agent_active']
    queue.clear_processing_pid(item['id'])
    assert not chats.find(chat['id'])['agent_active']
    queue.mark_processing(item['id'])
    real_kill = queue.os.kill
    def dead_owner(pid, signal):
        if pid == queue.os.getpid():
            raise ProcessLookupError()
        return real_kill(pid, signal)
    monkeypatch.setattr(queue.os, 'kill', dead_owner)
    assert not chats.find(chat['id'])['agent_active']
    queue.submit_answer(item['id'], 'Ответ')
    assert not chats.find(chat['id'])['agent_active']


@pytest.mark.parametrize('failed', [False, True])
def test_runner_releases_activity_on_answer_and_error(state, monkeypatch, failed):
    from koi.agent_chat import runner
    chat = chats.create('a')
    item = queue.enqueue_question('a', 'Вопрос', conversation_id=chat['id'], cli_agent='codex')
    monkeypatch.setattr(runner, 'load_env_file', lambda: None)
    monkeypatch.setattr(runner, 'is_api_agent_mode', lambda: False)
    monkeypatch.setattr(runner, 'is_cursor_manual_agent_mode', lambda: False)
    monkeypatch.setattr(runner, 'cli_agents', lambda: [{'id':'codex', 'label':'Codex', 'available':True}])
    monkeypatch.setattr(runner, '_sdk_prompt', lambda _: 'Вопрос')
    def answer(*args, **kwargs):
        assert chats.find(chat['id'])['agent_active']
        if failed:
            raise RuntimeError('test agent error')
        return 'Ответ', 'Codex'
    monkeypatch.setattr(runner, '_run_local_agent', answer)
    assert runner.process_item(item['id'])
    assert not chats.find(chat['id'])['agent_active']
    assert queue.find_item(item['id']).get('processing_pid') is None
