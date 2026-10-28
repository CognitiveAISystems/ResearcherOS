"""Managed edits are durable proposals; accepted text is never an agent workspace."""
from pathlib import Path
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from api.main import app
from api.routers import paper as paper_router
from api.routers import collaboration as collab_router
from koi.paper import edit_tasks, comment_agent
from koi.paper.collaboration.session import CollabSession
from koi.paper.collaboration.text_ops import merge_proposal


@pytest.fixture
def paper(monkeypatch, tmp_path):
    slot = tmp_path / "paper"
    slot.mkdir()
    (slot / "main.tex").write_text("Intro\n\nMethods\n\nResults\n")
    (slot / "references.bib").write_text("@article{demo}")
    (slot / "figures").mkdir()
    (slot / "figures/chart.png").write_bytes(b"figure")
    session = CollabSession("demo", "paper", slot / "main.tex", watch=False,
                            debounce_s=600, proposal_root=tmp_path / "proposals")
    monkeypatch.setattr(edit_tasks, "TASK_ROOT", tmp_path / "tasks")
    monkeypatch.setattr(edit_tasks, "get_or_create_session", lambda *a: session)
    yield slot, session
    session.close()


def test_copy_roundtrip_accept_and_restart(paper):
    slot, session = paper
    original = (slot / "main.tex").read_bytes()
    task = edit_tasks.begin("demo", "paper", slot, "Clarify methods")
    work = Path(task["workspace"])
    assert (work / "references.bib").is_file()
    assert (work / "figures/chart.png").read_bytes() == b"figure"
    (work / "main.tex").write_text("Intro\n\nBetter methods\n\nResults\n")
    assert (slot / "main.tex").read_bytes() == original
    edit_tasks._running.clear()  # no in-memory task state is needed to submit
    result = edit_tasks.submit("demo", "paper", task["id"])
    assert result["status"] == "review"
    assert (slot / "main.tex").read_bytes() == original
    assert session.proposal.title == "Clarify methods"
    session.accept_proposal(session.proposal.id)
    assert "Better methods" in (slot / "main.tex").read_text()
    assert edit_tasks.get("demo", "paper", task["id"])["status"] == "resolved"
    assert edit_tasks.submit("demo", "paper", task["id"])["status"] == "resolved"


def test_human_edits_during_agent_preserved_and_conflict_blocked(paper):
    slot, session = paper
    task = edit_tasks.begin("demo", "paper", slot, "Improve methods")
    Path(task["workspace"], "main.tex").write_text("Intro\n\nAgent methods\n\nResults\n")
    session.apply_client_text("human", "Human intro\n\nMethods\n\nResults\n", 0)
    edit_tasks.submit("demo", "paper", task["id"])
    assert not session.proposal.conflict
    assert "Human intro" in session.proposal.candidate
    # Another person may type while the proposal is open on our screen.
    old_id = session.proposal.id
    session.apply_client_text("human", "Human intro\n\nHuman methods\n\nResults\n", session.document.revision)
    assert session.proposal.conflict
    with pytest.raises(KeyError):
        session.accept_proposal(old_id)
    with pytest.raises(KeyError):
        session.accept_proposal(session.proposal.id)
    with pytest.raises(KeyError):
        session.resolve_proposal_hunk(session.proposal.id, session.proposal.hunks()[0]["id"], accept=True)
    session.reject_proposal(session.proposal.id)
    assert "Human methods" in (slot / "main.tex").read_text()
    assert "Agent methods" not in (slot / "main.tex").read_text()


def test_existing_conflict_and_proposal_survives_restart(paper, tmp_path):
    slot, session = paper
    task = edit_tasks.begin("demo", "paper", slot, "Change intro")
    Path(task["workspace"], "main.tex").write_text("Agent intro\n\nMethods\n\nResults\n")
    session.apply_client_text("human", "Human intro\n\nMethods\n\nResults\n", 0)
    edit_tasks.submit("demo", "paper", task["id"])
    assert session.proposal.conflict
    session.close()
    restored = CollabSession("demo", "paper", slot / "main.tex", watch=False,
                             proposal_root=tmp_path / "proposals")
    try:
        assert restored.proposal.conflict
        with pytest.raises(KeyError):
            restored.accept_proposal(restored.proposal.id)
        assert restored.proposal.task_id == task["id"]
    finally:
        restored.close()


def test_pending_task_cannot_be_overwritten_by_second_task_or_editor_buffer(paper):
    slot, session = paper
    task = edit_tasks.begin("demo", "paper", slot, "Edit intro")
    with pytest.raises(RuntimeError):
        edit_tasks.begin("demo", "paper", slot, "Other task")
    Path(task["workspace"], "main.tex").write_text("Agent intro\n")
    edit_tasks.submit("demo", "paper", task["id"])
    pid = session.proposal.id
    result = session.import_external("Another file edit\n", source="agent")
    assert not result.ok
    assert session.proposal.id == pid
    with pytest.raises(RuntimeError):
        edit_tasks.begin("demo", "paper", slot, "Other task")


def test_interrupted_and_unchanged_tasks(paper):
    slot, session = paper
    task = edit_tasks.begin("demo", "paper", slot, "Review")
    task["status"] = "running"
    edit_tasks._save(task)
    assert edit_tasks.get("demo", "paper", task["id"])["status"] == "interrupted"
    assert edit_tasks.submit("demo", "paper", task["id"])["status"] == "unchanged"
    assert session.proposal is None


def test_symlinks_and_unsupported_edits_are_not_silently_applied(paper, tmp_path):
    slot, session = paper
    outside = tmp_path / "secret.tex"
    outside.write_text("private")
    (slot / "escape.tex").symlink_to(outside)
    task = edit_tasks.begin("demo", "paper", slot, "Edit")
    work = Path(task["workspace"])
    assert not (work / "escape.tex").exists()
    (work / "references.bib").write_text("changed")
    with pytest.raises(ValueError, match="кроме main.tex"):
        edit_tasks.submit("demo", "paper", task["id"])
    (work / "references.bib").write_text("@article{demo}")
    (work / "main.tex").unlink()
    (work / "main.tex").symlink_to(outside)
    with pytest.raises(ValueError):
        edit_tasks.submit("demo", "paper", task["id"])
    assert session.proposal is None


def test_conflicting_insertion_and_independent_multi_edits():
    assert not merge_proposal("A\n", "human\nA\n", "agent\nA\n").ok
    base = "A\nB\nC\nD\nE\n"
    merged = merge_proposal(base, "human A\nB\nC\nD\nhuman E\n", "A\nB\nagent C\nD\nE\n")
    assert merged.ok and merged.text == "human A\nB\nagent C\nD\nhuman E\n"


def test_sandbox_denies_original_and_metadata_but_allows_copy(paper):
    slot, _ = paper
    task = edit_tasks.begin("demo", "paper", slot, "Edit")
    directory = Path(task["workspace"]).parent
    script = '''from pathlib import Path
import sys
source, work, base = map(Path, sys.argv[1:])
(work / "main.tex").write_text("agent")
for path in [source / "main.tex", base]:
    try: path.write_text("bad")
    except PermissionError: pass
    else: raise AssertionError("original or base is writable")
'''
    try:
        cmd = edit_tasks.sandbox_command([sys.executable, "-c", script, str(slot),
                                         task["workspace"], str(directory / "base.tex")], slot, directory)
    except RuntimeError:
        pytest.skip("OS sandbox not installed")
    result = subprocess.run(cmd, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert (slot / "main.tex").read_text().startswith("Intro")


def test_comment_worker_creates_real_review_and_reply(paper, monkeypatch):
    from koi.paper.comments import create_comment, load_comments
    slot, session = paper
    comment = create_comment(slot, line_start=1, line_end=1, body="Clarify")
    seen = {}
    def run(task, backend):
        seen.update(task)
        Path(task["workspace"], "main.tex").write_text("Clear intro\n\nMethods\n\nResults\n")
        return {"answer": "Clarified", "backend": "fake"}
    monkeypatch.setattr(edit_tasks, "_run", run)
    monkeypatch.setattr(edit_tasks, "sandbox_command", lambda *args: [])
    monkeypatch.setattr(edit_tasks.threading, "Thread", lambda target, args, **kw: SimpleNamespace(start=lambda: target(*args)))
    comment_agent.launch("demo", "paper", comment["id"], "Clarify intro", slot)
    assert seen["source"] != seen["workspace"]
    assert comment_agent.status("demo", "paper", comment["id"])["status"] == "done"
    assert session.proposal is not None
    assert (slot / "main.tex").read_text().startswith("Intro")
    assert load_comments(slot)["comments"][0]["thread"][-1]["body"] == "Clarified"


def test_api_prepare_submit_accept_and_path_validation(paper, monkeypatch):
    slot, session = paper
    monkeypatch.setattr(paper_router, "_require_paper_slot", lambda *_: ("paper", slot))
    monkeypatch.setattr(collab_router, "_session", lambda *args, **kw: session)
    client = TestClient(app)
    url = "/projects/demo/papers/paper/edit-tasks"
    task = client.post(url, json={"prompt": "Improve intro", "run_agent": False}).json()
    Path(task["workspace"], "main.tex").write_text("Better intro\n\nMethods\n\nResults\n")
    assert client.post(url + f"/{task['id']}/submit").json()["status"] == "review"
    assert client.get(url).json()["tasks"][0]["id"] == task["id"]
    response = client.post("/projects/demo/papers/paper/collab/proposal/accept", json={"proposal_id": session.proposal.id})
    assert response.status_code == 200
    assert (slot / "main.tex").read_text().startswith("Better intro")
    assert client.post(url + "/bad/submit").status_code == 400


def test_worker_runs_an_ordinary_file_edit_under_sandbox(paper, monkeypatch, tmp_path):
    slot, session = paper
    task = edit_tasks.begin("demo", "paper", slot, "Improve intro")
    fake = tmp_path / "fake-codex"
    fake.write_text(f'''#!{sys.executable}
from pathlib import Path
import sys
# Model the actual CLI behavior: it starts a second OS sandbox unless delegated.
if sys.argv[sys.argv.index("-s") + 1] != "danger-full-access":
    import subprocess
    subprocess.run(["sandbox-exec", "-p", "(version 1)(allow default)", "/bin/cat", "main.tex"], check=True)
assert Path("main.tex").read_text().startswith("Intro")
Path("main.tex").write_text("Proposed intro\\n\\nMethods\\n\\nResults\\n")
try:
    Path({str(slot / 'main.tex')!r}).write_text("forbidden")
except PermissionError:
    pass
else:
    raise RuntimeError("Original is writable")
Path(sys.argv[sys.argv.index("-o") + 1]).write_text("Improved intro")
''')
    fake.chmod(0o755)
    monkeypatch.setenv("KOI_CODEX_BIN", str(fake))
    monkeypatch.delenv("KOI_CODEX_ARGS", raising=False)
    try:
        edit_tasks.sandbox_command([], slot, Path(task["workspace"]).parent)
    except RuntimeError:
        pytest.skip("OS sandbox not installed")
    result = edit_tasks._run(task, "codex")
    assert result["answer"] == "Improved intro"
    assert (slot / "main.tex").read_text().startswith("Intro")
    edit_tasks.submit("demo", "paper", task["id"])
    assert session.proposal.candidate.startswith("Proposed intro")


def test_generation_cannot_overwrite_an_existing_paper(paper, monkeypatch):
    from koi.paper import generator
    slot, _ = paper
    monkeypatch.setattr(generator, "get_paper_slot_dir", lambda *_: slot)
    with pytest.raises(RuntimeError, match="Попросить агента"):
        generator.start_paper_generation("demo", "paper")
    assert (slot / "main.tex").read_text().startswith("Intro")


def test_codex_sandbox_only_delegated_for_protected_worker(monkeypatch, tmp_path):
    from koi.adapters import agent_backends
    monkeypatch.setattr(agent_backends, '_codex_bin', lambda: '/fake/codex')
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        Path(command[command.index('-o') + 1]).write_text('done')
        return subprocess.CompletedProcess(command, 0, '', '')
    monkeypatch.setattr(agent_backends.subprocess, 'run', run)
    monkeypatch.delenv('KOI_CODEX_ARGS', raising=False)
    for edits, external, expected in [(False, False, 'read-only'),
                                      (True, False, 'workspace-write'),
                                      (True, True, 'danger-full-access')]:
        assert agent_backends.run_agent('edit', backend='codex', cwd=tmp_path,
            allow_edits=edits, externally_sandboxed=external)[0] == 'done'
        assert commands[-1][commands[-1].index('-s') + 1] == expected
        assert ('sandbox_workspace_write.network_access=true' in commands[-1]) == (edits and not external)
    # Explicit operator settings still override the network default.
    monkeypatch.setenv('KOI_CODEX_ARGS', '-c sandbox_workspace_write.network_access=false')
    assert agent_backends.run_agent('edit', backend='codex', cwd=tmp_path,
                                   allow_edits=True)[0] == 'done'
    configs = [commands[-1][i + 1] for i, arg in enumerate(commands[-1]) if arg == '-c']
    assert configs[-1] == 'sandbox_workspace_write.network_access=false'
