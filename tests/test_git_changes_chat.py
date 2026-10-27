"""Exercise the human-approved Git chat against real temporary repositories."""
from pathlib import Path
from types import SimpleNamespace
import subprocess
from datetime import datetime, timezone, timedelta

import pytest
from fastapi import BackgroundTasks, HTTPException

from koi.adapters import agent_chat_queue as queue
from koi.adapters import agent_chat_activity as activity
from koi.adapters import project_sync_queue as push_queue
from koi.adapters.project_mount import ProjectMount
from koi.agent_chat import conversations, git_changes as changes


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def tree(tmp_path, monkeypatch):
    remote = tmp_path / "remote.git"
    remote.mkdir()
    git(remote, "init", "--bare")
    repo = tmp_path / "tree" / "demo"
    root = repo / "koi-structure"
    root.mkdir(parents=True)
    git(repo, "init", "-b", "koi/research")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Research test")
    (root / "project.md").write_text("Original\n")
    (root / "research.json").write_text('{"questions": []}\n')
    (repo / "outside.txt").write_text("outside\n")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "initial")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-u", "origin", "koi/research")
    mount = ProjectMount("demo", repo, root, repo, (), True, "koi/research")
    monkeypatch.setattr(queue, "QUEUE_PATH", tmp_path / "chat-queue.json")
    monkeypatch.setattr(push_queue, "QUEUE_PATH", tmp_path / "push-queue.json")
    monkeypatch.setattr(conversations, "PATH", tmp_path / "conversations.json")
    monkeypatch.setattr(changes, "SCHEDULE_PATH", tmp_path / "git-checks.json")
    monkeypatch.setattr(activity, "ACTIVITY_DIR", tmp_path / "activity")
    monkeypatch.setattr(changes, "get_mount", lambda pid: mount if pid == "demo" else None)
    monkeypatch.setattr(changes.sync, "sync_mounts", lambda: [mount])
    def reviewer(prompt, *_a):
        import json
        if '{"draft":' in prompt:
            data = json.loads(prompt[prompt.index('{"draft":'):])
            return data['draft'].replace('\n\n' + changes.HELP, '')
        return "Напишите, что сделать: сохранить, отправить или объединить изменения."
    monkeypatch.setattr(changes, "_suggest", reviewer)
    changes._card_mtimes.clear()
    return mount, remote


def notice(mount):
    item = changes.notify(mount, changes.snapshot(mount))
    assert item
    changes.process(item)
    return conversations.find(item["conversation_id"])


def command(chat, text, token=None):
    item = queue.enqueue_question("demo", text, purpose="git_chat", conversation_id=chat["id"],
                                  git_snapshot=token or chat["git_snapshot"])
    changes.process(item)
    return queue.find_item(item["id"])


def test_notice_is_readonly_deduplicated_and_survives_restart(tree):
    mount, _ = tree
    (mount.koi_root / "project.md").write_text("Updated setup\n")
    before = git(mount.repo_root, "rev-parse", "HEAD")
    assert changes.scan_once(now=datetime(2026, 10, 27, 17, 59), fetch=False) == []
    items = changes.scan_once(now=datetime(2026, 10, 27, 18), fetch=False)
    assert len(items) == 1
    changes.process(items[0])
    assert git(mount.repo_root, "rev-parse", "HEAD") == before
    assert (mount.koi_root / "project.md").read_text() == "Updated setup\n"
    assert changes.scan_once(now=datetime(2026, 10, 27, 18, 1), fetch=False) == []
    changes._card_mtimes.clear()
    assert changes.scan_once(now=datetime(2026, 10, 27, 19), fetch=False) == []
    assert changes.scan_once(now=datetime(2026, 10, 28, 18), fetch=False) == []
    assert len(conversations.list_conversations("demo")) == 1
    assert len(queue._load()) == 1


def card_document(column):
    cells = ["", "", ""]
    cells[["backlog", "running", "done"].index(column)] = "Проверить сокращение памяти <!-- id:c-memory -->"
    return ("---\nid: demo\ntitle: Demo\ngit_repo: true\ngit_sync_branch: koi/research\n---\n"
            "# problem: p\n\nMemory\n\n#### method: m\n\nMemory check\n\n"
            "<!-- koi:kanban b -->\n| backlog | running | done |\n| --- | --- | --- |\n| " + " | ".join(cells) + " |\n")


def seed_card(mount, column="running"):
    (mount.koi_root / "project.md").write_text(card_document(column))
    git(mount.repo_root, "add", ".")
    git(mount.repo_root, "commit", "-m", "card baseline")
    git(mount.repo_root, "push", "origin", "koi/research")


def test_no_automatic_git_scan_for_ordinary_edits_before_local_18(tree, monkeypatch):
    mount, _ = tree
    (mount.koi_root / "project.md").write_text("Edited setup\n")
    monkeypatch.setattr(changes, "snapshot", lambda *_a: pytest.fail("Git scan before daily time"))
    monkeypatch.setattr(changes.sync, "_fetch_branch", lambda *_a: pytest.fail("Periodic fetch"))
    local = timezone(timedelta(hours=-7))
    assert changes.scan_once(now=datetime(2026, 10, 27, 17, 59, tzinfo=local)) == []
    assert changes.scan_once(now=datetime(2026, 10, 27, 17, 59, 59, tzinfo=local)) == []


def test_local_18_check_catches_up_after_closed_app_and_runs_once(tree, monkeypatch):
    mount, _ = tree
    (mount.koi_root / "project.md").write_text("Edited setup\n")
    calls = []
    monkeypatch.setattr(changes.sync, "_fetch_branch", lambda *_a: calls.append(True))
    local = timezone(timedelta(hours=9))
    items = changes.scan_once(now=datetime(2026, 10, 27, 20, tzinfo=local))
    assert len(items) == 1 and calls == [True]
    changes.process(items[0])
    changes._card_mtimes.clear()
    assert changes.scan_once(now=datetime(2026, 10, 27, 22, tzinfo=local)) == []
    assert calls == [True]
    changes.scan_once(now=datetime(2026, 10, 28, 18, tzinfo=local))
    assert calls == [True, True]


def test_missed_evening_check_catches_up_on_next_morning_launch(tree, monkeypatch):
    mount, _ = tree
    changes._save_schedule({"last_daily": "2026-10-25"})
    (mount.koi_root / "project.md").write_text("Edited while app was closed\n")
    calls = []
    monkeypatch.setattr(changes.sync, "_fetch_branch", lambda *_a: calls.append(True))
    items = changes.scan_once(now=datetime(2026, 10, 27, 9))
    assert len(items) == 1 and calls == [True]
    changes.process(items[0])
    assert changes._load_schedule()["last_daily"] == "2026-10-26"
    assert changes.scan_once(now=datetime(2026, 10, 27, 10)) == []
    assert calls == [True]
    changes.scan_once(now=datetime(2026, 10, 27, 18))
    assert calls == [True, True]


def test_external_card_done_triggers_check_without_waiting_for_evening(tree):
    mount, _ = tree
    seed_card(mount)
    now = datetime(2026, 10, 27, 10)
    assert changes.scan_once(now=now, fetch=False) == []
    (mount.koi_root / "project.md").write_text(card_document("done"))
    items = changes.scan_once(now=now, fetch=False)
    assert len(items) == 1
    changes.process(items[0])
    chat = conversations.find(items[0]["conversation_id"])
    assert chat["git_proposal"] == "commit_push"
    text = queue.find_item(items[0]["id"])["answer"]
    assert "Проверить сокращение памяти" in text
    assert "koi-structure" not in text and len(text) < 400
    assert changes.scan_once(now=now, fetch=False) == []


def test_save_hook_triggers_done_check_even_when_research_answer_exists(tree, monkeypatch):
    from koi.adapters import repository, done_research_queue
    from koi.core.md_io import parse_project_md
    from koi.core.models import MethodResearchQuestion
    mount, _ = tree
    seed_card(mount)
    before = parse_project_md(card_document("running"), project_id="demo")
    after = parse_project_md(card_document("done"), project_id="demo")
    after.nodes[-1].research_questions = [MethodResearchQuestion(id="rq-existing", question="Enough memory?", card_id="c-memory", narrative="Already answered")]
    monkeypatch.setattr(repository, "get_mount", lambda _id: mount)
    monkeypatch.setattr(repository, "_project_snapshot", lambda _id: before)
    monkeypatch.setattr(repository, "save_research", lambda _project: None)
    monkeypatch.setattr(done_research_queue, "sync_done_research_on_save", lambda *_a: None)
    monkeypatch.setattr("koi.knowledge.write_project_knowledge", lambda _project: None)
    repository.save_project(after)
    assert changes._load_schedule()["pending"]["demo"]["done"] == {"b/c-memory": "Проверить сокращение памяти"}
    assert len(changes.scan_once(now=datetime(2026, 10, 27, 10), fetch=False)) == 1


@pytest.mark.parametrize("changed,offer", [(19, False), (20, False), (21, True)])
def test_paper_threshold_is_strictly_more_than_20_percent(tree, changed, offer):
    mount, _ = tree
    paper = mount.koi_root / "paper" / "study" / "main.tex"
    paper.parent.mkdir(parents=True)
    words = [f"word{i}" for i in range(100)]
    paper.write_text(" ".join(words))
    git(mount.repo_root, "add", ".")
    git(mount.repo_root, "commit", "-m", "paper baseline")
    git(mount.repo_root, "push", "origin", "koi/research")
    paper.write_text(" ".join([f"revised{i}" for i in range(changed)] + words[changed:]))
    state = changes.snapshot(mount)
    assert changes._offer(state) is offer


def test_article_threshold_is_per_paper_and_accumulates_since_last_push(tree):
    mount, _ = tree
    one = mount.koi_root / "paper" / "one" / "main.tex"
    two = mount.koi_root / "paper" / "two" / "main.tex"
    for path, count in [(one, 100), (two, 2000)]:
        path.parent.mkdir(parents=True)
        path.write_text(" ".join(f"word{i}" for i in range(count)))
    git(mount.repo_root, "add", ".")
    git(mount.repo_root, "commit", "-m", "papers baseline")
    git(mount.repo_root, "push", "origin", "koi/research")
    words = one.read_text().split()
    one.write_text(" ".join([f"new{i}" for i in range(15)] + words[15:]))
    git(mount.repo_root, "add", ".")
    git(mount.repo_root, "commit", "-m", "first small edit")
    assert not changes._offer(changes.snapshot(mount))
    one.write_text(" ".join([f"new{i}" for i in range(21)] + words[21:]))
    assert changes._offer(changes.snapshot(mount))
    (one.parent / "main.aux").write_text("many build changes " * 1000)
    assert changes.snapshot(mount)["facts"]["paper_fraction"] == pytest.approx(.21)


def test_ordinary_report_update_does_not_offer_commit_or_push(tree):
    mount, _ = tree
    report = mount.koi_root / "reports" / "report.md"
    report.parent.mkdir()
    report.write_text("A small edit\n")
    chat = notice(mount)
    assert chat["git_proposal"] is None
    text = conversations.messages(chat["id"])[0]["answer"]
    assert "Обновлены отчёты" in text and "Сохранить" not in text


def test_combined_commit_push_requires_human_and_sends_approved_state(tree):
    mount, remote = tree
    seed_card(mount)
    (mount.koi_root / "project.md").write_text(card_document("done"))
    chat = notice(mount)
    before = git(remote, "rev-parse", "koi/research")
    assert chat["git_proposal"] == "commit_push"
    assert git(mount.repo_root, "rev-parse", "HEAD") == before
    reply = command(chat, "Сохранить и отправить")
    assert reply["answer"] == "Изменения сохранены и отправлены."
    assert git(remote, "rev-parse", "koi/research") == git(mount.repo_root, "rev-parse", "HEAD") != before


def test_incoming_notice_names_git_author_and_stays_short(tree):
    mount, remote = tree
    seed_card(mount)
    colleague_commit(mount, remote, card_document("done"))
    chat = notice(mount)
    text = conversations.messages(chat["id"])[0]["answer"]
    assert text.startswith("Новый коммит от Colleague.")
    assert "Проверить сокращение памяти" in text
    assert len(text) < 400 and "koi-structure" not in text
    assert chat["git_proposal"] == "merge"


def test_notice_is_reviewed_by_agent_before_any_offer(tree, monkeypatch):
    mount, _ = tree
    seed_card(mount)
    (mount.koi_root / "project.md").write_text(card_document("done"))
    calls = []
    def review(prompt, backend):
        calls.append(prompt)
        assert "Проверь предварительную сводку" in prompt
        assert "Проверить сокращение памяти" in prompt and '"diff":' in prompt
        return "Завершена проверка сокращения памяти. Статус карточки обновлён; результат эксперимента нужно смотреть в отчёте."
    monkeypatch.setattr(changes, "_suggest", review)
    chat = notice(mount)
    answer = conversations.messages(chat["id"])[0]["answer"]
    assert calls and answer.startswith("Завершена проверка сокращения памяти.")
    assert chat["git_proposal"] == "commit_push"
    assert "Напишите в чат" in answer


def test_automatic_notice_uses_available_reviewer_without_changing_human_chat_preference(tree):
    mount, _ = tree
    chat = conversations.create("demo", backend="cursor")
    conversations.update(chat["id"], kind="git_sync")
    (mount.koi_root / "project.md").write_text("Changed setup")
    item = changes.notify(mount, changes.snapshot(mount))
    assert not item.get("cli_agent")
    changes.process(item)
    assert conversations.find(chat["id"])["backend"] == "cursor"


def test_yes_after_single_reviewed_offer_commits_and_pushes(tree):
    mount, remote = tree
    seed_card(mount)
    (mount.koi_root / "project.md").write_text(card_document("done"))
    chat = notice(mount)
    before = git(remote, "rev-parse", "koi/research")
    assert command(chat, "да")["answer"] == "Изменения сохранены и отправлены."
    assert git(remote, "rev-parse", "koi/research") != before


def test_agent_failure_does_not_publish_draft_as_verified_or_allow_yes(tree, monkeypatch):
    mount, _ = tree
    seed_card(mount)
    (mount.koi_root / "project.md").write_text(card_document("done"))
    monkeypatch.setattr(changes, "_suggest", lambda *_a: None)
    chat = notice(mount)
    item = conversations.messages(chat["id"])[0]
    assert item["answer"] == changes.REVIEW_FAILED and item["answer_kind"] == "warning"
    assert chat["git_proposal"] is None
    before = git(mount.repo_root, "rev-parse", "HEAD")
    command(chat, "да")
    assert git(mount.repo_root, "rev-parse", "HEAD") == before


def test_new_edits_reject_yes_to_the_previous_reviewed_offer(tree):
    mount, _ = tree
    seed_card(mount)
    (mount.koi_root / "project.md").write_text(card_document("done"))
    chat = notice(mount)
    (mount.koi_root / "extra.md").write_text("New edit after review")
    before = git(mount.repo_root, "rev-parse", "HEAD")
    assert "Появились новые правки" in command(chat, "да")["answer"]
    assert git(mount.repo_root, "rev-parse", "HEAD") == before
    assert conversations.find(chat["id"])["git_proposal"] is None


def test_commit_and_push_are_separate_and_exclude_unrelated_staging(tree):
    mount, remote = tree
    (mount.repo_root / "outside.txt").write_text("unrelated work\n")
    git(mount.repo_root, "add", "outside.txt")
    (mount.koi_root / "project.md").write_text("New setup\n")
    (mount.koi_root / "new report.md").write_text("Results\n")
    chat = notice(mount)
    remote_before = git(remote, "rev-parse", "koi/research")
    reply = command(chat, "Сохранить коммит")
    assert "Сохранён коммит" in reply["answer"]
    assert git(mount.repo_root, "show", "--format=", "--name-only", "HEAD").splitlines() == [
        "koi-structure/new report.md", "koi-structure/project.md"]
    assert git(mount.repo_root, "diff", "--cached", "--name-only") == "outside.txt"
    assert git(remote, "rev-parse", "koi/research") == remote_before
    chat = conversations.find(chat["id"])
    assert "отправлены" in command(chat, "Отправить в Git")["answer"]
    assert git(remote, "rev-parse", "koi/research") == git(mount.repo_root, "rev-parse", "HEAD")


def test_same_file_changed_after_proposal_requires_new_instruction(tree):
    mount, _ = tree
    path = mount.koi_root / "project.md"
    path.write_text("A\n")
    chat = notice(mount)
    before = git(mount.repo_root, "rev-parse", "HEAD")
    path.write_text("B\n")
    reply = command(chat, "Сохранить коммит")
    assert "Появились новые правки" in reply["answer"]
    assert git(mount.repo_root, "rev-parse", "HEAD") == before
    assert git(mount.repo_root, "diff", "--cached", "--name-only") == ""
    fresh = conversations.find(chat["id"])
    assert fresh["git_snapshot"] != chat["git_snapshot"]
    assert "Сохранён коммит" in command(fresh, "Сохранить коммит")["answer"]


@pytest.mark.parametrize("message", ["да", "объясни, что значит коммит", "не делай коммит", "Сохранить коммит и отправить"])
def test_unapproved_or_ambiguous_reply_never_executes_git(tree, message):
    mount, remote = tree
    (mount.koi_root / "project.md").write_text("Changed\n")
    chat = notice(mount)
    before = git(mount.repo_root, "rev-parse", "HEAD")
    command(chat, message)
    assert git(mount.repo_root, "rev-parse", "HEAD") == before
    assert git(remote, "rev-parse", "koi/research") == before


def colleague_commit(mount, remote, content, filename="project.md"):
    clone = remote.parent / "colleague"
    git(remote.parent, "clone", "--branch", "koi/research", str(remote), str(clone))
    git(clone, "config", "user.email", "colleague@example.invalid")
    git(clone, "config", "user.name", "Colleague")
    (clone / "koi-structure" / filename).write_text(content)
    git(clone, "add", ".")
    git(clone, "commit", "-m", "colleague change")
    git(clone, "push", "origin", "koi/research")
    git(mount.repo_root, "fetch", "origin", "koi/research")


def test_incoming_commit_waits_for_human_then_merges(tree):
    mount, remote = tree
    before = git(mount.repo_root, "rev-parse", "HEAD")
    colleague_commit(mount, remote, "From colleague\n")
    chat = notice(mount)
    assert git(mount.repo_root, "rev-parse", "HEAD") == before
    assert "объединены" in command(chat, "да")["answer"]
    assert (mount.koi_root / "project.md").read_text() == "From colleague\n"


def test_diverged_branch_merges_after_human_command(tree):
    mount, remote = tree
    colleague_commit(mount, remote, "From colleague\n")
    (mount.koi_root / "research.json").write_text('{"questions": [1]}\n')
    git(mount.repo_root, "add", ".")
    git(mount.repo_root, "commit", "-m", "local results")
    chat = notice(mount)
    assert "объединены" in command(chat, "Объединить изменения")["answer"]
    assert len(git(mount.repo_root, "rev-list", "--parents", "-1", "HEAD").split()) == 3
    assert (mount.koi_root / "research.json").read_text() == '{"questions": [1]}\n'


def test_merge_conflict_is_aborted_without_choosing_content(tree):
    mount, remote = tree
    colleague_commit(mount, remote, "Remote choice\n")
    (mount.koi_root / "project.md").write_text("Local choice\n")
    git(mount.repo_root, "add", ".")
    git(mount.repo_root, "commit", "-m", "local choice")
    chat = notice(mount)
    before = git(mount.repo_root, "rev-parse", "HEAD")
    assert "Слияние отменено" in command(chat, "Объединить изменения")["answer"]
    assert (mount.koi_root / "project.md").read_text() == "Local choice\n"
    assert git(mount.repo_root, "rev-parse", "HEAD") == before
    assert git(mount.repo_root, "status", "--porcelain") == ""
    chat = conversations.find(chat["id"])
    assert chat["git_conflicts"] == chat["git_snapshot"]


@pytest.mark.parametrize("choice,expected", [
    ("Объединить с локальными вариантами", "Local choice\n"),
    ("Объединить с входящими вариантами", "Remote choice\n"),
])
def test_conflict_resolution_uses_only_human_selected_variant(tree, choice, expected):
    mount, remote = tree
    colleague_commit(mount, remote, "Remote choice\n")
    (mount.koi_root / "project.md").write_text("Local choice\n")
    git(mount.repo_root, "add", ".")
    git(mount.repo_root, "commit", "-m", "local choice")
    chat = notice(mount)
    command(chat, "Объединить изменения")
    chat = conversations.find(chat["id"])
    assert "объединены" in command(chat, choice)["answer"]
    assert (mount.koi_root / "project.md").read_text() == expected
    assert conversations.find(chat["id"])["git_conflicts"] is None


def test_notice_does_not_disclose_or_commit_secret_files(tree):
    mount, _ = tree
    (mount.koi_root / ".env").write_text("PRIVATE_TEST_VALUE=never-in-prompt\n")
    (mount.koi_root / "project.md").write_text("New setup\n")
    state = changes.snapshot(mount)
    assert state["files"] == ["koi-structure/project.md"]
    assert "PRIVATE_TEST_VALUE" not in changes._diff(mount, state)
    chat = notice(mount)
    assert "Сохранён коммит" in command(chat, "Сохранить коммит")["answer"]
    assert git(mount.repo_root, "ls-files", "koi-structure/.env") == ""
    chat = conversations.find(chat["id"])
    assert "не показанные в сводке" in command(chat, "Отправить в Git")["answer"]


def test_route_preserves_snapshot_and_does_not_trust_client_purpose(tree, monkeypatch):
    from api.routers import agents
    from api.schemas import AgentChatBody, ConversationScopeBody
    mount, _ = tree
    (mount.koi_root / "project.md").write_text("Changed\n")
    chat = notice(mount)
    monkeypatch.setattr(agents, "load_project", lambda *_a, **_kw: SimpleNamespace(boards=[]))
    monkeypatch.setattr(agents, "get_agent_chat_mode", lambda: "cursor_inbox")
    tasks = BackgroundTasks()
    reply = agents.post_agent_chat(AgentChatBody(project_id="demo", conversation_id=chat["id"],
        question="Сохранить коммит", purpose="question", git_snapshot=chat["git_snapshot"]), tasks)
    assert reply["item"]["purpose"] == "git_chat"
    assert reply["item"]["git_snapshot"] == chat["git_snapshot"]
    assert len(tasks.tasks) == 1
    with pytest.raises(HTTPException):
        agents.move_conversation(chat["id"], ConversationScopeBody(project_id="other"))


def test_corrupted_push_queue_does_not_break_status_and_is_backed_up(tmp_path, monkeypatch):
    path = tmp_path / "push.json"
    monkeypatch.setattr(push_queue, "QUEUE_PATH", path)
    path.write_bytes(b'[{"broken": "\x86"}]')
    assert push_queue.list_pending_push() == []
    assert path.read_bytes() == b'[{"broken": "\x86"}]'
    push_queue.enqueue_push("demo", "research_updated", "New results")
    assert len(push_queue.list_pending_push()) == 1
    assert list(tmp_path.glob("push.json.invalid-*"))[0].read_bytes() == b'[{"broken": "\x86"}]'


def test_runner_routes_git_messages_before_edit_capable_agent(tree, monkeypatch):
    from koi.agent_chat import runner
    mount, _ = tree
    (mount.koi_root / "project.md").write_text("New setup\n")
    item = changes.notify(mount, changes.snapshot(mount))
    monkeypatch.setattr(runner, "_run_local_agent", lambda *_a, **_kw: pytest.fail("generic write-capable agent"))
    assert runner.process_item(item["id"])
    assert queue.find_item(item["id"])["status"] == "answered"


def test_analysis_agent_gets_readonly_mode_and_has_no_edit_capable_fallback(monkeypatch):
    from koi.adapters import agent_backends
    from koi.agent_chat import runner
    monkeypatch.setattr(agent_backends, "cli_agents", lambda: [{"id": "codex", "available": True}])
    calls = []
    monkeypatch.setattr(agent_backends, "run_codex_exec", lambda prompt, **kw: calls.append(kw) or "Summary")
    assert changes._suggest("diff", "codex") == "Summary"
    assert calls == [{"timeout": 180, "allow_edits": False}]
    assert changes._suggest("diff", "claude") is None
    monkeypatch.setattr(agent_backends, "cli_agents", lambda: [{"id": "cursor", "available": True}])
    monkeypatch.setattr(runner, "_run_local_agent", lambda prompt, item_id, **kw: calls.append(kw) or ("Summary", "cursor"))
    assert changes._suggest("diff", "cursor") == "Summary"
    assert calls[-1]["mode"] == "ask" and calls[-1]["force"] is False


def test_default_reviewer_tries_another_readonly_cli_when_first_cannot_answer(monkeypatch):
    from koi.adapters import agent_backends
    from koi.agent_chat import runner
    monkeypatch.setattr(agent_backends, "cli_agents", lambda: [
        {"id": "cursor", "available": True}, {"id": "codex", "available": True}])
    monkeypatch.setattr(runner, "_run_local_agent", lambda *_a, **_kw: (None, None))
    calls = []
    monkeypatch.setattr(agent_backends, "run_codex_exec", lambda _prompt, **kw: calls.append(kw) or "Reviewed")
    assert changes._suggest("diff") == "Reviewed"
    assert calls == [{"timeout": 180, "allow_edits": False}]
    assert changes._suggest("diff", "cursor") is None


@pytest.mark.parametrize("mode,hook_input", [("stop", {"status": "completed"}), ("session", {"composer_mode": "ask"})])
def test_sync_hooks_do_not_pull_or_request_autonomous_git(mode, hook_input, monkeypatch, capsys):
    import io
    import json
    import runpy
    import sys
    path = Path(__file__).resolve().parents[1] / "agents/skills/koi-project-sync/hooks/koi-project-sync-hook.py"
    namespace = runpy.run_path(str(path), run_name="test_hook")
    main = namespace["main"]
    monkeypatch.setitem(main.__globals__, "MODE", mode)
    monkeypatch.setitem(main.__globals__, "git_summary", lambda **kw: pytest.fail("No Git needed for stop/ask"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(hook_input)))
    main()
    assert json.loads(capsys.readouterr().out) == {}


def test_session_hook_does_not_add_a_git_check(monkeypatch, capsys):
    import io
    import json
    import runpy
    import sys
    path = Path(__file__).resolve().parents[1] / "agents/skills/koi-project-sync/hooks/koi-project-sync-hook.py"
    main = runpy.run_path(str(path), run_name="test_hook")["main"]
    calls = []
    monkeypatch.setitem(main.__globals__, "MODE", "session")
    monkeypatch.setitem(main.__globals__, "git_summary", lambda **kw: calls.append(kw) or
                        {"behind": 1, "dirty_project_paths": ["demo/koi-structure/project.md"]})
    monkeypatch.setattr(sys, "stdin", io.StringIO('{}'))
    main()
    reply = json.loads(capsys.readouterr().out)
    assert calls == []
    assert reply == {}
