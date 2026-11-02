"""Tests for background project discovery watcher."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from koi.adapters import project_mount as pm
from koi.adapters import project_discovery_watch as watch
from koi.adapters.workspace import reset_workspace_cache


@pytest.fixture(autouse=True)
def _reset_watch_state():
    watch._stop_event.set()
    if watch._watch_thread and watch._watch_thread.is_alive():
        watch._watch_thread.join(timeout=2.0)
    watch._stop_event.clear()
    with watch._lock:
        watch._revision = 0
        watch._running = False
        watch._last_fingerprint = {}
        for key in watch._pending_changes:
            watch._pending_changes[key].clear()
    watch._watch_thread = None
    yield
    watch._stop_event.set()


@pytest.fixture
def discovery_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    engine = tmp_path / "ReseachOS"
    engine.mkdir()
    repo = tmp_path / "sample_project"
    koi = repo / "koi-structure"
    koi.mkdir(parents=True)
    (repo / "projectcode").mkdir()
    (koi / "project.md").write_text(
        "---\nid: sample-project\ntitle: Sample\nprograms:\n  - test-program\ncode_root: ../projectcode\n---\n\n# problem: p\n\nSample\n",
        encoding="utf-8",
    )
    (koi / "research.json").write_text(
        json.dumps({"version": 1, "questions": []}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pm, "ENGINE_ROOT", engine)
    monkeypatch.setattr(pm, "scan_roots", lambda: (tmp_path,))
    monkeypatch.setenv("KOI_SCAN_ROOTS", str(tmp_path))
    reset_workspace_cache()
    pm.rescan_projects()
    yield tmp_path
    reset_workspace_cache()


def test_scan_once_detects_new_project(discovery_layout: Path):
    watch.scan_once(initial=True)
    assert watch.discovery_status()["projects"] == ["sample-project"]

    repo2 = discovery_layout / "another_project"
    koi2 = repo2 / "koi-structure"
    koi2.mkdir(parents=True)
    (koi2 / "project.md").write_text(
        "---\nid: another-project\ntitle: Another\n---\n\n# problem: p\n",
        encoding="utf-8",
    )

    result = watch.scan_once()
    assert result.added == ("another-project",)
    status = watch.discovery_status()
    assert status["revision"] == 1
    assert status["projects"] == ["another-project", "sample-project"]
    assert status["changes"]["added"] == [
        {"id": "another-project", "title": "Another"}
    ]

    # Up-to-date clients receive no repeat until the next change.
    assert watch.discovery_status(since_revision=1)["changes"]["added"] == []


def test_discovery_status_since_revision(discovery_layout: Path):
    watch.scan_once(initial=True)
    before = watch.discovery_status(since_revision=0)
    assert before["revision"] == 0
    assert before["changes"]["added"] == []


def test_start_watch_sets_running(discovery_layout: Path):
    watch.start_project_discovery_watch()
    import time

    time.sleep(0.1)
    status = watch.discovery_status()
    assert status["running"] is True
    assert "sample-project" in status["projects"]
    watch.stop_project_discovery_watch()


def test_changed_graph_is_delivered_to_each_browser(discovery_layout: Path):
    watch.scan_once(initial=True)
    md = discovery_layout / "sample_project/koi-structure/project.md"
    import os

    stamp = md.stat().st_mtime
    md.write_text(md.read_text() + "\n## method: new-method\n", encoding="utf-8")
    os.utime(md, (stamp + 1, stamp + 1))
    assert watch.scan_once().changed == ("sample-project",)
    first = watch.discovery_status(since_revision=0)
    second = watch.discovery_status(since_revision=0)
    assert first == second
    assert first["changes"]["changed"] == [{"id": "sample-project", "title": "Sample"}]
    assert watch.discovery_status(since_revision=1)["changes"]["changed"] == []

    os.utime(md, (stamp + 2, stamp + 2))
    watch.scan_once()
    latest = watch.discovery_status(since_revision=1)
    assert latest["revision"] == 2
    assert latest["changes"]["changed"] == first["changes"]["changed"]
    assert len(watch._pending_changes["changed"]) == 1
