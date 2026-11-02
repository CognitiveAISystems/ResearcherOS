from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from koi.adapters import glossary


@pytest.fixture
def vocabulary(monkeypatch, tmp_path):
    monkeypatch.setattr(glossary, "get_workspace", lambda: SimpleNamespace(agent_cwd=lambda: tmp_path))
    monkeypatch.setattr(glossary, "koi_root", lambda project: tmp_path / "tree" / project / "koi-structure")
    return tmp_path


def test_scopes_preserve_global_rules_and_override_locally(vocabulary):
    glossary.write("пайплайн > процесс\nпостановка — описание эксперимента", glossary.read()["revision"])
    glossary.write("пайплайн > последовательность", glossary.read("a")["revision"], "a")
    a = glossary.context("a")
    b = glossary.context("b")
    assert a["effective"][0]["replacement"] == "последовательность"
    assert a["effective"][0]["scope"] == "tree"
    assert b["effective"][0]["replacement"] == "процесс"
    assert a["effective"][1]["meaning"] == "описание эксперимента"
    assert glossary.global_path() == vocabulary / "tree/glossary.txt"


def test_stale_save_never_overwrites_fresh_text(vocabulary):
    old = glossary.read()
    glossary.write("термин", old["revision"])
    with pytest.raises(FileExistsError):
        glossary.write("другое", old["revision"])
    assert glossary.read()["text"] == "термин"


@pytest.mark.parametrize("text", ["слово >", "> замена", "a > b > c", "Термин\nтермин > другое"])
def test_invalid_dictionary_is_rejected(vocabulary, text):
    with pytest.raises(ValueError):
        glossary.write(text, glossary.read()["revision"])
    assert not glossary.global_path().exists()


def test_external_malformed_file_can_be_opened_and_repaired(vocabulary):
    path = glossary.global_path()
    path.parent.mkdir()
    path.write_text("термин >", encoding="utf-8")
    ctx = glossary.context()
    assert ctx["errors"] and ctx["global"]["text"] == "термин >"
    glossary.write("термин > замена", ctx["global"]["revision"])
    assert not glossary.context()["errors"]


def test_http_validation_and_conflict(vocabulary, monkeypatch):
    from api.routers import glossary as routes
    monkeypatch.setattr(routes, "get_project", lambda project: None)
    monkeypatch.setattr(routes, "enqueue_sync", lambda *args: None)
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)
    revision = client.get("/glossary").json()["global"]["revision"]
    assert client.put("/glossary", json={"text": "a >", "revision": revision}).status_code == 400
    assert client.put("/glossary", json={"text": "a > b", "revision": revision}).status_code == 200
    assert client.put("/glossary", json={"text": "c", "revision": revision}).status_code == 409
    local = client.get("/glossary?project_id=a").json()["tree"]
    assert client.put("/glossary?project_id=a", json={"text": "a > c", "revision": local["revision"]}).status_code == 200
    assert client.get("/glossary?project_id=a").json()["effective"][0]["replacement"] == "c"


def test_agent_writer_and_critic_receive_current_vocabulary(vocabulary, monkeypatch):
    from koi.agent_chat import runner, setup_pipeline
    glossary.write("пайплайн > процесс", glossary.read()["revision"])
    monkeypatch.setattr(runner, "find_item", lambda _: {"project_id": "a"})
    monkeypatch.setattr(runner, "_base_sdk_prompt", lambda _: "Запрос человека")
    assert "пайплайн" in runner._sdk_prompt("item")
    assert "словар" in setup_pipeline._writer_prompt({"glossary": glossary.context("a")}).lower()
    captured = []
    monkeypatch.setattr(runner, "_run_local_agent", lambda prompt, *args, **kwargs: (captured.append(prompt) or "PASS", "test"))
    assert runner._review_grill_proposal("item", {}, local_mode=True, log_activity=False)[0]
    assert "пайплайн" in captured[0] and "стилистическим причинам" in captured[0]
    glossary.write("пайплайн > последовательность", glossary.read()["revision"])
    assert "последовательность" in runner._sdk_prompt("item")


def test_report_ingest_agent_receives_vocabulary(vocabulary):
    from koi.projects.report_ingest.cli import build_prompt
    from koi.core.models import NodeType
    glossary.write("пайплайн > процесс", glossary.read()["revision"])
    method = SimpleNamespace(id="m", title="Метод", description="", node_type=NodeType.METHOD)
    project = SimpleNamespace(id="a", title="Исследование")
    card = SimpleNamespace(id="c", title="Проверка", description="")
    result = build_prompt(project, None, card, {"method": method}, vocabulary / "report.run.md")
    assert "пайплайн" in result and "процесс" in result
