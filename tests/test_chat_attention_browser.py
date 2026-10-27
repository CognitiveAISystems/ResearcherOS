"""Real HTTP/UI: working/unread indicators, visible children, read receipts and motion."""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
import test_chat_conversations_e2e as fixture


async def smoke(url):
    from koi.agent_chat import conversations as chats
    from koi.adapters import agent_chat_queue as queue
    chat = chats.create('demo', title='Проверка новых ответов')
    async def wait_read():
        for _ in range(100):
            if not chats.find(chat['id'])['unread']:
                return
            await asyncio.sleep(.1)
        raise AssertionError('Visible active reply was not acknowledged')
    for index in range(16):
        chats.create('demo', title=f'Предыдущее обсуждение {index}')
    old = queue.enqueue_question('demo', 'История', conversation_id=chat['id'])
    queue.submit_answer(old['id'], 'Предыдущий результат проверки.\n\n' * 100)
    chats.mark_read(chat['id'], old['id'])
    work = queue.enqueue_question('demo', 'Новая проверка', conversation_id=chat['id'])
    queue.mark_processing(work['id'])
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={'width':1440, 'height':900})
        page = await context.new_page()
        page.set_default_timeout(12000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.route('https://**/*', lambda route: route.abort())
        await page.goto(url + '?desktop=1', wait_until='networkidle')
        await page.locator('.lab-project-frame[data-project-id=demo]').focus()
        await page.keyboard.press('Enter')
        section = page.locator('.research-chat-section[data-section-id=demo]')
        toggle = section.locator('.research-chat-section-toggle')
        entry = page.locator(f'.research-chat-entries [data-conversation="{chat["id"]}"]')
        program = page.locator('.research-program[data-focus-key=program-agents]')
        all_program = page.locator('.research-program[data-focus-key=program-all]')
        await entry.wait_for(state='visible')
        assert await entry.get_attribute('class') and 'has-activity' in await entry.get_attribute('class')
        dot = entry.locator('.chat-status-dot')
        assert await dot.is_visible()
        assert await dot.evaluate("el=>getComputedStyle(el).animationName") == 'none'
        assert 'has-activity' not in (await program.get_attribute('class'))
        assert 'has-activity' not in (await all_program.get_attribute('class'))
        await toggle.click()
        await page.wait_for_function("document.querySelector('[data-focus-key=program-agents]').classList.contains('has-activity')")
        assert 'has-activity' in await all_program.get_attribute('class')
        await toggle.click()
        await entry.wait_for(state='visible')
        await page.wait_for_function("!document.querySelector('[data-focus-key=program-agents]').classList.contains('has-activity')")
        search = page.locator('.research-chat-search input')
        await search.fill('Нет такого чата')
        await page.wait_for_function("document.querySelector('[data-focus-key=program-agents]').classList.contains('has-activity')")
        await search.fill('')
        await toggle.dblclick()
        entries = page.locator('.research-chat-entries')
        await entries.evaluate('el=>el.scrollTop=el.scrollHeight')
        await page.wait_for_function("document.querySelector('[data-focus-key=program-agents]').classList.contains('has-activity')")
        await entries.evaluate('el=>el.scrollTop=0')
        await page.wait_for_function("!document.querySelector('[data-focus-key=program-agents]').classList.contains('has-activity')")
        await toggle.click()
        await toggle.click()
        queue.submit_answer(work['id'], 'Проверка завершена. Получен новый результат.')
        await page.wait_for_function("document.querySelector('.research-chat-entries .conversation-entry.has-unread')")
        assert 'has-activity' not in await entry.get_attribute('class')
        assert await dot.evaluate("el=>getComputedStyle(el).animationName") == 'chat-reply-pulse'
        assert 'has-unread' not in await program.get_attribute('class')
        await page.wait_for_timeout(1200)
        assert chats.find(chat['id'])['unread'], 'Seeing the list must not mark a reply as read'
        output = Path(__file__).resolve().parents[1] / '.run/ui-screenshots/chat-attention'
        output.mkdir(parents=True, exist_ok=True)
        for theme in ('light', 'dark'):
            await page.evaluate('theme=>document.documentElement.dataset.theme=theme', theme)
            await page.wait_for_timeout(300)
            await page.screenshot(path=str(output / f'{theme}.png'))
        await page.emulate_media(reduced_motion='reduce')
        assert await dot.evaluate("el=>getComputedStyle(el).animationName") == 'none'
        assert await dot.is_visible() and chats.find(chat['id'])['unread']
        await page.emulate_media(reduced_motion='no-preference')
        await page.locator(f'[data-chat-menu="{chat["id"]}"]').click()
        await page.get_by_role('button', name='Отключить мигание', exact=True).click()
        assert await dot.evaluate("el=>getComputedStyle(el).animationName") == 'none'
        await page.reload(wait_until='networkidle')
        assert await page.locator('html').get_attribute('data-chat-blink') == 'off'
        assert chats.find(chat['id'])['unread']
        await page.locator('.lab-project-frame[data-project-id=demo]').focus()
        await page.keyboard.press('Enter')
        if await toggle.get_attribute('aria-expanded') == 'false':
            await toggle.click()
        await entry.click()
        await wait_read()
        assert not chats.find(chat['id'])['unread']
        log = page.locator('#agent-chat-log')
        await log.evaluate('el=>el.scrollTop=0')
        next_item = queue.enqueue_question('demo', 'Ещё одна проверка', conversation_id=chat['id'])
        queue.submit_answer(next_item['id'], 'Ещё один ответ ниже истории.')
        jump = page.locator('#agent-chat-controls .conversation-new-reply')
        await jump.wait_for(state='visible')
        await page.wait_for_timeout(1200)
        assert chats.find(chat['id'])['unread'], 'An answer below the viewport must stay unread'
        assert await log.evaluate('el=>el.scrollTop') == 0
        assert 'has-unread' not in await program.get_attribute('class')
        await jump.focus()
        await page.keyboard.press('Enter')
        await wait_read()
        assert not chats.find(chat['id'])['unread']
        # Headless Chromium treats tabs as focused; simulate the OS focus contract.
        await page.evaluate("""() => {
          window.originalAttentionFocus = document.hasFocus.bind(document);
          document.hasFocus = () => false;
          window.dispatchEvent(new Event('blur'));
        }""")
        last = queue.enqueue_question('demo', 'Фоновая проверка', conversation_id=chat['id'])
        queue.submit_answer(last['id'], 'Ответ в неактивном окне.')
        await page.wait_for_function("document.querySelector('#agent-chat-controls .conversation-new-reply')")
        await page.wait_for_timeout(1200)
        assert chats.find(chat['id'])['unread'], 'An inactive window must not consume a reply'
        await page.evaluate("() => { document.hasFocus = window.originalAttentionFocus; window.dispatchEvent(new Event('focus')); }")
        await wait_read()
        assert not chats.find(chat['id'])['unread']
        assert not errors, errors
        await browser.close()
        print('PASS: working/unread, no duplicate parent dots, collapse/search, read viewport/focus/dwell, persistence, reduced motion, pause and keyboard jump')


if __name__ == '__main__':
    fixture.smoke = smoke
    fixture.check()
