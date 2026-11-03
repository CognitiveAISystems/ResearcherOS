import json

import pytest

from koi.adapters import agent_chat_activity, agent_chat_queue
from koi.agent_chat import research, research_tools
from koi.core.models import DEFAULT_KANBAN_COLUMNS, KanbanBoard, Node, NodeType, Project


@pytest.fixture
def scope_run(tmp_path, monkeypatch):
    monkeypatch.setattr(research, 'PATH', tmp_path / 'research.sqlite3')
    monkeypatch.setattr(agent_chat_activity, 'ACTIVITY_DIR', tmp_path / 'activity')
    project = Project(id='demo', title='Research', nodes=[
        Node(id='root', project_id='demo', node_type=NodeType.PROBLEM, title='Problem'),
        Node(id='method', project_id='demo', parent_id='root', node_type=NodeType.METHOD,
             title='Method', description='Existing evidence'),
    ], boards=[KanbanBoard(id='board', owner_node_id='method', columns=DEFAULT_KANBAN_COLUMNS)])
    monkeypatch.setattr(research_tools.repository, 'load_project', lambda *a, **kw: project)
    monkeypatch.setattr(research_tools.repository, 'save_project', lambda *a: None)
    monkeypatch.setattr(research_tools.commands, '_enqueue_sync', lambda *a: None)

    def start(level=None, board_id='board'):
        item = dict(id='aq-start', conversation_id='chat-demo', project_id='demo',
                    question='/koi-arbor-autoresearch Improve', research_scope=level, board_id=board_id)
        context = dict(project_id='demo', scope_method={'id': 'method', 'title': 'Method'})
        research.coordinator_prompt(item, context)
        return research.participants('chat-demo')[0]['run_id'], item, context

    return start


def test_unconfirmed_launch_cannot_mutate_or_dispatch(scope_run):
    run, _, _ = scope_run()
    for operation, args in [('contract', {}), ('create_card', {'board_id': 'board'}),
                            ('update_node', {'node_id': 'method', 'description': 'Changed'})]:
        with pytest.raises(ValueError, match='Confirm the research scope'):
            research_tools.perform(run, operation, args)
    with pytest.raises(ValueError, match='contract'):
        research.reserve_executors(run, 1, 60)
    research_tools.perform(run, 'scope', {'level': 'method'})
    assert research_tools.perform(run, 'view', {})['arbor_metadata']['research_scope'] == {
        'level': 'method', 'method_id': 'method'}


def test_method_scope_cannot_expand_and_survives_resume(scope_run):
    run, item, context = scope_run('method')
    for operation, args in [
        ('create_node', {'parent_id': 'root', 'title': 'Other method', 'node_type': 'method'}),
        ('delete_node', {'node_id': 'method'}),
        ('update_node', {'node_id': 'root', 'description': 'Changed'}),
        ('create_card', {'board_id': 'other', 'title': 'Outside scope'}),
        ('phase', {'phase': 'hypotheses', 'node_ids': ['root']}),
        ('scope', {'level': 'tree'}),
    ]:
        with pytest.raises(ValueError):
            research_tools.perform(run, operation, args)
    research_tools.perform(run, 'phase', {'phase': 'hypotheses', 'node_ids': ['method']})
    research.finish_coordinator(item['id'], 'completed', 'Waiting for budget')
    research.coordinator_prompt({**item, 'id': 'aq-resume', 'research_scope': 'tree'}, context, resume_id=run)
    scope = research_tools.perform(run, 'view', {})['arbor_metadata']['research_scope']
    assert scope == {'level': 'method', 'method_id': 'method'}


def test_tree_launch_does_not_inherit_selected_method(scope_run):
    run, _, _ = scope_run('tree', board_id=None)
    assert research_tools.perform(run, 'view', {})['arbor_metadata']['research_scope'] == {
        'level': 'tree', 'method_id': None}


def test_pending_tree_cannot_descend_to_selected_method(scope_run):
    run, _, _ = scope_run(board_id=None)
    with pytest.raises(ValueError, match='No method'):
        research_tools.perform(run, 'scope', {'level': 'method'})
    research_tools.perform(run, 'scope', {'level': 'tree'})


def test_scope_survives_queue_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_chat_queue, 'QUEUE_PATH', tmp_path / 'queue.json')
    item = agent_chat_queue.enqueue_question('demo', '/koi-arbor-autoresearch Improve',
                                            research_scope='method', board_id='board')
    assert agent_chat_queue.find_item(item['id'])['research_scope'] == 'method'
    assert json.loads((tmp_path / 'queue.json').read_text())[0]['research_scope'] == 'method'


def test_method_scope_allows_improvements_and_own_experiments(scope_run, monkeypatch):
    run, _, _ = scope_run('method')
    monkeypatch.setattr(research_tools.card_reports, 'ensure_card_report', lambda *a: None)
    research_tools.perform(run, 'update_node', {'node_id': 'method', 'description': 'Evidence and improvement hypothesis'})
    research_tools.perform(run, 'phase', {'phase': 'hypotheses', 'node_ids': ['method']})
    result = research_tools.perform(run, 'create_card', {'board_id': 'board', 'title': 'Check improvement'})
    card = result['boards'][0]['cards'][0]
    assert card['title'] == 'Check improvement'
    assert card['column_id'] == 'backlog'
