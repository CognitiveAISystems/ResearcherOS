"""Desktop workspace preference and project discovery integration."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from koi.adapters import desktop_workspace, project_mount
from koi.adapters.workspace import reset_workspace_cache


@pytest.fixture(autouse=True)
def desktop_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("KOI_DESKTOP_CONFIG_DIR", str(tmp_path / "app-support"))
    yield
    reset_workspace_cache()
    project_mount.rescan_projects()


def _write_project(root: Path, name: str, project_id: str) -> Path:
    koi = root / "tree" / name / "koi-structure"
    koi.mkdir(parents=True)
    (koi / "project.md").write_text(
        f"---\nid: {project_id}\ntitle: {project_id}\n---\n\n# problem: p\n",
        encoding="utf-8",
    )
    return koi


def test_workspace_root_persists_outside_research_tree(tmp_path: Path):
    root = tmp_path / "research"
    root.mkdir()

    assert desktop_workspace.selected_workspace_root() is None
    assert desktop_workspace.set_workspace_root(root) == root.resolve()
    assert desktop_workspace.selected_workspace_root() == root.resolve()
    assert desktop_workspace.config_path().parent != root
    assert desktop_workspace.config_path().is_file()


def test_selected_root_is_first_and_discovers_its_projects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    engine_parent = tmp_path / "engine-parent"
    engine = engine_parent / "ReseachOS"
    engine.mkdir(parents=True)
    selected = tmp_path / "selected-research"
    selected.mkdir()
    _write_project(selected, "alpha", "alpha-project")
    _write_project(engine_parent, "beta", "beta-project")
    monkeypatch.setattr(project_mount, "ENGINE_ROOT", engine)

    desktop_workspace.set_workspace_root(selected)
    reset_workspace_cache()
    project_mount.rescan_projects()

    assert project_mount.scan_roots()[0] == selected.resolve()
    assert {mount.project_id for mount in project_mount.discover_projects()} == {
        "alpha-project",
        "beta-project",
    }


def test_workspace_root_api_validates_and_refreshes_discovery(tmp_path: Path):
    root = tmp_path / "research"
    root.mkdir()
    _write_project(root, "alpha", "alpha-project")

    with TestClient(app) as client:
        assert client.get("/desktop/workspace-root").json() == {"workspace_root": None}
        response = client.put("/desktop/workspace-root", json={"workspace_root": str(root)})
        assert response.status_code == 200
        assert response.json() == {"workspace_root": str(root.resolve())}
        assert client.get("/desktop/workspace-root").json() == response.json()
        assert client.put(
            "/desktop/workspace-root", json={"workspace_root": str(root / "missing")}
        ).status_code == 400

    assert project_mount.get_mount("alpha-project") is not None
