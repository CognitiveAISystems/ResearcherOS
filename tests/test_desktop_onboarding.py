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
    monkeypatch.setenv("KOI_DESKTOP_CONFIG_DIR", str(tmp_path / "settings"))
    monkeypatch.setattr(project_mount, "ENGINE_ROOT", tmp_path / "engine" / "ReseachOS")
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
