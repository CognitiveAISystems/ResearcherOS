"""New root types and incoming relations survive the actual persistence path."""
import pytest

from koi.core.md_io import parse_project_md, serialize_project_md
from koi.core.models import EdgeType, Node, NodeType, Project
from koi.core.project_ops import add_node, update_node
from koi.projects import commands
from koi.projects.views import project_to_client


@pytest.mark.parametrize("root_type", [NodeType.TOPIC, NodeType.PROBLEM, NodeType.DIRECTION, NodeType.PROGRAM])
def test_new_tree_roundtrip(root_type):
    project = Project(id="example", title="Example", nodes=[
        Node(id="root", project_id="example", node_type=root_type, title="Root")
    ])
    parent = project.nodes[0]
    if root_type == NodeType.TOPIC:
        parent = add_node(project, parent.id, NodeType.PROBLEM, "Problem")
    program = add_node(project, parent.id, NodeType.PROGRAM, "Implementation",
        edge_type=EdgeType.HYPOTHESIS if parent.node_type == NodeType.PROBLEM else EdgeType.DIRECTION,
        edge_label='Память уменьшит повторы: "проверим"\nна новых задачах' if parent.node_type == NodeType.PROBLEM else "")
    method = add_node(project, program.id, NodeType.METHOD, "Run code")
    board = project.boards[0]
    loaded = parse_project_md(serialize_project_md(project))
    assert {n.id: n.model_dump() for n in loaded.nodes} == {n.id: n.model_dump() for n in project.nodes}
    assert loaded.boards[0].id == board.id
    assert loaded.boards[0].owner_node_id == method.id
    client = project_to_client(loaded)
    assert next(n for n in client["nodes"] if n["id"] == method.id)["has_kanban"]


def test_edge_edit_validates_before_mutation():
    project = Project(id="p", title="P", nodes=[Node(id="root", project_id="p", node_type="problem", title="P")])
    method = add_node(project, "root", NodeType.METHOD, "Measure", edge_type=EdgeType.EVIDENCE)
    with pytest.raises(ValueError, match="hypothesis"):
        update_node(project, method.id, edge_type=EdgeType.HYPOTHESIS)
    assert method.edge_type == EdgeType.EVIDENCE
    update_node(project, method.id, edge_type=EdgeType.HYPOTHESIS, edge_label="  Memory helps  ")
    assert method.edge_label == "Memory helps"
    with pytest.raises(ValueError, match="Root"):
        update_node(project, "root", edge_type=EdgeType.EVIDENCE)


def test_direction_cannot_be_a_hypothesis():
    project = Project(id="p", title="P", nodes=[Node(id="root", project_id="p", node_type="direction", title="P")])
    with pytest.raises(ValueError, match="start at a problem"):
        add_node(project, "root", NodeType.METHOD, "Run", edge_type=EdgeType.HYPOTHESIS, edge_label="H")
    assert len(project.nodes) == 1


def test_replace_preserves_incoming_edges(monkeypatch):
    project = Project(id="p", title="P", nodes=[Node(id="root", project_id="p", node_type="problem", title="P")])
    add_node(project, "root", NodeType.METHOD, "Run", edge_type=EdgeType.HYPOTHESIS, edge_label="Memory helps")
    monkeypatch.setattr(commands, "_require_project", lambda _: project)
    monkeypatch.setattr(commands.repository, "save_project", lambda _: None)
    monkeypatch.setattr(commands, "_enqueue_sync", lambda *args: None)
    restored = commands.replace_project("p", project_to_client(project))
    assert restored.nodes[1].edge_label == "Memory helps"
    assert restored.nodes[1].edge_type == EdgeType.HYPOTHESIS


def test_root_can_change_before_building_tree():
    project = Project(id="p", title="P", nodes=[Node(id="root", project_id="p", node_type="problem", title="P")])
    update_node(project, "root", root_type=NodeType.TOPIC)
    problem = add_node(project, "root", NodeType.PROBLEM, "Nested problem")
    update_node(project, problem.id, title="Another problem")
    assert project.title == "P"
    with pytest.raises(ValueError, match="incompatible"):
        update_node(project, "root", root_type=NodeType.PROGRAM)
    assert project.nodes[0].node_type == NodeType.TOPIC
