"""Worker attribution follows reports and card edits in the research checkout."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from koi.projects import discoveries


@pytest.fixture
def research_repo(tmp_path, monkeypatch):
    code = tmp_path / "demo"
    tree = tmp_path / "tree" / "demo"
    code.mkdir()
    structure = tree / "koi-structure"
    structure.mkdir(parents=True)

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tree, check=True, capture_output=True, text=True
        )

    git("init", "-q")
    git("config", "user.name", "machine-owner")
    git("config", "user.email", "machine@example.test")

    def commit(name, email="person@example.test"):
        git("add", ".")
        git("-c", f"user.name={name}", "-c", f"user.email={email}", "commit", "-qm", "Update research")

    path = structure / "project.md"
    header = """---
id: demo
title: Demo
---
# problem: problem
Problem
## cause: cause
Cause
### remediation: remedy
Remedy
#### method: method
Method
<!-- koi:kanban board-method -->
| backlog | running | done | successful |
| --- | --- | --- | --- |
"""
    path.write_text(header + "| | First <!-- id:first --> | | |\n")
    commit("alice")
    mount = SimpleNamespace(repo_root=code, koi_root=structure)
    monkeypatch.setattr("koi.adapters.project_mount.get_mount_or_raise", lambda _: mount)
    monkeypatch.setattr("koi.adapters.card_reports.project_reports_dir", lambda _: structure / "reports")
    return tree, path, commit, git


def test_workers_use_current_tree_without_guessing_local_author(research_repo):
    tree, path, commit, git = research_repo
    # The machine owner and last editor of the tree did not write this new card.
    path.write_text(path.read_text() + "| | Local <!-- id:local --> | | |\n")
    assert discoveries._project_md_git_candidates("demo")[0] == (tree, "koi-structure/project.md")
    items = discoveries.running_kanban_activity("demo")
    assert {item["card_id"]: item["authors"] for item in items} == {
        "first": ["alice"], "local": []
    }


def test_report_and_card_contributors_survive_rename_and_ignore_other_cards(research_repo):
    tree, path, commit, git = research_repo
    reports = path.parent / "reports"
    reports.mkdir()
    report = reports / "first.md"
    report.write_text("First results\n")
    (reports / "index.json").write_text(json.dumps({"first": "first.md"}))
    commit("Bob Smith", "42+bob@users.noreply.github.com")
    git("mv", "koi-structure/reports/first.md", "koi-structure/reports/renamed.md")
    (reports / "renamed.md").write_text("First results\nMore results\n")
    (reports / "index.json").write_text(json.dumps({"first": "renamed.md"}))
    commit("alice")
    # Editing another card must not attribute first to carol.
    path.write_text(path.read_text() + "| Other <!-- id:other --> | | | |\n")
    commit("carol")
    item = discoveries.running_kanban_activity("demo")[0]
    assert set(item["authors"]) == {"alice", "bob"}
    assert "carol" not in item["author"]


def test_multiple_editors_of_card_row_are_contributors(research_repo):
    tree, path, commit, git = research_repo
    path.write_text(path.read_text().replace("First <!--", "New title <!--"))
    commit("bob")
    assert set(discoveries.running_kanban_activity("demo")[0]["authors"]) == {"alice", "bob"}
