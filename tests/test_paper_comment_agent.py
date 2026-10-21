"""A paper comment asks the hidden CLI with the copied review block."""

from types import SimpleNamespace

from api.routers import paper as paper_router
from koi.paper.comments import create_comment


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
