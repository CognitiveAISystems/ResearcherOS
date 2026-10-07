"""Project tree and kanban commands shared by HTTP and future entry points."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from uuid import uuid4

from koi.adapters import card_reports, repository
from koi.core import project_ops
from koi.core.md_io import card_now_iso, normalize_card_tags, register_project_card_tags
from koi.core.models import (
    DEFAULT_KANBAN_COLUMNS,
    ExperimentCard,
    KanbanBoard,
    KanbanColumn,
    MethodResearchQuestion,
    Node,
    NodeType,
    Project,
    ResearchQuestionCertainty,
    Verdict,
)
from koi.projects.kanban.dependencies import (
    normalize_dependency_ids,
    would_create_cycle,
)
from koi.laboratory import programs as program_service


class EntityNotFoundError(LookupError):
    """A project aggregate or one of its requested children does not exist."""


@dataclass(frozen=True)
class CreateProjectCommand:
    title: str
    project_id: str
    description: str = ""
    program_id: Optional[str] = None
    program_title: Optional[str] = None


@dataclass(frozen=True)
class CreateNodeCommand:
    parent_id: str
    node_type: NodeType
    title: str
    description: str = ""


@dataclass(frozen=True)
class ResearchQuestionInput:
    question: str
    id: Optional[str] = None
    answer: str = ""
    narrative: str = ""
    certainty: ResearchQuestionCertainty = ResearchQuestionCertainty.DEFINITE
    importance: int = 3
    card_id: Optional[str] = None


@dataclass(frozen=True)
class UpdateNodeCommand:
    title: Optional[str] = None
    description: Optional[str] = None
    research_questions: Optional[list[ResearchQuestionInput]] = None


@dataclass(frozen=True)
class CreateCardCommand:
    column_id: str
    title: str
    description: str = ""
    tags: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class UpdateCardCommand:
    title: Optional[str] = None
    description: Optional[str] = None
    column_id: Optional[str] = None
    tags: Optional[tuple[str, ...]] = None
    depends_on: Optional[tuple[str, ...]] = None
    pinned: Optional[bool] = None


def _require_project(project_id: str) -> Project:
    project = repository.load_project(project_id, sync_reports=False)
    if project is None:
        raise EntityNotFoundError("Project not found")
    return project


def _require_board(project: Project, board_id: str) -> KanbanBoard:
    board = next((item for item in project.boards if item.id == board_id), None)
    if board is None:
        raise EntityNotFoundError("Board not found")
    return board


def _require_card(board: KanbanBoard, card_id: str) -> ExperimentCard:
    card = next((item for item in board.cards if item.id == card_id), None)
    if card is None:
        raise EntityNotFoundError("Card not found")
    return card


def _enqueue_sync(project_id: str, reason: str, detail: str) -> None:
    try:
        from koi.adapters.project_sync_queue import enqueue_push

        enqueue_push(project_id, reason, detail)
    except Exception:
        # Sync is best-effort and must not make a local edit fail.
        pass


def create_project(command: CreateProjectCommand) -> Project:
    if command.program_id and command.program_title:
        raise ValueError("Specify either program_id or program_title, not both")

    programs: list[str] = []
    if command.program_id:
        programs.append(command.program_id.strip())
    elif command.program_title:
        programs.append(program_service.create_program(command.program_title)["id"])

    return repository.create_project(
        command.title,
        project_id=command.project_id,
        description=command.description,
        programs=programs,
    )


def replace_project(project_id: str, snapshot: dict) -> Project:
    """Replace a project aggregate from the serialized UI snapshot."""
    existing = _require_project(project_id)
    project = Project(
        id=project_id,
        title=snapshot.get("title", existing.title),
        description=snapshot.get("description", existing.description),
    )

    project.card_tags = list(existing.card_tags)
    project.card_tag_colors = dict(existing.card_tag_colors)

    project.nodes = [
        Node(
            id=raw["id"],
            project_id=project_id,
            parent_id=raw.get("parent_id"),
            node_type=NodeType(raw["node_type"]),
            title=raw["title"],
            description=raw.get("description", ""),
            verdict=Verdict(raw.get("verdict", "open")),
            research_questions=[
                MethodResearchQuestion(
                    id=item.get("id") or f"rq-{uuid4().hex[:8]}",
                    question=item["question"],
                    answer=item.get("answer", ""),
                    narrative=item.get("narrative", ""),
                    certainty=ResearchQuestionCertainty(
                        item.get(
                            "certainty",
                            ResearchQuestionCertainty.DEFINITE.value,
                        )
                    ),
                    importance=max(1, min(5, int(item.get("importance", 3)))),
                    card_id=item.get("card_id"),
                )
                for item in (raw.get("research_questions") or [])
            ],
        )
        for raw in snapshot.get("nodes", [])
    ]

    project.boards = [
        KanbanBoard(
            id=raw.get("id", board_id),
            owner_node_id=raw["owner_node_id"],
            columns=[
                KanbanColumn(**column) if isinstance(column, dict) else column
                for column in raw.get("columns", DEFAULT_KANBAN_COLUMNS)
            ],
            cards=[
                ExperimentCard(**card)
                for card in raw.get("cards", [])
            ],
        )
        for board_id, raw in snapshot.get("boards", {}).items()
    ]

    repository.save_project(project)
    _enqueue_sync(project_id, "project_saved", "полное сохранение проекта из UI")
    return project


def create_node(project_id: str, command: CreateNodeCommand) -> Project:
    project = _require_project(project_id)
    project_ops.add_node(
        project,
        command.parent_id,
        command.node_type,
        command.title,
        command.description,
    )
    repository.save_project(project)
    _enqueue_sync(project_id, "tree_updated", f"новый узел: {command.title}")
    return project


def update_node(project_id: str, node_id: str, command: UpdateNodeCommand) -> Project:
    project = _require_project(project_id)
    questions = None
    if command.research_questions is not None:
        questions = [
            MethodResearchQuestion(
                id=item.id or f"rq-{uuid4().hex[:8]}",
                question=item.question,
                answer=item.answer,
                narrative=item.narrative,
                certainty=item.certainty,
                importance=item.importance,
                card_id=item.card_id,
            )
            for item in command.research_questions
        ]
    try:
        project_ops.update_node(
            project,
            node_id,
            title=command.title,
            description=command.description,
            research_questions=questions,
        )
    except StopIteration as exc:
        raise EntityNotFoundError("Node not found") from exc

    repository.save_project(project)
    if command.research_questions is not None:
        _enqueue_sync(project_id, "research_updated", f"research_questions узла {node_id}")
    elif command.title is not None or command.description is not None:
        _enqueue_sync(project_id, "tree_updated", f"обновлён узел {node_id}")
    return project


def delete_node(project_id: str, node_id: str) -> Project:
    project = _require_project(project_id)
    node = next((item for item in project.nodes if item.id == node_id), None)
    if node is None:
        raise EntityNotFoundError("Node not found")

    to_remove = {node_id}

    def collect_children(parent_id: str) -> None:
        for item in project.nodes:
            if item.parent_id == parent_id:
                to_remove.add(item.id)
                collect_children(item.id)

    collect_children(node_id)
    report_card_ids = [
        card.id
        for board in project.boards
        if board.owner_node_id in to_remove
        for card in board.cards
    ]

    try:
        project_ops.delete_node(project, node_id)
    except StopIteration as exc:
        raise EntityNotFoundError("Node not found") from exc
    repository.save_project(project)
    for card_id in report_card_ids:
        card_reports.delete_report(project_id, card_id)
    _enqueue_sync(project_id, "tree_updated", f"удалён узел {node_id}")
    return project


def create_card(project_id: str, board_id: str, command: CreateCardCommand) -> Project:
    project = _require_project(project_id)
    board = _require_board(project, board_id)
    card_id = f"c-{uuid4().hex[:8]}"
    now = card_now_iso()
    card = ExperimentCard(
        id=card_id,
        board_id=board_id,
        column_id=command.column_id,
        title=command.title,
        description=command.description,
        tags=normalize_card_tags(list(command.tags)),
        depends_on=normalize_dependency_ids(
            list(command.depends_on),
            {item.id for item in board.cards},
            card_id,
        ),
        created_at=now,
        updated_at=now,
    )
    register_project_card_tags(project, card.tags)
    board.cards.append(card)
    repository.save_project(project)
    card_reports.ensure_card_report(project, board_id, card.id, card.title)
    _enqueue_sync(project_id, "kanban_updated", f"новая карточка: {card.title}")
    return project


def update_card(
    project_id: str,
    board_id: str,
    card_id: str,
    command: UpdateCardCommand,
) -> Project:
    project = _require_project(project_id)
    board = _require_board(project, board_id)
    card = _require_card(board, card_id)
    old_title = card.title
    old_column = card.column_id
    dependencies_changed = False
    touched = False

    if command.title is not None:
        card.title = command.title
        touched = True
    if command.description is not None:
        card.description = command.description
        touched = True
    if command.column_id is not None:
        card.column_id = command.column_id
        touched = True
    if command.tags is not None:
        card.tags = normalize_card_tags(list(command.tags))
        register_project_card_tags(project, card.tags)
        touched = True
    if command.depends_on is not None:
        dependencies = normalize_dependency_ids(
            list(command.depends_on),
            {item.id for item in board.cards},
            card_id,
        )
        if dependencies != list(card.depends_on or []):
            if would_create_cycle(board.cards, card_id, dependencies):
                raise ValueError("depends_on would create a cycle")
            card.depends_on = dependencies
            dependencies_changed = True
            touched = True
    pin_changed = False
    if command.pinned is not None:
        pinned = bool(command.pinned)
        if pinned != bool(card.pinned):
            card.pinned = pinned
            pin_changed = True

    if touched:
        now = card_now_iso()
        if not card.created_at:
            card.created_at = now
        card.updated_at = now

    repository.save_project(project)
    if command.column_id is not None and command.column_id != old_column:
        if command.column_id != "done":
            _enqueue_sync(
                project_id,
                "kanban_updated",
                f"карточка {card.title}: {old_column} → {command.column_id}",
            )
    elif dependencies_changed:
        _enqueue_sync(project_id, "kanban_updated", f"зависимости карточки {card.title}")
    elif command.title is not None or command.description is not None or command.tags is not None:
        _enqueue_sync(project_id, "kanban_updated", f"правка карточки {card.title}")
    elif pin_changed:
        verb = "закреплена" if card.pinned else "откреплена"
        _enqueue_sync(project_id, "kanban_updated", f"{verb} карточка {card.title}")

    if command.title is not None and command.title != old_title:
        card_reports.rename_report_for_card(project, board_id, card_id, card.title)
    return project


def delete_card(project_id: str, board_id: str, card_id: str) -> Project:
    project = _require_project(project_id)
    board = _require_board(project, board_id)
    board.cards = [card for card in board.cards if card.id != card_id]
    for card in board.cards:
        if card_id in (card.depends_on or []):
            card.depends_on = [
                dependency
                for dependency in card.depends_on
                if dependency != card_id
            ]
    repository.save_project(project)
    card_reports.delete_report(project_id, card_id)
    return project


def update_card_tag(project_id: str, tag: str, name: str, color: str) -> Project:
    project = _require_project(project_id)
    name = name.strip()
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
        raise ValueError("Используйте латинские буквы, цифры, дефис или подчёркивание.")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise ValueError("Некорректный цвет тега.")
    key = tag.lower()
    vocabulary = normalize_card_tags(project.card_tags + [
        t for board in project.boards for card in board.cards for t in card.tags
    ])
    if key not in {t.lower() for t in vocabulary}:
        raise EntityNotFoundError("Тег не найден.")
    if name.lower() != key and name.lower() in {t.lower() for t in vocabulary}:
        raise ValueError("Тег с таким названием уже существует.")
    project.card_tags = [name if t.lower() == key else t for t in vocabulary]
    project.card_tag_colors.pop(key, None)
    project.card_tag_colors[name.lower()] = color.lower()
    for board in project.boards:
        for card in board.cards:
            if key in {t.lower() for t in card.tags}:
                card.tags = [name if t.lower() == key else t for t in card.tags]
    repository.save_project(project)
    _enqueue_sync(project_id, "kanban_updated", f"настройки тега {name}")
    return project


def delete_card_tag(project_id: str, tag: str) -> Project:
    project = _require_project(project_id)
    key = tag.lower()
    vocabulary = normalize_card_tags(project.card_tags + [
        t for board in project.boards for card in board.cards for t in card.tags
    ])
    if key not in {t.lower() for t in vocabulary}:
        raise EntityNotFoundError("Тег не найден.")
    project.card_tags = [t for t in vocabulary if t.lower() != key]
    project.card_tag_colors.pop(key, None)
    for board in project.boards:
        for card in board.cards:
            card.tags = [t for t in card.tags if t.lower() != key]
    repository.save_project(project)
    _enqueue_sync(project_id, "kanban_updated", f"удалён тег {tag}")
    return project
