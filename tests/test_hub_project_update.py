from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from hub.app.access import can_view_project_with_store
from hub.app.config import HubConfig
from hub.app.main import UpdateProjectBody, update_project
from hub.app.store import HubProject, HubStore


def _store(tmp_path) -> HubStore:
    return HubStore(
        HubConfig(
            public_url="http://localhost",
            github_client_id="",
            github_client_secret="",
            session_secret="test",
            data_dir=tmp_path,
            s3_bucket="",
            s3_endpoint="",
            s3_access_key="",
            s3_secret_key="",
            default_branch="koi/research",
            koi_path="koi-structure",
        )
    )


def _project(slug="demo", branch="koi/research", visibility="public") -> HubProject:
    return HubProject(
        slug=slug,
        owner_github_id=7,
        owner_login="alice",
        repo_full_name="alice/research",
        branch=branch,
        title="Research",
        visibility=visibility,
        secret_token="old-token" if visibility == "unlisted" else "",
    )


def _run(body: UpdateProjectBody):
    return asyncio.run(update_project(SimpleNamespace(), "demo", body))


def _setup(monkeypatch, tmp_path):
    store = _store(tmp_path)
    project = _project()
    store.save_project(project)
    monkeypatch.setattr("hub.app.main.store", store)
    monkeypatch.setattr(
        "hub.app.main.require_session",
        lambda *_args, **_kwargs: SimpleNamespace(github_id=7, access_token="token"),
    )

    async def sync(candidate, _token):
        store.save_snapshot(candidate.slug, {"meta": {"branch": candidate.branch}})
        store.save_project(candidate)
        return {"project": {}}

    monkeypatch.setattr("hub.app.main._sync_project", sync)
    return store


def test_enabled_only_update_remains_compatible(monkeypatch, tmp_path):
    store = _setup(monkeypatch, tmp_path)
    result = _run(UpdateProjectBody(enabled=False))

    assert result["enabled"] is False
    assert store.get_project("demo").enabled is False


def test_branch_update_preserves_identity_and_social_data(monkeypatch, tmp_path):
    store = _setup(monkeypatch, tmp_path)
    store.toggle_like(42, "demo")
    store.add_bookmark(42, "demo", "")

    result = _run(UpdateProjectBody(branch=" safety-research "))

    assert result["branch"] == "safety-research"
    assert store.get_project("demo").slug == "demo"
    assert store.get_snapshot("demo")["meta"]["branch"] == "safety-research"
    assert store.get_likes("demo")["user_ids"] == [42]
    assert store.user_bookmarks(42)[0]["slug"] == "demo"


def test_failed_source_validation_keeps_project_and_snapshot(monkeypatch, tmp_path):
    store = _setup(monkeypatch, tmp_path)
    store.save_snapshot("demo", {"meta": {"branch": "koi/research"}})

    async def fail(_candidate, _token):
        raise HTTPException(400, "Failed to parse project.md")

    monkeypatch.setattr("hub.app.main._sync_project", fail)

    with pytest.raises(HTTPException) as error:
        _run(UpdateProjectBody(branch="broken"))

    assert error.value.status_code == 400
    assert store.get_project("demo").branch == "koi/research"
    assert store.get_snapshot("demo")["meta"]["branch"] == "koi/research"


def test_branch_collision_is_rejected(monkeypatch, tmp_path):
    store = _setup(monkeypatch, tmp_path)
    store.save_project(_project(slug="other", branch="taken"))

    with pytest.raises(HTTPException) as error:
        _run(UpdateProjectBody(branch="taken"))

    assert error.value.status_code == 409
    assert store.get_project("demo").branch == "koi/research"


def test_unlisted_token_rotates_after_leaving(monkeypatch, tmp_path):
    store = _setup(monkeypatch, tmp_path)
    secrets = iter(["token-one", "token-two"])
    monkeypatch.setattr(HubStore, "new_secret", staticmethod(lambda: next(secrets)))

    first = _run(UpdateProjectBody(visibility="unlisted"))
    assert first["secret_token"] == "token-one"
    store.add_bookmark(42, "demo", first["secret_token"])

    _run(UpdateProjectBody(visibility="network"))
    assert store.get_project("demo").secret_token == ""

    second = _run(UpdateProjectBody(visibility="unlisted"))
    assert second["secret_token"] == "token-two"
    assert second["secret_token"] != first["secret_token"]
    project = store.get_project("demo")
    assert not can_view_project_with_store(
        project, 42, store, token=first["secret_token"]
    )


def test_restricting_visibility_is_local_and_clears_skills(monkeypatch, tmp_path):
    store = _setup(monkeypatch, tmp_path)
    store.save_snapshot("demo", {"meta": {"visibility": "public"}})
    store.replace_project_skills(
        "demo", [{"id": "example", "key": "demo/example"}]
    )

    async def unexpected_sync(*_args):
        raise AssertionError("restricting visibility must not require GitHub")

    monkeypatch.setattr("hub.app.main._sync_project", unexpected_sync)
    result = _run(UpdateProjectBody(visibility="network"))

    assert result["visibility"] == "network"
    assert store.get_snapshot("demo")["meta"]["visibility"] == "network"
    assert store.list_skills_catalog() == []


def test_returning_to_public_resyncs_project(monkeypatch, tmp_path):
    store = _setup(monkeypatch, tmp_path)
    project = store.get_project("demo")
    project.visibility = "network"
    store.save_project(project)
    calls = []

    async def sync(candidate, _token):
        calls.append((candidate.branch, candidate.visibility))
        store.save_project(candidate)
        return {"project": {}}

    monkeypatch.setattr("hub.app.main._sync_project", sync)
    result = _run(UpdateProjectBody(visibility="public"))

    assert result["visibility"] == "public"
    assert calls == [("koi/research", "public")]


def test_invalid_visibility_and_non_owner_are_rejected(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    with pytest.raises(HTTPException) as invalid:
        _run(UpdateProjectBody(visibility="private"))
    assert invalid.value.status_code == 400

    monkeypatch.setattr(
        "hub.app.main.require_session",
        lambda *_args, **_kwargs: SimpleNamespace(github_id=99, access_token="token"),
    )
    with pytest.raises(HTTPException) as forbidden:
        _run(UpdateProjectBody(branch="other"))
    assert forbidden.value.status_code == 403


def test_project_manager_exposes_edit_form_and_action():
    root = Path(__file__).resolve().parents[1]
    html = (root / "hub/web/index.html").read_text(encoding="utf-8")
    js = (root / "hub/web/hub.js").read_text(encoding="utf-8")

    for element_id in (
        "hub-project-edit-modal",
        "hub-project-edit-form",
        "hub-project-edit-repo",
        "hub-project-edit-branch",
        "hub-project-edit-visibility",
        "hub-project-edit-status",
    ):
        assert f'id="{element_id}"' in html
    assert 'data-action="edit"' in js
    assert "initProjectEditModal" in js
    assert '{ branch: branch.value.trim(), visibility: visibility.value }' in js
