"""Parallel card loads must preserve every report and its index entry."""
from concurrent.futures import ThreadPoolExecutor
import time

from koi.adapters import card_reports
from koi.core.models import KanbanBoard, Node, NodeType, Project


def test_parallel_report_creation_preserves_entries_and_unique_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(card_reports, "project_reports_dir", lambda project_id: tmp_path)
    project = Project(id="demo", title="Demo", nodes=[
        Node(id="method", project_id="demo", node_type=NodeType.METHOD, title="Проверка")
    ], boards=[KanbanBoard(id="board", owner_node_id="method")])
    load = card_reports.load_index

    def slow_load(project_id):
        index = load(project_id)
        time.sleep(.005)  # Expose overlapping read/modify/write transactions.
        return index

    monkeypatch.setattr(card_reports, "load_index", slow_load)

    def create(number):
        path = card_reports.ensure_card_report(project, "board", str(number), "Одинаковое название")
        path.write_text(str(number), encoding="utf-8")
        return path

    with ThreadPoolExecutor(max_workers=12) as pool:
        paths = list(pool.map(create, range(24)))
    index = load("demo")
    assert set(index) == {str(number) for number in range(24)}
    assert len(set(paths)) == 24
    for number, path in enumerate(paths):
        assert path.read_text(encoding="utf-8") == str(number)
        assert tmp_path / index[str(number)] == path
