import pytest
from koi.agent_chat import research, research_tools
from koi.core.models import Node, NodeType, Project


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setattr(research, 'PATH', tmp_path / 'runs.sqlite3')
    run = research.create_run('chat-a', 'aq-123', 'demo', 'Goal')
    project = Project(id='demo', title='Original', nodes=[
        Node(id='root', project_id='demo', node_type=NodeType.PROBLEM, title='Original'),
        Node(id='method', project_id='demo', parent_id='root', node_type=NodeType.METHOD, title='Method')])
    monkeypatch.setattr(research_tools.repository, 'load_project', lambda *a, **kw: project)
    monkeypatch.setattr(research_tools.repository, 'save_project', lambda *a: None)
    monkeypatch.setattr(research_tools.commands, '_enqueue_sync', lambda *a: None)
    return run, project


def test_root_guard_and_existing_commands(context):
    run, project = context
    for operation in ('update_node', 'delete_node'):
        with pytest.raises(ValueError, match='protected'):
            research_tools.perform(run, operation, {'node_id': 'root', 'title': 'Changed'})
    result = research_tools.perform(run, 'update_node', {'node_id': 'method', 'title': 'Improved'})
    assert result['nodes'][1]['title'] == 'Improved'
    assert project.nodes[0].title == 'Original'


def test_unknown_run_and_operations_fail(context):
    run, project = context
    with pytest.raises(KeyError):
        research_tools.perform('missing', 'view', {})
    with pytest.raises(ValueError, match='Unknown operation'):
        research_tools.perform(run, 'replace_project', {'title': 'Overwrite everything'})


def test_budget_is_required_bounded_and_cannot_be_reset(context):
    run, _ = context
    with pytest.raises(ValueError, match='contract'):
        research.reserve_executors(run, 1, 10)
    research_tools.perform(run, 'contract', {'max_seconds':60, 'max_executors':2, 'stop_condition':'Compare variants'})
    assert 0 < research.reserve_executors(run, 2, 100) <= 60
    live_budget = research_tools.perform(run, 'view', {})['research_budget']
    assert live_budget['launched'] == 2
    assert live_budget['max_executors'] == 2
    with pytest.raises(ValueError, match='exhausted'):
        research.reserve_executors(run, 1, 10)
    with pytest.raises(ValueError, match='replaced'):
        research_tools.perform(run, 'contract', {'max_seconds':60, 'max_executors':20, 'stop_condition':'More work'})


def test_arbor_metadata_uses_existing_run_without_a_second_tree(context):
    run, _ = context
    settings={'baseline_score':.4, 'metric_direction':'maximize', 'eval_cmd':'python evaluate.py'}
    assert research_tools.perform(run,'meta',settings)==settings
    view=research_tools.perform(run,'view',{})
    assert view['arbor_metadata']==settings
    assert view['nodes'][0]['title']=='Original'
    with pytest.raises(ValueError,match='scientific state'):
        research_tools.perform(run,'meta',{'nodes':[]})


def test_agent_titles_follow_project_eight_word_limit(context):
    run,_=context
    with pytest.raises(ValueError,match='eight words'):
        research_tools.perform(run,'update_node',{'node_id':'method','title':'one two three four five six seven eight nine'})


def test_coordinator_can_build_multiple_research_levels(context):
    run,_=context
    first=research_tools.perform(run,'create_node',{'parent_id':'root','node_type':'program','title':'Верхняя гипотеза','edge_type':'hypothesis','edge_label':'Разнообразие улучшает перенос'})
    upper=first['nodes'][-1]['id']
    second=research_tools.perform(run,'create_node',{'parent_id':upper,'node_type':'program','title':'Нижняя гипотеза','description':'Разнообразие окружений важнее числа эпизодов.'})
    lower=second['nodes'][-1]['id']
    final=research_tools.perform(run,'create_node',{'parent_id':lower,'node_type':'method','title':'Сравнение фиксированных бюджетов'})
    assert final['nodes'][-1]['parent_id']==lower
    assert final['nodes'][-2]['parent_id']==upper
    assert final['nodes'][0]['title']=='Original'
    assert any(board['owner_node_id']==final['nodes'][-1]['id'] for board in final['boards'])


def test_visible_wave_must_precede_execution_and_single_run_can_finish(context, monkeypatch):
    run, project = context
    monkeypatch.setattr(research_tools.card_reports, 'ensure_card_report', lambda *a: None)
    # Use real existing project commands for the tree/card/status transitions.
    created = research_tools.perform(run, 'create_node', {
        'parent_id': 'root', 'node_type': 'method', 'title': 'Adaptive retrieval',
        'edge_type': 'hypothesis', 'edge_label': 'Disagreement identifies missing evidence',
        'description': 'Retrieve evidence only when competing predictions disagree.'})
    board = created['boards'][-1]['id']
    created = research_tools.perform(run, 'create_card', {
        'board_id': board, 'title': 'Check disagreement mechanism'})
    card = created['boards'][-1]['cards'][-1]['id']
    ref = {'board_id': board, 'card_id': card}
    report = {'content': '## 1. Purpose\nTest mechanism.\n## 2. Metric\nFixed criterion.\n## 3. Setup\nControl and intervention.'}
    monkeypatch.setattr(research_tools.card_reports, 'read_report', lambda *a: report)
    with pytest.raises(ValueError, match='hypotheses'):
        research_tools.perform(run, 'phase', {'phase': 'execution'})
    with pytest.raises(ValueError, match='backlog wave'):
        research_tools.perform(run, 'update_card', {**ref, 'column_id': 'running'})
    with pytest.raises(ValueError, match='non-root'):
        research_tools.perform(run, 'phase', {'phase': 'hypotheses', 'node_ids': ['root']})
    research_tools.perform(run, 'phase', {'phase': 'hypotheses', 'node_ids': [created['nodes'][-1]['id']]})
    with pytest.raises(ValueError, match='nonempty'):
        research_tools.perform(run, 'phase', {'phase': 'backlog', 'cards': []})
    report['content'] = '## 1. Purpose\nOnly a draft.'
    with pytest.raises(ValueError, match='every wave'):
        research_tools.perform(run, 'phase', {'phase': 'backlog', 'cards': [ref]})
    report['content'] += '\n## 2. Metric\nFixed rule.\n## 3. Setup\nControl and intervention.'
    research_tools.perform(run, 'phase', {'phase': 'backlog', 'cards': [ref]})
    research_tools.perform(run, 'phase', {'phase': 'execution'})
    research_tools.perform(run, 'update_card', {**ref, 'column_id': 'running'})
    with pytest.raises(ValueError, match='results'):
        research_tools.perform(run, 'update_card', {**ref, 'column_id': 'done'})
    report['content'] += '\n## 4. Experiment\n### 4.1 Results\nMeasured evidence.\n### 4.2 Conclusions\nRefuted.'
    result = research_tools.perform(run, 'update_card', {**ref, 'column_id': 'done'})
    assert result['boards'][-1]['cards'][-1]['column_id'] == 'done'
    workflow = research_tools.perform(run, 'view', {})['arbor_metadata']['research_workflow']
    assert workflow['cards'] == [ref]
    # A new wave must publish its hypotheses again, without duplicating old cards.
    research_tools.perform(run, 'phase', {'phase': 'hypotheses', 'node_ids': workflow['node_ids']})
    assert 'cards' not in research_tools.perform(run, 'view', {})['arbor_metadata']['research_workflow']


@pytest.fixture
def progress_card(context, tmp_path, monkeypatch):
    from koi.core.models import KanbanBoard, ExperimentCard
    from koi.projects import live_artifacts
    run, project = context
    project.boards.append(KanbanBoard(id='board', owner_node_id='method', cards=[
        ExperimentCard(id='card', board_id='board', title='Experiment', column_id='running')]))
    reports = tmp_path / 'tree' / 'demo' / 'koi-structure' / 'reports'
    reports.mkdir(parents=True)
    monkeypatch.setattr(research_tools.card_reports, 'reports_dir', lambda _: reports)
    repo = tmp_path / 'code'
    repo.mkdir()
    monkeypatch.setattr(live_artifacts, 'repo_root', lambda _: repo)
    research_tools.perform(run, 'write_report', {'board_id': 'board', 'card_id': 'card',
        'content': '## 1. Goal\nTest.\n## 2. Metric\nScore.\n## 3. Setup\n- [ ] Prepare\n- [ ] Evaluate\n## 4. Experiment\n### 4.1 Results\n\n### 4.2 Conclusions\n'})
    return run, project, {'board_id': 'board', 'card_id': 'card'}


def test_progress_is_saved_before_experiment_finishes(progress_card):
    run, project, ref = progress_card
    research_tools.perform(run, 'complete_subtask', {**ref, 'task': 'Prepare'})
    report = research_tools.perform(run, 'read_report', ref)['content']
    assert '- [x] Prepare' in report
    assert '- [ ] Evaluate' in report
    assert project.boards[0].cards[0].column_id == 'running'
    research_tools.perform(run, 'complete_subtask', {**ref, 'task': 'Prepare'})  # idempotent
    with pytest.raises(ValueError, match='exactly one'):
        research_tools.perform(run, 'complete_subtask', {**ref, 'task': 'Missing'})


def test_executor_image_is_visible_in_monitor_and_report(progress_card, tmp_path):
    from koi.projects import live_artifacts
    run, project, ref = progress_card
    source = tmp_path / 'isolated-executor' / 'loss.png'
    source.parent.mkdir()
    import base64
    source.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='))
    result = research_tools.perform(run, 'publish_image', {**ref, 'source_path': str(source),
        'caption': 'Observed loss', 'section': '### 4.1 Results'})
    source.unlink()  # executor workspace can disappear
    report = research_tools.perform(run, 'read_report', ref)['content']
    assert f'![Observed loss]({result["markdown_path"]})' in report
    assert report.index('![Observed loss]') < report.index('### 4.2 Conclusions')
    image = research_tools.card_reports.resolve_report_asset_path(project, 'board', 'card', 'Experiment',
        result['markdown_path'].removeprefix('assets/'))
    assert image.is_file()
    snapshot = live_artifacts.live_snapshot('demo', hints=live_artifacts.parse_live_hints(report),
        description=report, column_id='running')
    assert snapshot['metrics_dir']['images'][0]['name'] == image.name
    assert snapshot['metrics_dir']['exists']
    assert '- [ ] Evaluate' in report


def test_progress_rejects_wrong_section_and_inactive_card(progress_card, tmp_path):
    run, project, ref = progress_card
    with pytest.raises(ValueError, match='existing report heading'):
        research_tools.perform(run, 'publish_image', {**ref, 'source_path': str(tmp_path / 'absent.png'),
            'caption': 'Loss', 'section': '### Missing'})
    project.boards[0].cards[0].column_id = 'done'
    with pytest.raises(ValueError, match='running'):
        research_tools.perform(run, 'complete_subtask', {**ref, 'task': 'Prepare'})
