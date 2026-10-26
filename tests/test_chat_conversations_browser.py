"""Run directly with .venv/bin/python; actual DOM/CSS and mocked agent responses."""
import asyncio
import mimetypes
import re
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".run/ui-screenshots/conversations"

async def check():
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        async def serve(route):
            from urllib.parse import urlparse
            name = urlparse(route.request.url).path.lstrip("/") or "index.html"
            path = ROOT / "web" / name
            if not path.is_file():
                await route.abort(); return
            body = path.read_bytes()
            if name == "index.html":
                body = re.sub(rb"<script\b[^>]*>.*?</script>", b"", body, flags=re.S)
            await route.fulfill(body=body, content_type=mimetypes.guess_type(name)[0] or "text/javascript")
        await page.route("http://chat.test/**", serve)
        await page.goto("http://chat.test/", wait_until="domcontentloaded")
        await page.evaluate("""async () => {
          const {ChatConversations} = await import('./chat-conversations.js');
          const {attachReportChatResize} = await import('./report-chat-resize.js');
          attachReportChatResize(document.getElementById('report-interview'));
          const rows = [
            {id:'card-a',project_id:'a',board_id:'board',card_id:'card',title:'Протокол эксперимента',created_at:'1'},
            {id:'project-b',project_id:'b',title:'Результаты второго проекта',created_at:'2'},
            {id:'card-b',project_id:'a',board_id:'board',card_id:'card',title:'Разбор ошибок обучения',created_at:'3',pending:true}
          ];
          window.permissions = []; window.cancelled = [];
          const api = {
            listConversations: async scope => ({items: rows.filter(r=>(!scope.project_id || r.project_id===scope.project_id) && (!scope.card_id || r.card_id===scope.card_id && r.board_id===scope.board_id))}),
            createConversation: async scope => {const item={id:'new-'+rows.length,title:'Новый чат',...scope}; rows.unshift(item); return {item};},
            getConversation: async id => ({conversation: rows.find(r=>r.id===id),items:[{id:'message-'+id}],live:id==='card-a'?{item_id:'message-card-a',text:'Изучаю постановку',permission:{id:'perm',title:'Изменить файл отчёта?',tool_call:{rawInput:{path:'report.md'}},options:[{optionId:'allow',name:'Разрешить один раз'},{optionId:'deny',name:'Запретить'}]}}:null}),
            cancelConversation: async id => window.cancelled.push(id),
            decideConversationPermission: async (id,pid,option) => window.permissions.push([id,pid,option])
          };
          const make = (prefix, main) => {
            const scope = main ? ()=>({project_id:'a'}) : ()=>({project_id:'a',board_id:'board',card_id:'card'});
            const controller = new ChatConversations({api, main, scope,
              sidebar:document.getElementById(prefix+'-conversations'), controls:document.getElementById(prefix+'-controls'), input:document.getElementById(prefix+'-input'),
              projectName:id=>id==='a'?'Обучение агента':'Другой проект',
              changed:async()=>{await controller.refresh();}});
            return controller;
          };
          window.main=make('agent-chat',true); window.card=make('report-interview',false);
          document.getElementById('agent-chat-panel').classList.remove('hidden');
          document.getElementById('workspace').classList.add('is-chat-open');
          document.getElementById('agent-chat-title').textContent='Чаты';
          await main.refresh(); await card.refresh();
        }""")
        assert await page.locator('#agent-chat-conversations [data-conversation]').count() == 3
        boxes=await page.evaluate("""() => {
          const panel=document.querySelector('#agent-chat-panel');
          return ['.conversation-content','.conversation-sidebar','.conversation-rail'].map(s=>{const r=panel.querySelector(s).getBoundingClientRect();return {x:r.x,right:r.right};});
        }""")
        assert boxes[0]['right'] <= boxes[1]['x']+1 and boxes[1]['right'] <= boxes[2]['x']+1,boxes
        assert await page.locator('#agent-chat-panel [data-current-project]').inner_text() == ''
        assert await page.locator('#agent-chat-panel [role="tab"]').count() == 0
        assert 'Outfit' in await page.locator('#agent-chat-panel').evaluate('(el)=>getComputedStyle(el).fontFamily')
        await page.locator('#agent-chat-panel [data-current-project]').click()
        await page.wait_for_function("main.rows.length === 2")
        await page.locator('#agent-chat-panel [data-current-project]').click()
        await page.wait_for_function("main.rows.length === 3")
        resize=page.locator('#agent-chat-panel .conversation-list-resize')
        sidebar=page.locator('#agent-chat-conversations')
        before=await sidebar.bounding_box()
        handle=await resize.bounding_box()
        await page.mouse.move(handle['x']+4,handle['y']+180)
        await page.mouse.down()
        await page.mouse.move(handle['x']-96,handle['y']+180)
        await page.mouse.up()
        after=await sidebar.bounding_box()
        assert after['width'] >= before['width']+95,(before,after)
        assert int(await resize.get_attribute('aria-valuenow')) == round(after['width'])
        await resize.focus()
        await page.keyboard.press('ArrowRight')
        assert (await sidebar.bounding_box())['width'] <= after['width']-15
        await page.keyboard.press('Home')
        assert round((await sidebar.bounding_box())['width']) == 160
        await page.keyboard.press('End')
        maximum=round((await sidebar.bounding_box())['width'])
        assert maximum <= 440
        assert int(await resize.get_attribute('aria-valuenow')) == maximum
        await resize.dblclick()
        assert round((await sidebar.bounding_box())['width']) == 200
        field = page.locator('#agent-chat-input')
        await field.fill('Несохранённый вопрос')
        await page.locator('#agent-chat-conversations [data-conversation="project-b"]').click()
        await page.locator('#agent-chat-conversations [data-conversation="card-a"]').click()
        assert await field.input_value() == 'Несохранённый вопрос'
        await page.locator('#agent-chat-controls [data-permission-option="allow"]').click()
        assert await page.evaluate('permissions[0]') == ['card-a','perm','allow']
        assert await page.locator('#agent-chat-controls [data-cancel-chat]').count() == 0
        assert await page.locator('#btn-agent-chat-send').get_attribute('aria-label') == 'Остановить'
        await page.locator('#agent-chat-input').fill('Черновик следующего сообщения')
        await page.locator('#btn-agent-chat-send').click()
        assert await page.locator('#agent-chat-input').input_value() == 'Черновик следующего сообщения'
        assert await page.evaluate('cancelled[0]') == 'card-a'
        await page.locator('#agent-chat-conversations [data-new-chat]').click()
        await page.wait_for_function("main.row.id.startsWith('new-')")
        assert await page.locator('#btn-agent-chat-send').get_attribute('data-action') == 'send'
        await page.locator('#agent-chat-conversations [data-conversation="card-b"]').click()
        await page.evaluate("""() => {
          for (const select of document.querySelectorAll('[data-cli-agent]')) select.innerHTML='<option>Codex · ACP</option>';
          document.querySelector('#agent-chat-log').innerHTML='<article class="agent-chat-thread"><div class="agent-chat-q-row"><p class="agent-chat-q">Почему обучение стало менее устойчивым после изменения награды?</p></div><div class="agent-chat-reply"><p>Сначала сравним запуски при одинаковых условиях. По одному графику пока рано связывать изменение с наградой.</p><p>Проверю три вещи:</p><ul><li>Масштаб и распределение награды.</li><li>Разброс результата между запусками.</li><li>Изменения в данных и настройках обучения.</li></ul><p>Начнём с базового запуска и нового варианта с тем же начальным состоянием.</p></div><time>Сегодня, 18:24</time></article>';
        }""")
        for theme in ('dark','light'):
            await page.evaluate("theme=>document.documentElement.dataset.theme=theme",theme)
            await page.screenshot(path=str(OUT / f'main-{theme}.png'))
        await page.evaluate("""() => {
          document.getElementById('agent-chat-panel').classList.add('hidden');
          document.getElementById('card-report-modal').classList.remove('hidden');
          document.getElementById('report-interview').hidden=false;
          document.getElementById('card-report-card-title').textContent='Проверка обучения агента';
          document.getElementById('card-report-preview').innerHTML='<h2>Цель</h2><p>Проверить устойчивость обучения на нескольких запусках.</p><h2>Постановка эксперимента</h2><p>Сравниваем базовый метод с новым на одинаковых данных.</p>';
        }""")
        # Closing the agent must release its entire grid column, including without a TOC.
        for width in (1440, 2560):
            await page.set_viewport_size({'width':width,'height':900})
            for toc_hidden in (False, True):
                await page.locator('#report-toc').evaluate('(el,hidden)=>el.hidden=hidden',toc_hidden)
                await page.locator('#report-interview').evaluate('(el)=>el.hidden=false')
                opened=await page.locator('.report-document').bounding_box()
                chat_box=await page.locator('#report-interview').bounding_box()
                assert chat_box['x'] < opened['x']
                if not toc_hidden:
                    toc_box=await page.locator('#report-toc').bounding_box()
                    assert opened['x'] < toc_box['x']
                handle=page.locator('.report-chat-resize')
                before_width=chat_box['width']
                await handle.focus();await page.keyboard.press('ArrowRight')
                assert (await page.locator('#report-interview').bounding_box())['width'] > before_width
                await page.locator('.report-workspace').evaluate('(el)=>el.style.removeProperty("--report-chat-width")')
                await page.locator('#report-interview').evaluate('(el)=>el.hidden=true')
                closed=await page.locator('.report-document').bounding_box()
                workspace=await page.locator('.report-workspace').bounding_box()
                assert closed['width'] > opened['width']+300,(width,opened,closed)
                assert abs(closed['x']-workspace['x']) < 2
                ear=await page.locator('#report-agent-fab').bounding_box()
                panel=await page.locator('#card-report-modal .modal-panel--report').bounding_box()
                assert abs(ear['x']-panel['x']-48) < 2
                assert ear['width'] == 64 and ear['height'] == 64
                assert await page.locator('#report-agent-fab').evaluate('(el)=>getComputedStyle(el).backgroundColor') == 'rgba(0, 0, 0, 0)'
                assert abs(panel['y']+panel['height']-ear['y']-ear['height']-80) < 2
                assert await page.locator('#report-agent-fab').evaluate('(el)=>getComputedStyle(el,"::before").display') != 'none'
                assert await page.locator('#report-agent-fab').is_visible()
                for theme in ('dark','light'):
                    await page.evaluate('theme=>document.documentElement.dataset.theme=theme',theme)
                    if width == 1440 and not toc_hidden:
                        await page.screenshot(path=str(OUT / f'card-closed-{theme}.png'))
                await page.locator('#report-interview').evaluate('(el)=>el.hidden=false')
                restored=await page.locator('.report-document').bounding_box()
                assert abs(restored['width']-opened['width']) < 2
                assert not await page.locator('#report-agent-fab').is_visible()
        await page.set_viewport_size({'width':1440,'height':900})
        await page.locator('#report-toc').evaluate('(el)=>el.hidden=false')
        assert await page.locator('#report-interview-conversations [data-conversation]').count() == 2
        assert await page.locator('#report-interview .agent-chat-send').get_attribute('aria-label') == 'Остановить'
        await page.locator('#report-interview-input').fill('Черновик карточки')
        await page.locator('#report-interview .agent-chat-send').click()
        assert await page.evaluate('cancelled[1]') == 'card-a'
        assert await page.locator('#report-interview-input').input_value() == 'Черновик карточки'
        await page.locator('#report-interview-conversations [data-conversation="card-b"]').click()
        assert await page.locator('#report-interview [data-conversation-title]').inner_text() == 'Разбор ошибок обучения'
        await page.evaluate("""() => {
          document.querySelector('#report-interview-log').innerHTML=document.querySelector('#agent-chat-log').innerHTML;
          document.querySelector('#report-interview-input').value='Сравни запуски с одинаковыми настройками';
          document.activeElement.blur();
        }""")
        for theme in ('dark','light'):
            await page.evaluate("theme=>document.documentElement.dataset.theme=theme",theme)
            await page.screenshot(path=str(OUT / f'card-{theme}.png'))
        card_resize=page.locator('#report-interview .conversation-list-resize')
        await card_resize.focus()
        await page.keyboard.press('ArrowRight')
        assert round((await page.locator('#report-interview-conversations').bounding_box())['width']) == 216
        await card_resize.dblclick()
        before = await page.locator('#report-interview-conversations [data-conversation="card-b"]').evaluate('(el)=>{window.retainedRow=el;return true}')
        await page.evaluate('card.refresh()')
        assert await page.evaluate('window.retainedRow.isConnected')
        await page.locator('#report-interview-conversations [data-conversation="card-b"]').focus()
        await page.keyboard.press('Enter')
        assert await page.locator('#report-interview-input').evaluate('(el)=>el===document.activeElement')
        for width in (1440, 900, 390, 320):
            await page.set_viewport_size({'width':width,'height':900})
            if width <= 390: assert not await card_resize.is_visible()
            widths=await page.locator('#report-interview .conversation-layout').evaluate('(el)=>({client:el.clientWidth,scroll:el.scrollWidth})')
            assert widths['scroll'] <= widths['client'] + 1, (width,widths)
        toggle=page.locator('#report-interview [data-chat-navigation]')
        await toggle.click()
        assert await page.locator('#report-interview-conversations').is_visible()
        await page.keyboard.press('Escape')
        assert not await page.locator('#report-interview-conversations').is_visible()
        assert await toggle.evaluate('(el)=>el===document.activeElement')
        await toggle.click()
        await page.locator('#report-interview-conversations [data-conversation="card-b"]').click()
        assert await page.locator('#report-interview-input').is_visible()
        await page.screenshot(path=str(OUT / 'card-mobile.png'))
        await page.set_viewport_size({'width':1440,'height':900})
        await page.evaluate("document.documentElement.style.fontSize='200%'")
        assert await page.locator('#report-interview [data-chat-navigation]').is_visible()
        await page.evaluate("document.documentElement.style.fontSize='';document.documentElement.dir='rtl'")
        widths=await page.locator('#report-interview .conversation-layout').evaluate('(el)=>({client:el.clientWidth,scroll:el.scrollWidth})')
        assert widths['scroll'] <= widths['client']+1
        await page.evaluate("document.documentElement.dir='ltr'")
        import json
        pairs={}
        for theme in ('dark','light'):
            await page.evaluate("theme=>document.documentElement.dataset.theme=theme",theme)
            pairs[theme]=await page.evaluate("""() => {
              const css=getComputedStyle(document.querySelector('#report-interview'));
              const canvas=document.createElement('canvas'); canvas.width=canvas.height=1;
              const ctx=canvas.getContext('2d'); const probe=document.createElement('span'); document.querySelector('#report-interview').append(probe);
              const resolve=key=>{probe.style.color='var('+key+')';return getComputedStyle(probe).color;};
              const colors=Object.fromEntries(['--text','--muted','--surface-navigation','--surface-selected','--bg-elevated','--control-border','--action-fill','--action-text','--purple'].map(key=>{
                ctx.clearRect(0,0,1,1); ctx.fillStyle=resolve('--bg-elevated'); ctx.fillRect(0,0,1,1); ctx.fillStyle=resolve(key);ctx.fillRect(0,0,1,1);
                return [key,'#'+[...ctx.getImageData(0,0,1,1).data].slice(0,3).map(v=>v.toString(16).padStart(2,'0')).join('')];
              })); probe.remove(); return colors;
            }""")
        def luminance(h):
            rgb=[int(h[i:i+2],16)/255 for i in (1,3,5)]
            return sum(v*w for v,w in zip([v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in rgb],[.2126,.7152,.0722]))
        results={}
        for theme,colors in pairs.items():
            results[theme]={}
            for fg,bg,minimum in [('--text','--surface-selected',4.5),('--muted','--surface-navigation',4.5),('--muted','--bg-elevated',4.5),('--control-border','--bg-elevated',3),('--action-text','--action-fill',4.5),('--purple','--bg-elevated',3),('--purple','--surface-navigation',3)]:
                a,b=sorted([luminance(colors[fg]),luminance(colors[bg])]);ratio=(b+.05)/(a+.05)
                assert ratio>=minimum,(theme,fg,bg,ratio)
                results[theme][fg+' / '+bg]=round(ratio,2)
        (OUT/'contrast.json').write_text(json.dumps(results,indent=2))
        assert not errors, errors
        await browser.close()
        print('Conversation UI: scope, drafts, selection, permissions, cancellation and themes passed')

if __name__ == '__main__':
    asyncio.run(check())
