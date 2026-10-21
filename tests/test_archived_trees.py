"""The archive survives new clients/ports and does not alter workspace selection."""

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from koi.adapters import desktop_workspace


@pytest.fixture(autouse=True)
def config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("KOI_DESKTOP_CONFIG_DIR", str(tmp_path / "settings"))


def test_archive_survives_restart_and_unarchive(tmp_path):
    desktop_workspace.set_workspace_root(tmp_path)
    with TestClient(app, base_url="http://localhost:12345") as client:
        assert client.get("/desktop/archived-trees").json() == {"ids": None}
        response = client.put("/desktop/archived-trees", json={"ids": ["a", "composite:b", "a"]})
        assert response.status_code == 200
        assert response.json() == {"ids": ["a", "composite:b"]}
    importlib.reload(desktop_workspace)
    with TestClient(app, base_url="http://localhost:54321") as client:
        assert client.get("/desktop/archived-trees").json() == {"ids": ["a", "composite:b"]}
        assert client.put("/desktop/archived-trees", json={"ids": []}).status_code == 200
    importlib.reload(desktop_workspace)
    assert desktop_workspace.archived_tree_ids() == []
    assert desktop_workspace.selected_workspace_root() == tmp_path


def test_invalid_settings_are_not_silently_reset():
    path = desktop_workspace.application_support_dir() / "archived-trees.json"
    path.parent.mkdir(parents=True)
    path.write_text('{broken', encoding="utf-8")
    with TestClient(app) as client:
        assert client.get("/desktop/archived-trees").status_code == 500
        assert client.put("/desktop/archived-trees", json={"ids": [42]}).status_code == 422
    assert path.read_text() == '{broken'


def test_failed_write_preserves_previous_archive(monkeypatch):
    desktop_workspace.save_archived_tree_ids(["a"])
    def fail(*args):
        raise OSError("disk full")
    monkeypatch.setattr(Path, "replace", fail)
    with TestClient(app) as client:
        assert client.put("/desktop/archived-trees", json={"ids": []}).status_code == 500
    assert desktop_workspace.archived_tree_ids() == ["a"]
    assert len(list(desktop_workspace.application_support_dir().iterdir())) == 1
