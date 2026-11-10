"""Shared creation UI keeps the hierarchy clean and the full brief visible."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from playwright.sync_api import expect, sync_playwright

from koi.adapters import onboarding_interview as interview

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('theme', ['dark', 'light'])
@pytest.mark.parametrize('source', ['repository', 'local'])
@pytest.mark.parametrize('failure', [False, True])
def test_description_tree_brief_and_method_question(theme, source, failure, monkeypatch):
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(ROOT / 'web')))
    Thread(target=server.serve_forever, daemon=True).start()
    state = dict(repo_path='/tmp/example' if source == 'repository' else None, title='Example', session_id=None if source == 'repository' else 'a' * 32, phase='description', repo_name='example', nodes=[], brief={}, messages=[{'role': 'assistant', 'text': 'Опиши проект своими словами.'}], complete=False, question_count=1, confirmation_count=0)
    brief = {key: dict(answer='Не определено', source='Описание пользователя', needs_clarification=False, clarification='') for key, *_ in interview.BRIEF_FIELDS}
    root = dict(id='root', node_type='direction', parent_id=None, title='Адаптивные рассуждения агента', description='Содержательное описание вне дерева.', edge_type='direction', edge_label='')
    tutorial = theme == 'light' and source == 'repository' and not failure
    monkeypatch.setattr(interview, '_ask_program_reply', lambda state, answer, repo, **kwargs: dict(intent='select', title='PAR' if answer == 'ОК, дерево согласовано' else 'ML', expansion='projection augmented reality' if answer == 'ОК, дерево согласовано' else 'машинное обучение'))
    requests = []
    waiting = []
    pause_reply = [True]
    fail_next = [failure]
    def route_api(route):
        url = route.request.url
        payload = route.request.post_data_json
        if url.endswith('/reply') and pause_reply[0]:
            waiting.append(route)
            return
        requests.append((url, payload))
        if url.endswith('/start'):
            state['tutorial_required'] = payload.get('onboarding', False)
            state['tutorial_seen'] = False
            route.fulfill(json=interview._public(state))
        elif url.endswith('/reply'):
            if payload.get('decision') in ('edit_node', 'add_node', 'tutorial_seen'):
                interview._edit_draft(state, payload['decision'], payload.get('node'))
                route.fulfill(json=interview._public(state))
                return
            if fail_next[0]:
                fail_next[0] = False
                route.fulfill(status=400, json={'detail': 'Codex не вернул ответ. Выбери другого агента и повтори отправку.'})
                return
            if state.get('tree_approved') or (state.get('complete') and payload['answer'] == 'ОК, дерево согласовано'):
                initial = not state.get('tree_approved')
                state['tree_approved'] = True
                interview._program_dialog(state, payload['answer'], ROOT, initial=initial)
                route.fulfill(json=interview._public(state))
                return
            state['messages'].append({'role': 'user', 'text': payload['answer'], 'question_text': 'Описание проекта'})
            has_method = len(state['messages']) > 2
            nodes = [root]
            if has_method:
                nodes.append(dict(id='method', node_type='method', parent_id='root', title='Обучение с учётом риска', description='Стартовый метод, предложенный агентом.', edge_type='direction', edge_label=''))
            if state.get('manual_tree'):
                nodes = state['nodes']
            interview._apply_reply(state, dict(nodes=nodes, brief=brief, method_status='proposed' if has_method else 'unknown', message='Дерево построено.', question=None, changes='Добавлен стартовый метод' if has_method else 'Нет'))
            route.fulfill(json=interview._public(state))
        else:
            route.fulfill(status=500, json={'detail': 'Unexpected request'})
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/api/desktop/onboarding/interview/**', route_api)
            page.route(f'http://127.0.0.1:{server.server_port}/', lambda route: route.fulfill(content_type='text/html', body='<html><head><link rel="stylesheet" href="/styles.css"><link rel="stylesheet" href="/desktop-onboarding.css"><link rel="stylesheet" href="/onboarding-interview.css"></head><body></body></html>'))
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            page.evaluate('''async ({theme, source, tutorial}) => {
                document.documentElement.dataset.theme = theme;
                const {runOnboardingInterview} = await import('/onboarding-interview.js');
                const overlay = document.createElement('div');
                overlay.className = 'desktop-onboarding'; document.body.append(overlay);
                await runOnboardingInterview({overlay, repoPath: source === 'repository' ? '/tmp/example' : null, workspaceRoot: '/tmp/research', localProject: source === 'local' ? {tag:'example', title:'Example'} : null, onBack: () => overlay.remove(), onboarding: tutorial});
            }''', {'theme': theme, 'source': source, 'tutorial': tutorial})
            textarea = page.get_by_role('textbox', name='Ваш ответ')
            expect(textarea).to_be_focused()
            expect(page.get_by_role('button', name='Бриф', exact=True)).to_be_disabled()
            agent_select = page.get_by_role('combobox', name='Выбрать агента')
            expect(agent_select).to_be_visible()
            agent_select.select_option('codex')
            textarea.fill('Хочу изучить адаптивное мышление агента.')
            page.get_by_role('button', name='Отправить сообщение').click()
            expect(page.get_by_text('Хочу изучить адаптивное мышление агента.', exact=True)).to_be_visible()
            expect(textarea).to_have_value('')
            expect(textarea).to_be_disabled()
            expect(agent_select).to_be_disabled()
            expect(page.get_by_text('Агент погружается в ваше исследование', exact=True)).to_be_visible()
            if theme == 'light' and source == 'repository' and not failure:
                shots = ROOT / '.run/ui-screenshots'
                shots.mkdir(exist_ok=True, parents=True)
                for index, caption in enumerate(['Агент погружается в ваше исследование', 'Агент выстраивает дерево', 'Агент выбирает программу'], 1):
                    expect(page.get_by_text(caption, exact=True)).to_be_visible(timeout=7000)
                    page.screenshot(path=str(shots / f'onboarding-loading-{index}.png'))
                activity = page.locator('[data-loading] .ma-core')
                assert activity.evaluate("node => getComputedStyle(node).animationName") != 'none'
            pause_reply[0] = False
            route_api(waiting.pop())
            if failure:
                expect(textarea).to_have_value('Хочу изучить адаптивное мышление агента.')
                expect(textarea).to_be_enabled()
                expect(page.get_by_role('alert')).to_have_text('Codex не вернул ответ. Выбери другого агента и повтори отправку.')
                expect(page.locator('[data-pending]')).to_have_count(0)
                agent_select.select_option('cursor')
                page.get_by_role('button', name='Отправить сообщение').click()
            tree = page.get_by_role('region', name='Дерево исследования')
            expect(tree.locator('.map-node')).to_have_count(1)
            expect(tree.locator('.node-title')).to_have_text('Адаптивные рассуждения агента')
            expect(tree.locator('.node-label')).to_have_text('[Направление]')
            expect(page.locator('.onboarding-interview__messages').get_by_text('Есть ли у тебя подход или метод, с которого хочешь начать?', exact=True)).to_be_visible()
            expect(page.get_by_role('heading', name='Инженерная задача или исследовательская', exact=True)).to_be_hidden()
            textarea.fill('Сохраняемый черновик')
            page.get_by_role('button', name='Бриф', exact=True).click()
            brief_panel = page.get_by_role('region', name='Бриф построения дерева', exact=True)
            expect(brief_panel).to_be_visible()
            expect(brief_panel.get_by_role('heading', name='Инженерная задача или исследовательская', exact=True)).to_be_visible()
            expect(brief_panel.get_by_role('columnheader', name='Мой ответ', exact=True)).to_have_count(7)
            expect(tree).to_be_visible()
            output = ROOT / '.run/ui-screenshots'
            output.mkdir(exist_ok=True, parents=True)
            page.screenshot(path=str(output / f'tree-brief-{source}-{theme}.png'))
            expect(textarea).to_be_hidden()
            page.get_by_role('button', name='Чат', exact=True).click()
            expect(brief_panel).to_be_hidden()
            expect(textarea).to_have_value('Сохраняемый черновик')
            expect(page.get_by_role('button', name='Дерево подходит — продолжить')).to_be_hidden()
            textarea.fill('У меня пока нет идей.')
            textarea.press('Enter')
            expect(tree.locator('.map-node')).to_have_count(2)
            expect(tree.locator('.node-title')).to_have_text(['Адаптивные рассуждения агента', 'Обучение с учётом риска'])
            expect(tree.locator('.node-label')).to_have_text(['[Направление]', '[Метод]'])
            expect(tree.locator('.onboarding-interview__edge')).to_have_count(1)
            expect(page.get_by_role('button', name='Дерево подходит — продолжить')).to_be_hidden()
            expect(page.get_by_role('button', name='Бриф', exact=True)).to_have_count(1)
            expect(page.locator('.onboarding-interview__tabs').get_by_role('button', name='Бриф')).to_be_visible()
            expect(page.locator('.onboarding-interview__messages button')).to_have_count(0)
            expect(textarea).to_be_enabled()
            expect(textarea).to_be_visible()
            expect(textarea).to_be_focused()
            assert 'Содержательное описание' not in tree.inner_text()
            assert not page.locator('.onboarding-interview__messages pre').count()
            assert page.locator('.onboarding-interview__chat').bounding_box()['x'] < tree.bounding_box()['x']
            assert len(requests) == (4 if failure else 3)
            selected = [payload['cli_agent'] for url, payload in requests if url.endswith('/reply')]
            assert selected == (['codex', 'cursor', 'cursor'] if failure else ['codex', 'codex'])
            assert requests[0][1]['repo_path'] == ('/tmp/example' if source == 'repository' else None)
            assert not errors
            output = ROOT / '.run/ui-screenshots'
            output.mkdir(exist_ok=True, parents=True)
            if tutorial:
                finish = page.get_by_role('button', name='Дерево подходит — продолжить')
                expect(finish).to_be_hidden()
                root = tree.locator('[data-node-id="root"]')
                expect(root).to_have_class(__import__('re').compile('is-tutorial'))
                root.hover()
                expect(finish).to_be_hidden()
                expect(page.get_by_text('Можно отредактировать дерево здесь; когда закончишь, напиши «ОК, дерево согласовано».', exact=True)).to_be_visible()
                root = tree.locator('[data-node-id="root"]')
                root.dblclick()
                title_editor = page.get_by_role('textbox', name='Имя узла', exact=True)
                title_editor.fill('Уточнённое направление')
                title_editor.press('Enter')
                expect(tree.get_by_text('Уточнённое направление', exact=True)).to_be_visible()
                root = tree.locator('[data-node-id="root"]')
                root.hover()
                root.get_by_role('button', name='Действия с узлом «Уточнённое направление»').click()
                page.screenshot(path=str(output / 'tree-node-actions-light.png'))
                page.get_by_role('button', name='Добавить: Метод', exact=True).click()
                editor = page.get_by_role('dialog', name='Добавить узел', exact=True)
                expect(editor.get_by_label('Название', exact=True)).to_be_focused()
                for width, height in [(1440, 1000), (1280, 750), (320, 640)]:
                    page.set_viewport_size({'width': width, 'height': height})
                    box = editor.bounding_box()
                    assert box['width'] <= 480
                    assert abs(box['x'] + box['width'] / 2 - width / 2) <= 1
                    assert abs(box['y'] + box['height'] / 2 - height / 2) <= 1
                    assert box['height'] <= height - 32
                page.set_viewport_size({'width': 1280, 'height': 750})
                page.screenshot(path=str(output / 'tree-add-node-centered-light.png'))
                page.set_viewport_size({'width': 1440, 'height': 1000})
                editor.get_by_label('Тип узла', exact=True).select_option('method')
                editor.get_by_label('Название', exact=True).fill('Второй метод')
                editor.get_by_role('button', name='Добавить узел', exact=True).click()
                expect(editor).to_have_count(0)
                expect(tree.locator('.map-node.method')).to_have_count(2)
                textarea.fill('Сохрани ручные дополнения при уточнении описания.')
                textarea.press('Enter')
                expect(textarea).to_have_value('')
                expect(tree.locator('.map-node.method')).to_have_count(2)
                expect(finish).to_be_hidden()
            expect(page.get_by_text('Общее направление объединяет несколько тем исследования.', exact=False)).to_be_hidden()
            if theme == 'light' and source == 'repository' and not failure:
                page.screenshot(path=str(output / 'onboarding-awaiting-approval.png'))
            textarea.fill('ОК, дерево согласовано')
            textarea.press('Enter')
            expect(page.get_by_text('Общее направление объединяет несколько тем исследования.', exact=False)).to_be_visible()
            expect(page.locator('.onboarding-interview__messages strong').filter(has_text='Пришли короткое обозначение общего направления')).to_be_visible()
            expect(textarea).to_have_attribute('placeholder', 'Что думаешь о названии?')
            expect(agent_select).to_be_hidden()
            expect(page.get_by_role('button', name='Дерево подходит — продолжить')).to_be_hidden()
            if theme == 'light' and source == 'repository' and not failure:
                page.screenshot(path=str(output / 'onboarding-program-required.png'))
            expect(page.get_by_role('button', name='Перейти к исследованию')).to_be_hidden()
            before_empty = len(requests)
            textarea.fill('   ')
            textarea.press('Enter')
            assert len(requests) == before_empty
            textarea.fill('Название хорошее, но лучше ML')
            textarea.press('Enter')
            expect(page.get_by_text('Тогда выбираем', exact=False)).to_be_visible()
            expect(page.get_by_role('button', name='Перейти к исследованию')).to_be_hidden()
            expect(textarea).to_have_attribute('placeholder', 'Да, нет или правка')
            if theme == 'light' and source == 'repository' and not failure:
                page.screenshot(path=str(output / 'onboarding-program-confirmation.png'))
            textarea.fill('да')
            textarea.press('Enter')
            expect(page.get_by_role('button', name='Перейти к исследованию')).to_be_visible()
            if theme == 'light' and source == 'repository' and not failure:
                page.screenshot(path=str(output / 'onboarding-program-confirmed.png'))
            page.route('**/api/desktop/onboarding/interview/finish', lambda route: route.fulfill(status=400, json={'detail': 'Проверка сохранения'}))
            with page.expect_request('**/api/desktop/onboarding/interview/finish') as saving:
                page.get_by_role('button', name='Перейти к исследованию').click()
            assert 'program_title' not in saving.value.post_data_json
            expect(page.get_by_role('alert')).to_have_text('Проверка сохранения')
            page.screenshot(path=str(output / f'tree-interview-{source}-{theme}.png'))
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
