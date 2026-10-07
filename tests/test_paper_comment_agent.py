"""A paper comment asks the hidden CLI with the copied review block."""

from types import SimpleNamespace

import pytest

from api.routers import paper as paper_router
from koi.paper import comment_agent
from koi.paper.comments import create_comment


def test_launch_creates_proposal_and_reply(monkeypatch, tmp_path) -> None:
    seen = {}
    monkeypatch.delenv("KOI_PAPER_COMMENT_MODEL", raising=False)
    (tmp_path / "main.tex").write_text("old text\n", encoding="utf-8")

    def fake(prompt, item_id, *, mode=None, force=False, cwd=None, timeout=1800, model=None, fallback=True):
        seen["prompt"] = prompt
        seen["item_id"] = item_id
        seen["mode"] = mode
        seen["force"] = force
        seen["cwd"] = cwd
        seen["timeout"] = timeout
        seen["model"] = model
        seen["fallback"] = fallback
        (cwd / "main.tex").write_text("new text\n", encoding="utf-8")
        return ("ok", "Cursor CLI")

    monkeypatch.setattr(comment_agent, "_run_local_agent", fake)
    monkeypatch.setattr(comment_agent, "get_or_create_session", lambda *_: SimpleNamespace(proposal=object(), import_external=lambda candidate, **kwargs: seen.update(candidate=candidate, source=kwargs["source"])))
    monkeypatch.setattr(comment_agent, "add_reply", lambda *args, **kwargs: seen.update(reply=kwargs["body"]))
    monkeypatch.setattr(
        comment_agent.threading,
        "Thread",
        lambda target, args, daemon, name: SimpleNamespace(start=lambda: target(*args)),
    )
    prompt = "Paper review · main.tex L48 · demo/zerohero\n\n> what is an interactive task?"
    assert comment_agent.launch("demo", "zerohero", "c_abc", prompt, tmp_path)["status"] == "running"
    assert seen["prompt"] == prompt
    assert seen["item_id"] == "demo/zerohero/c_abc"
    assert seen["mode"] is None
    assert seen["force"] is True
    assert seen["cwd"] != tmp_path
    assert seen["timeout"] == 180
    assert seen["model"] == "gpt-5.3-codex-low-fast"
    assert seen["fallback"] is False
    assert seen["candidate"] == "new text\n"
    assert seen["source"] == "paper-comment-agent"
    assert seen["reply"] == "ok"
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == "old text\n"
    assert comment_agent.status("demo", "zerohero", "c_abc")["status"] == "done"


def test_second_launch_is_rejected() -> None:
    comment_agent._jobs["demo/zerohero/c_busy"] = {"status": "running", "error": None}
    with pytest.raises(RuntimeError):
        comment_agent.launch("demo", "zerohero", "c_busy", "Paper review")


def test_endpoint_forwards_prompt(monkeypatch, tmp_path) -> None:
    (tmp_path / "main.tex").write_text("interactive tasks\n", encoding="utf-8")
    comment = create_comment(
        tmp_path, line_start=1, line_end=1, char_start=0, char_end=11,
        selected_text="interactive", body="define it",
    )
    monkeypatch.setattr(paper_router, "_require_paper_slot", lambda _pid, _slug: ("zerohero", tmp_path))
    called = {}

    def fake_launch(project_id, slug, comment_id, prompt, slot_dir):
        called.update(project_id=project_id, slug=slug, comment_id=comment_id, prompt=prompt, slot_dir=slot_dir)
        return {"status": "running"}

    monkeypatch.setattr(paper_router, "launch_comment_agent", fake_launch)
    body = SimpleNamespace(prompt="Paper review · exact")
    response = paper_router.post_project_paper_comment_agent("demo", "zerohero", comment["id"], body)
    assert response == {"ok": True, "status": "running"}
    assert "Замечание к main.tex (строка 1, символы 1–11): define it" in called["prompt"]
    assert "Выделенный текст, к которому относится замечание:\ninteractive" in called["prompt"]
    assert "1: interactive tasks" in called["prompt"]
    assert "Paper review · exact" not in called["prompt"]
    assert called["slot_dir"] == tmp_path
    assert called["comment_id"] == comment["id"]
