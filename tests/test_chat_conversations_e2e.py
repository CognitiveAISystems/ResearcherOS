import os, tempfile, json, ast, sys, asyncio
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from playwright.async_api import async_playwright
async def smoke(url):
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        page=await browser.new_page(viewport={'width':1440,'height':900})
        errors=[]
        page.on('pageerror',lambda e:(errors.append(str(e)),print('PAGE ERROR:',str(e),flush=True)))
        await page.route('https://**/*',lambda route:route.abort())
        page.set_default_timeout(10000)
        await page.goto(url+'?desktop=1',wait_until='networkidle')
        assert not await page.locator('.projects-drawer').is_visible()
        assert await page.locator('[data-chat-project-toggle="global"]').get_attribute('aria-expanded') == 'false'
        assert await page.locator('#agent-chat-conversations [data-chat-project-toggle][aria-expanded="true"]').count() == 0
        initial=ROOT/'.run/ui-screenshots/global-chat';initial.mkdir(parents=True,exist_ok=True)
        await page.screenshot(path=str(initial/'collapsed-default.png'))
        header_height=(await page.locator('.topbar').bounding_box())['height']
        assert header_height <= 65,header_height
        await page.locator('#brand-tagline').evaluate('(el)=>el.textContent="Creating a memory that grows with every question"')
        assert (await page.locator('.topbar').bounding_box())['height'] == header_height
        rail_box=await page.locator('#agent-chat-panel .conversation-rail').bounding_box()
        nav_box=await page.locator('#agent-chat-conversations').bounding_box()
        map_box=await page.locator('.canvas-wrap').bounding_box()
        assert rail_box['x'] < nav_box['x'] < map_box['x']
        assert await page.locator('.topbar-row').evaluate('(el)=>el.firstElementChild.classList.contains("topbar-start")')
        assert await page.locator('#agent-chat-conversations #btn-new-project').is_visible()
        assert await page.locator('#agent-chat-conversations #projects-archive-bar').is_visible()
        assert await page.locator('.unified-chat-navigation #projects-archive-bar').count() == 1
        assert await page.locator('.unified-navigation-actions #projects-archive-bar').count() == 0
        assert await page.locator('.unified-chat-navigation').evaluate('(el)=>el.firstElementChild.id') == 'projects-archive-bar'
        assert await page.locator('#agent-chat-conversations #project-list').is_visible()
        tree_actions=page.locator('#agent-chat-conversations [data-tree-new-chat="comparison"]')
        await page.mouse.move(400,80)
        assert not await tree_actions.is_visible()
        await page.locator('#agent-chat-conversations .project-list__btn[data-project-id="comparison"]').hover()
        assert await tree_actions.evaluate('(el)=>getComputedStyle(el).opacity') == '1'
        await page.mouse.move(400,80)
        await page.locator('#agent-chat-conversations .project-list__btn[data-project-id="comparison"]').focus()
        await tree_actions.focus()
        assert await tree_actions.evaluate('(el)=>getComputedStyle(el).opacity') == '1'
        await page.mouse.move(400,80)
        await page.locator('#btn-agent-chat').focus()
        await page.mouse.move(400,80)
        title=page.locator('#agent-chat-conversations .project-list__btn[data-project-id="comparison"]')
        before=(await title.bounding_box())['width']
        await title.hover()
        after=(await title.bounding_box())['width']
        assert before > after+50,(before,after)
        await tree_actions.hover()
        await page.locator('#researcheros-tooltip:popover-open').wait_for()
        assert await page.locator('#researcheros-tooltip').inner_text() == 'Новый чат'
        assert await tree_actions.get_attribute('title') is None
        await page.keyboard.press('Escape')
        await page.locator('#researcheros-tooltip:popover-open').wait_for(state='hidden')

        assert await page.locator('.unified-navigation-heading [data-current-project]').is_visible()
        await page.locator('.unified-navigation-heading [data-current-project]').click()
        assert not await page.locator('#agent-chat-panel .conversation-content').is_visible()
        await page.locator('.unified-navigation-heading [data-current-project]').click()
        await page.locator('#btn-agent-chat').click()
        assert not await page.locator('#agent-chat-conversations').is_visible()
        assert await page.locator('#agent-chat-panel .conversation-rail').is_visible()
        assert not await page.locator('#agent-chat-panel .conversation-list-resize').is_visible()
        assert not await page.locator('#agent-chat-panel .main-chat-resize').is_visible()
        assert round((await page.locator('#agent-chat-panel').bounding_box())['width']) == 44
        await page.screenshot(path=str(initial/'collapsed-sidebar.png'))
        assert not await page.locator('#agent-chat-panel [data-current-project]').is_visible()
        await page.locator('#btn-agent-chat').click()
        assert await page.locator('#agent-chat-conversations').is_visible()
        assert await page.locator('.unified-navigation-heading [data-current-project]').is_visible()
        await page.locator('#agent-chat-conversations [data-new-chat]').click()
        await page.wait_for_selector('#agent-chat-conversations [data-conversation]')
        await page.locator('#agent-chat-form [data-cli-agent]').select_option('acp:test')
        await page.wait_for_function("document.querySelector('#agent-chat-panel [data-conversation-context]')?.textContent==='Без проекта'")
        await page.locator('#agent-chat-input').fill('Вопрос по всем исследованиям')
        await page.locator('#btn-agent-chat-send').click()
        await page.wait_for_function("document.querySelector('#agent-chat-log')?.textContent.includes('Поток ответа')",timeout=15000)
        await page.locator('#agent-chat-input').fill('Продолжи тот же разговор')
        await page.locator('#btn-agent-chat-send').click()
        await page.wait_for_function("document.querySelectorAll('#agent-chat-log article:not(.is-pending)').length === 2",timeout=15000)
        assert await page.locator('.agent-chat-delete').count() == 0
        assert await page.locator('#agent-chat-tab-activity').count() == 0
        assert await page.locator('#agent-chat-panel [data-current-project]').is_visible()
        outer=page.locator('#agent-chat-panel .main-chat-resize')
        old_width=(await page.locator('#agent-chat-panel').bounding_box())['width']
        box=await outer.bounding_box()
        await page.mouse.move(box['x']+4,box['y']+100)
        await page.mouse.down()
        await page.mouse.move(box['x']+84,box['y']+100,steps=8)
        await page.mouse.up()
        panel_width=round((await page.locator('#agent-chat-panel').bounding_box())['width'])
        assert panel_width > old_width+60
        await page.wait_for_function("width=>fetch('/api/settings').then(r=>r.json()).then(s=>s.chat_panel_width===width)",arg=panel_width)
        await outer.focus();await page.keyboard.press('ArrowRight')
        panel_width=round((await page.locator('#agent-chat-panel').bounding_box())['width'])
        resize=page.locator('#agent-chat-panel .conversation-list-resize')
        await resize.focus()
        await page.keyboard.press('ArrowLeft')
        saved_width=round((await page.locator('#agent-chat-conversations').bounding_box())['width'])
        await page.wait_for_function("width=>fetch('/api/settings').then(r=>r.json()).then(s=>s.chat_list_main_width===width)",arg=saved_width)
        await page.evaluate("localStorage.removeItem('koi-chat-list-width-main')")
        await page.reload(wait_until='networkidle')
        await page.locator('[data-chat-project-toggle="global"][aria-expanded="false"]').wait_for()
        await page.locator('[data-chat-project-toggle="global"]').click()
        await page.locator('#agent-chat-conversations [data-conversation][aria-pressed="true"]').click()
        await page.wait_for_function("document.querySelectorAll('#agent-chat-log article').length === 2",timeout=10000)
        await page.wait_for_function("width=>Math.round(document.querySelector('#agent-chat-conversations').getBoundingClientRect().width)===width",arg=saved_width)
        assert round((await page.locator('#agent-chat-conversations').bounding_box())['width']) == saved_width
        assert round((await page.locator('#agent-chat-panel').bounding_box())['width']) == panel_width
        global_toggle=page.locator('[data-chat-project-toggle="global"]')
        await global_toggle.click()
        assert not await page.locator('#unified-global-chats').is_visible()
        assert await global_toggle.get_attribute('aria-expanded') == 'false'
        await global_toggle.focus();await page.keyboard.press('Enter')
        assert await page.locator('#unified-global-chats').is_visible()
        # Native drag and drop: global -> project -> global -> card -> global.
        source=page.locator('#agent-chat-conversations [data-conversation][aria-pressed="true"]')
        project_target=page.locator('#agent-chat-conversations button.project-list__btn[data-project-id="demo"]')
        global_target=page.locator('#agent-chat-conversations h3[data-project-id=""]')
        await source.drag_to(project_target)
        await page.wait_for_function("document.querySelector('#agent-chat-panel [data-conversation-context]')?.textContent==='Проверка чатов'")
        assert await page.locator('#agent-chat-log article').count() == 2
        disclosure=page.locator('[data-chat-project-toggle="demo"]')
        await disclosure.click()
        assert not await source.is_visible()
        await disclosure.focus(); await page.keyboard.press('Enter')
        assert await source.is_visible()
        await page.locator('#agent-chat-input').fill('Теперь продолжи в проекте')
        await page.locator('#btn-agent-chat-send').click()
        await page.wait_for_function("document.querySelectorAll('#agent-chat-log article:not(.is-pending)').length === 3",timeout=15000)
        await source.drag_to(global_target)
        await page.wait_for_function("document.querySelector('#agent-chat-panel [data-conversation-context]')?.textContent==='Без проекта'")
        assert await page.locator('#agent-chat-log article').count() == 3
        await source.scroll_into_view_if_needed()
        await project_target.scroll_into_view_if_needed()
        source_box=await source.bounding_box(); target_box=await project_target.bounding_box()
        await page.mouse.move(source_box['x']+30,source_box['y']+16)
        await page.mouse.down()
        await page.mouse.move(source_box['x']+40,source_box['y']+24,steps=4)
        await page.mouse.move(target_box['x']+30,target_box['y']+16,steps=10)
        target_box=await project_target.bounding_box()
        await page.mouse.move(target_box['x']+40,target_box['y']+20,steps=4)
        drop_card=page.locator('#agent-chat-conversations [data-chat-drop][data-card-id="card"]')
        try:
            await drop_card.wait_for(state='visible')
        except Exception:
            await page.screenshot(path='/Users/zoya/Documents/Codex/2026-10-26/vj/work/unified-drag-error.png')
            raise
        card_box=await drop_card.bounding_box()
        await page.mouse.move(card_box['x']+30,card_box['y']+16,steps=10)
        await page.mouse.up()
        await page.wait_for_function("document.querySelector('#agent-chat-panel [data-conversation-context]')?.textContent.includes('Карточка')")
        assert await page.locator('#agent-chat-log article').count() == 3
        await source.drag_to(global_target)
        await page.wait_for_function("document.querySelector('#agent-chat-panel [data-conversation-context]')?.textContent==='Без проекта'")
        out=ROOT/'.run/ui-screenshots/global-chat';out.mkdir(parents=True,exist_ok=True)
        for theme in ('light','dark'):
            await page.evaluate('theme=>document.documentElement.dataset.theme=theme',theme)
            await page.screenshot(path=str(out/f'{theme}.png'))
        await page.locator('#agent-chat-conversations [data-move-chat]').focus()
        await page.keyboard.press('Enter')
        dialog=page.locator('.conversation-move-dialog')
        await page.wait_for_function("!document.querySelector('.conversation-move-dialog [name=project]').disabled")
        for theme in ('light','dark'):
            await page.evaluate('theme=>document.documentElement.dataset.theme=theme',theme)
            await page.screenshot(path=str(out/f'move-{theme}.png'))
        await page.keyboard.press('Escape')
        await dialog.wait_for(state='detached')
        # A real ACP permission wait keeps the process alive until the composer stop is clicked.
        await page.locator('#agent-chat-input').fill('Проверка остановки')
        await page.locator('#btn-agent-chat-send').click()
        await page.wait_for_function("document.querySelector('#btn-agent-chat-send')?.getAttribute('aria-label')==='Остановить'",timeout=15000)
        assert await page.locator('#agent-chat-controls [data-cancel-chat]').count() == 0
        await page.locator('#agent-chat-input').fill('Несохранённый следующий вопрос')
        await page.locator('#agent-chat-input').press('Enter')
        assert await page.locator('#btn-agent-chat-send').get_attribute('data-action') == 'stop'
        for theme in ('light','dark'):
            await page.evaluate('theme=>document.documentElement.dataset.theme=theme',theme)
            await page.screenshot(path=str(out/f'stop-{theme}.png'))
        await page.locator('#btn-agent-chat-send').click()
        await page.wait_for_function("document.querySelector('#btn-agent-chat-send')?.dataset.action==='send'",timeout=15000)
        assert await page.locator('#agent-chat-input').input_value() == 'Несохранённый следующий вопрос'
        assert await page.locator('#agent-chat-log article').count() == 4
        assert await page.locator('#agent-chat-conversations .project-list__eye').count() == 0
        tree=page.locator('#agent-chat-conversations .project-list__btn[data-project-id="comparison"]')
        await tree.drag_to(page.locator('#agent-chat-conversations [data-archive-nav="open"]'))
        await tree.wait_for(state='detached')
        await page.locator('#agent-chat-conversations [data-archive-nav="open"]').click()
        await page.locator('#agent-chat-conversations [data-archive-nav="close"]').wait_for()
        assert not await page.locator('.unified-global-chats').is_visible()
        assert await page.locator('#agent-chat-conversations .project-list__btn[data-project-id="demo"]').count() == 0
        menu=page.locator('#agent-chat-conversations [data-tree-menu="comparison"]')
        await menu.locator("..").hover(); await menu.click()
        action=page.locator('.tree-actions-popover:popover-open .tree-archive-action')
        assert await action.inner_text() == 'Вернуть из архива'
        for theme in ('light','dark'):
            await page.evaluate('theme=>document.documentElement.dataset.theme=theme',theme)
            await page.screenshot(path=str(out/f'tree-archive-menu-{theme}.png'))
        await action.click()
        await page.locator('#agent-chat-conversations [data-archive-nav="open"]').wait_for()
        assert await page.locator('.unified-global-chats').is_visible()
        await menu.locator("..").hover(); await menu.click()
        await page.keyboard.press('Escape')
        await page.locator('.tree-actions-popover:popover-open').wait_for(state='hidden')
        await menu.locator("..").hover(); await menu.click()
        assert await action.inner_text() == 'В архив'
        await action.click()
        await tree.wait_for(state='detached')
        await page.locator('#agent-chat-conversations [data-archive-nav="open"]').click()
        await menu.locator("..").hover(); await menu.click(); await action.click()
        await tree.wait_for()
        await page.locator('#agent-chat-conversations [data-archive-nav="open"]').click()
        await page.locator('#agent-chat-conversations [data-archive-nav="close"]').wait_for()
        await page.locator('#agent-chat-conversations [data-archive-nav="close"]').click()
        await page.locator('#agent-chat-conversations .project-list__btn[data-project-id="demo"]').wait_for()
        # One right-hand navigator survives closing chat; narrow layouts expose it through the rail.
        nav=page.locator('#agent-chat-conversations')
        assert await nav.locator('.program-group__label').filter(has_text='Исследования агентов').count() == 1
        long_title=nav.locator('.project-list__btn[data-project-id="comparison"]')
        assert await long_title.get_attribute('data-tooltip') == await long_title.inner_text()
        assert await page.locator('[title]').count() == 0
        for theme in ('light','dark'):
            await page.evaluate('theme=>document.documentElement.dataset.theme=theme',theme)
            await page.screenshot(path=str(out/f'unified-{theme}.png'))
        await page.locator('#btn-agent-chat').click()
        assert not await nav.is_visible()
        assert await page.locator('#agent-chat-panel .conversation-content').is_visible()
        await page.locator('#btn-agent-chat').click()
        assert await nav.is_visible()
        assert await page.locator('#agent-chat-panel .conversation-content').is_visible()
        await page.locator('#btn-chat-collapse').click()
        assert await nav.is_visible()
        assert not await page.locator('#agent-chat-panel .conversation-content').is_visible()
        assert await page.locator('.canvas-wrap').is_visible()
        for width in (320,390,900,1440,2560):
            await page.set_viewport_size({'width':width,'height':900})
            assert await nav.is_visible()
            assert (await page.locator('.topbar').bounding_box())['height'] <= 65
            assert abs((await page.locator('#workspace').bounding_box())['y']+(await page.locator('#workspace').bounding_box())['height']-900)<=1
            geometry=await nav.evaluate('(el)=>({client:el.clientWidth,scroll:el.scrollWidth})')
            assert geometry['scroll'] <= geometry['client']+1,(width,geometry)
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            await page.screenshot(path=str(out/f'unified-{width}.png'))
            await page.locator('#btn-rq-bell').click()
            feed=await page.locator('#rq-bell-panel').bounding_box()
            assert feed['x'] >= 0 and feed['x']+feed['width'] <= width+1,(width,feed)
            await page.locator('#btn-rq-bell').click()
            if width <= 390:
                await page.locator('#agent-chat-conversations [data-conversation][aria-pressed="true"]').click()
                assert await nav.is_visible()
                assert await page.locator('#agent-chat-panel .conversation-content').is_visible()
                await page.screenshot(path=str(out/f'persistent-open-{width}.png'))
                await page.locator('#btn-chat-collapse').click()
                assert await nav.is_visible()

        await page.set_viewport_size({'width':1440,'height':900})
        await page.evaluate("document.documentElement.style.fontSize='200%'")
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        await page.evaluate("document.documentElement.style.fontSize='';document.documentElement.dir='rtl'")
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        await page.evaluate("document.documentElement.dir='ltr'")
        await page.locator('#agent-chat-conversations .project-list__btn[data-project-id="comparison"]').hover()
        await page.locator('#agent-chat-conversations [data-tree-new-chat="comparison"]').click()
        await page.wait_for_function("document.querySelector('#agent-chat-panel [data-conversation-context]')?.textContent==='Языковые и зрительные модели плохо планируют в новых средах'")
        selected=page.locator('#agent-chat-conversations [data-conversation][aria-pressed="true"]')
        first_id=await selected.get_attribute('data-conversation')
        assert await page.locator('#agent-chat-input').evaluate('(el)=>el===document.activeElement')
        await page.locator('#agent-chat-conversations .project-list__btn[data-project-id="comparison"]').hover()
        await page.locator('#agent-chat-conversations [data-tree-new-chat="comparison"]').click()
        await page.wait_for_function("id=>document.querySelector('#agent-chat-conversations [data-conversation][aria-pressed=true]')?.dataset.conversation!==id",arg=first_id)
        assert await selected.get_attribute('data-conversation') != first_id
        await page.locator('#btn-new-project').click()
        await page.locator('#create-project-modal:not(.hidden)').wait_for()
        assert await page.locator('#create-project-title').inner_text() == 'Создать дерево исследований'
        assert not errors,errors
        print('Full application: global ACP chat, reload, drag to project/card and back, history and continued turn passed',flush=True)
        await browser.close()
def check():
    with tempfile.TemporaryDirectory(prefix='researcheros-full-ui-') as d:
        t=Path(d)
        os.environ['KOI_DATA_DIR']=str(t/'runtime')
        os.environ['KOI_DESKTOP_CONFIG_DIR']=str(t/'config')
        os.environ['KOI_WORKSPACE']=str(t)
        os.environ['KOI_SCAN_ROOTS']=str(t)
        code=next(n.value for n in ast.parse((ROOT/'tests/test_chat_conversations.py').read_text()).body if isinstance(n,ast.Assign) and any(isinstance(x,ast.Name) and x.id=='FAKE_AGENT' for x in n.targets))
        script=t/'fake_agent.py';script.write_text(ast.literal_eval(code).replace('mode = msg["params"]["prompt"][0]["text"]', 'mode = msg["params"]["prompt"][0]["text"]\n        if "Проверка остановки" in mode: mode = "cancel"'))
        os.environ['KOI_ACP_AGENTS']=json.dumps({'test':[sys.executable,str(script)]})
        from koi.adapters import project_mount as pm
        pm.ENGINE_ROOT=t/'engine';pm.ENGINE_ROOT.mkdir()
        from koi.adapters.desktop_workspace import set_workspace_root
        set_workspace_root(t)
        from koi.adapters.workspace import reset_workspace_cache
        reset_workspace_cache()
        research=t/'demo/koi-structure';research.mkdir(parents=True)
        (research/'project.md').write_text('---\nid: demo\ntitle: Проверка чатов\n---\n\n# problem: p\n\nПроверка чатов\n')
        (research/'research.json').write_text('{"version":1,"questions":[]}')
        pm.rescan_projects()
        from koi.adapters.repository import load_project, save_project
        from koi.core.models import Node, NodeType, KanbanBoard, KanbanColumn, ExperimentCard
        fixture=load_project('demo',sync_reports=False)
        fixture.nodes.append(Node(id='method',project_id='demo',parent_id='p',node_type=NodeType.METHOD,title='Проверка чатов'))
        fixture.boards.append(KanbanBoard(id='board',owner_node_id='method',columns=[KanbanColumn(id='backlog',title='Backlog',order=0)],cards=[ExperimentCard(id='card',board_id='board',column_id='backlog',title='Проверка чатов',tags=['harness','td'])]))
        save_project(fixture)
        import yaml
        source=(research/'project.md').read_text().split('---',2)
        meta=yaml.safe_load(source[1]);meta['programs']=[{'id':'agents','title':'Исследования агентов'}]
        (research/'project.md').write_text('---\n'+yaml.safe_dump(meta,allow_unicode=True)+'---'+source[2])
        extra=t/'comparison/koi-structure';extra.mkdir(parents=True)
        (extra/'project.md').write_text('---\nid: comparison\ntitle: Языковые и зрительные модели плохо планируют в новых средах\nprograms:\n- id: agents\n  title: Исследования агентов\n---\n\n# problem: comparison-root\n\nСравнение результатов\n')
        (extra/'research.json').write_text('{"version":1,"questions":[]}')
        pm.rescan_projects()
        from koi.agent_chat import conversations
        conversations.create('demo',title='Проверка чатов')
        from koi.desktop.server import DesktopServer
        server=DesktopServer()
        try: asyncio.run(smoke(server.start()))
        finally: server.stop()

if __name__ == '__main__':
    check()
