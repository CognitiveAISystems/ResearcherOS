"""HTTP contract tests for routes backed by project application commands."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app
from koi.projects import commands as project_commands
from koi.core.models import KanbanBoard, Project


def test_create_project_route_maps_request_to_application_command() -> None:
    project = Project(id="demo", title="Demo")
    client = TestClient(app)

    with patch(
        "api.routers.projects.project_commands.create_project",
        return_value=project,
    ) as create_project:
        response = client.post(
            "/projects",
            json={
                "title": "Demo",
                "description": "Description",
                "tag": "demo",
                "program_title": "Embodied AI",
            },
        )

    assert response.status_code == 200
    assert create_project.call_args.args[0] == project_commands.CreateProjectCommand(
        title="Demo",
        project_id="demo",
        description="Description",
        program_title="Embodied AI",
    )


def test_create_project_route_maps_application_validation_to_http_400() -> None:
    client = TestClient(app)
    with patch(
        "api.routers.projects.project_commands.create_project",
        side_effect=ValueError("Project already exists: demo"),
    ):
        response = client.post(
            "/projects",
            json={"title": "Demo", "tag": "demo"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Project already exists: demo"


def test_create_card_route_maps_request_to_application_command() -> None:
    project = Project(
        id="demo",
        title="Demo",
        boards=[KanbanBoard(id="board-method", owner_node_id="method")],
    )
    client = TestClient(app)

    with patch(
        "api.routers.projects.project_commands.create_card",
        return_value=project,
    ) as create_card:
        response = client.post(
            "/projects/demo/boards/board-method/cards",
            json={
                "column_id": "backlog",
                "title": "Experiment",
                "tags": ["baseline"],
                "depends_on": ["card-a"],
            },
        )

    assert response.status_code == 200
    command = create_card.call_args.args[2]
    assert command == project_commands.CreateCardCommand(
        column_id="backlog",
        title="Experiment",
        tags=("baseline",),
        depends_on=("card-a",),
    )


def test_replace_project_route_delegates_snapshot_to_application_command() -> None:
    project = Project(id="demo", title="Replaced")
    payload = {
        "title": "Replaced",
        "description": "Snapshot from UI",
        "nodes": [],
        "boards": {},
    }
    client = TestClient(app)

    with patch(
        "api.routers.projects.project_commands.replace_project",
        return_value=project,
    ) as replace_project:
        response = client.put("/projects/demo", json=payload)

    assert response.status_code == 200
    replace_project.assert_called_once_with("demo", payload)
    assert response.json()["id"] == "demo"
    assert response.json()["title"] == "Replaced"


def test_update_card_route_maps_domain_validation_to_http_400() -> None:
    client = TestClient(app)
    with patch(
        "api.routers.projects.project_commands.update_card",
        side_effect=ValueError("depends_on would create a cycle"),
    ):
        response = client.patch(
            "/projects/demo/boards/board-method/cards/card-a",
            json={"depends_on": ["card-b"]},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "depends_on would create a cycle"


def test_removed_board_features_have_no_api_routes() -> None:
    paths = app.openapi()["paths"]
    assert not any("/dag" in path or "/milestones" in path for path in paths)


def test_delete_node_route_maps_application_not_found_to_http_404() -> None:
    client = TestClient(app)
    with patch(
        "api.routers.projects.project_commands.delete_node",
        side_effect=project_commands.EntityNotFoundError("Node not found"),
    ):
        response = client.delete("/projects/demo/nodes/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "Node not found"


def test_tag_color_persists_and_delete_survives_reload(tmp_path):
    from types import SimpleNamespace
    from koi.adapters import repository
    from koi.core.md_io import parse_project_md, serialize_project_md

    path = tmp_path / 'project.md'
    path.write_text(serialize_project_md(Project(id='demo', title='Demo', card_tags=['eval'])))

    def load(project_id, **kwargs):
        return parse_project_md(path.read_text(), project_id=project_id)

    client = TestClient(app)
    with patch.object(repository, 'load_project', side_effect=load), \
         patch.object(repository, 'get_mount', return_value=SimpleNamespace(koi_root=tmp_path)), \
         patch.object(repository, '_project_path', return_value=path), \
         patch.object(repository, 'save_research'), \
         patch('koi.adapters.done_research_queue.sync_done_research_on_save'), \
         patch('koi.knowledge.write_project_knowledge'), \
         patch.object(project_commands, '_enqueue_sync'):
        response = client.patch('/projects/demo/card-tags/eval', json={'name': 'eval', 'color': '#ff65ae'})
        assert response.status_code == 200
        assert load('demo').card_tag_colors == {'eval': '#ff65ae'}
        response = client.delete('/projects/demo/card-tags/eval')
        assert response.status_code == 200
        assert load('demo').card_tags == []
        assert load('demo').card_tag_colors == {}
