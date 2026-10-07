"""Spike A: CRDT document, FS bridge, and concurrent browser/agent edits."""

from __future__ import annotations

import base64
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from koi.paper.collaboration.document import CollabDocument
from koi.paper.collaboration.fs_bridge import FilesystemBridge
from koi.paper.collaboration.ids import document_id, room_id
from koi.paper.collaboration.materializer import atomic_write_text
from koi.paper.collaboration.revisions import content_hash
from koi.paper.collaboration.session import (
    CollabSession,
    get_session,
    shutdown_all_sessions,
)
from koi.paper.collaboration.text_ops import import_relative, prefix_suffix_span
from koi.paper.generator import TEX_NAME


@pytest.fixture(autouse=True)
def _clean_sessions():
    yield
    shutdown_all_sessions()


def test_document_ids_are_deterministic() -> None:
    assert document_id("github:ZoyaV/paper", "neurips", "sections/method.tex") == (
        "github:ZoyaV/paper:neurips:sections/method.tex"
    )
    assert room_id("a", "b", "main.tex") == room_id("a", "b", "main.tex")
    assert room_id("a", "b", "main.tex") != room_id("a", "c", "main.tex")


def test_prefix_suffix_span_insert_and_replace() -> None:
    span = prefix_suffix_span("hello", "helXlo")
    assert span.start == 3
    assert span.end == 3
    assert span.new_text == "X"
    span = prefix_suffix_span("The model performs well.", "The proposed model performs well.")
    assert "proposed " in span.new_text


def test_pycrdt_documents_converge() -> None:
    left = CollabDocument("hello")
    right = CollabDocument()
    right.apply_update(left.get_update())
    assert right.to_string() == "hello"
    state = right.get_state()
    left.apply_edit(5, 0, "!")
    right.apply_update(left.get_update(state))
    assert left.to_string() == right.to_string() == "hello!"


def test_pycrdt_server_edits_use_python_offsets_after_unicode() -> None:
    doc = CollabDocument("кккABC")
    assert doc.apply_edit(3, 3, "XYZ") == "кккXYZ"
    expected = "% 11кккккккцца\n\nHe\n\nHello!\n"
    assert doc.replace_with(expected)
    assert doc.to_string() == expected


def test_crdt_updates_are_relayed_verbatim_between_peers(tmp_path: Path) -> None:
    tex = tmp_path / "main.tex"
    tex.write_text("hello\n", encoding="utf-8")
    session = CollabSession(
        "demo", "emnlp", tex, watch=False, debounce_s=10, proposal_root=tmp_path / "proposals"
    )
    received: list[dict] = []
    session.join("alice")
    session.join("bob", handler=received.append)

    alice = CollabDocument()
    alice.apply_update(base64.b64decode(session.sync_event()["update"]))
    state = alice.get_state()
    alice.apply_edit(5, 0, "!")
    update = alice.get_update(state)
    ack = session.apply_crdt_update("alice", update)

    relayed = next(item for item in received if item.get("type") == "crdt_update")
    assert base64.b64decode(relayed["update"]) == update
    bob = CollabDocument()
    bob.apply_update(base64.b64decode(session.sync_event()["update"]))
    assert bob.to_string() == session.document.to_string() == "hello!\n"
    assert ack["type"] == "ack"
    command = session.latest_editor_command()
    assert command is not None
    assert command["text"] == "hello!\n"
    assert command["force"] is False
    assert command["save"] is True
    session.close()


def test_import_keeps_non_overlapping_human_edits() -> None:
    base = "aaa\nThe model performs well.\nzzz\n"
    current = "aaa\nThe proposed model performs well.\nzzz\n"
    incoming = "aaa\nThe model performs well.\nzzz\nThanks.\n"
    result = import_relative(base, current, incoming)
    assert result.ok
    assert "proposed" in result.text
    assert "Thanks." in result.text


def test_stale_revision_extends_same_insert() -> None:
    base = "The model performs well."
    current = "The model Xperforms well."
    incoming = "The model XYperforms well."
    result = import_relative(base, current, incoming)
    assert result.ok
    assert result.text == incoming


def test_session_fast_typing_does_not_insert_earlier(tmp_path: Path) -> None:
    tex = tmp_path / "main.tex"
    tex.write_text("The model performs well.\n", encoding="utf-8")
    session = CollabSession(
        "demo", "emnlp", tex, watch=False, debounce_s=10, proposal_root=tmp_path / "proposals"
    )
    session.join("alice", user_name="Alice")
    session.apply_client_op("alice", 10, 0, "X", 0)
    session.apply_client_op("alice", 11, 0, "Y", session.document.revision)
    assert session.document.to_string() == "The model XYperforms well.\n"
    session.close()


def test_repeated_letters_insert_at_caret_index(tmp_path: Path) -> None:
    tex = tmp_path / "main.tex"
    tex.write_text("aaa aaa\n", encoding="utf-8")
    session = CollabSession(
        "demo", "emnlp", tex, watch=False, debounce_s=10, proposal_root=tmp_path / "proposals"
    )
    session.join("a")
    session.apply_client_op("a", 4, 0, "X", 0)
    assert session.document.to_string() == "aaa Xaaa\n"
    session.close()


def test_client_op_reports_applied_span(tmp_path: Path) -> None:
    tex = tmp_path / "main.tex"
    tex.write_text("The model performs well.\n", encoding="utf-8")
    session = CollabSession(
        "demo", "emnlp", tex, watch=False, debounce_s=10, proposal_root=tmp_path / "proposals"
    )
    session.join("alice")
    event = session.apply_client_op("alice", 10, 0, "X", 0)
    assert event["origin"] == "alice"
    assert event["applied"] == {"start": 10, "delete_len": 0, "new_text": "X"}
    assert event["text"] == "The model Xperforms well.\n"
    session.close()


def test_matching_hash_uses_caret_without_transform(tmp_path: Path) -> None:
    tex = tmp_path / "main.tex"
    tex.write_text("hello world\n", encoding="utf-8")
    session = CollabSession(
        "demo", "emnlp", tex, watch=False, debounce_s=10, proposal_root=tmp_path / "proposals"
    )
    session.join("a")
    session.join("b")
    session.apply_client_op("a", 0, 0, "NOTE ", 0)
    current = session.document.to_string()
    event = session.apply_client_op("b", 5, 0, "X", 0, base_hash=content_hash(current))
    assert event["applied"]["start"] == 5
    assert session.document.to_string() == "NOTE Xhello world\n"
    session.close()


def test_stale_op_is_transformed_against_log(tmp_path: Path) -> None:
    tex = tmp_path / "main.tex"
    tex.write_text("hello world\n", encoding="utf-8")
    session = CollabSession(
        "demo", "emnlp", tex, watch=False, debounce_s=10, proposal_root=tmp_path / "proposals"
    )
    session.join("a")
    session.join("b")
    session.apply_client_op("a", 0, 0, "NOTE ", 0)
    session.apply_client_op("b", 5, 0, "X", 0)
    assert session.document.to_string() == "NOTE helloX world\n"
    session.close()


def test_two_peers_same_index_keep_both_inserts(tmp_path: Path) -> None:
    tex = tmp_path / "main.tex"
    tex.write_text("hello\n", encoding="utf-8")
    session = CollabSession(
        "demo", "emnlp", tex, watch=False, debounce_s=10, proposal_root=tmp_path / "proposals"
    )
    session.join("a")
    session.join("b")
    session.apply_client_op("a", 5, 0, "A", 0)
    session.apply_client_op("b", 5, 0, "B", 0)
    text = session.document.to_string()
    assert "A" in text and "B" in text
    assert text.startswith("hello")
    session.close()


def test_three_peers_keep_each_others_inserts(tmp_path: Path) -> None:
    tex = tmp_path / "main.tex"
    tex.write_text("The model performs well.\n", encoding="utf-8")
    session = CollabSession(
        "demo", "emnlp", tex, watch=False, debounce_s=10, proposal_root=tmp_path / "proposals"
    )
    session.join("a")
    session.join("b")
    session.join("c")
    session.apply_client_op("a", 4, 0, " proposed", 0)
    session.apply_client_op("b", 24, 0, " extremely", 0)
    session.apply_client_op("c", 0, 0, "Note: ", 0)
    text = session.document.to_string()
    assert "proposed" in text
    assert "extremely" in text
    assert text.startswith("Note: ")
    session.close()


def test_overlapping_agent_edit_is_a_conflict() -> None:
    base = "The model performs well."
    current = "The proposed model performs extremely well."
    incoming = "Our method significantly outperforms the baseline."
    result = import_relative(base, current, incoming)
    assert result.conflict
    assert result.text == current


def test_bridge_ignores_own_materialization(tmp_path: Path) -> None:
    tex = tmp_path / "main.tex"
    tex.write_text("hello\n", encoding="utf-8")
    doc = CollabDocument("hello\n")
    bridge = FilesystemBridge(doc, tex)
    assert not bridge.materialize().wrote
    doc.apply_edit(5, 0, "!")
    assert bridge.materialize().wrote
    assert tex.read_text(encoding="utf-8") == "hello!\n"
    assert bridge.is_own_materialization()
    second = bridge.import_file()
    assert not second.changed
    assert doc.to_string() == "hello!\n"


def test_bridge_imports_external_write(tmp_path: Path) -> None:
    tex = tmp_path / "main.tex"
    tex.write_text("hello\n", encoding="utf-8")
    doc = CollabDocument("hello\n")
    bridge = FilesystemBridge(doc, tex)
    bridge.materialize()
    tex.write_text("hello world\n", encoding="utf-8")
    result = bridge.import_file()
    assert result.ok
    assert result.changed
    assert doc.to_string() == "hello world\n"


def test_flush_rejects_stale_hash_without_writing(tmp_path: Path) -> None:
    tex = tmp_path / "main.tex"
    original = "hello\n"
    updated = "hello world\n"
    tex.write_text(original, encoding="utf-8")
    session = CollabSession(
        "demo", "emnlp", tex, watch=False, debounce_s=10, proposal_root=tmp_path / "proposals"
    )
    session.apply_client_text("alice", updated, 0)

    rejected = session.flush(expected_hash=content_hash(original))
    assert rejected["type"] == "flush_rejected"
    assert rejected["hash"] == content_hash(updated)
    assert tex.read_text(encoding="utf-8") == original

    saved = session.flush(expected_hash=content_hash(updated))
    assert saved["type"] == "materialized"
    assert saved["hash"] == content_hash(updated)
    assert tex.read_text(encoding="utf-8") == updated
    session.close()


def test_atomic_write_replaces_file(tmp_path: Path) -> None:
    path = tmp_path / "main.tex"
    atomic_write_text(path, "one")
    atomic_write_text(path, "two")
    assert path.read_text(encoding="utf-8") == "two"
    assert not list(tmp_path.glob(".*.tmp"))


def test_session_two_browsers_and_agent(tmp_path: Path) -> None:
    tex = tmp_path / "main.tex"
    tex.write_text("The model performs well.\n", encoding="utf-8")
    session = CollabSession(
        "demo", "emnlp", tex, watch=False, debounce_s=0.05, proposal_root=tmp_path / "proposals"
    )
    events_a: list[dict] = []
    events_b: list[dict] = []
    session.join("alice", user_name="Alice", handler=events_a.append)
    session.join("bob", user_name="Bob", handler=events_b.append)

    session.apply_client_text("alice", "The proposed model performs well.\n", 0)
    assert session.document.to_string() == "The proposed model performs well.\n"
    assert any(item.get("type") == "crdt_update" for item in events_b)

    task = session.register_agent_task("review-1")
    assert task.base_revision == session.document.revision
    incoming = "The proposed model performs well.\nThanks.\n"
    tex.write_text(incoming, encoding="utf-8")
    result = session.import_external(incoming, task_id="review-1", source="agent")
    assert result.ok
    assert "proposed" in session.document.to_string()
    assert "Thanks." not in session.document.to_string()
    assert session.proposal is not None
    assert session.proposal.source == "agent"
    assert tex.read_text(encoding="utf-8") == session.document.to_string()
    assert any(item.get("type") == "proposal" for item in events_b)

    proposal_id = session.proposal.id
    resolved = session.accept_proposal(proposal_id)
    assert resolved["resolution"] == "accepted"
    assert "Thanks." in session.document.to_string()
    assert tex.read_text(encoding="utf-8") == incoming
    assert any(item.get("type") == "proposal_resolved" for item in events_b)
    session.close()


def test_session_agent_from_old_revision_does_not_clobber(tmp_path: Path) -> None:
    tex = tmp_path / "main.tex"
    base = "The model performs well.\n"
    tex.write_text(base, encoding="utf-8")
    session = CollabSession(
        "demo", "emnlp", tex, watch=False, debounce_s=10, proposal_root=tmp_path / "proposals"
    )
    task = session.register_agent_task("old")
    session.apply_client_text("alice", "The proposed model performs well.\n", 0)
    incoming = "Our method significantly outperforms the baseline.\n"
    tex.write_text(incoming, encoding="utf-8")
    result = session.import_external(
        incoming,
        task_id=task.task_id,
        source="agent",
    )
    assert result.ok
    assert session.proposal is not None
    assert "proposed" in session.document.to_string()
    assert tex.read_text(encoding="utf-8") == session.document.to_string()
    proposal_id = session.proposal.id
    session.reject_proposal(proposal_id)
    assert session.proposal is None
    assert "proposed" in tex.read_text(encoding="utf-8")
    with pytest.raises(KeyError):
        session.accept_proposal(proposal_id)
    session.close()


def test_rejected_snapshot_does_not_return_or_clobber_edits(tmp_path: Path) -> None:
    tex = tmp_path / "main.tex"
    original = "policies for interactive tasks,\n"
    replacement = "policies for sequential decision making,\n"
    tex.write_text(original, encoding="utf-8")
    session = CollabSession(
        "demo", "emnlp", tex, watch=False, debounce_s=10, proposal_root=tmp_path / "proposals"
    )
    session.import_external(replacement, source="external")
    assert session.proposal is not None
    session.reject_proposal(session.proposal.id)
    assert session.proposal is None
    assert session.document.to_string() == original

    tex.write_text(replacement, encoding="utf-8")
    again = session.import_external(replacement, source="external")
    assert again.changed is False
    assert session.proposal is None
    assert session.document.to_string() == original
    assert tex.read_text(encoding="utf-8") == original

    edited = "policies for interactive tasks, with a definition.\n"
    session.apply_client_text("alice", edited, 0)
    tex.write_text(replacement, encoding="utf-8")
    session.import_external(replacement, source="external")
    assert session.document.to_string() == edited
    assert tex.read_text(encoding="utf-8") == edited
    assert session.proposal is None
    session.close()


def test_proposal_survives_session_restart(tmp_path: Path) -> None:
    tex = tmp_path / "main.tex"
    tex.write_text("live\n", encoding="utf-8")
    proposal_root = tmp_path / "proposals"
    session = CollabSession(
        "demo", "emnlp", tex, watch=False, debounce_s=10, proposal_root=proposal_root
    )
    tex.write_text("candidate\n", encoding="utf-8")
    session.import_external("candidate\n")
    proposal_id = session.proposal.id if session.proposal else ""
    session.close()

    restored = CollabSession(
        "demo", "emnlp", tex, watch=False, debounce_s=10, proposal_root=proposal_root
    )
    assert restored.document.to_string() == "live\n"
    assert restored.proposal is not None
    assert restored.proposal.id == proposal_id
    assert restored.proposal.candidate == "candidate\n"
    restored.close()


def test_new_disk_save_replaces_pending_proposal_and_rejects_stale_id(tmp_path: Path) -> None:
    tex = tmp_path / "main.tex"
    tex.write_text("live\n", encoding="utf-8")
    session = CollabSession(
        "demo", "emnlp", tex, watch=False, debounce_s=10, proposal_root=tmp_path / "proposals"
    )
    tex.write_text("candidate one\n", encoding="utf-8")
    session.import_external("candidate one\n")
    first_id = session.proposal.id if session.proposal else ""
    tex.write_text("candidate two\n", encoding="utf-8")
    session.import_external("candidate two\n")
    assert session.proposal is not None
    assert session.proposal.id != first_id
    assert session.proposal.candidate == "candidate two\n"
    with pytest.raises(KeyError):
        session.accept_proposal(first_id)
    session.close()


def test_proposal_hunks_resolve_independently(tmp_path: Path) -> None:
    tex = tmp_path / "main.tex"
    current = "a\nb\nc\nd\ne\nf\n"
    candidate = "A\nb\nc\nd\ne\nF\n"
    tex.write_text(current, encoding="utf-8")
    session = CollabSession(
        "demo", "emnlp", tex, watch=False, debounce_s=10, proposal_root=tmp_path / "proposals"
    )
    session.import_external(candidate, source="cursor-buffer")
    assert session.proposal is not None
    first_id = session.proposal.id
    hunks = session.proposal.hunks()
    assert len(hunks) == 2

    accepted = session.resolve_proposal_hunk(first_id, hunks[0]["id"], accept=True)
    assert accepted["resolution"] == "accepted"
    assert session.document.to_string().startswith("A\n")
    assert session.document.to_string().endswith("f\n")
    assert session.proposal is not None
    assert len(session.proposal.hunks()) == 1
    with pytest.raises(KeyError):
        session.resolve_proposal_hunk(first_id, hunks[1]["id"], accept=True)

    remaining_id = session.proposal.id
    remaining_hunk = session.proposal.hunks()[0]
    rejected = session.resolve_proposal_hunk(
        remaining_id, remaining_hunk["id"], accept=False
    )
    assert rejected["resolution"] == "rejected"
    assert session.proposal is None
    assert session.document.to_string() == "A\nb\nc\nd\ne\nf\n"
    command = session.latest_editor_command()
    assert command is not None
    assert command["text"] == session.document.to_string()
    session.close()


def test_final_accepted_hunk_reconciles_cursor_buffer(tmp_path: Path) -> None:
    tex = tmp_path / "main.tex"
    current = "a\nb\nc\nd\ne\nf\n"
    candidate = "A\nb\nc\nd\ne\nF\n"
    tex.write_text(current, encoding="utf-8")
    session = CollabSession(
        "demo", "emnlp", tex, watch=False, debounce_s=10, proposal_root=tmp_path / "proposals"
    )
    session.import_external(candidate, source="cursor-buffer")
    proposal = session.proposal
    assert proposal is not None
    first, second = proposal.hunks()
    session.resolve_proposal_hunk(proposal.id, first["id"], accept=False)
    proposal = session.proposal
    assert proposal is not None
    remaining = proposal.hunks()[0]
    session.resolve_proposal_hunk(proposal.id, remaining["id"], accept=True)
    assert session.proposal is None
    assert session.document.to_string() == "a\nb\nc\nd\ne\nF\n"
    command = session.latest_editor_command()
    assert command is not None
    assert command["text"] == session.document.to_string()
    assert tex.read_text(encoding="utf-8") == session.document.to_string()
    session.close()


def test_moved_repeated_line_is_one_atomic_hunk(tmp_path: Path) -> None:
    tex = tmp_path / "main.tex"
    current = "title\n123\nbody\n"
    candidate = "title\nbody\n123\n"
    tex.write_text(current, encoding="utf-8")
    session = CollabSession(
        "demo", "emnlp", tex, watch=False, debounce_s=10, proposal_root=tmp_path / "proposals"
    )
    session.import_external(candidate, source="cursor-buffer")
    proposal = session.proposal
    assert proposal is not None
    hunks = proposal.hunks()
    assert len(hunks) == 1
    session.resolve_proposal_hunk(proposal.id, hunks[0]["id"], accept=True)
    assert session.document.to_string() == candidate
    assert tex.read_text(encoding="utf-8") == candidate
    session.close()


def test_put_tex_without_session_still_writes() -> None:
    client = TestClient(app)
    with tempfile.TemporaryDirectory() as tmp:
        slot = Path(tmp) / "emnlp-demo"
        slot.mkdir()
        (slot / TEX_NAME).write_text("% old\n", encoding="utf-8")
        with patch("api.routers.paper.parse_project"), patch(
            "api.routers.paper.get_paper_slot_dir",
            return_value=slot,
        ):
            put = client.put(
                "/projects/demo/papers/emnlp-demo/tex",
                json={"content": "new\n"},
            )
            assert put.status_code == 200
        assert (slot / TEX_NAME).read_text(encoding="utf-8") == "new\n"


def test_collab_rest_edit_and_live_get() -> None:
    client = TestClient(app)
    with tempfile.TemporaryDirectory() as tmp:
        slot = Path(tmp) / "emnlp-demo"
        slot.mkdir()
        (slot / TEX_NAME).write_text("hello\n", encoding="utf-8")
        with patch("api.deps.parse_project"), patch(
            "api.routers.collaboration.parse_project",
        ), patch(
            "api.routers.paper.parse_project",
        ), patch(
            "api.routers.collaboration.get_paper_slot_dir",
            return_value=slot,
        ), patch(
            "api.routers.paper.get_paper_slot_dir",
            return_value=slot,
        ):
            opened = client.post("/projects/demo/papers/emnlp-demo/collab/open")
            assert opened.status_code == 200
            edited = client.post(
                "/projects/demo/papers/emnlp-demo/collab/edit",
                json={"text": "hello world\n", "base_revision": 0, "peer_id": "alice"},
            )
            assert edited.status_code == 200
            assert edited.json()["text"] == "hello world\n"
            got = client.get("/projects/demo/papers/emnlp-demo/tex")
            assert got.text == "hello world\n"
            flushed = client.post("/projects/demo/papers/emnlp-demo/collab/flush")
            assert flushed.status_code == 200
            buffered = client.post(
                "/collaboration/editor-buffer",
                json={
                    "path": str(slot / TEX_NAME),
                    "text": "unsaved cursor text\n",
                    "version": 7,
                },
            )
            assert buffered.status_code == 200
            assert buffered.json()["proposal"]["source"] == "cursor-buffer"
            assert (slot / TEX_NAME).read_text(encoding="utf-8") == "hello world\n"
            buffer_proposal_id = buffered.json()["proposal"]["id"]
            rejected_buffer = client.post(
                "/projects/demo/papers/emnlp-demo/collab/proposal/reject",
                json={"proposal_id": buffer_proposal_id},
            )
            assert rejected_buffer.status_code == 200
            editor_command = client.get(
                "/collaboration/editor-buffer/command",
                params={"path": str(slot / TEX_NAME)},
            )
            assert editor_command.status_code == 200
            assert editor_command.json()["command"]["text"] == "hello world\n"
            forced_sync = client.post(
                "/collaboration/editor-buffer/sync",
                json={"path": str(slot / TEX_NAME), "force": True},
            )
            assert forced_sync.status_code == 200
            assert forced_sync.json()["command"]["force"] is True
            (slot / TEX_NAME).write_text("agent candidate\n", encoding="utf-8")
            live_session = get_session("demo", "emnlp-demo")
            assert live_session is not None
            live_session._poll_file()
            proposal_response = client.get(
                "/projects/demo/papers/emnlp-demo/collab/proposal"
            )
            proposal = proposal_response.json()["proposal"]
            assert proposal["candidate_hash"] == content_hash("agent candidate\n")
            assert (slot / TEX_NAME).read_text(encoding="utf-8") == "hello world\n"
            accepted = client.post(
                "/projects/demo/papers/emnlp-demo/collab/proposal/accept",
                json={"proposal_id": proposal["id"]},
            )
            assert accepted.status_code == 200
            assert (slot / TEX_NAME).read_text(encoding="utf-8") == "agent candidate\n"
            stale = client.post(
                "/projects/demo/papers/emnlp-demo/collab/proposal/accept",
                json={"proposal_id": proposal["id"]},
            )
            assert stale.status_code == 409
            with client.websocket_connect(
                "/projects/demo/papers/emnlp-demo/collab?peer=bob&user=Bob"
            ) as ws:
                first = ws.receive_json()
                assert first["type"] == "sync"
                browser_doc = CollabDocument()
                browser_doc.apply_update(base64.b64decode(first["update"]))
                assert browser_doc.to_string() == "agent candidate\n"
        assert (slot / TEX_NAME).read_text(encoding="utf-8") == "agent candidate\n"


def test_collab_websocket_flush_correlates_and_checks_hash() -> None:
    client = TestClient(app)
    with tempfile.TemporaryDirectory() as tmp:
        slot = Path(tmp) / "emnlp-demo"
        slot.mkdir()
        tex = slot / TEX_NAME
        tex.write_text("hello\n", encoding="utf-8")
        with patch("api.deps.parse_project"), patch(
            "api.routers.collaboration.parse_project",
        ), patch(
            "api.routers.collaboration.get_paper_slot_dir",
            return_value=slot,
        ):
            with client.websocket_connect(
                "/projects/demo/papers/emnlp-demo/collab?peer=alice&user=Alice"
            ) as ws:
                def receive_type(expected_type: str) -> dict:
                    for _ in range(8):
                        message = ws.receive_json()
                        if message.get("type") == expected_type:
                            return message
                    raise AssertionError(f"websocket did not send {expected_type}")

                sync = ws.receive_json()
                assert sync["type"] == "sync"
                receive_type("hello")
                browser_doc = CollabDocument()
                browser_doc.apply_update(base64.b64decode(sync["update"]))
                state = browser_doc.get_state()
                browser_doc.apply_edit(5, 0, " world")
                ws.send_json(
                    {
                        "type": "crdt_update",
                        "update": base64.b64encode(browser_doc.get_update(state)).decode("ascii"),
                    }
                )
                receive_type("ack")

                ws.send_json(
                    {
                        "type": "flush",
                        "request_id": "stale-save",
                        "expected_hash": content_hash("hello\n"),
                    }
                )
                rejected = receive_type("flush_rejected")
                assert rejected["type"] == "flush_rejected"
                assert rejected["request_id"] == "stale-save"
                assert tex.read_text(encoding="utf-8") == "hello\n"

                expected = content_hash("hello world\n")
                ws.send_json(
                    {
                        "type": "flush",
                        "request_id": "current-save",
                        "expected_hash": expected,
                    }
                )
                saved = receive_type("materialized")
                assert saved["type"] == "materialized"
                assert saved["request_id"] == "current-save"
                assert saved["hash"] == expected
                assert tex.read_text(encoding="utf-8") == "hello world\n"
