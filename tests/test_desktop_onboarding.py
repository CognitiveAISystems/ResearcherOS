"""First-run desktop onboarding with existing and new Git research branches."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from koi.adapters.desktop_onboarding import (
    connect_git_project,
    inspect_existing_projects,
    inspect_existing_tree,
    inspect_git_project,
)
from koi.adapters.desktop_workspace import selected_workspace_root
from koi.adapters import project_mount
from koi.adapters.workspace import reset_workspace_cache


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


@pytest.fixture(autouse=True)
def isolated_desktop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from koi.adapters import agent_chat_queue

    monkeypatch.setattr(agent_chat_queue, "QUEUE_PATH", tmp_path / "agent-chat-queue.json")
    monkeypatch.setenv("KOI_DESKTOP_CONFIG_DIR", str(tmp_path / "settings"))
    monkeypatch.setattr(project_mount, "ENGINE_ROOT", tmp_path / "engine" / "ReseachOS")
    monkeypatch.setattr(app.router, "on_startup", [])
    monkeypatch.setattr(app.router, "on_shutdown", [])
    reset_workspace_cache()
    yield
    reset_workspace_cache()


def code_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "code" / "example"
    repo.mkdir(parents=True)
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Test User")
    git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("experiment code\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "Initial code")
    return repo


def test_existing_project_folder_resolves_to_workspace(tmp_path: Path) -> None:
    root = tmp_path / "research"
    koi = root / "tree" / "example" / "koi-structure"
    koi.mkdir(parents=True)
    (koi / "project.md").write_text("---\nid: example\n---\n", encoding="utf-8")

    assert inspect_existing_projects(str(koi)) == {
        "workspace_root": str(root),
        "projects": ["example"],
    }
    with TestClient(app) as client:
        response = client.post("/desktop/onboarding/existing-projects", json={"path": str(root)})
        assert response.status_code == 200
        assert response.json()["projects"] == ["example"]
        assert client.post("/desktop/onboarding/existing-projects", json={"path": str(tmp_path)}).status_code == 400

    assert inspect_existing_tree(str(root / "tree")) == {
        "workspace_root": str(root),
        "tree_root": str(root / "tree"),
        "projects": ["example"],
    }
    with TestClient(app) as client:
        assert client.post("/desktop/onboarding/existing-tree", json={"path": str(root / "tree")}).status_code == 200
        assert client.post("/desktop/onboarding/existing-tree", json={"path": str(root)}).status_code == 400


def test_existing_koi_project_branch_attaches_without_creating_another(tmp_path: Path) -> None:
    repo = code_repo(tmp_path)
    bootstrap = tmp_path / "bootstrap"
    git(repo, "worktree", "add", "-b", "koi-project", "--orphan", str(bootstrap))
    koi = bootstrap / "koi-structure"
    koi.mkdir()
    (koi / "project.md").write_text(
        "---\nid: example\ntitle: Example\ngit_repo: true\n"
        "git_sync_branch: koi-project\n---\n\n# problem: p\n\nExample\n",
        encoding="utf-8",
    )
    git(bootstrap, "add", "koi-structure")
    git(bootstrap, "commit", "-m", "Research tree")
    git(repo, "worktree", "remove", "--force", str(bootstrap))

    inspected = inspect_git_project(str(repo))
    assert inspected["branch_exists"] is True
    assert inspected["branch"] == "koi-project"
    git(repo, "switch", "koi-project")
    with pytest.raises(ValueError, match="Переключитесь на ветку с кодом"):
        inspect_git_project(str(repo))
    git(repo, "switch", "main")
    root = tmp_path / "research"
    root.mkdir()
    result = connect_git_project(str(repo), str(root))
    assert result["install"]["ok"] is True
    assert (root / "tree" / "example" / "koi-structure" / "project.md").is_file()
    assert (root / "example").resolve() == repo
    assert selected_workspace_root() == root
    assert project_mount.get_mount("example").code_root == repo
    assert connect_git_project(str(repo), str(root))["install"]["case"] == "already_ok"


def test_existing_tree_preview_keeps_all_nodes_and_connections(tmp_path: Path) -> None:
    repo = code_repo(tmp_path)
    workspace = tmp_path / "research"
    workspace.mkdir()
    connected = connect_git_project(str(repo), str(workspace), require_existing=False)
    project = Path(connected["install"]["tree_koi"]) / "project.md"
    # Show the latest worktree, including changes not committed to the branch.
    project.write_text(
        "---\nid: example\ntitle: Research tree\n---\n\n"
        "# problem: p\n\nLost goal\n\n"
        "## cause: c\n\nShort context\n\n"
        "### remediation: r\n\nAdd a summary\n\n"
        "#### method: m1\n\nCompare summaries\n\n"
        "Description of the comparison.\n\n"
        "#### method: m2\n\nCompare context windows\n",
        encoding="utf-8",
    )
    response = TestClient(app).post("/desktop/onboarding/git-project", json={"path": str(repo)})
    assert response.status_code == 200, response.text
    tree = response.json()["trees"][0]
    assert tree["title"] == "Research tree"
    assert [(node["id"], node["parent_id"], node["type"]) for node in tree["nodes"]] == [
        ("p", None, "problem"), ("c", "p", "cause"), ("r", "c", "remediation"),
        ("m1", "r", "method"), ("m2", "r", "method"),
    ]
    assert tree["nodes"][-1]["title"] == "Compare context windows"
    assert "Description of the comparison." in tree["nodes"][3]["description"]


def test_new_branch_is_local_and_keeps_code_branch(tmp_path: Path) -> None:
    repo = code_repo(tmp_path)
    root = tmp_path / "research"
    root.mkdir()
    inspected = inspect_git_project(str(repo))
    assert inspected["branch_exists"] is False
    assert inspected["branch"] == "koi-project"

    with TestClient(app) as client:
        response = client.post(
            "/desktop/onboarding/connect",
            json={"repo_path": str(repo), "workspace_root": str(root), "require_existing": False},
        )
    assert response.status_code == 200, response.text
    assert (root / "tree" / "example" / "koi-structure" / "project.md").is_file()
    assert subprocess.check_output(
        ["git", "-C", str(repo), "branch", "--show-current"], text=True
    ).strip() == "main"
    assert selected_workspace_root() == root


def test_connection_rejects_occupied_name_without_changes(tmp_path: Path) -> None:
    repo = code_repo(tmp_path)
    root = tmp_path / "research"
    (root / "example").mkdir(parents=True)
    with pytest.raises(ValueError, match="другой проект"):
        connect_git_project(str(repo), str(root))
    assert not (root / "tree").exists()
    assert selected_workspace_root() is None


def test_connection_preserves_unrecognized_koi_directory(tmp_path: Path) -> None:
    repo = code_repo(tmp_path)
    existing = repo / "koi-structure"
    existing.mkdir()
    (existing / "notes.txt").write_text("keep me", encoding="utf-8")
    root = tmp_path / "research"
    root.mkdir()
    with pytest.raises(ValueError, match="Проверьте её содержимое"):
        connect_git_project(str(repo), str(root))
    assert (existing / "notes.txt").read_text(encoding="utf-8") == "keep me"
    assert not (root / "tree").exists()


def test_documents_default_uses_tree_without_extra_tree_level(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    documents = tmp_path / "Documents"
    documents.mkdir()
    repo = code_repo(tmp_path)

    with TestClient(app) as client:
        location = client.get("/desktop/onboarding/default-location")
        assert location.json() == {
            "workspace_root": str(documents),
            "research_root": str(documents / "tree"),
        }
        response = client.post(
            "/desktop/onboarding/connect",
            json={"repo_path": str(repo), "workspace_root": str(documents), "require_existing": False},
        )
    assert response.status_code == 200, response.text
    assert (documents / "tree" / "example" / "koi-structure" / "project.md").is_file()
    assert not (documents / ".tree").exists()
    assert project_mount.get_mount("example").code_root == repo
    assert inspect_existing_projects(str(documents / "tree")) == {
        "workspace_root": str(documents),
        "projects": ["example"],
    }


def test_empty_documents_workspace_creates_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    documents = tmp_path / "Documents"
    documents.mkdir()
    with TestClient(app) as client:
        response = client.put("/desktop/workspace-root", json={"workspace_root": str(documents)})
    assert response.status_code == 200
    assert (documents / "tree").is_dir()
    assert not (documents / ".tree").exists()


def test_existing_branch_only_step_rejects_plain_repo(tmp_path: Path) -> None:
    repo = code_repo(tmp_path)
    root = tmp_path / "research"
    root.mkdir()
    with TestClient(app) as client:
        response = client.post(
            "/desktop/onboarding/connect",
            json={"repo_path": str(repo), "workspace_root": str(root), "require_existing": True},
        )
    assert response.status_code == 400
    assert not (root / "tree").exists()


def test_existing_branch_is_fetched_from_origin(tmp_path: Path) -> None:
    repo = code_repo(tmp_path)
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    git(repo, "remote", "add", "origin", str(bare))
    bootstrap = tmp_path / "bootstrap"
    git(repo, "worktree", "add", "-b", "koi-project", "--orphan", str(bootstrap))
    koi = bootstrap / "koi-structure"
    koi.mkdir()
    (koi / "project.md").write_text("---\nid: example\ntitle: Example\n---\n", encoding="utf-8")
    git(bootstrap, "add", "koi-structure")
    git(bootstrap, "commit", "-m", "Research tree")
    git(repo, "push", "origin", "koi-project")
    git(repo, "worktree", "remove", "--force", str(bootstrap))
    git(repo, "branch", "-D", "koi-project")

    inspected = inspect_git_project(str(repo))
    assert inspected["branch"] == "koi-project"
    assert inspected["branch_exists"] is True
    workspace = tmp_path / "research"
    workspace.mkdir()
    result = connect_git_project(str(repo), str(workspace), require_existing=True)
    assert result["install"]["ok"] is True
    assert (workspace / "tree" / "example" / "koi-structure" / "project.md").is_file()


def test_plain_folder_and_uncommitted_repo_explain_preparation(tmp_path: Path) -> None:
    folder = tmp_path / 'not-a-repo'
    folder.mkdir()
    with pytest.raises(ValueError, match='Создайте репозиторий и первый коммит'):
        inspect_git_project(str(folder))
    assert not (folder / '.git').exists()
    git(folder, 'init', '-b', 'main')
    with pytest.raises(ValueError, match='Сделайте первый коммит'):
        inspect_git_project(str(folder))


def test_tree_locations_only_return_valid_known_folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv('HOME', str(tmp_path))
    documents = tmp_path / 'Documents'
    koi = documents / 'tree' / 'example' / 'koi-structure'
    koi.mkdir(parents=True)
    (koi / 'project.md').write_text('---\nid: example\n---\n')
    from koi.adapters.desktop_workspace import set_workspace_root
    set_workspace_root(documents)
    client = TestClient(app)
    response = client.get('/desktop/onboarding/tree-locations')
    assert response.json() == {'trees': [{
        'workspace_root': str(documents), 'tree_root': str(documents / 'tree'), 'projects': ['example'],
    }]}
    (koi / 'project.md').unlink()
    assert client.get('/desktop/onboarding/tree-locations').json() == {'trees': []}


def test_tree_locations_remember_previous_selections(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from koi.adapters.desktop_workspace import config_path, set_workspace_root

    monkeypatch.setenv('HOME', str(tmp_path))
    first = tmp_path / 'custom research'
    second = tmp_path / 'another research'
    for root in (first, second):
        koi = root / 'tree' / 'example' / 'koi-structure'
        koi.mkdir(parents=True)
        (koi / 'project.md').write_text('---\nid: example\n---\n')
    # Upgrade the original single-folder preference without losing it.
    config_path().parent.mkdir(parents=True)
    import json
    config_path().write_text(json.dumps({'workspace_root': str(first)}))
    set_workspace_root(second)
    set_workspace_root(second)
    client = TestClient(app)
    found = client.get('/desktop/onboarding/tree-locations').json()['trees']
    assert [tree['workspace_root'] for tree in found] == [str(second), str(first)]
    (first / 'tree' / 'example' / 'koi-structure' / 'project.md').unlink()
    found = client.get('/desktop/onboarding/tree-locations').json()['trees']
    assert [tree['workspace_root'] for tree in found] == [str(second)]


def test_second_tree_interview_preserves_existing_tree_and_code(tmp_path: Path) -> None:
    repo = code_repo(tmp_path)
    workspace = tmp_path / 'research'
    workspace.mkdir()
    first = connect_git_project(str(repo), str(workspace), require_existing=False)
    first_tree = Path(first['install']['tree_koi'])
    (first_tree / 'keep.txt').write_text('old research notes')
    old_project = (first_tree / 'project.md').read_bytes()
    old_commit = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'koi-project'])
    client = TestClient(app)
    inspected = client.post('/desktop/onboarding/git-project', json={'path': str(repo)}).json()
    assert inspected['trees'][0]['branch'] == 'koi-project'
    assert inspected['trees'][0]['title'] == 'example'
    assert inspected['next_branch'] == 'koi/research-2'
    branch = inspected['next_branch']
    payload = {'repo_path': str(repo), 'workspace_root': str(workspace), 'branch': branch}
    started = client.post('/desktop/onboarding/interview/start', json=payload)
    assert started.status_code == 200, started.text
    assert not (workspace / 'tree' / 'example-2').exists()
    # Going back and reopening resumes this tree's own draft.
    assert client.post('/desktop/onboarding/interview/start', json=payload).json() == started.json()
    for answer in ('Агент теряет цель', 'История шагов короткая', 'Развить гипотезу решения', 'Резюме удерживает цель', 'Сравнить задачи с резюме и без'):
        reply = client.post('/desktop/onboarding/interview/reply', json={
            'repo_path': str(repo), 'branch': branch, 'answer': answer,
        })
        assert reply.status_code == 200, reply.text
    assert reply.json()['complete'] is True
    result = client.post('/desktop/onboarding/interview/finish', json={'path': str(repo), 'branch': branch})
    assert result.status_code == 200, result.text
    assert result.json()['project_id'] == 'example-2'
    second_tree = workspace / 'tree' / 'example-2' / 'koi-structure'
    content = (second_tree / 'project.md').read_text()
    assert 'id: example-2' in content and 'git_sync_branch: koi/research-2' in content
    assert 'Агент теряет цель' in content
    assert not (second_tree / 'keep.txt').exists()
    assert (first_tree / 'keep.txt').read_text() == 'old research notes'
    assert (first_tree / 'project.md').read_bytes() == old_project
    assert subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'koi-project']) == old_commit
    assert subprocess.check_output(['git', '-C', str(repo), 'branch', '--show-current']).strip() == b'main'
    assert subprocess.run(['git', '-C', str(repo), 'merge-base', '--is-ancestor', 'main', branch]).returncode == 1
    project_mount.rescan_projects()
    for project_id in ('example', 'example-2'):
        assert project_mount.get_mount(project_id).code_root == repo
    # Both choices reopen their own checkout without substituting the other tree.
    for selected in ('koi-project', branch):
        response = client.post('/desktop/onboarding/connect', json={
            'repo_path': str(repo), 'workspace_root': str(workspace), 'require_existing': True, 'branch': selected,
        })
        assert response.status_code == 200, response.text
        assert response.json()['project_id'] == ('example-2' if selected == branch else 'example')
    refreshed = inspect_git_project(str(repo))
    assert [tree['branch'] for tree in refreshed['trees']] == ['koi-project', branch]
    assert refreshed['trees'][1]['title'] == 'Агент теряет цель'
    assert refreshed['next_branch'] == 'koi/research-3'
    # A stale request cannot turn an existing branch into a new tree.
    conflict = client.post('/desktop/onboarding/interview/start', json=payload)
    assert conflict.status_code == 400 and 'уже существует' in conflict.json()['detail']


def test_numbered_research_branch_is_discovered_on_origin(tmp_path: Path) -> None:
    repo = code_repo(tmp_path)
    workspace = tmp_path / 'research'
    workspace.mkdir()
    bare = tmp_path / 'origin.git'
    subprocess.run(['git', 'init', '--bare', str(bare)], check=True, capture_output=True)
    git(repo, 'remote', 'add', 'origin', str(bare))
    connect_git_project(str(repo), str(workspace), require_existing=False, branch='koi/research-2')
    git(repo, 'push', 'origin', 'koi/research-2')
    git(repo, 'worktree', 'remove', '--force', str(workspace / 'tree' / 'example-2'))
    git(repo, 'branch', '-D', 'koi/research-2')
    git(repo, 'update-ref', '-d', 'refs/remotes/origin/koi/research-2')
    inspected = inspect_git_project(str(repo))
    assert inspected['branch_exists'] is True and inspected['branch'] == 'koi/research-2'
    assert inspected['next_branch'] == 'koi/research-3'
    attached = connect_git_project(str(repo), str(workspace), require_existing=True, branch='koi/research-2')
    assert Path(attached['install']['tree_koi']).parent.name == 'example-2'


def test_existing_checkout_is_reused_even_outside_default_workspace(tmp_path: Path) -> None:
    repo = code_repo(tmp_path)
    original = tmp_path / 'research'
    original.mkdir()
    attached = connect_git_project(str(repo), str(original), require_existing=False)
    other = tmp_path / 'Documents'
    other.mkdir()
    continued = connect_git_project(str(repo), str(other), require_existing=True, branch='koi-project')
    assert continued['install']['tree_koi'] == attached['install']['tree_koi']
    assert continued['workspace_root'] == str(original)
    assert not (other / 'tree').exists()


def test_new_tree_never_reuses_occupied_branch_or_folder(tmp_path: Path) -> None:
    repo = code_repo(tmp_path)
    workspace = tmp_path / 'research'
    workspace.mkdir()
    connect_git_project(str(repo), str(workspace), require_existing=False)
    # The occupied branch has code, not research; it still reserves its name.
    git(repo, 'branch', 'koi/research-2', 'main')
    inspected = inspect_git_project(str(repo))
    assert inspected['next_branch'] == 'koi/research-3'
    occupied = workspace / 'tree' / 'example-3'
    occupied.mkdir()
    (occupied / 'keep.txt').write_text('Keep this folder')
    client = TestClient(app)
    conflict = client.post('/desktop/onboarding/interview/start', json={
        'repo_path': str(repo), 'workspace_root': str(workspace), 'branch': 'koi/research-3',
    })
    assert conflict.status_code == 400 and 'уже занята' in conflict.json()['detail']
    assert (occupied / 'keep.txt').read_text() == 'Keep this folder'
    assert subprocess.run(['git', '-C', str(repo), 'show-ref', '--verify', '--quiet', 'refs/heads/koi/research-3']).returncode == 1


def test_unreachable_origin_does_not_look_like_a_new_repository(tmp_path: Path) -> None:
    repo = code_repo(tmp_path)
    git(repo, 'remote', 'add', 'origin', str(tmp_path / 'missing-origin.git'))
    client = TestClient(app)
    response = client.post('/desktop/onboarding/git-project', json={'path': str(repo)})
    assert response.status_code == 400
    assert 'Проверьте подключение и доступ' in response.json()['detail']
    assert not (repo / 'koi-structure').exists()


def test_malformed_existing_tree_returns_a_recoverable_error(tmp_path: Path) -> None:
    repo = code_repo(tmp_path)
    workspace = tmp_path / 'research'
    workspace.mkdir()
    connected = connect_git_project(str(repo), str(workspace), require_existing=False)
    project = Path(connected['install']['tree_koi']) / 'project.md'
    project.write_text('---\ntitle: [unfinished\n---\n')
    response = TestClient(app).post('/desktop/onboarding/git-project', json={'path': str(repo)})
    assert response.status_code == 400
    assert 'Проверьте репозиторий' in response.json()['detail']
    assert project.read_text() == '---\ntitle: [unfinished\n---\n'
