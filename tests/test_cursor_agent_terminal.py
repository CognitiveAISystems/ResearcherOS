"""The explain button opens a real terminal; the prompt must not be piped into agent."""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from koi.literature.cursor_agent_terminal import (
    agent_terminal_shell,
    explain_note_file,
    open_agent_terminal,
    read_explain_note,
)


def test_shell_reads_prompt_from_a_file() -> None:
    shell = agent_terminal_shell(
        Path("/tmp/koi-explain-1.txt"),
        Path("/work/tree/ZeroHero"),
        Path("/Users/zoya/.local/bin/agent"),
    )
    assert shell == (
        "cd /work/tree/ZeroHero && "
        '/Users/zoya/.local/bin/agent --trust "$(cat /tmp/koi-explain-1.txt)"'
    )


def test_explain_note_path_stays_inside_the_run(tmp_path: Path) -> None:
    path = explain_note_file(tmp_path, "run_1", "n05")
    assert path == tmp_path / "run_1" / "explain-n05.txt"
    with pytest.raises(ValueError):
        explain_note_file(tmp_path, "../secrets", "n05")
    path.parent.mkdir()
    path.write_text("  абзац  \n", encoding="utf-8")
    assert read_explain_note(tmp_path, "run_1", "n05") == "абзац"


def test_open_writes_prompt_and_keeps_a_tty(monkeypatch, tmp_path: Path) -> None:
    written = tmp_path / "prompt.txt"
    captured: dict[str, str] = {}

    def fake_mkstemp(*, prefix: str, suffix: str):
        fd = os.open(written, os.O_CREAT | os.O_RDWR, 0o600)
        return fd, str(written)

    def fake_run(args, input, text, capture_output, check):  # noqa: A002
        captured["script"] = input

        class Result:
            returncode = 0
            stderr = ""
            stdout = ""

        return Result()

    monkeypatch.setattr("koi.literature.cursor_agent_terminal.sys.platform", "darwin")
    monkeypatch.setattr(
        "koi.literature.cursor_agent_terminal.find_agent_bin",
        lambda: Path("/Users/zoya/.local/bin/agent"),
    )
    monkeypatch.setattr("koi.literature.cursor_agent_terminal.tempfile.mkstemp", fake_mkstemp)
    monkeypatch.setattr("koi.literature.cursor_agent_terminal.subprocess.run", fake_run)

    open_agent_terminal("поясни связку", tmp_path)

    assert written.read_text(encoding="utf-8") == "поясни связку"
    script = captured["script"]
    assert 'do script' in script
    assert '$(cat ' in script
    assert "поясни связку" not in script


def test_explain_terminal_route_opens_agent_in_tree(monkeypatch, tmp_path: Path) -> None:
    from api.main import app

    tree = tmp_path / "tree" / "ZeroHero"
    morphology = tree / "koi-structure" / "paper_morphology"
    (morphology / "run_1").mkdir(parents=True)
    seen: dict[str, object] = {}

    def fake_open(prompt: str, cwd: Path) -> Path:
        seen["prompt"] = prompt
        seen["cwd"] = cwd
        return tmp_path / "prompt.txt"

    monkeypatch.setattr("api.routers.morphology.parse_project", lambda _project_id: object())
    monkeypatch.setattr("api.routers.morphology._tree_cwd", lambda _project_id: tree)
    monkeypatch.setattr(
        "api.routers.morphology.paper_morphology_dir",
        lambda _project_id: morphology,
    )
    monkeypatch.setattr("api.routers.morphology.open_agent_terminal", fake_open)

    response = TestClient(app).post(
        "/projects/demo/morphology/explain-terminal",
        json={"prompt": "поясни", "run_id": "run_1", "node_id": "n05"},
    )

    assert response.status_code == 200
    assert seen["cwd"] == tree
    prompt = str(seen["prompt"])
    assert prompt.startswith("поясни")
    assert "koi-structure/paper_morphology/run_1/explain-n05.txt" in prompt
    assert "--trust" not in prompt
