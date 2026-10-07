"""Tests for done-research queue helpers."""

from __future__ import annotations

import json
from pathlib import Path

from koi.adapters import done_research_queue as drq
from koi.core.models import (
    ExperimentCard,
    KanbanBoard,
    MethodResearchQuestion,
    Node,
    NodeType,
    Project,
    ResearchQuestionCertainty,
)


def _sample_project(*, column_id: str = "backlog") -> Project:
    method_id = "m-test"
    board_id = "board-test"
    card_id = "c-test"
    return Project(
        id="proj-test",
        title="Test",
        nodes=[
            Node(
                id=method_id,
                project_id="proj-test",
                parent_id=None,
                node_type=NodeType.METHOD,
                title="Method",
            )
        ],
        boards=[
            KanbanBoard(
                id=board_id,
                owner_node_id=method_id,
                cards=[
                    ExperimentCard(
                        id=card_id,
                        board_id=board_id,
                        column_id=column_id,
                        title="Card",
                    )
                ],
            )
        ],
    )


def test_enqueue_on_transition_to_done(tmp_path: Path, monkeypatch) -> None:
    queue = tmp_path / "done-research-queue.json"
    monkeypatch.setattr(drq, "QUEUE_PATH", queue)
    monkeypatch.setattr(
        "koi.adapters.project_sync_queue.enqueue_push", lambda *a, **k: None
    )

    before = _sample_project(column_id="running")
    after = _sample_project(column_id="done")

    drq.sync_done_research_on_save(before, after)

    items = json.loads(queue.read_text(encoding="utf-8"))
    assert len(items) == 1
    assert items[0]["card_id"] == "c-test"


def test_skip_when_rq_already_exists(tmp_path: Path, monkeypatch) -> None:
    queue = tmp_path / "done-research-queue.json"
    monkeypatch.setattr(drq, "QUEUE_PATH", queue)

    after = _sample_project(column_id="done")
    after.nodes[0].research_questions = [
        MethodResearchQuestion(
            id="rq-1",
            question="Q?",
            narrative="A.",
            certainty=ResearchQuestionCertainty.DEFINITE,
            card_id="c-test",
        )
    ]

    assert drq.reconcile_done_research_queue(after) == 0
    assert not queue.exists()


def test_skip_when_rq_mentions_card_in_answer(tmp_path: Path, monkeypatch) -> None:
    queue = tmp_path / "done-research-queue.json"
    monkeypatch.setattr(drq, "QUEUE_PATH", queue)

    after = _sample_project(column_id="done")
    after.nodes[0].research_questions = [
        MethodResearchQuestion(
            id="rq-1",
            question="Q?",
            narrative="A.",
            answer="pipeline includes c-test smoke OK",
            certainty=ResearchQuestionCertainty.DEFINITE,
            card_id="c-other",
        )
    ]

    assert drq.reconcile_done_research_queue(after) == 0
    assert not queue.exists()


def test_auto_parses_json_and_saves_question(monkeypatch) -> None:
    from koi.projects import done_research_auto as auto

    saved: list = []
    discoveries: list = []
    monkeypatch.setattr(auto, "load_env_file", lambda: None)
    monkeypatch.setattr(auto, "_cursor_cli", lambda prompt: None)
    monkeypatch.setattr(
        auto,
        "build_context",
        lambda *a, **k: {
            "project_id": "proj-test",
            "board_id": "board-test",
            "card_id": "c-test",
            "method": {"id": "m-test", "research_questions": []},
        },
    )
    monkeypatch.setattr(
        auto,
        "run_agent",
        lambda *a, **k: (
            '{"question":"Стало ли лучше?","narrative":"Да, стало.","answer":"1","certainty":"definite","importance":4}',
            "test",
        ),
    )
    monkeypatch.setattr(auto, "update_node", lambda *a, **k: saved.append(a) or None)
    monkeypatch.setattr(auto, "dequeue", lambda *a, **k: True)
    monkeypatch.setattr(auto, "append_discoveries", discoveries.extend)

    assert auto.process_card("proj-test", "board-test", "c-test")
    questions = saved[0][2].research_questions
    assert questions[0].question == "Стало ли лучше?"
    assert questions[0].card_id == "c-test"
    assert discoveries[0]["card_id"] == "c-test"


def test_reconcile_catches_already_done_without_rq(tmp_path: Path, monkeypatch) -> None:
    queue = tmp_path / "done-research-queue.json"
    monkeypatch.setattr(drq, "QUEUE_PATH", queue)
    monkeypatch.setattr(
        "koi.adapters.project_sync_queue.enqueue_push", lambda *a, **k: None
    )

    project = _sample_project(column_id="done")
    assert drq.reconcile_done_research_queue(project) == 1
    assert drq.reconcile_done_research_queue(project) == 0
