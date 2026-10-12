"""Desktop interview keeps a draft until the researcher accepts its tree."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from koi.adapters import onboarding_interview, project_mount
from koi.adapters.workspace import reset_workspace_cache


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KOI_DESKTOP_CONFIG_DIR", str(tmp_path / "settings"))
    monkeypatch.setattr(project_mount, "ENGINE_ROOT", tmp_path / "engine" / "ReseachOS")
    reset_workspace_cache()
    code = tmp_path / "code" / "example"
    code.mkdir(parents=True)
    git(code, "init", "-b", "main")
    git(code, "config", "user.name", "Test User")
    git(code, "config", "user.email", "test@example.com")
    (code / "README.md").write_text("An agent in a long task environment.\n", encoding="utf-8")
    git(code, "add", "README.md")
    git(code, "commit", "-m", "Initial code")
    yield code
    reset_workspace_cache()


def test_guide_fills_from_the_persons_words(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = tmp_path / "research"
    workspace.mkdir()
    calls = {"n": 0}

    def fake_agent(prompt: str, **_kwargs) -> tuple[str, str]:
        calls["n"] += 1
        phase = re.search(r'"phase":"(\w+)"', prompt).group(1)
        return json.dumps({"phase": phase, "message": "Что здесь остаётся неясным?", "options": ["Первый вариант", "Второй вариант"], "complete": False}, ensure_ascii=False), "test"

    monkeypatch.setattr(onboarding_interview, "_cursor_cli_text", lambda prompt, repo: None)
    monkeypatch.setattr(onboarding_interview, "run_agent", fake_agent)
    monkeypatch.setattr(onboarding_interview, "update_literature", lambda state, context, repo, ask: [])
    answers = {
        "problem": "Агент теряет цель в задаче",
        "cause": "История шагов слишком короткая",
        "hypothesis": "Резюме поможет удержать цель",
        "method": "Сравнить задачи с резюме и без",
    }
    with TestClient(app) as client:
        started = client.post("/desktop/onboarding/interview/start", json={"repo_path": str(repo), "workspace_root": str(workspace)})
        assert started.status_code == 200, started.text
        body = started.json()
        assert body["guide"] is True and body["grill"] is False and body["nodes"] == []
        assert [item["text"] for item in body["messages"]] == [
            "Нужно заполнить дерево исследования.",
            "Для этого нужно описать проблему и её причину в вашей работе. Затем вы выбираете: доказывать причину или развивать гипотезу решения. В конце — метод проверки.",
            onboarding_interview._PHASE_PROMPTS["problem"],
        ]
        assert calls["n"] == 0
        again = client.post("/desktop/onboarding/interview/start", json={"repo_path": str(repo), "workspace_root": str(workspace)})
        assert again.json() == body
        problem = client.post("/desktop/onboarding/interview/reply", json={"repo_path": str(repo), "answer": answers["problem"]})
        assert problem.status_code == 200, problem.text
        assert problem.json()["nodes"][0]["title"] == answers["problem"]
        assert problem.json()["nodes"][0]["description"] == answers["problem"]
        assert problem.json()["phase"] == "cause"
        assert calls["n"] == 0
        grilled = client.post("/desktop/onboarding/interview/reply", json={"repo_path": str(repo), "decision": "grill"})
        assert grilled.status_code == 200, grilled.text
        assert grilled.json()["grill"] is True
        assert grilled.json()["nodes"][0]["title"] == answers["problem"]
        assert grilled.json()["messages"][-1]["text"] == "Что здесь остаётся неясным?"
        assert grilled.json()["messages"][-1]["options"] == ["Первый вариант", "Второй вариант"]
        assert calls["n"] == 1
        clarified = client.post("/desktop/onboarding/interview/reply", json={"repo_path": str(repo), "answer": "Агент теряет цель между шагами"})
        assert clarified.json()["phase"] == "cause"
        assert clarified.json()["grill"] is True
        assert len(clarified.json()["nodes"]) == 1
        assert clarified.json()["nodes"][0]["title"] == answers["problem"]
        assert clarified.json()["messages"][-1]["text"] == "Что здесь остаётся неясным?"
        picked = client.post("/desktop/onboarding/interview/reply", json={"repo_path": str(repo), "answer": "Первый вариант"})
        assert picked.json()["grill"] is True
        assert picked.json()["nodes"][0]["title"] == answers["problem"]
        assert picked.json()["messages"][-1]["role"] == "user"
        agreed = client.post("/desktop/onboarding/interview/reply", json={"repo_path": str(repo), "decision": "approve"})
        assert agreed.json()["grill"] is False
        assert agreed.json()["phase"] == "cause"
        assert agreed.json()["nodes"][0]["title"] == answers["problem"]
        for phase, answer in (("cause", answers["cause"]),):
            response = client.post("/desktop/onboarding/interview/reply", json={"repo_path": str(repo), "answer": answer})
            assert response.status_code == 200, response.text
        assert response.json()["phase"] == "branch"
        assert response.json()["messages"][-1]["options"] == ["Доказать причину", "Развить гипотезу решения"]
        assert len(response.json()["nodes"]) == 2
        skipped = client.post("/desktop/onboarding/interview/reply", json={"repo_path": str(repo), "answer": "свой текст"})
        assert skipped.json()["phase"] == "branch"
        assert len(skipped.json()["nodes"]) == 2
        picked = client.post("/desktop/onboarding/interview/reply", json={"repo_path": str(repo), "answer": "Доказать причину"})
        assert picked.json()["phase"] == "evidence"
        assert picked.json()["track"] == "evidence"
        assert picked.json()["messages"][-1]["text"].startswith("Опишите, как вы будете доказывать причину.")
        evidence = client.post("/desktop/onboarding/interview/reply", json={"repo_path": str(repo), "answer": "Хлеб плотнее в холодные дни"})
        assert evidence.json()["nodes"][2]["type"] == "cause_evidence"
        assert evidence.json()["phase"] == "method"
        response = client.post("/desktop/onboarding/interview/reply", json={"repo_path": str(repo), "answer": answers["method"]})
        assert response.status_code == 200, response.text
        assert response.json()["complete"] is True
        assert [node["title"] for node in response.json()["nodes"]] == [
            answers["problem"],
            answers["cause"],
            "Хлеб плотнее в холодные дни",
            answers["method"],
        ]
        assert calls["n"] == 2
        finished = client.post("/desktop/onboarding/interview/finish", json={"path": str(repo)})
        assert finished.status_code == 200, finished.text
        project_md = workspace / "tree" / "example" / "koi-structure" / "project.md"
        text = project_md.read_text(encoding="utf-8")
        assert "# problem: problem" in text
        assert "### cause_evidence: e-1" in text
        assert "#### method: m-1" in text
        assert answers["problem"] in text
        assert (project_md.parent / "onboard-brief.md").is_file()


def test_track_choice_accepts_only_the_two_paths() -> None:
    assert onboarding_interview._track_choice("Доказать причину") == "evidence"
    assert onboarding_interview._track_choice("развить гипотезу решения.") == "hypothesis"
    assert onboarding_interview._track_choice("свой текст") is None
    assert onboarding_interview._answer_options(["один"]) == []
    assert onboarding_interview._answer_options(["  первый  ", "второй", "первый", 3, "x" * 241]) == ["первый", "второй"]


def test_interview_prefers_cursor_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"codex": False}

    def fail_agent(*_args, **_kwargs) -> tuple[None, None]:
        called["codex"] = True
        return None, None

    monkeypatch.setattr(
        onboarding_interview, "_cursor_cli_text",
        lambda prompt, repo: '{"phase":"problem","message":"Какую трудность вы наблюдаете?","complete":false}',
    )
    monkeypatch.setattr(onboarding_interview, "run_agent", fail_agent)
    reply = onboarding_interview._ask_agent("prompt", tmp_path)
    assert reply["message"] == "Какую трудность вы наблюдаете?"
    assert called["codex"] is False


def test_start_keeps_the_chosen_program(repo: Path, tmp_path: Path) -> None:
    workspace = tmp_path / "research"
    workspace.mkdir()
    with TestClient(app) as client:
        started = client.post(
            "/desktop/onboarding/interview/start",
            json={"repo_path": str(repo), "workspace_root": str(workspace), "program_title": "Кухня хлеба"},
        )
        assert started.status_code == 200, started.text
        assert started.json()["program"]["title"] == "Кухня хлеба"
        assert started.json()["program"]["id"] == "кухня-хлеба"
        both = client.post(
            "/desktop/onboarding/interview/start",
            json={
                "repo_path": str(repo),
                "workspace_root": str(workspace),
                "program_id": "other",
                "program_title": "Кухня хлеба",
            },
        )
        assert both.status_code == 400


def test_cannot_finish_before_interview(repo: Path) -> None:
    with TestClient(app) as client:
        response = client.post("/desktop/onboarding/interview/finish", json={"path": str(repo)})
    assert response.status_code == 400
