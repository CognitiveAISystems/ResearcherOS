"""Compact chat navigation against the real desktop app and isolated project data."""
from pathlib import Path
from playwright.async_api import async_playwright
import test_chat_conversations_e2e as fixture

async def smoke(url):
    from koi.agent_chat import runner
    from koi.adapters import agent_backends
    from api.routers import agents
    from koi.adapters.agent_chat_queue import find_item
    from koi.agent_chat import conversations
    import os
    from koi.adapters import project_mount
    third = Path(os.environ['KOI_WORKSPACE']) / 'third/koi-structure'
    third.mkdir(parents=True)
    (third / 'project.md').write_text('---\nid: third\ntitle: Другое дерево\nprograms:\n- id: language\n  title: Языковые исследования\n---\n\n# problem: third-root\n\nДругая программа\n')
    (third / 'research.json').write_text('{"version":1,"questions":[]}')
    project_mount.rescan_projects()
    other_tree_chat = conversations.create('comparison', title='Чат другого дерева')
    extra_chats = [conversations.create('comparison', title=f'Обсуждение {i}') for i in range(6)]
    def catalog(): return [{'id': 'codex', 'label': 'Codex', 'available': True}]
    agent_backends.cli_agents = agents.cli_agents = runner.cli_agents = catalog
    runs = []
    def reply(prompt, item_id, **kwargs):
        item = find_item(item_id)
        runs.append((item, kwargs))
        if item['project_id'] is None and item['question'].startswith('Эксперимент BP35'):
            return ('Сначала выберите контекст эксперимента.\n```research_context\n'
                    '{"awaiting_selection":true,"options":[{"project_id":"demo","board_id":"board"},'
                    '{"project_id":"comparison"}]}\n```', 'codex')
        return 'Ответ тестового CLI', 'codex'
    runner._run_local_agent = reply
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={'width':1440, 'height':900}, timezone_id='America/New_York')
        page.set_default_timeout(10000)
        errors = []
        creations = []
        page.on("request", lambda request: creations.append(request.post_data_json) if request.method == "POST" and request.url.endswith("/agent-conversations") else None)
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.route('https://**/*', lambda route: route.abort())
        await page.goto(url + '?desktop=1', wait_until='networkidle')
        await page.evaluate("fetch('/api/settings/agent-chat',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({agent_chat_mode:'local'})})")
        await page.locator('.research-program[aria-pressed="true"]').wait_for()
        await page.locator('.lab-project-frame[data-project-id="demo"]').focus()
        await page.keyboard.press('Enter')
        await page.wait_for_function("document.querySelector('.lab-project-frame[data-project-id=demo]').getAttribute('aria-pressed')==='true'")
        assert await page.locator('.research-tree-picker').count() == 0
        demo_group = page.locator('.research-chat-section[data-section-id="demo"]')
        comparison_group = page.locator('.research-chat-section[data-section-id="comparison"]')
        general_group = page.locator('.research-chat-section[data-section-id="unassigned"]')
        all_program = page.locator('.research-program[data-focus-key="program-all"]')
        assert await page.locator('.research-filter-toggle').count() == 0
        assert await demo_group.locator('.research-chat-section-toggle').get_attribute('aria-expanded') == 'true'
        assert await page.locator('.research-chat-section[data-section-id=general], .research-chat-section[data-section-id=all]').count() == 0
        assert await all_program.is_visible()
        assert await page.locator('.research-program[data-focus-key=program-global]').is_visible()
        toggle = comparison_group.locator('.research-chat-section-toggle')
        await toggle.click()
        await page.wait_for_function("document.querySelector('.lab-project-frame[data-project-id=comparison]').getAttribute('aria-pressed')==='true'")
        assert await comparison_group.locator('[data-conversation]').count() == 3
        assert await comparison_group.locator('[data-conversation]').evaluate_all('(els)=>els.map(el=>el.dataset.conversation)') == [row['id'] for row in reversed(extra_chats[-3:])]
        await toggle.dblclick()
        assert await comparison_group.locator('[data-conversation]').count() == 7
        await toggle.click()
        await toggle.click()
        assert await comparison_group.locator('[data-conversation]').count() == 3
        await comparison_group.locator('.research-chat-show-all').focus()
        await page.keyboard.press('Enter')
        assert await comparison_group.locator('[data-conversation]').count() == 7
        await comparison_group.locator('.research-chat-show-all').click()
        assert await comparison_group.locator('[data-conversation]').count() == 3
        await all_program.click()
        assert await page.locator('.research-chat-section-toggle').count() == 3
        assert await page.locator('.research-chat-section[data-section-id=third]').is_visible()
        assert await page.locator('.research-chat-section[data-section-id=all]').count() == 0
        await comparison_group.locator('.research-chat-section-toggle').dblclick()
        assert await comparison_group.locator(f'[data-conversation="{other_tree_chat["id"]}"]').count() == 1
        await page.locator('.research-program[data-focus-key=program-agents]').click()
        await page.locator('.lab-project-frame[data-project-id="demo"]').focus()
        await page.keyboard.press('Enter')
        assert not await page.locator('#agent-chat-panel .conversation-content').is_visible()
        assert (await page.locator('.canvas-wrap').bounding_box())['width'] > 900
        assert (await page.locator('#mindmap-viewport').bounding_box())['height'] >= 899
        assert (await page.locator('.workspace-dock').bounding_box())['y'] > 800
        handle = page.locator('#agent-chat-panel .main-chat-resize')
        assert await handle.is_visible()
        assert (await page.locator('#agent-chat-panel').bounding_box())['width'] == 400
        search_box = await page.locator('.research-chat-search').bounding_box()
        create_box = await page.locator('[data-research-create]').bounding_box()
        heading_box = await page.locator('.research-chat-heading').bounding_box()
        assert abs(create_box['y'] + create_box['height']/2 - search_box['y'] - search_box['height']/2) <= 1
        assert create_box['x'] >= search_box['x'] + search_box['width'] + 4
        assert create_box['width'] == 44 and create_box['height'] == 44
        assert await page.locator('[data-research-create]').get_attribute('aria-label') == 'Новый чат'
        assert await comparison_group.locator('.conversation-entry').evaluate_all('els=>els.every(el=>el.getBoundingClientRect().height<=52)')
        footer = page.locator('.research-tree-actions')
        assert await footer.is_visible()
        assert (await footer.bounding_box())['height'] <= 50
        assert (await page.locator('#btn-new-project').bounding_box())['height'] <= 40
        assert search_box['y'] >= heading_box['y'] + heading_box['height']
        assert search_box['y'] + search_box['height'] - heading_box['y'] <= 132
        edge = await handle.bounding_box()
        await page.mouse.move(edge['x'] + 5, edge['y'] + 160)
        await page.mouse.down()
        await page.mouse.move(edge['x'] + 105, edge['y'] + 160, steps=6)
        await page.mouse.up()
        assert (await page.locator('#agent-chat-panel').bounding_box())['width'] == 500
        await page.wait_for_function("fetch('/api/settings').then(r=>r.json()).then(s=>s.chat_panel_width===500)")
        await handle.focus()
        await page.keyboard.press('ArrowLeft')
        assert (await page.locator('#agent-chat-panel').bounding_box())['width'] == 476
        await page.wait_for_function("fetch('/api/settings').then(r=>r.json()).then(s=>s.chat_panel_width===476)")
        await page.reload(wait_until='networkidle')
        await page.wait_for_function("document.querySelector('#agent-chat-panel').getBoundingClientRect().width===476")
        await handle.focus()
        await page.keyboard.press('Home')
        assert (await page.locator('#agent-chat-panel').bounding_box())['width'] == 340
        await handle.dblclick(position={'x': 5, 'y': 160})
        await page.wait_for_function("document.querySelector('#agent-chat-panel').getBoundingClientRect().width===400")
        navigation_width = (await page.locator('#agent-chat-panel').bounding_box())['width']
        rail = await page.locator('#agent-chat-panel .conversation-rail').bounding_box()
        for box in await page.locator('.research-program').evaluate_all('(els)=>els.map(el=>({x:el.getBoundingClientRect().x,right:el.getBoundingClientRect().right}))'):
            assert box['x'] >= rail['x'] and box['right'] <= rail['x'] + rail['width']
        await page.locator('.lab-project-frame[data-project-id="comparison"]').focus()
        await page.keyboard.press('Enter')
        await page.wait_for_function("document.querySelector('.lab-project-frame[data-project-id=comparison]').getAttribute('aria-pressed')==='true'")
        await comparison_group.locator('[data-conversation]').first.wait_for()
        await page.locator('[data-research-create]').click()
        await page.locator('#agent-chat-input').wait_for(state='visible')
        assert await page.locator('#agent-chat-input').evaluate('(el)=>el===document.activeElement')
        await page.wait_for_function("document.querySelector('#agent-chat-title').textContent==='Исследования агентов'")
        await page.locator('#agent-chat-conversations').wait_for(state='hidden')
        assert (await page.locator('#agent-chat-panel').bounding_box())['width'] == navigation_width
        assert await page.locator('#agent-chat-conversations').evaluate('(el)=>el.inert')
        assert await handle.is_visible()
        await handle.focus()
        await page.keyboard.press('ArrowRight')
        assert (await page.locator('#agent-chat-panel').bounding_box())['width'] == 424
        await page.keyboard.press('ArrowLeft')
        await page.locator('#agent-chat-input').focus()
        assert (await page.locator('.canvas-wrap').bounding_box())['width'] >= 900
        assert creations == [{'project_id': None, 'program_id': 'agents', 'focus_project_id': 'comparison'}], creations
        await page.locator('#agent-chat-form [data-cli-agent]').select_option('codex')
        await page.locator('#agent-chat-input').fill('Вопрос по выбранному дереву')
        await page.locator('#btn-agent-chat-send').click()
        await page.wait_for_function("document.querySelector('#agent-chat-log').textContent.includes('Ответ тестового CLI')")
        await page.wait_for_timeout(1100)  # Read the completed reply before closing the chat.
        await page.locator('#agent-chat-input').fill('Черновик выбранного дерева')
        await page.locator('#btn-chat-collapse').click()
        assert await general_group.locator('[data-conversation]').count() == 1
        general_toggle = general_group.locator('.research-chat-section-toggle')
        await general_toggle.click()
        assert await general_toggle.get_attribute('aria-expanded') == 'false'
        assert not await general_group.locator('.research-chat-section-content').is_visible()
        await page.wait_for_timeout(2200)  # Include a normal conversation polling refresh.
        assert await general_toggle.get_attribute('aria-expanded') == 'false'
        await general_toggle.focus()
        await page.keyboard.press('Enter')
        assert await general_group.locator('[data-conversation]').count() == 1
        assert await page.locator('.research-chat-section-toggle > small').count() == 0
        assert await page.locator('.research-chat-date-group').count() == 0
        await page.mouse.move(800, 80)
        selected = page.locator('.research-chat-entries [data-conversation][aria-pressed="true"]')
        assert await selected.locator('..').evaluate("el=>getComputedStyle(el).backgroundColor==='rgba(0, 0, 0, 0)' && getComputedStyle(el).boxShadow==='none' && getComputedStyle(el).borderTopColor==='rgba(0, 0, 0, 0)'")
        assert await selected.locator('.conversation-entry-title').evaluate("el=>getComputedStyle(el).fontWeight==='400'")
        assert await comparison_group.locator('.research-chat-section-toggle').evaluate("el=>getComputedStyle(el).backgroundColor==='rgba(0, 0, 0, 0)'")
        await page.keyboard.press('Tab')
        await selected.focus()
        assert await selected.evaluate("el=>getComputedStyle(el).outlineStyle!=='none'")
        await page.locator('.research-chat-entries [data-conversation][aria-pressed="true"]').click()
        assert await page.locator('#agent-chat-input').input_value() == 'Черновик выбранного дерева'
        await page.locator('#btn-chat-collapse').click()
        await page.locator('.research-chat-search input').fill('Несуществующий чат')
        assert await page.locator('.research-chat-entries [data-conversation]').count() == 0
        await page.locator('.research-chat-search input').fill('')
        await page.locator('.research-chat-entries [data-conversation]').first.wait_for()
        assert not await page.locator('#btn-agent-chat').is_visible()
        await page.locator('[data-research-collapse]').click()
        quick = page.get_by_role('button', name='Написать в общий чат', exact=True)
        assert await quick.is_visible()
        quick_box = await quick.bounding_box()
        rail_box = await page.locator('#agent-chat-panel .conversation-rail').bounding_box()
        theme_box = await page.locator('#btn-theme').bounding_box()
        assert quick_box['x'] >= rail_box['x'] and quick_box['x'] + quick_box['width'] <= rail_box['x'] + rail_box['width']
        assert quick_box['y'] >= theme_box['y'] + theme_box['height']
        assert await quick.evaluate("el=>el.parentElement.classList.contains('conversation-rail') && el.parentElement.lastElementChild===el")
        before_global = len(creations)
        await quick.click()
        await page.wait_for_function("!document.querySelector('.research-global-compose').disabled && document.activeElement===document.querySelector('#agent-chat-input')")
        assert len(creations) == before_global + 1
        assert creations[-1] == {'project_id': None}, creations[-1]
        assert not await quick.is_visible()
        await page.locator('#btn-chat-collapse').click()
        assert await quick.is_visible()
        await quick.click()
        await page.wait_for_function("!document.querySelector('.research-global-compose').disabled && document.activeElement===document.querySelector('#agent-chat-input')")
        assert len(creations) == before_global + 2
        assert creations[-1] == {'project_id': None}, creations[-1]
        await page.wait_for_function("document.querySelector('.research-program[aria-pressed=true]').dataset.focusKey==='program-global'")
        await page.locator('#agent-chat-input').wait_for(state='visible')
        await page.wait_for_function("document.querySelector('#agent-chat-title').textContent==='Общий чат'")
        await page.locator('#agent-chat-input').fill('Общий вопрос о рабочем процессе')
        async with page.expect_request(lambda r: r.method == 'POST' and r.url.endswith('/agent-chat')) as sent:
            await page.locator('#btn-agent-chat-send').click()
        payload = (await sent.value).post_data_json
        assert payload['project_id'] is None
        assert not any(payload.get(key) for key in ['board_id', 'card_id', 'method_id', 'node_id']), payload
        await page.wait_for_function("document.querySelector('#agent-chat-log').textContent.includes('Ответ тестового CLI')")
        assert await page.locator('.agent-chat-context-suggestions').count() == 0
        await page.locator('#btn-chat-collapse').click()
        await page.locator('.research-manage').click()
        assert await page.locator('#btn-new-project').is_visible()
        management = page.locator('.research-tree-management')
        assert await management.locator('[data-new-chat]').count() == 0
        assert await management.locator('[data-conversation], [data-tree-new-chat], [data-current-project]').count() == 0
        assert await management.get_by_text('Управление деревьями', exact=True).is_visible()
        await page.locator('#agent-chat-panel .conversation-content').wait_for(state='hidden')
        out = Path(__file__).resolve().parents[1] / '.run/ui-screenshots/compact-chat'
        out.mkdir(parents=True, exist_ok=True)
        for theme in ['light', 'dark']:
            await page.evaluate('theme=>document.documentElement.dataset.theme=theme', theme)
            await page.screenshot(path=str(out / (theme + '-management.png')))
        title = management.locator('.project-list__btn[data-project-id="comparison"]')
        await title.hover()
        await title.locator('..').locator('[data-tree-menu]').click()
        await page.locator('.tree-actions-popover:popover-open .tree-archive-action').click()
        await management.locator('.project-list__btn[data-project-id="comparison"]').wait_for(state='detached')
        await management.locator('[data-archive-nav="open"]').click()
        title = management.locator('.project-list__btn[data-project-id="comparison"]')
        await title.wait_for()
        await title.hover()
        await title.locator('..').locator('[data-tree-menu]').click()
        await page.locator('.tree-actions-popover:popover-open .tree-archive-action').click()
        await management.locator('[data-archive-nav="open"]').wait_for()
        assert await management.locator('.project-list__btn[data-project-id="comparison"]').is_visible()
        await page.locator('.research-manage').click()
        out = Path(__file__).resolve().parents[1] / '.run/ui-screenshots/compact-chat'
        out.mkdir(parents=True, exist_ok=True)
        await page.locator('.research-program[data-focus-key=program-agents]').click()
        await page.locator('.lab-project-frame[data-project-id="comparison"]').focus()
        await page.keyboard.press('Enter')
        await page.wait_for_function("document.querySelector('.lab-project-frame[data-project-id=comparison]').getAttribute('aria-pressed')==='true'")
        assert await page.locator('.research-tree-picker').count() == 0
        for theme in ['light', 'dark']:
            await page.evaluate('theme=>document.documentElement.dataset.theme=theme', theme)
            await page.locator('#agent-chat-panel .conversation-content').wait_for(state='hidden')
            await page.screenshot(path=str(out / (theme + '-navigation.png')))
            await page.locator('.research-chat-entries [data-conversation]').first.click()
            await page.wait_for_function("document.querySelector('#agent-chat-log').textContent.includes('Ответ тестового CLI')")
            await page.locator('#agent-chat-panel .conversation-sidebar').wait_for(state='hidden')
            await page.screenshot(path=str(out / (theme + '-chat.png')))
            await page.locator('#btn-chat-collapse').click()
        await page.wait_for_timeout(600)
        transform = await page.locator('#mindmap-canvas').evaluate('(el)=>el.style.transform')
        for _ in range(3):
            await page.locator('.research-chat-entries [data-conversation]').first.click()
            assert (await page.locator('#agent-chat-panel').bounding_box())['width'] == navigation_width
            await page.locator('#btn-chat-collapse').click()
        assert await page.locator('#mindmap-canvas').evaluate('(el)=>el.style.transform') == transform
        await page.emulate_media(reduced_motion='reduce')
        await page.locator('.research-chat-entries [data-conversation]').first.click()
        assert await page.locator('#agent-chat-panel .conversation-content').evaluate('(el)=>getComputedStyle(el).transform') == 'none'
        await page.locator('#btn-chat-collapse').click()
        await page.set_viewport_size({'width':900, 'height':700})
        assert (await page.locator('.canvas-wrap').bounding_box())['width'] > 300
        await page.set_viewport_size({'width':390, 'height':844})
        await page.locator('.research-chat-entries [data-conversation]').first.click()
        assert await page.locator('#agent-chat-input').is_visible()
        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        await page.wait_for_function("document.querySelector('#agent-chat-log').textContent.includes('Ответ тестового CLI')")
        await page.screenshot(path=str(out / 'mobile-chat.png'))
        await page.locator('#btn-chat-collapse').click()
        await page.set_viewport_size({'width':320, 'height':740})
        await page.locator('#agent-chat-panel .conversation-content').wait_for(state='hidden')
        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert (await page.locator('#agent-chat-panel').bounding_box())['width'] == 320
        assert (await page.locator('.research-chat-browser').bounding_box())['width'] >= 247
        await page.screenshot(path=str(out / 'narrow-navigation.png'))
        await page.evaluate("document.documentElement.dir='rtl'")
        assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        await page.screenshot(path=str(out / 'rtl-navigation.png'))
        await page.evaluate("document.documentElement.dir='ltr'")
        await page.set_viewport_size({'width':1440, 'height':900})
        await page.locator('.research-program[data-focus-key=program-agents]').click()
        await quick.click()
        await page.wait_for_function("!document.querySelector('.research-global-compose').disabled && document.activeElement===document.querySelector('#agent-chat-input')")
        await page.locator('#agent-chat-input').fill('Эксперимент BP35 с короткой памятью')
        await page.locator('#btn-agent-chat-send').click()
        choices = page.locator('.agent-chat-context-suggestions')
        await choices.wait_for()
        assert await choices.locator('.agent-chat-context-option').count() == 2
        assert not runs[-1][1].get('force') and runs[-1][0]['project_id'] is None
        for theme in ['light', 'dark']:
            await page.evaluate('theme=>document.documentElement.dataset.theme=theme', theme)
            await page.wait_for_timeout(200)  # Wait for existing button theme transitions before capture.
            await page.screenshot(path=str(out / (theme + '-context-choice.png')))
        await choices.locator('[data-context-option="0"]').click()
        await choices.wait_for(state='hidden')
        await page.wait_for_function("document.querySelector('#agent-chat-log').textContent.includes('Ответ тестового CLI')")
        assert runs[-1][0]['project_id'] == 'demo' and runs[-1][0]['board_id'] == 'board'
        assert runs[-1][1]['force'] is True
        await page.wait_for_function("document.querySelector('.lab-project-frame[data-project-id=demo]').getAttribute('aria-pressed')==='true'")
        await page.locator('#agent-chat-input').fill('Продолжим обсуждение выбранного метода')
        await page.locator('#btn-agent-chat-send').click()
        await page.wait_for_function("document.querySelectorAll('#agent-chat-log article').length===3 && !document.querySelector('#agent-chat-log .is-pending')")
        from koi.agent_chat.cli import build_context
        assert build_context(runs[-1][0]['id'])['scope_method']['id'] == 'method'
        await page.reload(wait_until='networkidle')
        assert await page.locator('.agent-chat-context-suggestions').count() == 0
        await page.locator('.research-program[data-focus-key=program-agents]').click()
        await quick.click()
        await page.wait_for_function("!document.querySelector('.research-global-compose').disabled && document.activeElement===document.querySelector('#agent-chat-input')")
        await page.locator('#agent-chat-input').fill('Эксперимент BP35, но пока обсуждение')
        await page.locator('#btn-agent-chat-send').click()
        await choices.wait_for()
        await choices.locator('[data-context-option="general"]').click()
        await choices.wait_for(state='hidden')
        await page.locator('#agent-chat-input').fill('Эксперимент BP35, продолжим обсуждение')
        await page.locator('#btn-agent-chat-send').click()
        await page.wait_for_function("document.querySelectorAll('#agent-chat-log article').length===2 && !document.querySelector('#agent-chat-log .is-pending')")
        assert await choices.count() == 0
        await page.locator('.research-program[data-focus-key=program-agents]').click()
        await page.locator('.lab-project-frame[data-project-id="comparison"]').focus()
        await page.keyboard.press('Enter')
        await page.locator('[data-research-create]').click()
        await page.wait_for_function("document.activeElement===document.querySelector('#agent-chat-input')")
        assert creations[-1] == {'project_id':None, 'program_id':'agents', 'focus_project_id':'comparison'}
        await page.locator('#agent-chat-input').fill('Эксперимент BP35 в выбранной программе')
        await page.locator('#btn-agent-chat-send').click()
        await choices.wait_for()
        assert await choices.get_by_text('Без привязки к дереву', exact=True).is_visible()
        await choices.locator('[data-context-option="0"]').click()
        await choices.wait_for(state='hidden')
        await page.wait_for_function("document.querySelector('#agent-chat-log').textContent.includes('Ответ тестового CLI')")
        await page.wait_for_function("document.querySelector('.lab-project-frame[data-project-id=demo]').getAttribute('aria-pressed')==='true'")
        assert conversations.find(runs[-1][0]['conversation_id'])['program_id'] == 'agents'
        await page.locator('#btn-chat-collapse').click()
        assert await demo_group.locator('.research-chat-section-toggle').get_attribute('aria-expanded') == 'true'
        await all_program.click()
        await comparison_group.locator('.research-chat-section-toggle').dblclick()
        assert await comparison_group.locator(f'[data-conversation="{other_tree_chat["id"]}"]').count() == 1
        await comparison_group.locator(f'[data-conversation="{other_tree_chat["id"]}"]').click()
        await page.wait_for_function("document.querySelector('.lab-project-frame[data-project-id=comparison]').getAttribute('aria-pressed')==='true'")
        assert await page.locator('#agent-chat-input').is_visible()
        for index in range(4):
            conversations.create(None, title=f'Сворачиваемый общий {index}')
        await all_program.click()
        await general_group.locator('.research-chat-show-all').wait_for()
        assert await general_group.locator('[data-conversation]').count() == 3
        await general_toggle.dblclick()
        assert await general_group.locator('[data-conversation]').count() >= 4
        await general_toggle.click()
        assert not await general_group.locator('.research-chat-section-content').is_visible()
        assert await page.locator('.research-chat-section[data-section-id=third]').is_visible()
        await page.locator('.research-chat-search input').fill('Сворачиваемый общий')
        await page.wait_for_function("document.querySelectorAll('.research-chat-section[data-section-id=unassigned] [data-conversation]').length===4")
        await page.locator('.research-chat-search input').fill('')
        assert await general_toggle.get_attribute('aria-expanded') == 'false'
        await page.mouse.move(800, 80)
        for theme in ['light', 'dark']:
            await page.evaluate('theme=>document.documentElement.dataset.theme=theme', theme)
            await page.screenshot(path=str(out / (theme + '-common-collapsed.png')))
        card_chat = conversations.create('demo', 'board', 'card', title='Только эта карточка')
        await page.locator('.research-program[data-focus-key=program-agents]').click()
        await page.locator('.lab-project-frame[data-project-id="demo"]').focus()
        await page.keyboard.press('Enter')
        await page.locator('.node-wrap[data-project-id="demo"][data-node-id="method"] .node-kanban-compact').click()
        await page.locator('#kanban-modal').wait_for(state='visible')
        await page.locator('.kanban-card[data-card-id="card"]').hover()
        await page.locator('.kanban-card[data-card-id="card"] .card-expand-report').click()
        await page.locator('#card-report-modal').wait_for(state='visible')
        await page.locator(f'.research-chat-entries [data-conversation="{card_chat["id"]}"]').wait_for()
        for key in ['program-all', 'program-global', 'program-language']:
            assert await page.locator(f'.research-program[data-focus-key="{key}"]').is_disabled()
        assert await comparison_group.locator('.research-chat-section-toggle').is_disabled()
        assert not await comparison_group.locator('.research-chat-section-content').is_visible()
        assert await page.locator('.research-chat-entries [data-conversation]').count() == 1
        for selector in ['.research-global-compose', '.research-manage', '#btn-new-project', '#projects-archive-bar button']:
            assert await page.locator(selector).is_disabled()
        before = len(creations)
        await quick.evaluate('el=>el.onclick()')  # Also guard the callback itself, not only the native button.
        assert len(creations) == before
        assert await page.locator('body').evaluate("el=>el.classList.contains('has-work-context')")
        await page.locator('.research-chat-search input').fill('Сворачиваемый общий')
        assert await page.locator('.research-chat-entries [data-conversation]').count() == 0
        await page.locator('.research-chat-search input').fill('')
        for theme in ['light', 'dark']:
            await page.evaluate('theme=>document.documentElement.dataset.theme=theme', theme)
            await page.mouse.move(1400, 850)
            await page.screenshot(path=str(out / (theme + '-card-context.png')))
        await page.locator('[data-research-create]').click()
        await page.locator('#agent-chat-input').wait_for(state='visible')
        assert creations[-1] == {'project_id':'demo', 'board_id':'board', 'card_id':'card'}
        await page.locator('#agent-chat-input').fill('Вопрос только по этой карточке')
        async with page.expect_request(lambda r: r.method == 'POST' and r.url.endswith('/agent-chat')) as scoped_send:
            await page.locator('#btn-agent-chat-send').click()
        scoped_payload = (await scoped_send.value).post_data_json
        assert [scoped_payload[key] for key in ['project_id', 'board_id', 'card_id']] == ['demo', 'board', 'card']
        await page.wait_for_function("document.querySelector('#agent-chat-log').textContent.includes('Ответ тестового CLI')")
        await page.locator('#card-report-modal button[data-close="card-report-modal"]').click()
        if await page.locator('#kanban-modal').is_visible():
            await page.locator('#kanban-modal button[data-close="kanban-modal"]').click()
        await page.wait_for_function("!document.body.classList.contains('has-work-context')")
        await page.wait_for_function("!document.querySelector('.research-program[data-focus-key=program-all]').disabled")
        assert await all_program.is_enabled()
        assert await quick.is_enabled()
        assert await page.locator('#btn-new-project').is_enabled()
        await page.evaluate("""async () => {
          const {ChatConversations} = await import('./chat-conversations.js');
          const controller = Object.create(ChatConversations.prototype);
          controller.main = true;
          controller.contextScope = {project_id:'demo', board_id:'board', card_id:'card'};
          const bad = [{project_id:null}, {project_id:'comparison'}, {project_id:'demo'},
            {project_id:'demo',board_id:'board'}, {project_id:'demo',board_id:'board',card_id:'other'}];
          controller.api = {createConversation:()=>{throw Error('Should not create unrelated chat');}};
          for (const scope of bad) {
            if (controller.acceptsScope(scope)) throw Error('Scope leak');
            await controller.select(scope); await controller.newChat(scope);
            controller.row = scope;
            let rejected = false;
            try {await controller.ensure();} catch {rejected = true;}
            if (!rejected) throw Error('Unrelated send allowed');
          }
          if (!controller.acceptsScope({...controller.contextScope, id:'own'})) throw Error('Own card blocked');
        }""")
        import re
        activity = {'running': False}
        async def activity_rows(route):
            response = await route.fetch()
            data = await response.json()
            for row in data['items']:
                row['pending'] = row['id'] == other_tree_chat['id']
                row['agent_active'] = row['id'] == other_tree_chat['id'] and activity['running']
            await route.fulfill(response=response, json=data)
        activity_url = re.compile(r'/api/agent-conversations(?:\?.*)?$')
        await page.route(activity_url, activity_rows)
        await page.reload(wait_until='networkidle')
        assert await page.locator('.research-program.has-activity').count() == 0
        activity['running'] = True
        await page.locator('.research-program[data-focus-key=program-agents].has-activity').wait_for()
        assert await page.locator('.research-program[data-focus-key=program-all].has-activity').count() == 1
        assert await page.locator('.research-program[data-focus-key=program-global].has-activity').count() == 0
        assert await page.locator('.research-program[data-focus-key=program-language].has-activity').count() == 0
        activity['running'] = False
        await page.wait_for_function("!document.querySelector('.research-program.has-activity')")
        await page.unroute(activity_url, activity_rows)
        assert not errors, errors
        await browser.close()
        print('PASS: program/tree groups, three recent chats, double-click and keyboard expansion, all-tree/general rail views, compact tree/archive actions, one-click program chat, drafts, search, management, light/dark, 900px and mobile; no date headings')

if __name__ == '__main__':
    fixture.smoke = smoke
    fixture.check()
