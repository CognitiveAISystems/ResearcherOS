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
    monkeypatch.setattr(app.router, "on_startup", [])
    monkeypatch.setattr(app.router, "on_shutdown", [])
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
        assert grilled.status_code == 400
        assert "пока недоступно" in grilled.json()["detail"]
        assert calls["n"] == 0
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
        assert calls["n"] == 0
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
    assert onboarding_interview._track_choice(" 1 ") == "evidence"
    assert onboarding_interview._track_choice("2.") == "hypothesis"
    assert onboarding_interview._track_choice("3") is None
    assert onboarding_interview._track_choice("свой текст") is None
    assert onboarding_interview._answer_options(["один"]) == []
    assert onboarding_interview._answer_options(["  первый  ", "второй", "первый", 3, "x" * 241]) == ["первый", "второй"]


@pytest.mark.parametrize(("answer", "track"), [("1", "evidence"), ("2", "hypothesis")])
def test_chat_accepts_a_number_for_the_next_path(repo: Path, tmp_path: Path, answer: str, track: str) -> None:
    workspace = tmp_path / "research"
    workspace.mkdir()
    with TestClient(app) as client:
        client.post("/desktop/onboarding/interview/start", json={"repo_path": str(repo), "workspace_root": str(workspace)})
        for text in ("Агент теряет цель", "История шагов слишком короткая"):
            response = client.post("/desktop/onboarding/interview/reply", json={"repo_path": str(repo), "answer": text})
            assert response.status_code == 200, response.text
        assert response.json()["phase"] == "branch"
        response = client.post("/desktop/onboarding/interview/reply", json={"repo_path": str(repo), "answer": answer})
        assert response.status_code == 200, response.text
        state = response.json()
        assert state["phase"] == state["track"] == track
        assert len(state["nodes"]) == 2
        assert state["messages"][-2] == {"role": "user", "phase": "branch", "text": answer}
        assert state["messages"][-1]["phase"] == track


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


ANSWERS = {
    'problem': 'Агент теряет цель в длинной задаче',
    'cause': 'История шагов слишком короткая',
    'hypothesis': 'Резюме поможет удержать цель',
    'evidence': 'Проверить влияние длины истории',
    'method': 'Сравнить задачи с разной историей',
}


def complete_guide(client: TestClient, repo: Path, track: str = 'hypothesis') -> dict:
    state = client.post('/desktop/onboarding/interview/start', json={
        'repo_path': str(repo), 'workspace_root': str(repo.parent.parent / 'research'),
    }).json()
    for _ in range(6):
        if state['complete']:
            return state
        answer = ('Доказать причину' if track == 'evidence' else 'Развить гипотезу решения') if state['phase'] == 'branch' else ANSWERS[state['phase']]
        response = client.post('/desktop/onboarding/interview/reply', json={'repo_path': str(repo), 'answer': answer})
        assert response.status_code == 200, response.text
        state = response.json()
    assert state['complete']
    return state


@pytest.mark.parametrize('track', ['hypothesis', 'evidence'])
@pytest.mark.parametrize('step', ['problem', 'cause', 'third', 'method'])
def test_editing_a_completed_tree_keeps_prefix_and_discards_following_nodes(repo: Path, monkeypatch: pytest.MonkeyPatch, track: str, step: str) -> None:
    monkeypatch.setattr(onboarding_interview, '_ask_agent', lambda *_args: pytest.fail('Onboarding must not invoke an agent'))
    workspace = repo.parent.parent / 'research'
    workspace.mkdir()
    client = TestClient(app)
    complete = complete_guide(client, repo, track)
    phase = track if step == 'third' else step
    index = {'problem': 0, 'cause': 1, 'third': 2, 'method': 3}[step]
    selected = complete['nodes'][index]
    response = client.post('/desktop/onboarding/interview/reply', json={'repo_path': str(repo), 'decision': 'rewind', 'phase': phase})
    assert response.status_code == 200, response.text
    state = response.json()
    assert state['nodes'] == complete['nodes'][:index + 1]
    assert state['edit_answer'] == selected['description']
    assert state['editing_phase'] == state['phase'] == phase
    assert state['complete'] is False and state['grill'] is False
    assert state['approved_nodes'] == [node['id'] for node in complete['nodes'][:index]]
    if index < 2:
        assert state['track'] is None
    else:
        assert state['track'] == track
    phases = ['problem', 'cause', 'branch', track, 'method']
    assert [message.get('phase') for message in state['messages'] if message['role'] == 'user'] == phases[:phases.index(phase)]
    assert client.post('/desktop/onboarding/interview/finish', json={'path': str(repo)}).status_code == 400
    reopened = client.post('/desktop/onboarding/interview/start', json={'repo_path': str(repo), 'workspace_root': str(workspace)})
    assert reopened.json() == state
    replacement = 'Новая формулировка выбранного узла'
    changed = client.post('/desktop/onboarding/interview/reply', json={'repo_path': str(repo), 'answer': replacement})
    assert changed.status_code == 200, changed.text
    assert changed.json()['nodes'][-1]['id'] == selected['id']
    assert changed.json()['nodes'][-1]['description'] == replacement
    assert changed.json()['edit_answer'] == '' and changed.json()['editing_phase'] is None
    refilled = complete_guide(client, repo, track)
    assert refilled['nodes'][index]['description'] == replacement
    assert len(refilled['nodes']) == 4
    assert client.post('/desktop/onboarding/interview/finish', json={'path': str(repo)}).status_code == 200


def test_editing_cause_allows_switching_from_evidence_to_hypothesis(repo: Path) -> None:
    workspace = repo.parent.parent / 'research'
    workspace.mkdir()
    client = TestClient(app)
    complete_guide(client, repo, 'evidence')
    rewind = client.post('/desktop/onboarding/interview/reply', json={'repo_path': str(repo), 'decision': 'rewind', 'phase': 'cause'})
    assert rewind.json()['track'] is None
    changed = client.post('/desktop/onboarding/interview/reply', json={'repo_path': str(repo), 'answer': 'Агенту не хватает нужных наблюдений'})
    assert changed.json()['phase'] == 'branch'
    state = complete_guide(client, repo, 'hypothesis')
    assert [node['type'] for node in state['nodes']] == ['problem', 'cause', 'remediation', 'method']
    assert all(message.get('phase') != 'evidence' for message in state['messages'])
    saved = onboarding_interview._read(onboarding_interview._session_path(repo))
    assert ANSWERS['evidence'] not in saved['brief']
    assert state['track'] == 'hypothesis'


def test_unavailable_edit_does_not_change_the_draft(repo: Path) -> None:
    workspace = repo.parent.parent / 'research'
    workspace.mkdir()
    client = TestClient(app)
    original = client.post('/desktop/onboarding/interview/start', json={'repo_path': str(repo), 'workspace_root': str(workspace)}).json()
    for phase in (None, 'method', 'branch', 'missing'):
        response = client.post('/desktop/onboarding/interview/reply', json={'repo_path': str(repo), 'decision': 'rewind', 'phase': phase})
        assert response.status_code == 400 and 'пока недоступен' in response.json()['detail']
        assert client.post('/desktop/onboarding/interview/start', json={'repo_path': str(repo), 'workspace_root': str(workspace)}).json() == original


@pytest.mark.parametrize('guide', [True, False])
def test_old_agent_draft_resumes_as_an_editable_form(repo: Path, monkeypatch: pytest.MonkeyPatch, guide: bool) -> None:
    workspace = repo.parent.parent / 'research'
    workspace.mkdir()
    client = TestClient(app)
    complete = complete_guide(client, repo)
    path = onboarding_interview._session_path(repo)
    saved = onboarding_interview._read(path)
    saved.update(guide=guide, grill=True, phase='cause', pending_node=complete['nodes'][1]['id'], complete=False)
    onboarding_interview._save(path, saved)
    monkeypatch.setattr(onboarding_interview, '_ask_agent', lambda *_args: pytest.fail('A resumed draft must not invoke an agent'))
    resumed = client.post('/desktop/onboarding/interview/start', json={'repo_path': str(repo), 'workspace_root': str(workspace)})
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()['guide'] is True and resumed.json()['grill'] is False
    assert resumed.json()['phase'] == 'cause'
    assert len(resumed.json()['nodes']) == 2
    assert resumed.json()['edit_answer'] == ANSWERS['cause']
    assert client.post('/desktop/onboarding/interview/reply', json={'repo_path': str(repo), 'answer': 'Новая причина из слов человека'}).json()['phase'] == 'branch'


def test_editing_one_research_branch_does_not_change_another_draft(repo: Path) -> None:
    workspace = repo.parent.parent / 'research'
    workspace.mkdir()
    client = TestClient(app)
    states = {}
    for branch, answer in ((None, 'Первая исследовательская проблема'), ('koi/research-2', 'Вторая исследовательская проблема')):
        started = client.post('/desktop/onboarding/interview/start', json={'repo_path': str(repo), 'workspace_root': str(workspace), 'branch': branch})
        assert started.status_code == 200, started.text
        response = client.post('/desktop/onboarding/interview/reply', json={'repo_path': str(repo), 'branch': branch, 'answer': answer})
        assert response.status_code == 200, response.text
        states[branch] = response.json()
    edited = client.post('/desktop/onboarding/interview/reply', json={'repo_path': str(repo), 'branch': 'koi/research-2', 'decision': 'rewind', 'phase': 'problem'})
    assert edited.status_code == 200, edited.text
    assert edited.json()['edit_answer'] == 'Вторая исследовательская проблема'
    reopened = client.post('/desktop/onboarding/interview/start', json={'repo_path': str(repo), 'workspace_root': str(workspace)})
    assert reopened.json() == states[None]
