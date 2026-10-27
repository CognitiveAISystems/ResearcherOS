"""Tests for project.md kanban parsing and normalization."""

from __future__ import annotations

from koi.core.md_io import normalize_kanban_board, parse_project_md, serialize_project_md
from koi.core.migrate import kanban_md_needs_upgrade
from koi.core.models import DEFAULT_KANBAN_COLUMNS, ExperimentCard, KanbanBoard


def test_kanban_md_needs_upgrade() -> None:
    old = "| backlog | running | done |\n"
    new = "| backlog | running | done | successful |\n"
    assert kanban_md_needs_upgrade(old) is False
    assert kanban_md_needs_upgrade(new) is True
    assert kanban_md_needs_upgrade(old + new) is True
    assert kanban_md_needs_upgrade("# no kanban\n") is False


def test_default_kanban_has_three_columns() -> None:
    col_ids = [c.id for c in DEFAULT_KANBAN_COLUMNS]
    assert col_ids == ["backlog", "running", "done"]


def test_normalize_kanban_keeps_done_column() -> None:
    board = KanbanBoard(
        id="board-test",
        owner_node_id="m-test",
        columns=DEFAULT_KANBAN_COLUMNS[:3],
        cards=[
            ExperimentCard(
                id="c1",
                board_id="board-test",
                column_id="done",
                title="Finished",
            )
        ],
    )
    normalized = normalize_kanban_board(board)
    assert [c.id for c in normalized.columns] == ["backlog", "running", "done"]
    assert normalized.cards[0].column_id == "done"


def test_roundtrip_preserves_card_tags() -> None:
    text = """---
id: proj-tags
title: Tags
card_tags:
  - gpu
  - baseline
---
# problem: root

Root

#### method: m1

Method

<!-- koi:kanban board-m1 -->
| backlog | running | done | successful |
| --- | --- | --- | --- |
| GPU run <!-- id:c-gpu desc:plan tags:gpu,ablation --> | | | |
| Plain card <!-- id:c-plain desc:no tags here --> | | | |
"""
    project = parse_project_md(text, project_id="proj-tags")
    assert project.card_tags == ["gpu", "baseline"]
    board = project.boards[0]
    by_id = {c.id: c for c in board.cards}
    assert by_id["c-gpu"].tags == ["gpu", "ablation"]
    assert by_id["c-plain"].tags == []

    reserialized = serialize_project_md(project)
    reloaded = parse_project_md(reserialized, project_id="proj-tags")
    reloaded_by_id = {c.id: c.tags for c in reloaded.boards[0].cards}
    assert reloaded.card_tags == ["gpu", "baseline"]
    assert reloaded_by_id == {"c-gpu": ["gpu", "ablation"], "c-plain": []}


def test_roundtrip_preserves_card_timestamps() -> None:
    text = """---
id: proj-ts
title: Timestamps
---
# problem: root

Root

#### method: m1

Method

<!-- koi:kanban board-m1 -->
| backlog | running | done | successful |
| --- | --- | --- | --- |
| Dated <!-- id:c-ts created:2026-08-01T10:00:00Z updated:2026-08-07T12:30:00Z desc:plan tags:gpu --> | | | |
| Legacy <!-- id:c-old desc:no dates --> | | | |
"""
    project = parse_project_md(text, project_id="proj-ts")
    board = project.boards[0]
    by_id = {c.id: c for c in board.cards}
    assert by_id["c-ts"].created_at == "2026-08-01T10:00:00Z"
    assert by_id["c-ts"].updated_at == "2026-08-07T12:30:00Z"
    assert by_id["c-ts"].tags == ["gpu"]
    assert by_id["c-old"].created_at is None
    assert by_id["c-old"].updated_at is None

    reserialized = serialize_project_md(project)
    assert "created:2026-08-01T10:00:00Z" in reserialized
    assert "updated:2026-08-07T12:30:00Z" in reserialized
    reloaded = parse_project_md(reserialized, project_id="proj-ts")
    re_by_id = {c.id: c for c in reloaded.boards[0].cards}
    assert re_by_id["c-ts"].created_at == "2026-08-01T10:00:00Z"
    assert re_by_id["c-ts"].updated_at == "2026-08-07T12:30:00Z"
    assert re_by_id["c-old"].created_at is None


def test_roundtrip_preserves_multiline_card_description() -> None:
    text = """---
id: proj-subtasks
title: Subtasks
---
# problem: root

Root

#### method: m1

Method

<!-- koi:kanban board-m1 -->
| backlog | running | done | successful |
| --- | --- | --- | --- |
| | Demo <!-- id:c-run desc:План\\n- [x] Sync\\n- [ ] Train --> | | |
"""
    project = parse_project_md(text, project_id="proj-subtasks")
    card = project.boards[0].cards[0]
    assert card.description == "План\n- [x] Sync\n- [ ] Train"

    reserialized = serialize_project_md(project)
    assert "desc:План\\n- [x] Sync\\n- [ ] Train" in reserialized
    reloaded = parse_project_md(reserialized, project_id="proj-subtasks")
    assert reloaded.boards[0].cards[0].description == card.description


def test_roundtrip_preserves_successful_cards() -> None:
    text = """---
id: proj-test
title: Test
---
# problem: root

Root

#### method: m1

Method

<!-- koi:kanban board-m1 -->
| backlog | running | done | successful |
| --- | --- | --- | --- |
| | | Old done <!-- id:c-old desc:report ready --> | Winner <!-- id:c-win desc:confirmed --> |
"""
    project = parse_project_md(text, project_id="proj-test")
    board = project.boards[0]
    assert [c.id for c in board.columns] == ["backlog", "running", "done"]
    by_id = {c.id: c.column_id for c in board.cards}
    assert by_id["c-old"] == "done"
    assert by_id["c-win"] == "done"
    assert next(c for c in board.cards if c.id == "c-win").favorite is True
    assert next(c for c in board.cards if c.id == "c-old").favorite is False

    reserialized = serialize_project_md(project)
    assert "successful" not in reserialized
    assert "favorite:1" in reserialized
    reloaded = parse_project_md(reserialized, project_id="proj-test")
    reloaded_by_id = {c.id: c.column_id for c in reloaded.boards[0].cards}
    assert reloaded_by_id == by_id
    assert next(c for c in reloaded.boards[0].cards if c.id == "c-win").favorite is True


def test_roundtrip_preserves_card_pinned() -> None:
    text = """---
id: proj-pin
title: Pins
---
# problem: root

Root

#### method: m1

Method

<!-- koi:kanban board-m1 -->
| backlog | running | done | successful |
| --- | --- | --- | --- |
| Pinned <!-- id:c-pin pinned:1 desc:keep top --> | | | |
| Plain <!-- id:c-plain desc:no pin --> | | | |
"""
    project = parse_project_md(text, project_id="proj-pin")
    board = project.boards[0]
    by_id = {c.id: c for c in board.cards}
    assert by_id["c-pin"].pinned is True
    assert by_id["c-plain"].pinned is False
    assert by_id["c-pin"].description == "keep top"

    reserialized = serialize_project_md(project)
    assert "pinned:1" in reserialized
    reloaded = parse_project_md(reserialized, project_id="proj-pin")
    re_by_id = {c.id: c.pinned for c in reloaded.boards[0].cards}
    assert re_by_id == {"c-pin": True, "c-plain": False}


def test_roundtrip_preserves_card_depends_on() -> None:
    text = """---
id: proj-deps
title: Deps
---
# problem: root

Root

#### method: m1

Method

<!-- koi:kanban board-m1 -->
| backlog | running | done | successful |
| --- | --- | --- | --- |
| Follow-up <!-- id:c-b desc:next step deps:c-a --> | | Base <!-- id:c-a desc:baseline --> | |
"""
    project = parse_project_md(text, project_id="proj-deps")
    by_id = {c.id: c for c in project.boards[0].cards}
    assert by_id["c-b"].depends_on == ["c-a"]
    assert by_id["c-a"].depends_on == []

    reserialized = serialize_project_md(project)
    assert "deps:c-a" in reserialized
    reloaded = parse_project_md(reserialized, project_id="proj-deps")
    reloaded_by_id = {c.id: c.depends_on for c in reloaded.boards[0].cards}
    assert reloaded_by_id == {"c-a": [], "c-b": ["c-a"]}


def test_roundtrip_preserves_card_tags_with_depends_on() -> None:
    """Tags and deps share the same HTML comment; both write orders must roundtrip."""
    text = """---
id: proj-tags-deps
title: Tags and deps
card_tags:
  - gpu
  - ablation
---
# problem: root

Root

#### method: m1

Method

<!-- koi:kanban board-m1 -->
| backlog | running | done | successful |
| --- | --- | --- | --- |
| Writer order <!-- id:c-writer desc:plan tags:gpu,ablation deps:c-base --> | | | |
| Deps first <!-- id:c-legacy desc:legacy deps:c-base tags:gpu --> | | Base <!-- id:c-base desc:baseline --> | |
"""
    project = parse_project_md(text, project_id="proj-tags-deps")
    by_id = {c.id: c for c in project.boards[0].cards}
    assert by_id["c-writer"].tags == ["gpu", "ablation"]
    assert by_id["c-writer"].depends_on == ["c-base"]
    assert by_id["c-legacy"].tags == ["gpu"]
    assert by_id["c-legacy"].depends_on == ["c-base"]

    reserialized = serialize_project_md(project)
    assert "tags:gpu,ablation" in reserialized
    assert "deps:c-base" in reserialized
    reloaded = parse_project_md(reserialized, project_id="proj-tags-deps")
    reloaded_by_id = {c.id: c for c in reloaded.boards[0].cards}
    assert reloaded_by_id["c-writer"].tags == ["gpu", "ablation"]
    assert reloaded_by_id["c-writer"].depends_on == ["c-base"]
    assert reloaded_by_id["c-legacy"].tags == ["gpu"]
    assert reloaded_by_id["c-legacy"].depends_on == ["c-base"]
