"""Unit tests for project and kanban application commands."""

from __future__ import annotations

import pytest

from koi.projects import commands as project_commands
from koi.core.models import (
    ExperimentCard,
    KanbanBoard,
    Node,
    NodeType,
    Project,
    ResearchQuestionCertainty,
)


@pytest.fixture
def project() -> Project:
    board = KanbanBoard(
        id="board-method",
        owner_node_id="method",
        cards=[
            ExperimentCard(
                id="card-a",
                board_id="board-method",
                column_id="backlog",
                title="Card A",
            ),
            ExperimentCard(
                id="card-b",
                board_id="board-method",
                column_id="backlog",
                title="Card B",
                depends_on=["card-a"],
            ),
        ],
    )
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
                id="method",
                project_id="demo",
                parent_id="problem",
                node_type=NodeType.METHOD,
                title="Method",
            ),
        ],
        boards=[board],
    )


@pytest.fixture
def command_context(monkeypatch, project: Project) -> dict[str, list]:
    calls: dict[str, list] = {
        "created_projects": [],
        "saved_projects": [],
        "updated_boards": [],
        "reports": [],
        "renames": [],
        "deletions": [],
        "sync": [],
    }
    monkeypatch.setattr(
        project_commands.repository,
        "create_project",
        lambda *args, **kwargs: calls["created_projects"].append((args, kwargs))
        or project,
    )
    monkeypatch.setattr(
        project_commands.repository,
        "load_project",
        lambda project_id, *, sync_reports=False: project if project_id == project.id else None,
    )
    monkeypatch.setattr(
        project_commands.repository,
        "save_project",
        lambda loaded: calls["saved_projects"].append(loaded),
    )
    monkeypatch.setattr(
        project_commands.repository,
        "update_board",
        lambda loaded, board: calls["updated_boards"].append((loaded, board))
        or board,
    )
    monkeypatch.setattr(
        project_commands.card_reports,
        "ensure_card_report",
        lambda *args: calls["reports"].append(args),
    )
    monkeypatch.setattr(
        project_commands.card_reports,
        "rename_report_for_card",
        lambda *args: calls["renames"].append(args),
    )
    monkeypatch.setattr(
        project_commands.card_reports,
        "delete_report",
        lambda *args: calls["deletions"].append(args),
    )
    monkeypatch.setattr(
        project_commands,
        "_enqueue_sync",
        lambda *args: calls["sync"].append(args),
    )
    return calls


def test_create_project_resolves_program_title_and_delegates_to_repository(
    project: Project,
    command_context: dict[str, list],
) -> None:
    result = project_commands.create_project(
        project_commands.CreateProjectCommand(
            title="Demo",
            project_id="demo",
            description="  Description  ",
            program_title="Embodied AI",
        )
    )

    assert result is project
    assert command_context["created_projects"] == [
        (
            ("Demo",),
            {
                "project_id": "demo",
                "description": "  Description  ",
                "programs": ["embodied-ai"],
            },
        )
    ]


def test_create_project_rejects_program_id_and_title_together(
    command_context: dict[str, list],
) -> None:
    with pytest.raises(ValueError, match="Specify either program_id or program_title"):
        project_commands.create_project(
            project_commands.CreateProjectCommand(
                title="Demo",
                project_id="demo",
                program_id="existing",
                program_title="New program",
            )
        )

    assert command_context["created_projects"] == []


def test_create_card_coordinates_domain_persistence_and_report(
    project: Project,
    command_context: dict[str, list],
) -> None:
    result = project_commands.create_card(
        "demo",
        "board-method",
        project_commands.CreateCardCommand(
            column_id="backlog",
            title="Card C",
            tags=("baseline", "baseline", "bad tag"),
            depends_on=("card-a", "missing"),
        ),
    )

    card = result.boards[0].cards[-1]
    assert card.title == "Card C"
    assert card.tags == ["baseline"]
    assert card.depends_on == ["card-a"]
    assert card.created_at
    assert card.updated_at == card.created_at
    assert result.card_tags == ["baseline"]
    assert command_context["saved_projects"] == [project]
    assert command_context["reports"][0][2] == card.id
    assert command_context["sync"] == [
        ("demo", "kanban_updated", "новая карточка: Card C")
    ]


def test_replace_project_rebuilds_snapshot_and_enqueues_sync(
    project: Project,
    command_context: dict[str, list],
) -> None:
    result = project_commands.replace_project(
        "demo",
        {
            "title": "Replaced",
            "description": "Snapshot from UI",
            "nodes": [
                {
                    "id": "method-new",
                    "parent_id": None,
                    "node_type": "method",
                    "title": "New method",
                    "verdict": "open",
                    "research_questions": [
                        {
                            "question": "What changed?",
                            "certainty": "tentative",
                            "importance": 9,
                        }
                    ],
                }
            ],
            "boards": {
                "board-new": {
                    "owner_node_id": "method-new",
                    "columns": [
                        {"id": "backlog", "title": "Backlog", "order": 0}
                    ],
                    "cards": [
                        {
                            "id": "card-new",
                            "board_id": "board-new",
                            "column_id": "backlog",
                            "title": "New card",
                        }
                    ],
                }
            },
        },
    )

    assert result.title == "Replaced"
    assert result.description == "Snapshot from UI"
    assert result.nodes[0].project_id == "demo"
    question = result.nodes[0].research_questions[0]
    assert question.id.startswith("rq-")
    assert question.certainty == ResearchQuestionCertainty.TENTATIVE
    assert question.importance == 5
    assert result.boards[0].id == "board-new"
    assert result.boards[0].cards[0].title == "New card"
    assert command_context["saved_projects"] == [result]
    assert command_context["sync"] == [
        ("demo", "project_saved", "полное сохранение проекта из UI")
    ]


def test_update_card_rejects_dependency_cycle(
    project: Project,
    command_context: dict[str, list],
) -> None:
    with pytest.raises(ValueError, match="would create a cycle"):
        project_commands.update_card(
            "demo",
            "board-method",
            "card-a",
            project_commands.UpdateCardCommand(depends_on=("card-b",)),
        )

    assert command_context["saved_projects"] == []


def test_update_card_renames_report_and_enqueues_edit(
    project: Project,
    command_context: dict[str, list],
) -> None:
    result = project_commands.update_card(
        "demo",
        "board-method",
        "card-a",
        project_commands.UpdateCardCommand(title="Renamed"),
    )

    assert result.boards[0].cards[0].title == "Renamed"
    assert result.boards[0].cards[0].updated_at
    assert result.boards[0].cards[0].created_at
    assert command_context["renames"][0][2:] == ("card-a", "Renamed")
    assert command_context["sync"] == [
        ("demo", "kanban_updated", "правка карточки Renamed")
    ]


def test_update_card_toggles_pinned_without_touching_updated_at(
    project: Project,
    command_context: dict[str, list],
) -> None:
    card = project.boards[0].cards[0]
    card.updated_at = "2026-01-01T00:00:00Z"

    result = project_commands.update_card(
        "demo",
        "board-method",
        "card-a",
        project_commands.UpdateCardCommand(pinned=True),
    )

    pinned = result.boards[0].cards[0]
    assert pinned.pinned is True
    assert pinned.updated_at == "2026-01-01T00:00:00Z"
    assert command_context["sync"] == [
        ("demo", "kanban_updated", "закреплена карточка Card A")
    ]

    command_context["sync"].clear()
    result = project_commands.update_card(
        "demo",
        "board-method",
        "card-a",
        project_commands.UpdateCardCommand(pinned=False),
    )
    assert result.boards[0].cards[0].pinned is False
    assert command_context["sync"] == [
        ("demo", "kanban_updated", "откреплена карточка Card A")
    ]


def test_delete_card_removes_incoming_dependencies(
    project: Project,
    command_context: dict[str, list],
) -> None:
    result = project_commands.delete_card("demo", "board-method", "card-a")

    assert [card.id for card in result.boards[0].cards] == ["card-b"]
    assert result.boards[0].cards[0].depends_on == []
    assert command_context["deletions"] == [("demo", "card-a")]


def test_delete_node_removes_owned_boards_and_card_reports(
    project: Project,
    command_context: dict[str, list],
) -> None:
    result = project_commands.delete_node("demo", "method")

    assert {node.id for node in result.nodes} == {"problem"}
    assert result.boards == []
    assert command_context["deletions"] == [("demo", "card-a"), ("demo", "card-b")]
    assert command_context["sync"] == [
        ("demo", "tree_updated", "удалён узел method")
    ]


def test_create_node_uses_repository_rule_and_enqueues_sync(
    project: Project,
    command_context: dict[str, list],
) -> None:
    result = project_commands.create_node(
        "demo",
        project_commands.CreateNodeCommand(
            parent_id="problem",
            node_type=NodeType.CAUSE,
            title="Cause",
        ),
    )

    assert result.nodes[-1].node_type == NodeType.CAUSE
    assert command_context["sync"] == [
        ("demo", "tree_updated", "новый узел: Cause")
    ]


def test_missing_project_and_board_have_application_errors(
    command_context: dict[str, list],
) -> None:
    with pytest.raises(project_commands.EntityNotFoundError, match="Project"):
        project_commands.delete_node("missing", "node")
    with pytest.raises(project_commands.EntityNotFoundError, match="Board"):
        project_commands.delete_card("demo", "missing", "card")


def test_tag_settings_rename_across_boards_and_roundtrip(project, command_context):
    from koi.core.md_io import parse_project_md, serialize_project_md
    project.card_tags = ['eval', 'train']
    project.boards[0].cards[0].tags = ['Eval', 'train']
    project.boards.append(KanbanBoard(id='other', owner_node_id='other', cards=[
        ExperimentCard(id='other-card', board_id='other', column_id='backlog', title='Other', tags=['eval'])
    ]))
    updated = project_commands.update_card_tag('demo', 'eval', 'evaluation', '#12AbCd')
    assert updated.boards[0].cards[0].tags == ['evaluation', 'train']
    assert updated.boards[1].cards[0].tags == ['evaluation']
    assert updated.card_tags == ['evaluation', 'train']
    restored = parse_project_md(serialize_project_md(updated))
    assert restored.card_tag_colors == {'evaluation': '#12abcd'}
    assert len(command_context['saved_projects']) == 1


@pytest.mark.parametrize('name,color', [('train', '#112233'), ('bad name', '#112233'), ('eval', 'red')])
def test_tag_settings_reject_invalid_changes_without_save(project, command_context, name, color):
    project.card_tags = ['eval', 'train']
    project.boards[0].cards[0].tags = ['eval']
    with pytest.raises(ValueError):
        project_commands.update_card_tag('demo', 'eval', name, color)
    assert project.card_tags == ['eval', 'train']
    assert project.boards[0].cards[0].tags == ['eval']
    assert not command_context['saved_projects']


def test_delete_tag_preserves_cards_and_removes_all_references(project, command_context):
    project.card_tags = ['eval', 'train']
    project.card_tag_colors = {'eval': '#123456', 'train': '#abcdef'}
    project.boards[0].cards[0].tags = ['Eval', 'train']
    project.boards[0].cards[1].tags = ['eval']
    before = [c.id for c in project.boards[0].cards]
    result = project_commands.delete_card_tag('demo', 'EVAL')
    assert result.card_tags == ['train']
    assert result.card_tag_colors == {'train': '#abcdef'}
    assert [c.tags for c in result.boards[0].cards] == [['train'], []]
    assert [c.id for c in result.boards[0].cards] == before
    assert not command_context['deletions']
    assert len(command_context['saved_projects']) == 1


def test_delete_last_tag_persists_empty_vocabulary(project, command_context):
    from koi.core.md_io import parse_project_md, serialize_project_md
    from koi.adapters.repository import merge_org_frontmatter
    project.card_tags = ['eval']
    project.card_tag_colors = {'eval': '#123456'}
    old = serialize_project_md(project)
    result = project_commands.delete_card_tag('demo', 'eval')
    restored = parse_project_md(merge_org_frontmatter(old, serialize_project_md(result)))
    assert restored.card_tags == []
    assert restored.card_tag_colors == {}
    with pytest.raises(project_commands.EntityNotFoundError):
        project_commands.delete_card_tag('demo', 'eval')
