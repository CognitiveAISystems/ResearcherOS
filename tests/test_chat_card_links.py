"""Agent card attachments are validated and survive queue/history reloads."""
import json
from types import SimpleNamespace

import pytest

from koi.adapters import agent_chat_queue as queue, repository
from koi.agent_chat import card_links, context_routing, conversations, runner


@pytest.fixture
def state(monkeypatch, tmp_path):
    monkeypatch.setattr(queue, "QUEUE_PATH", tmp_path / "queue.json")
    monkeypatch.setattr(conversations, "PATH", tmp_path / "chats.json")
    project = SimpleNamespace(boards=[SimpleNamespace(id="b", cards=[
        SimpleNamespace(id="new", title="Новая карточка"),
        SimpleNamespace(id="old", title="Изменённая карточка"),
    ])])
    monkeypatch.setattr(repository, "load_project", lambda pid, **kw: project if pid in ("demo", "other") else None)
    monkeypatch.setattr(context_routing, "catalog", lambda: [
        {"project_id": "demo", "program_ids": ["agents"]},
        {"project_id": "other", "program_ids": ["elsewhere"]},
    ])


def reply(*refs):
    return "Готово.\n```research_cards\n" + json.dumps([
        {"project_id": pid, "board_id": bid, "card_id": cid} for pid, bid, cid in refs
    ]) + "\n```"


def test_project_chat_attaches_created_and_changed_cards_without_moving(state):
    chat = conversations.create("demo")
    item = queue.enqueue_question("demo", "Создай карточку", conversation_id=chat["id"])
    queue.submit_answer(item["id"], reply(("demo", "b", "new"), ("demo", "b", "old"),
                                         ("demo", "b", "new"), ("demo", "bad", "new"),
                                         ("demo", "b", "missing"), ("other", "b", "new")))
    saved = conversations.messages(chat["id"])[0]
    assert saved["answer"] == "Готово."
    assert [link["card_id"] for link in saved["card_links"]] == ["new", "old"]
    assert saved["card_links"][0]["title"] == "Новая карточка"
    assert conversations.find(chat["id"])["card_id"] is None
    conversations.update(chat["id"], project_id=None, board_id=None, card_id=None)
    assert queue.find_item(item["id"])["card_links"] == saved["card_links"]
    queue.submit_answer(item["id"], "Ответ без карточек")
    assert queue.find_item(item["id"])["card_links"] == []


def test_global_program_chat_only_attaches_cards_from_its_program(state):
    chat = conversations.create(program_id="agents")
    item = queue.enqueue_question(None, "Сравни карточки", conversation_id=chat["id"])
    saved = queue.submit_answer(item["id"], reply(("demo", "b", "new"), ("other", "b", "new")))
    assert [link["project_id"] for link in saved["card_links"]] == ["demo"]


@pytest.mark.parametrize("block", ["{bad json}", "{}", '[null, 1, {}, {"project_id":[]}]'])
def test_malformed_attachments_do_not_break_answer(state, block):
    text, links = card_links.parse_reply("Ответ.\n```research_cards\n" + block + "\n```", {"project_id": "demo"})
    assert text == "Ответ."
    assert links == []


@pytest.mark.parametrize("project_id", [None, "demo"])
def test_main_chat_prompt_asks_agent_to_attach_cards(monkeypatch, project_id):
    monkeypatch.setattr(runner, "build_context", lambda _: {
        "project_id": project_id, "purpose": "agent",
        "card_link_instructions": card_links.INSTRUCTIONS,
    })
    prompt = runner._sdk_prompt("test")
    assert "research_cards" in prompt
    assert "обязательно прикрепи" in prompt
    assert "после создания перечитай project.md" in prompt
