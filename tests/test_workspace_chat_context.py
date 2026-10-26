"""One persistent chat follows the visible method/card without losing drafts."""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
import test_chat_conversations_e2e as fixture

async def smoke(url):
    from koi.agent_chat import runner
    from koi.adapters import agent_backends
    from api.routers import agents
    def catalog(): return [{'id':'codex','label':'Codex','available':True}]
    agent_backends.cli_agents = catalog
    agents.cli_agents = catalog
    runner.cli_agents = catalog
    runner._run_local_agent = lambda *args, **kwargs: ('Ответ тестового CLI', 'codex')
    async with async_playwright() as p:
        browser=await p.chromium.launch()
        page=await browser.new_page(viewport={'width':1440,'height':900})
        errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        await page.route('https://**/*',lambda route:route.abort())
        await page.goto(url+'?desktop=1',wait_until='networkidle')
        out=fixture.ROOT/'.run/ui-screenshots/workspace-context';out.mkdir(parents=True,exist_ok=True)
        assert not await page.locator('.topbar').is_visible()
        assert await page.locator('#btn-rq-bell').is_visible()
        assert await page.locator('#agent-chat-panel .conversation-rail #btn-theme').is_visible()
        assert (await page.locator('#workspace').bounding_box())['y'] == 0
        await page.locator('#btn-rq-bell').click()
        await page.locator('#rq-bell-panel').wait_for(state='visible')
        await page.evaluate("fetch('/api/settings/agent-chat',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({agent_chat_mode:'local'})})")
        method=page.locator('.node-wrap[data-project-id="demo"][data-node-id="method"] .node-kanban-below')
        await method.click(force=True)
        await page.locator('#kanban-modal:not(.hidden)').wait_for()
        assert not await page.locator('#btn-rq-bell').is_visible()
        assert not await page.locator('#rq-bell-panel').is_visible()
        context=page.locator('.conversation-context-filter')
        await page.wait_for_function("document.querySelector('.conversation-context-filter')?.textContent.includes('Чаты метода')")
        filters=page.locator('#kanban-filters-toggle')
        await filters.click()
        popup=page.locator('#kanban-board-filters:popover-open')
        await popup.wait_for()
        await page.locator('#kanban-date-filter [data-window="7d"]').click()
        assert await page.locator('#kanban-filter-count').inner_text()=='1'
        await page.locator('#kanban-tag-filter [data-tag="harness"]').click()
        assert await page.locator('#kanban-filter-count').inner_text()=='2'
        assert await page.locator('#kanban-tag-filter [data-tag="harness"]').evaluate('(el)=>el===document.activeElement')
        await page.screenshot(path=str(out/'filters-light.png'))
        await page.evaluate("document.documentElement.dataset.theme='dark'")
        await page.screenshot(path=str(out/'filters-dark.png'))
        await page.keyboard.press('Escape')
        await popup.wait_for(state='hidden')
        assert await page.locator('#kanban-modal').is_visible()
        assert await filters.evaluate('(el)=>el===document.activeElement')
        await filters.click()
        assert await page.locator('#kanban-date-filter [data-window="7d"]').get_attribute('aria-pressed')=='true'
        await page.locator('#kanban-filters-clear').click()
        assert not await page.locator('#kanban-filter-count').is_visible()
        assert await page.locator('#kanban-date-filter [data-window="all"]').get_attribute('aria-pressed')=='true'
        await page.keyboard.press('Escape')
        await filters.click()
        await page.locator('#kanban-tags-settings').click()
        await page.locator('#tag-settings-dialog[open]').wait_for()
        await page.keyboard.press('Escape')
        await page.locator('#tag-settings-dialog[open]').wait_for(state='hidden')
        assert await page.locator('#kanban-modal').is_visible()
        await page.locator('#kanban-node-title-display').evaluate("el=>el.textContent='Правила в рассуждении против самостоятельного разбора и длинное название для проверки заголовка'")
        headline=page.locator('.kanban-modal-headline')
        assert (await headline.bounding_box())['height']<=48
        assert await headline.evaluate('(el)=>el.scrollWidth<=el.clientWidth+1')
        await page.evaluate("document.documentElement.style.fontSize='200%'")
        assert await headline.evaluate('(el)=>el.scrollWidth<=el.clientWidth+1')
        await page.evaluate("document.documentElement.style.fontSize=''")
        await page.locator('#kanban-details-toggle').click()
        await page.locator('#kanban-method-details:popover-open').wait_for()
        await page.keyboard.press('Escape')
        assert await page.locator('#kanban-modal').is_visible()
        await page.evaluate("document.documentElement.dataset.theme='light'")
        assert await page.locator('#agent-chat-conversations').is_visible()
        assert not await page.locator('#agent-chat-panel .conversation-content').is_visible()
        await page.screenshot(path=str(out/('default-card.png' if await page.locator('#card-report-modal').is_visible() else 'default-method.png')))
        await page.locator('#agent-chat-conversations [data-global-chat]').click()
        await page.wait_for_function("document.querySelector('#agent-chat-conversations [data-conversation][aria-pressed=true]')")
        selected=page.locator('#agent-chat-conversations [data-conversation][aria-pressed=true]')
        method_id=await selected.get_attribute('data-conversation')
        assert await selected.evaluate('(el)=>getComputedStyle(el).backgroundColor') == 'rgba(0, 0, 0, 0)'
        assert await selected.locator('..').evaluate('(el)=>getComputedStyle(el).backgroundColor') != 'rgba(0, 0, 0, 0)'
        assert await selected.locator('..').locator('[data-chat-menu]').count() == 1
        row=await page.evaluate("id=>fetch('/api/agent-conversations/'+id).then(r=>r.json())",method_id)
        assert row['conversation']['board_id']=='board' and not row['conversation'].get('card_id')
        await page.locator('#agent-chat-form [data-cli-agent]').select_option('codex')
        await page.locator('#agent-chat-input').fill('Вопрос по методу')
        await page.locator('#btn-agent-chat-send').click()
        await page.wait_for_function("document.querySelector('#agent-chat-log').textContent.includes('Ответ тестового CLI')")
        await page.locator('#agent-chat-input').fill('Черновик метода')
        await page.locator('#kanban-modal [data-card-id="card"]').hover()
        await page.locator('#kanban-modal [data-card-id="card"] .card-expand-report').click()
        await page.locator('#card-report-modal:not(.hidden)').wait_for()
        await page.wait_for_function("document.querySelector('.conversation-context-filter')?.textContent.includes('Чаты карточки')")
        assert not await page.locator('#report-interview').is_visible()
        assert not await page.locator('#report-agent-fab').is_visible()
        assert await page.locator('#agent-chat-conversations').is_visible()
        assert not await page.locator('#agent-chat-panel .conversation-content').is_visible()
        await page.screenshot(path=str(out/('default-card.png' if await page.locator('#card-report-modal').is_visible() else 'default-method.png')))
        await page.locator('#agent-chat-conversations [data-global-chat]').click()
        await page.wait_for_function("id=>document.querySelector('#agent-chat-conversations [data-conversation][aria-pressed=true]')?.dataset.conversation!==id",arg=method_id)
        card_id=await selected.get_attribute('data-conversation')
        row=await page.evaluate("id=>fetch('/api/agent-conversations/'+id).then(r=>r.json())",card_id)
        assert row['conversation']['card_id']=='card' and row['conversation']['board_id']=='board'
        await page.locator('#agent-chat-input').fill('Вопрос по карточке')
        await page.locator('#btn-agent-chat-send').click()
        await page.wait_for_function("document.querySelector('#agent-chat-log').textContent.includes('Ответ тестового CLI')")
        await page.locator('#agent-chat-input').fill('Черновик карточки')
        left=await page.locator('#agent-chat-panel').bounding_box()
        right=await page.locator('#card-report-modal').bounding_box()
        assert abs(left['x']+left['width']-right['x'])<=2,(left,right)
        out=fixture.ROOT/'.run/ui-screenshots/workspace-context';out.mkdir(parents=True,exist_ok=True)
        for theme in ('light','dark'):
            await page.evaluate('t=>document.documentElement.dataset.theme=t',theme)
            await page.screenshot(path=str(out/f'card-{theme}.png'))
        await context.click()
        await page.wait_for_function("document.querySelector('.conversation-context-filter').textContent.startsWith('Все чаты')")
        assert await page.locator('.unified-global-chats').is_visible()
        await context.click()
        await page.locator('#card-report-modal .modal-close').click()
        await page.wait_for_function("document.querySelector('.conversation-context-filter').textContent.includes('Чаты метода')")
        assert not await page.locator('#agent-chat-panel .conversation-content').is_visible()
        await page.locator(f'#agent-chat-conversations [data-conversation="{method_id}"]').click()
        assert await page.locator('#agent-chat-input').input_value()=='Черновик метода'
        await page.screenshot(path=str(out/'method.png'))
        await page.locator('#kanban-modal .modal-close').click()
        await context.wait_for(state='hidden')
        assert await page.locator('#btn-rq-bell').is_visible()
        assert not await page.locator('#rq-bell-panel').is_visible()
        await method.click(force=True)
        await page.wait_for_function("document.querySelector('.conversation-context-filter').textContent.includes('Чаты метода')")
        assert not await page.locator('#agent-chat-panel .conversation-content').is_visible()
        await page.locator(f'#agent-chat-conversations [data-conversation="{method_id}"]').click()
        assert await page.locator('#agent-chat-input').input_value()=='Черновик метода'
        await page.locator('#kanban-modal [data-card-id="card"]').hover()
        await page.locator('#kanban-modal [data-card-id="card"] .card-expand-report').click()
        await page.wait_for_function("document.querySelector('.conversation-context-filter').textContent.includes('Чаты карточки')")
        assert not await page.locator('#agent-chat-panel .conversation-content').is_visible()
        await context.click()
        assert not await page.locator('#agent-chat-panel .conversation-content').is_visible()
        await context.click()
        await page.locator(f'#agent-chat-conversations [data-conversation="{card_id}"]').click()
        assert await page.locator('#agent-chat-input').input_value()=='Черновик карточки'
        await page.locator('#card-report-modal .modal-close').click()
        await page.set_viewport_size({'width':390,'height':844})
        await filters.click()
        box=await popup.bounding_box()
        assert box['x']>=0 and box['x']+box['width']<=390
        await page.screenshot(path=str(out/'filters-mobile.png'))
        await page.keyboard.press('Escape')
        await page.set_viewport_size({'width':1440,'height':900})
        await page.locator('#kanban-modal [data-card-id="card"]').hover()
        await page.locator('#kanban-modal [data-card-id="card"] .card-expand-report').click()
        await page.wait_for_function("document.querySelector('.conversation-context-filter').textContent.includes('Чаты карточки')")
        await page.locator(f'#agent-chat-conversations [data-conversation="{card_id}"]').click()
        await page.set_viewport_size({'width':390,'height':844})
        await page.wait_for_timeout(100)
        assert await page.locator('#agent-chat-input').is_visible()
        assert await page.locator('#card-report-modal').is_visible()
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        await page.screenshot(path=str(out/'mobile.png'))
        await page.set_viewport_size({'width':1440,'height':900})
        if not await page.locator('#agent-chat-conversations').is_visible(): await page.locator('#btn-agent-chat').click()
        menu_button=page.locator(f'[data-chat-menu="{card_id}"]')
        await menu_button.locator('..').hover()
        await menu_button.click()
        await page.locator('.conversation-actions-popover:popover-open .conversation-delete-action').click()
        confirmation=page.locator('.conversation-delete-dialog[open]')
        await confirmation.wait_for()
        await page.screenshot(path=str(out/'delete-confirmation.png'))
        await confirmation.locator('[data-dismiss]').click()
        assert await page.locator(f'#agent-chat-conversations [data-conversation="{card_id}"]').count()==1
        await menu_button.locator('..').hover();await menu_button.click()
        await page.locator('.conversation-actions-popover:popover-open .conversation-delete-action').click()
        await confirmation.locator('[type=submit]').click()
        await confirmation.wait_for(state='detached')
        await page.wait_for_function("id=>!document.querySelector('#agent-chat-conversations [data-conversation=\"'+id+'\"]')",arg=card_id)
        assert await page.evaluate("id=>fetch('/api/agent-conversations/'+id).then(r=>r.status)",card_id)==404
        assert await page.locator('#agent-chat-conversations').evaluate('(el)=>el.contains(document.activeElement)')
        remaining=await page.evaluate("id=>fetch('/api/agent-conversations/'+id).then(r=>r.json())",method_id)
        assert remaining['items'] and remaining['conversation']['id']==method_id
        await page.locator('#agent-chat-conversations [data-global-chat]').click()
        await page.wait_for_function("document.querySelector('#agent-chat-conversations [data-conversation][aria-pressed=true]')")
        assert await selected.get_attribute('data-conversation') != card_id
        assert not errors,errors
        await browser.close()
        print('PASS: shared chat, method/card scopes, all-chat filter, restored drafts and responsive workspace')

if __name__=='__main__':
    fixture.smoke=smoke
    fixture.check()
