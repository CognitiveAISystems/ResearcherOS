"""Description-first interview: structure, bounded questions and review before writing."""
from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from koi.adapters import onboarding_interview as interview, project_mount
from koi.adapters.workspace import reset_workspace_cache
from koi.core.md_io import parse_project_md


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv('KOI_DESKTOP_CONFIG_DIR', str(tmp_path / 'settings'))
    monkeypatch.setattr(project_mount, 'ENGINE_ROOT', tmp_path / 'engine' / 'ReseachOS')
    monkeypatch.setattr(app.router, 'on_startup', [])
    monkeypatch.setattr(app.router, 'on_shutdown', [])
    reset_workspace_cache()
    code = tmp_path / 'code' / 'example'
    code.mkdir(parents=True)
    git(code, 'init', '-b', 'main')
    git(code, 'config', 'user.name', 'Test')
    git(code, 'config', 'user.email', 'test@example.com')
    (code / 'README.md').write_text('An agent in a long task environment.\n')
    git(code, 'add', 'README.md')
    git(code, 'commit', '-m', 'Initial code')
    yield code
    reset_workspace_cache()


def brief():
    return {key: {'answer': 'Не определено', 'source': 'Описание пользователя', 'needs_clarification': False, 'clarification': ''} for key, *_ in interview.BRIEF_FIELDS}


def node(kind, ident, parent=None, edge='direction', label=''):
    return dict(id=ident, node_type=kind, parent_id=parent, title={'direction': 'Адаптивные рассуждения агента', 'program': 'Реализация известной схемы', 'problem': 'Агент теряет цель', 'method': 'Обучение с учётом риска', 'topic': 'Обучение агентов'}[kind], description='Содержание узла по описанию проекта.', edge_type=edge, edge_label=label)


def reply(kind='direction', *, method=True, question=None, status=None):
    nodes = [node(kind, 'root')]
    if method:
        nodes.append(node('method', 'method', 'root', 'hypothesis' if kind == 'problem' else 'direction', 'Память поможет сохранять цель' if kind == 'problem' else ''))
    return dict(nodes=nodes, brief=brief(), message=question['text'] if question else 'Предварительное дерево построено.', method_status=status or ('provided' if method else 'unknown'), question=question, changes='Нет')


def question(kind='structural'):
    return dict(kind=kind, text='Схема известна или способ ещё предстоит найти?', target_id='root', change='node_type', alternatives=['Направление исследования', 'Инженерное решение'])


def fake_agent(monkeypatch, replies):
    prompts = []
    def ask(prompt, repo, **_kwargs):
        prompts.append(prompt)
        assert Path(repo).is_dir()
        return copy.deepcopy(replies.pop(0))
    monkeypatch.setattr(interview, '_ask_agent', ask)
    monkeypatch.setattr(interview, '_ask_program_reply', lambda state, answer, repo, **kwargs: dict(intent='select', title=answer if answer in {'ML', 'Общая'} else (state.get('program_candidate') or {}).get('title', 'Общая'), expansion=''))
    return prompts


def start(client, repo, workspace, **extra):
    workspace.mkdir(exist_ok=True)
    response = client.post('/desktop/onboarding/interview/start', json={'repo_path': str(repo), 'workspace_root': str(workspace), **extra})
    assert response.status_code == 200, response.text
    return response.json()


def answer(client, repo, text, **extra):
    response = client.post('/desktop/onboarding/interview/reply', json={'repo_path': str(repo), 'answer': text, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_description_builds_whole_tree_and_resume_keeps_answers(repo, tmp_path, monkeypatch):
    prompts = fake_agent(monkeypatch, [reply(question=question()), reply('program')])
    workspace = tmp_path / 'research'
    with TestClient(app) as client:
        initial = start(client, repo, workspace)
        assert initial['phase'] == 'description' and initial['nodes'] == []
        assert not prompts
        state = answer(client, repo, 'Хочу обучить агента рассуждать по ситуации.')
        assert [n['node_type'] for n in state['nodes']] == ['direction', 'method']
        assert state['question_count'] == 2 and not state['complete']
        assert all(line.endswith(('[направление]', '[метод]')) for line in state['tree_text'].splitlines())
        assert start(client, repo, workspace) == state
        assert len(prompts) == 1
        assert 'README.md' in prompts[0] and 'An agent' in prompts[0]
        assert not (workspace / 'tree').exists()
        assert client.post('/desktop/onboarding/interview/finish', json={'path': str(repo), 'program_title': 'Общая'}).status_code == 400
        done = answer(client, repo, 'Схема известна, хочу её реализовать.')
        assert done['complete'] and done['nodes'][0]['node_type'] == 'program'
        assert done['messages'][-1]['brief']
        assert len(prompts) == 2
        assert 'Хочу обучить агента' in prompts[1]
        assert git(repo, 'status', '--porcelain') == ''


def test_missing_method_is_asked_before_agent_proposes_one(repo, tmp_path, monkeypatch):
    fake_agent(monkeypatch, [reply(method=False), reply(status='proposed')])
    with TestClient(app) as client:
        start(client, repo, tmp_path / 'research')
        state = answer(client, repo, 'Хочу изучить адаптивное мышление агента.')
        assert not state['complete']
        assert state['question']['kind'] == 'method'
        assert state['messages'][-1]['text'] == 'Есть ли у тебя подход или метод, с которого хочешь начать?'
        done = answer(client, repo, 'Пока идей нет, предложи подход.')
        assert done['complete'] and done['nodes'][-1]['node_type'] == 'method'


@pytest.mark.parametrize('kind', ['direction', 'program', 'problem'])
def test_finish_persists_new_notation_brief_and_method_kanban(repo, tmp_path, monkeypatch, kind):
    fake_agent(monkeypatch, [reply(kind)])
    workspace = tmp_path / 'research'
    before = git(repo, 'rev-parse', 'HEAD')
    with TestClient(app) as client:
        start(client, repo, workspace)
        done = answer(client, repo, 'Задача и выбранный подход описаны.')
        assert done['complete']
        approval = client.post('/desktop/onboarding/interview/reply', json={'repo_path': str(repo), 'answer': 'ОК, дерево согласовано'})
        assert approval.status_code == 200, approval.text
        answer(client, repo, 'Общая')
        answer(client, repo, 'да')
        finished = client.post('/desktop/onboarding/interview/finish', json={'path': str(repo), 'program_title': 'Общая'})
        assert finished.status_code == 200, finished.text
    destination = Path(finished.json()['project_md'])
    text = destination.read_text()
    project = parse_project_md(text, project_id='example')
    assert [n.node_type.value for n in project.nodes] == [kind, 'method']
    assert len(project.boards) == 1 and project.boards[0].owner_node_id == 'method'
    assert {c.id for c in project.boards[0].columns} == {'backlog', 'running', 'done'}
    assert ('koi:edge' in text) == (kind == 'problem')
    assert git(repo, 'rev-parse', 'HEAD') == before
    saved_brief = (destination.parent / 'onboard-brief.md').read_text()
    assert 'Нужно ли уточнение' in saved_brief and 'Задача и выбранный подход' in saved_brief
    for _, section, *_ in interview.BRIEF_FIELDS:
        assert f'## {section}' in saved_brief


@pytest.mark.parametrize('bad', ['duplicate', 'parent', 'legacy', 'edge', 'no_method', 'multi_leaf'])
def test_invalid_tree_is_rejected_without_changing_draft(repo, tmp_path, monkeypatch, bad):
    value = reply()
    if bad == 'duplicate':
        value['nodes'].extend([node('method', 'another', 'root'), node('method', 'third', 'root')])
    elif bad == 'parent':
        value['nodes'][1]['parent_id'] = 'missing'
    elif bad == 'legacy':
        value['nodes'][0]['node_type'] = 'cause'
    elif bad == 'edge':
        value = reply('problem')
        value['nodes'][1]['edge_label'] = ''
    elif bad == 'no_method':
        value['nodes'] = value['nodes'][:1]
    else:
        value['nodes'].append(node('program', 'program', 'root'))
    fake_agent(monkeypatch, [value, value])
    with TestClient(app) as client:
        original = start(client, repo, tmp_path / 'research')
        response = client.post('/desktop/onboarding/interview/reply', json={'repo_path': str(repo), 'answer': 'Описание'})
        assert response.status_code == 400
        assert start(client, repo, tmp_path / 'research') == original


def test_server_enforces_four_questions_and_two_confirmations(repo, tmp_path, monkeypatch):
    fake_agent(monkeypatch, [reply(question=question()) for _ in range(5)])
    with TestClient(app) as client:
        start(client, repo, tmp_path / 'research')
        for count in (2, 3, 4):
            state = answer(client, repo, 'Ответ')
            assert state['question_count'] == count and not state['complete']
        state = answer(client, repo, 'Последний ответ')
        assert state['complete'] and state['question_count'] == 4
        assert '?' not in state['messages'][-1]['text']
    state = dict(nodes=[], brief={}, messages=[], question_count=1, confirmation_count=0)
    for _ in range(3):
        interview._apply_reply(state, reply(question=question('confirmation')))
    assert state['confirmation_count'] == 2 and state['complete']


def test_nonstructural_questions_and_incomplete_brief_are_rejected():
    state = dict(nodes=[], messages=[], question_count=1, confirmation_count=0)
    value = reply(question=question())
    value['question']['change'] = 'description'
    with pytest.raises(interview.InterviewError):
        interview._apply_reply(state, value)
    value = reply()
    value['brief'].pop('cause')
    with pytest.raises(interview.InterviewError):
        interview._apply_reply(state, value)


def test_drafts_for_research_branches_are_isolated(repo, tmp_path, monkeypatch):
    fake_agent(monkeypatch, [reply(method=False), reply('program')])
    workspace = tmp_path / 'research'
    with TestClient(app) as client:
        start(client, repo, workspace)
        first = answer(client, repo, 'Первая идея')
        start(client, repo, workspace, branch='koi/research-2')
        second = answer(client, repo, 'Вторая идея', branch='koi/research-2')
        assert second['complete']
        assert start(client, repo, workspace) == first


def test_old_draft_is_preserved_as_context_not_saved_as_legacy_tree(repo, tmp_path, monkeypatch):
    workspace = tmp_path / 'research'
    workspace.mkdir()
    path = interview._session_path(repo)
    interview._save(path, {'version': 1, 'nodes': [{'type': 'cause', 'title': 'Старая причина'}], 'messages': [{'role': 'user', 'text': 'Старый ответ'}]})
    prompts = fake_agent(monkeypatch, [reply()])
    with TestClient(app) as client:
        state = start(client, repo, workspace)
        assert state['phase'] == 'description' and not state['nodes']
        answer(client, repo, 'Новое описание')
        assert 'Старая причина' in prompts[0] and 'Старый ответ' in prompts[0]


def test_browser_local_creation_uses_same_interview_and_no_repo(repo, monkeypatch):
    monkeypatch.setenv('KOI_SCAN_ROOTS', str(repo.parent))
    prompts = fake_agent(monkeypatch, [reply('program')])
    with TestClient(app) as client:
        response = client.post('/desktop/onboarding/interview/start', json={'project_tag': 'local-test', 'title': 'Мой проект'})
        assert response.status_code == 200, response.text
        session = response.json()['session_id']
        done = client.post('/desktop/onboarding/interview/reply', json={'session_id': session, 'answer': 'Собрать известные компоненты.'})
        assert done.status_code == 200, done.text
        assert done.json()['complete']
        assert 'Репозиторий не выбран' in prompts[0]
        approval = client.post('/desktop/onboarding/interview/reply', json={'session_id': session, 'answer': 'ОК, дерево согласовано'})
        assert approval.status_code == 200, approval.text
        client.post('/desktop/onboarding/interview/reply', json={'session_id': session, 'answer': 'Общая'})
        client.post('/desktop/onboarding/interview/reply', json={'session_id': session, 'answer': 'да'})
        finished = client.post('/desktop/onboarding/interview/finish', json={'session_id': session, 'program_title': 'Общая'})
        assert finished.status_code == 200, finished.text
        project = parse_project_md(Path(finished.json()['project_md']).read_text(), project_id='local-test')
        assert [n.node_type.value for n in project.nodes] == ['program', 'method']
        assert len(project.boards) == 1
        assert client.post('/desktop/onboarding/interview/finish', json={'session_id': session, 'program_title': 'Общая'}).status_code == 400


def test_interview_prefers_cursor_cli(tmp_path, monkeypatch):
    monkeypatch.setattr(interview, '_cursor_cli_text', lambda *_: '{"message":"Ответ"}')
    monkeypatch.setattr(interview, 'run_agent', lambda *_args, **_kw: pytest.fail('Fallback should not run'))
    assert interview._ask_agent('prompt', tmp_path)['message'] == 'Ответ'


def test_cannot_finish_before_interview(repo):
    with TestClient(app) as client:
        assert client.post('/desktop/onboarding/interview/finish', json={'path': str(repo), 'program_title': 'Общая'}).status_code == 400


def test_selected_codex_does_not_try_other_backends(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(interview, '_cursor_cli_text', lambda *_: pytest.fail('Cursor must not run'))
    def run(prompt, **kwargs):
        calls.append(kwargs)
        return '{"ok":true}', 'Codex'
    monkeypatch.setattr(interview, 'run_agent', run)
    assert interview._ask_agent('prompt', tmp_path, cli_agent='codex') == {'ok': True}
    assert calls[0]['backend'] == 'codex' and calls[0]['timeout'] == 120


def test_cursor_failure_is_recoverable_without_silent_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(interview, '_cursor_cli_text', lambda *_: None)
    monkeypatch.setattr(interview, 'run_agent', lambda *_args, **_kwargs: pytest.fail('No fallback is allowed'))
    with pytest.raises(interview.InterviewError, match='Cursor'):
        interview._ask_agent('prompt', tmp_path, cli_agent='cursor')


def test_api_passes_selected_agent_to_interview(repo, tmp_path, monkeypatch):
    calls = []
    def ask(prompt, cwd, **kwargs):
        calls.append(kwargs)
        return reply()
    monkeypatch.setattr(interview, '_ask_agent', ask)
    monkeypatch.setattr(interview, '_ask_program_reply', lambda state, answer, repo, **kwargs: dict(intent='select', title=answer if answer in {'ML', 'Общая'} else (state.get('program_candidate') or {}).get('title', 'Общая'), expansion=''))
    with TestClient(app) as client:
        start(client, repo, tmp_path / 'research')
        answer(client, repo, 'Описание и выбранный метод', cli_agent='codex')
    assert calls == [{'cli_agent': 'codex'}]


def test_ready_tree_can_be_corrected_through_chat(repo, tmp_path, monkeypatch):
    changed = reply()
    changed['nodes'][0]['title'] = 'Обучение адаптивным рассуждениям'
    prompts = fake_agent(monkeypatch, [reply(), changed])
    with TestClient(app) as client:
        start(client, repo, tmp_path / 'research')
        ready = answer(client, repo, 'Описание с выбранным методом')
        assert ready['complete']
        updated = answer(client, repo, 'Исправь формулировку направления.')
        assert updated['complete']
        assert updated['nodes'][0]['title'] == 'Обучение адаптивным рассуждениям'
        assert updated['question_count'] == ready['question_count']
        assert len(prompts) == 2


def test_onboarding_requires_discovery_and_manual_edits_do_not_call_agent(repo, tmp_path, monkeypatch):
    prompts = fake_agent(monkeypatch, [reply()])
    workspace = tmp_path / 'research'
    with TestClient(app) as client:
        start(client, repo, workspace, onboarding=True)
        ready = answer(client, repo, 'Описание с выбранным методом')
        assert ready['complete'] and ready['tutorial_required'] and not ready['tutorial_seen']
        assert client.post('/desktop/onboarding/interview/finish', json={'path': str(repo), 'program_title': 'Общая'}).status_code == 400
        seen = client.post('/desktop/onboarding/interview/reply', json={'repo_path': str(repo), 'decision': 'tutorial_seen'})
        assert seen.status_code == 200, seen.text
        assert seen.json()['tutorial_seen']
        assert 'ОК, дерево согласовано' in seen.json()['messages'][-1]['text']
        assert start(client, repo, workspace, onboarding=True)['tutorial_seen']
        edited = client.post('/desktop/onboarding/interview/reply', json={'repo_path': str(repo), 'decision': 'edit_node', 'node': {'id': 'method', 'title': 'Уточнённый метод', 'description': 'Уточнённое содержание'}})
        assert edited.status_code == 200, edited.text
        assert edited.json()['nodes'][-1]['title'] == 'Уточнённый метод'
        added = client.post('/desktop/onboarding/interview/reply', json={'repo_path': str(repo), 'decision': 'add_node', 'node': {'node_type': 'method', 'parent_id': 'root', 'title': 'Дополнительный метод', 'description': 'Явный выбор человека', 'edge_type': 'direction', 'edge_label': ''}})
        assert added.status_code == 200, added.text
        assert len(added.json()['nodes']) == 3 and added.json()['complete']
        assert len(prompts) == 1
        approval = client.post('/desktop/onboarding/interview/reply', json={'repo_path': str(repo), 'answer': 'ОК, дерево согласовано'})
        assert approval.status_code == 200, approval.text
        answer(client, repo, 'Общая')
        answer(client, repo, 'да')
        finished = client.post('/desktop/onboarding/interview/finish', json={'path': str(repo), 'program_title': 'Общая'})
        assert finished.status_code == 200, finished.text
        parsed = parse_project_md(Path(finished.json()['project_md']).read_text(), project_id='example')
        assert len(parsed.boards) == 2


def test_two_agent_methods_persist_with_separate_kanbans(repo, tmp_path, monkeypatch):
    value = reply()
    value['nodes'].append(node('method', 'another', 'root'))
    fake_agent(monkeypatch, [value])
    with TestClient(app) as client:
        start(client, repo, tmp_path / 'research')
        state = answer(client, repo, 'Хочу проверить два метода.')
        assert state['complete']
        approval = client.post('/desktop/onboarding/interview/reply', json={'repo_path': str(repo), 'answer': 'ОК, дерево согласовано'})
        assert approval.status_code == 200, approval.text
        answer(client, repo, 'Общая')
        answer(client, repo, 'да')
        finished = client.post('/desktop/onboarding/interview/finish', json={'path': str(repo), 'program_title': 'Общая'})
        assert finished.status_code == 200, finished.text
    project = parse_project_md(Path(finished.json()['project_md']).read_text(), project_id='example')
    assert {board.owner_node_id for board in project.boards} == {'method', 'another'}


def test_program_required_after_tree_approval(repo, tmp_path, monkeypatch):
    fake_agent(monkeypatch, [reply()])
    with TestClient(app) as client:
        start(client, repo, tmp_path / 'research')
        assert answer(client, repo, 'Выбран метод')['complete']
        blocked = client.post('/desktop/onboarding/interview/finish', json={'path': str(repo), 'program_title': 'ML'})
        assert blocked.status_code == 400
        assert 'согласовано' in blocked.json()['detail']
        assert answer(client, repo, 'ОК, дерево согласовано')['tree_approved']
        blocked = client.post('/desktop/onboarding/interview/finish', json={'path': str(repo)})
        assert blocked.status_code == 400
        assert 'подтверди' in blocked.json()['detail']
        selected = answer(client, repo, 'ML')
        assert selected['program_confirmation_pending'] and not selected['program_confirmed']
        assert answer(client, repo, 'да')['program_confirmed']
        changed = client.post('/desktop/onboarding/interview/finish', json={'path': str(repo), 'program_title': 'Другое'})
        assert changed.status_code == 400
        response = client.post('/desktop/onboarding/interview/finish', json={'path': str(repo)})
        assert response.status_code == 200, response.text
        text = Path(response.json()['project_md']).read_text()
        assert 'title: ML' in text


def test_manual_edit_requires_approval_again(repo, tmp_path, monkeypatch):
    prompts = fake_agent(monkeypatch, [reply()])
    with TestClient(app) as client:
        start(client, repo, tmp_path / 'research')
        ready = answer(client, repo, 'Описание с методом')
        assert '**Пришли ОК' in ready['messages'][-1]['text']
        assert answer(client, repo, 'ОК, дерево согласовано')['tree_approved']
        edited = client.post('/desktop/onboarding/interview/reply', json={'repo_path': str(repo), 'decision': 'edit_node', 'node': {'id': 'method', 'title': 'Другой метод'}})
        assert edited.status_code == 200
        assert not edited.json()['tree_approved']
        blocked = client.post('/desktop/onboarding/interview/finish', json={'path': str(repo), 'program_title': 'ML'})
        assert blocked.status_code == 400
        assert answer(client, repo, 'ОК')['tree_approved']
        assert len(prompts) == 1


@pytest.mark.parametrize('defect', ['extra_program', 'duplicate_id', 'invalid_id'])
def test_invalid_agent_reply_is_repaired_without_losing_answer(repo, tmp_path, monkeypatch, defect):
    bad = reply()
    if defect == 'extra_program':
        bad['nodes'].insert(1, node('direction', 'other', 'root'))
    elif defect == 'duplicate_id':
        bad['nodes'][1]['id'] = 'root'
    else:
        bad['nodes'][1]['id'] = 'method_1'
    prompts = fake_agent(monkeypatch, [bad, reply()])
    with TestClient(app) as client:
        start(client, repo, tmp_path / 'research')
        state = answer(client, repo, 'Интерактивный проекционный стенд')
        assert state['complete']
        assert state['question_count'] == 1
        assert len([m for m in state['messages'] if m['role'] == 'user']) == 1
    assert len(prompts) == 2
    assert 'Предыдущий ответ не прошёл проверку' in prompts[1]
    diagnostics = list((tmp_path / 'settings' / 'onboarding-interviews').glob('*.failure.json'))
    assert len(diagnostics) == 1
    assert json.loads(diagnostics[0].read_text())['reply'] == bad


@pytest.mark.parametrize('free_answer, intent, title', [
    ('Мне нравится, оставим этот вариант', 'select', 'PAR'),
    ('Лучше SAR', 'select', 'SAR'),
    ('Общая', 'select', 'Общая'),
    ('А что значит PAR?', 'comment', 'PAR'),
])
def test_program_discussion_requires_separate_confirmation(repo, tmp_path, monkeypatch, free_answer, intent, title):
    fake_agent(monkeypatch, [reply()])
    responses = [dict(intent='select', title='PAR', expansion='projection augmented reality'), dict(intent=intent, title=title, expansion='', message='Это проекционная дополненная реальность.')]
    monkeypatch.setattr(interview, '_ask_program_reply', lambda *args, **kwargs: responses.pop(0))
    with TestClient(app) as client:
        start(client, repo, tmp_path / 'research')
        answer(client, repo, 'Проекционная реальность')
        proposed = answer(client, repo, 'ОК')
        assert proposed['program_candidate']['title'] == 'PAR'
        assert 'Что думаешь?' in proposed['messages'][-1]['text']
        assert not proposed['program_confirmation_pending']
        assert not proposed.get('program_confirmed')
        selected = answer(client, repo, free_answer)
        assert not selected['program_confirmed']
        assert selected['program_confirmation_pending'] == (intent == 'select')
        assert client.post('/desktop/onboarding/interview/finish', json={'path': str(repo)}).status_code == 400
        if intent == 'select':
            assert selected['program_candidate']['title'] == title
            assert answer(client, repo, 'да')['program_confirmed']
            saved = client.post('/desktop/onboarding/interview/finish', json={'path': str(repo)})
            assert saved.status_code == 200, saved.text
            assert f'title: {title}' in Path(saved.json()['project_md']).read_text()


def test_program_rejection_and_reload_preserve_discussion(repo, tmp_path, monkeypatch):
    fake_agent(monkeypatch, [reply()])
    with TestClient(app) as client:
        workspace = tmp_path / 'research'
        start(client, repo, workspace)
        answer(client, repo, 'Описание')
        answer(client, repo, 'ОК')
        answer(client, repo, 'ML')
        rejected = answer(client, repo, 'нет')
        assert not rejected['program_confirmation_pending'] and not rejected['program_confirmed']
        assert start(client, repo, workspace)['program_candidate']['title'] == 'ML'
        assert not start(client, repo, workspace)['program_confirmed']
        answer(client, repo, 'Общая')
        answer(client, repo, 'да')
        assert start(client, repo, workspace)['program_confirmed']


def test_program_agent_receives_context_and_freeform_answer(monkeypatch, tmp_path):
    captured = {}
    def ask(prompt, repo, **kwargs):
        captured.update(prompt=prompt, repo=repo, options=kwargs)
        return dict(intent='select', title='PAR', expansion='projection augmented reality')
    monkeypatch.setattr(interview, '_ask_agent', ask)
    state = dict(nodes=[node('program', 'root')], messages=[{'role': 'user', 'text': 'Интерактивный проекционный стенд'}], program_candidate={'title': 'PAR', 'expansion': ''})
    result = interview._ask_program_reply(state, 'Название нравится, но можно без слова reality?', tmp_path, cli_agent='codex')
    assert result['title'] == 'PAR'
    assert 'Интерактивный проекционный стенд' in captured['prompt']
    assert 'Название нравится, но можно без слова reality?' in captured['prompt']
    assert captured['options']['cli_agent'] == 'codex'


def test_repository_answer_keeps_agents_contextual_clarification(repo, tmp_path, monkeypatch):
    followup = reply(method=False, question={
        'kind': 'clarification',
        'text': 'Найден цикл действий с запросом помощи оператору. Он и есть основа исследования?',
    })
    followup['brief']['repository_method']['answer'] = 'Реализован цикл действий, запроса помощи и продолжения с историей диалога.'
    prompts = fake_agent(monkeypatch, [reply(method=False), followup, reply()])
    with TestClient(app) as client:
        start(client, repo, tmp_path / 'research')
        answer(client, repo, 'Платформа взаимодействия агента и оператора')
        state = answer(client, repo, 'посмотри в репозитории')
        assert state['question']['kind'] == 'clarification'
        assert state['messages'][-1]['text'].endswith(followup['question']['text'])
        assert state['question']['alternatives'] == []
        assert state['brief']['repository_method']['answer'] == followup['brief']['repository_method']['answer']
        assert not state['complete']
        assert answer(client, repo, 'Да, именно этот цикл')['complete']
    assert 'посмотри в репозитории' in prompts[1]
    assert 'не спрашивай метод заново' in prompts[1]


def test_repeated_generic_method_question_requests_repair(repo, tmp_path, monkeypatch):
    specific = reply(method=False, question={'kind': 'clarification', 'text': 'Нашёл взаимодействие через диалог. Ты хочешь исследовать его?'})
    prompts = fake_agent(monkeypatch, [reply(method=False), reply(method=False), specific])
    with TestClient(app) as client:
        start(client, repo, tmp_path / 'research')
        answer(client, repo, 'Описание')
        state = answer(client, repo, 'Посмотри в репозитории')
        assert state['messages'][-1]['text'].endswith(specific['question']['text'])
        assert state['question_count'] == 3
    assert len(prompts) == 3
    assert 'Этот вопрос уже задан' in prompts[-1]


def test_freeform_question_keeps_context_and_limits_message_length():
    state = dict(nodes=[], messages=[], question_count=1, confirmation_count=0)
    value = reply(question={'kind': 'clarification', 'target_id': 'method', 'text': 'Этот подход относится к твоей задаче?'}, status='unknown')
    value['message'] = 'В репозитории нашёл обучение с учётом риска. Этот подход относится к твоей задаче?'
    interview._apply_reply(state, value)
    assert state['messages'][-1]['text'] == value['message']
    assert state['nodes'][-1]['id'] == 'method'
    value['question']['text'] = 'Один. Два. Три. Что дальше?'
    value['message'] = value['question']['text']
    with pytest.raises(interview.InterviewError):
        interview._apply_reply(state, value)
