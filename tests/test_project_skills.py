"""Skills persist across contexts without leaking to adjacent methods or projects."""
import json

import pytest

from koi.agent_chat import project_skills as skills
from koi.core.models import ExperimentCard, KanbanBoard, Node, NodeType, Project


@pytest.fixture
def project(tmp_path, monkeypatch):
    nodes = [Node(id=m, project_id="demo", parent_id=None, node_type=NodeType.METHOD, title=m)
             for m in ("m1", "m2")]
    boards = [KanbanBoard(id=f"b{i}", owner_node_id=f"m{i}", cards=[
        ExperimentCard(id=f"c{i}", board_id=f"b{i}", column_id="backlog", title="Report")]) for i in (1, 2)]
    project = Project(id="demo", title="Demo", nodes=nodes, boards=boards)
    monkeypatch.setattr(skills, "koi_root", lambda pid: tmp_path / pid)
    monkeypatch.setattr(skills, "load_project", lambda *_a, **_kw: project)
    return tmp_path / "demo"


def create(root, name):
    path = root / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nname: {name}\ndescription: Check research evidence\n---\nCompare evidence before conclusions.\n")
    return path


def names(ctx):
    assert not ctx["skill_errors"]
    return {s["name"] for s in ctx["applicable_project_skills"]}


def test_levels_are_reusable_in_every_context_and_keep_work_boundaries(project):
    for name in ("tree-check", "method-check", "card-check"):
        create(project, name)
    skills.bind("demo", "tree-check", "tree")
    skills.bind("demo", "method-check", "method")
    skills.bind("demo", "card-check", "card")
    skills.bind("demo", "card-check", "card")
    assert len(json.loads((project / "skills/bindings.json").read_text())["bindings"]) == 3
    assert names(skills.context("demo")) == {"tree-check"}
    for i in (1, 2):
        assert names(skills.context("demo", method_id=f"m{i}")) == {"method-check"}
        ctx = skills.context("demo", board_id=f"b{i}", card_id=f"c{i}", question="/card-check Compare")
        assert names(ctx) == {"card-check"}
        assert ctx["selected_project_skill"]["name"] == "card-check"
        assert ctx["skill_execution_scope"] == {"level": "card", "project_id": "demo", "method_id": f"m{i}", "board_id": f"b{i}", "card_id": f"c{i}"}
    assert names(skills.context("other", method_id="m1")) == set()
    # Re-read on every context: no registry cache that could outlive a restart.
    skills.bind("demo", "card-check", "method")
    skills.bind("demo", "card-check", "card", remove=True)
    assert names(skills.context("demo", method_id="m2")) == {"method-check", "card-check"}
    assert names(skills.context("demo", card_id="c1")) == set()
    assert (project / "skills/card-check/SKILL.md").exists()


@pytest.mark.parametrize("name,scope,target", [
    ("../escape", "tree", ""), ("absent", "tree", ""),
    ("good", "tree", "m1"), ("good", "method", "other-method"),
    ("good", "report", "other-card"), ("good", "anything", ""),
])
def test_invalid_attachment_does_not_write_registry(project, name, scope, target):
    create(project, "good")
    with pytest.raises((ValueError, OSError)):
        skills.bind("demo", name, scope, target)
    assert not (project / "skills/bindings.json").exists()


def test_invalid_metadata_missing_file_and_corrupt_bindings_are_visible(project):
    path = create(project, "good")
    path.write_text("---\nname: wrong\ndescription: test\n---\nInstructions")
    with pytest.raises(ValueError):
        skills.bind("demo", "good", "tree")
    create(project, "good")
    skills.bind("demo", "good", "tree")
    path.unlink()
    assert skills.context("demo")["skill_errors"]
    (project / "skills/bindings.json").write_text("broken")
    assert skills.context("demo")["skill_errors"]
    with pytest.raises(ValueError):
        skills.bind("demo", "good", "tree", remove=True)
    assert (project / "skills/bindings.json").read_text() == "broken"
    assert not (project / "skills/.bindings-lock").exists()


def test_yaml_delimiter_is_a_whole_line(project):
    path = create(project, "good")
    path.write_text('---\nname: good\ndescription: "Evidence---then conclusion"\n---\nCheck evidence.\n')
    skills.bind("demo", "good", "tree")
    assert names(skills.context("demo")) == {"good"}


def test_external_symlink_and_active_writer_are_rejected(project, tmp_path):
    outside = tmp_path / "external"
    outside.mkdir()
    (project / "skills").mkdir(parents=True)
    (project / "skills/escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes"):
        skills.bind("demo", "escape", "tree")
    create(project, "good")
    (project / "skills/.bindings-lock").mkdir()
    with pytest.raises(FileExistsError):
        skills.bind("demo", "good", "tree")
    assert not (project / "skills/bindings.json").exists()


def test_chat_prompt_receives_skills_for_specialized_report_mode(project, monkeypatch):
    from koi.agent_chat import runner
    from koi.adapters import glossary
    create(project, "report-check")
    skills.bind("demo", "report-check", "card")
    monkeypatch.setattr(runner, "find_item", lambda _: {
        "project_id": "demo", "board_id": "b1", "card_id": "c1", "purpose": "report_grill"})
    monkeypatch.setattr(glossary, "prompt", lambda _: "")
    monkeypatch.setattr(runner, "_base_sdk_prompt", lambda _: "Interview policy: no writes")
    prompt = runner._sdk_prompt("aq-test")
    assert str(project / "skills/report-check/SKILL.md") in prompt
    assert str(skills.CREATOR) in prompt
    assert "Interview policy: no writes" in prompt


def test_cli_bind_list_unbind(project, monkeypatch, capsys):
    import sys
    create(project, "good")
    for action in ("bind", "list", "unbind"):
        args = ["skills", action, "demo"]
        if action != "list":
            args += ["--skill", "good", "--scope", "method"]
        monkeypatch.setattr(sys, "argv", args)
        skills.main()
        output = json.loads(capsys.readouterr().out)
        assert bool(output["bindings"]) == (action != "unbind")


def test_bundled_cli_dispatch_and_command(project, monkeypatch, capsys):
    import sys
    from api import desktop_server
    create(project, "good")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert skills.command() == [sys.executable, "--project-skills"]
    monkeypatch.setattr(sys, "argv", ["researchos-server", "--project-skills", "bind", "demo",
                                     "--skill", "good", "--scope", "tree"])
    assert desktop_server.main() == 0
    assert json.loads(capsys.readouterr().out)["bindings"][0]["scope"] == "tree"


def test_executor_uses_selected_method_skills(project, tmp_path, monkeypatch):
    from koi.agent_chat import research, research_runtime
    from koi.adapters import agent_chat_activity
    create(project, "method-check")
    skills.bind("demo", "method-check", "method")
    monkeypatch.setattr(research, "PATH", tmp_path / "runs.sqlite3")
    monkeypatch.setattr(agent_chat_activity, "ACTIVITY_DIR", tmp_path / "activity")
    run = research.create_run("chat-skills", "aq-skills", "demo", "Check evidence")
    with research._db() as db:
        db.execute("UPDATE runs SET metadata=? WHERE id=?", (json.dumps({"research_scope": {"method_id": "m1"}}), run))
    prompts = []
    monkeypatch.setattr(research_runtime, "run_agent", lambda prompt, **kw: (prompts.append(prompt) or "Checked", "Codex"))
    result = research_runtime.execute(run, {"backend": "codex", "cwd": str(tmp_path), "task": "Review", "readonly": True})
    assert result["status"] == "completed"
    assert str(project / "skills/method-check/SKILL.md") in prompts[0]
    assert "Работай только на чтение" in prompts[0]


def test_menu_api_returns_only_skills_at_requested_level(project, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routers import agents
    monkeypatch.setattr(agents, "load_project", skills.load_project)
    create(project, "shap")
    create(project, "plan-method")
    create(project, "edit-tree")
    skills.bind("demo", "shap", "card")
    skills.bind("demo", "plan-method", "method")
    skills.bind("demo", "edit-tree", "tree")
    app = FastAPI()
    app.include_router(agents.router)
    client = TestClient(app)
    for level, name in (("card", "shap"), ("method", "plan-method"), ("tree", "edit-tree")):
        response = client.get(f"/projects/demo/skills?level={level}")
        assert response.status_code == 200
        assert [row["command"] for row in response.json()["items"]] == [name]
    assert client.get("/projects/demo/skills?level=report").status_code == 422


def test_selected_card_skill_can_only_write_current_card(project, tmp_path, monkeypatch):
    from koi.agent_chat import research, research_tools
    from koi.adapters import agent_chat_activity
    create(project, "shap")
    skills.bind("demo", "shap", "card")
    monkeypatch.setattr(research, "PATH", tmp_path / "runs.sqlite3")
    monkeypatch.setattr(agent_chat_activity, "ACTIVITY_DIR", tmp_path / "activity")
    monkeypatch.setattr(research_tools.repository, "load_project", skills.load_project)
    monkeypatch.setattr(research_tools.card_reports, "write_report", lambda *args: {"card": args[2]})
    for i in (1, 2):
        item = {"id": f"aq-skill{i}", "conversation_id": f"chat-{i}", "project_id": "demo",
                "board_id": f"b{i}", "card_id": f"c{i}", "question": "/shap Analyse model"}
        run, _ = research.prepare_delegation(item, allow_edits=True)
        assert research_tools.perform(run, "write_report", {"board_id": f"b{i}", "card_id": f"c{i}", "content": "SHAP result"}) == {"card": f"c{i}"}
        for operation, args in (("write_report", {"board_id": f"b{3-i}", "card_id": f"c{3-i}", "content": "wrong"}),
                                ("create_card", {"board_id": f"b{i}", "title": "New"}),
                                ("update_node", {"node_id": f"m{i}", "description": "wrong"}),
                                ("scope", {"level": "tree"})):
            with pytest.raises(ValueError):
                research_tools.perform(run, operation, args)


def test_method_skill_can_create_cards_only_in_current_method(project, tmp_path, monkeypatch):
    from koi.agent_chat import research, research_tools
    from koi.adapters import agent_chat_activity
    create(project, "plan-method")
    skills.bind("demo", "plan-method", "method")
    monkeypatch.setattr(research, "PATH", tmp_path / "runs.sqlite3")
    monkeypatch.setattr(agent_chat_activity, "ACTIVITY_DIR", tmp_path / "activity")
    monkeypatch.setattr(research_tools.repository, "load_project", skills.load_project)
    created = []
    def create_card(pid, bid, command):
        created.append(bid)
        return skills.load_project(pid)
    monkeypatch.setattr(research_tools.commands, "create_card", create_card)
    for i in (1, 2):
        run, _ = research.prepare_delegation({"id": f"aq-method{i}", "conversation_id": f"chat-method-{i}",
                "project_id": "demo", "board_id": f"b{i}", "question": "/plan-method Create experiment"}, allow_edits=True)
        research_tools.perform(run, "create_card", {"board_id": f"b{i}", "title": "New experiment"})
        with pytest.raises(ValueError):
            research_tools.perform(run, "create_card", {"board_id": f"b{3-i}", "title": "Wrong method"})
        with pytest.raises(ValueError):
            research_tools.perform(run, "create_node", {"title": "Wrong node"})
    assert created == ["b1", "b2"]
