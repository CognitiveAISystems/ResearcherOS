"""Tests for persistence-free Project aggregate mutations."""

from __future__ import annotations

import pytest

from koi.core import project_ops
from koi.core.models import (
    ExperimentCard,
    KanbanBoard,
    MethodResearchQuestion,
    Node,
    NodeType,
    Project,
)


def project_tree() -> Project:
    return Project(
        id="demo",
        title="Demo",
        nodes=[
            Node(
                id="problem",
                project_id="demo",
                parent_id=None,
                node_type=NodeType.PROBLEM,
                title="Problem",
            ),
            Node(
                id="cause",
                project_id="demo",
                parent_id="problem",
                node_type=NodeType.CAUSE,
                title="Cause",
            ),
            Node(
                id="remediation",
                project_id="demo",
                parent_id="cause",
                node_type=NodeType.REMEDIATION,
                title="Remediation",
            ),
        ],
    )


def test_add_method_creates_its_board_without_persistence() -> None:
    project = project_tree()

    node = project_ops.add_node(
        project,
        "remediation",
        NodeType.METHOD,
        "Method",
    )

    assert node in project.nodes
    assert len(project.boards) == 1
    assert project.boards[0].owner_node_id == node.id
    assert [column.id for column in project.boards[0].columns] == [
        "backlog",
        "running",
        "done",
    ]


def test_add_node_enforces_domain_tree_rules() -> None:
    project = project_tree()

    with pytest.raises(ValueError, match="Cannot add"):
        project_ops.add_node(project, "problem", NodeType.METHOD, "Invalid")


def test_update_method_validates_and_normalizes_research_questions() -> None:
    project = project_tree()
    method = project_ops.add_node(
        project,
        "remediation",
        NodeType.METHOD,
        "Method",
    )
    project.boards[0].cards.append(
        ExperimentCard(
            id="card-a",
            board_id=project.boards[0].id,
            column_id="backlog",
            title="Experiment",
        )
    )

    project_ops.update_node(
        project,
        method.id,
        research_questions=[
            MethodResearchQuestion(
                id="rq-a",
                question="  What changed?  ",
                answer="  raw  ",
                narrative="  conclusion  ",
                importance=5,
                card_id="card-a",
            )
        ],
    )

    question = method.research_questions[0]
    assert question.question == "What changed?"
    assert question.answer == "raw"
    assert question.narrative == "conclusion"
    assert question.importance == 5


def test_delete_node_removes_descendants_and_owned_boards() -> None:
    project = project_tree()
    method = project_ops.add_node(
        project,
        "remediation",
        NodeType.METHOD,
        "Method",
    )

    project_ops.delete_node(project, "remediation")

    assert {node.id for node in project.nodes} == {"problem", "cause"}
    assert all(board.owner_node_id != method.id for board in project.boards)


def test_update_board_rejects_board_outside_aggregate() -> None:
    project = project_tree()
    board = KanbanBoard(id="missing", owner_node_id="method")

    with pytest.raises(ValueError, match="Board not found"):
        project_ops.update_board(project, board)
