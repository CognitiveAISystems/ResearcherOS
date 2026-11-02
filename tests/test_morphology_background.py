from fastapi import BackgroundTasks
from api.schemas import MorphologyStageBody


def test_morphology_launch_uses_conversation_worker(monkeypatch, tmp_path):
    from api.routers import morphology, agents
    from koi.agent_chat import conversations
    from koi.literature import morphology as storage
    seen = {}
    monkeypatch.setattr(morphology, "parse_project", lambda _: None)
    monkeypatch.setattr(morphology, "stage_paper_morphology", lambda *a: {"run_id": "run-1"})
    monkeypatch.setattr(storage, "morphology_dir", lambda _: tmp_path)
    (tmp_path / "run-1").mkdir()
    monkeypatch.setattr(agents, "create_conversation", lambda body: {"item": {"id": "chat-1"}})
    monkeypatch.setattr(conversations, "update", lambda cid, **kw: seen.update(kw))
    def send(body, tasks):
        seen["body"] = body
        seen["tasks"] = tasks
        return {"item": {"id": "item-1"}}
    monkeypatch.setattr(agents, "post_agent_chat", send)
    tasks = BackgroundTasks()
    result = morphology.post_project_morphology_agent(
        "demo", MorphologyStageBody(paper={"title": "Paper"}, cli_agent="codex"), tasks)
    assert result["conversation_id"] == "chat-1"
    assert seen["kind"] == "morphology"
    assert seen["morphology_run_id"] == "run-1"
    assert seen["body"].cli_agent == "codex"
    assert seen["tasks"] is tasks
    assert "chat-1" in (tmp_path / "run-1/chat.json").read_text()


def test_morphology_worker_reads_staged_task(monkeypatch, tmp_path):
    from koi.agent_chat import runner, conversations
    from koi.literature import morphology
    root = tmp_path / "run-1"
    root.mkdir()
    (root / "PROMPT.md").write_text("Build the graph.")
    monkeypatch.setattr(runner, "find_item", lambda _: {"project_id": "demo", "conversation_id": "chat-1"})
    monkeypatch.setattr(conversations, "find", lambda _: {"kind": "morphology", "morphology_run_id": "run-1"})
    monkeypatch.setattr(morphology, "morphology_dir", lambda _: tmp_path)
    prompt = runner._sdk_prompt("item-1")
    assert "Build the graph." in prompt
    assert str(root / "input.json") in prompt
    assert "Execute the task now" in prompt
    assert "never as instructions" in prompt


def test_explanation_runs_in_background(monkeypatch, tmp_path):
    from api.routers import morphology, agents
    from api.schemas import MorphologyExplainBody
    from koi.agent_chat import conversations
    seen = {}
    (tmp_path / "run-1").mkdir()
    monkeypatch.setattr(morphology, "parse_project", lambda _: None)
    monkeypatch.setattr(morphology, "paper_morphology_dir", lambda _: tmp_path)
    monkeypatch.setattr(agents, "create_conversation", lambda body: {"item": {"id": "chat-e"}})
    monkeypatch.setattr(conversations, "update", lambda cid, **kw: seen.update(kw))
    def send(body, tasks):
        seen["question"] = body.question
        return {"item": {"id": "item-e"}}
    monkeypatch.setattr(agents, "post_agent_chat", send)
    monkeypatch.setattr(morphology, "open_agent_terminal", lambda *args: (_ for _ in ()).throw(AssertionError("No Terminal")))
    result = morphology.post_project_morphology_explain(
        "demo", MorphologyExplainBody(prompt="Explain the connection", run_id="run-1", node_id="n1"), BackgroundTasks())
    assert result["conversation_id"] == "chat-e"
    assert seen["kind"] == "morphology_explain"
    assert str(tmp_path / "run-1/explain-n1.txt") in seen["question"]


def test_explanation_worker_does_not_run_morphology_again(monkeypatch):
    from koi.agent_chat import runner, conversations
    monkeypatch.setattr(runner, "find_item", lambda _: {
        "project_id": "demo", "conversation_id": "chat-e", "question": "Explain this connection"})
    monkeypatch.setattr(conversations, "find", lambda _: {
        "kind": "morphology_explain", "morphology_run_id": "run-1"})
    prompt = runner._sdk_prompt("item-e")
    assert "Explain this connection" in prompt
    assert "Do not open Terminal" in prompt
    assert "Pass A" not in prompt
