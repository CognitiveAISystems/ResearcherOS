"""Card-chat links navigate from the main screen and remain usable after reload."""
from pathlib import Path
import asyncio
from urllib.parse import parse_qs, urlparse

from playwright.async_api import async_playwright
import test_chat_conversations_e2e as fixture


async def smoke(url):
    from koi.agent_chat import conversations
    from koi.adapters import agent_chat_queue as queue
    from koi.adapters.repository import load_project, save_project
    from koi.core.models import Node, NodeType

    other = load_project('comparison', sync_reports=False)
    other.nodes.append(Node(id='other-method', project_id='comparison', parent_id='comparison-root', node_type=NodeType.METHOD, title='Другая проверка'))
    board = load_project('demo', sync_reports=False).boards[0].model_copy(deep=True)
    board.owner_node_id = 'other-method'
    board.cards[0].title = 'Другая карточка'
    other.boards.append(board)
    save_project(other)

    card_chat = conversations.create('demo', 'board', 'card', title='Обсуждение карточки')
    item = queue.enqueue_question('demo', 'Что показала проверка?', board_id='board', card_id='card', conversation_id=card_chat['id'])
    queue.submit_answer(item['id'], 'Проверка завершена. Подробности сохранены в карточке.')
    general = conversations.create(title='Общий вопрос')
    question = queue.enqueue_question(None, 'Общий вопрос', conversation_id=general['id'])
    queue.submit_answer(question['id'], 'Ответ без привязки к карточке.')
    output = Path(__file__).resolve().parents[1] / '.run/ui-screenshots/chat-card-link'
    output.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={'width':1440, 'height':900})
        page.set_default_timeout(15000)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.route('https://**/*', lambda route: route.abort())
        await page.goto(url+'?desktop=1', wait_until='networkidle')
        await page.locator('.research-program[data-focus-key=program-global]').click()
        await page.locator(f'.research-chat-entries [data-conversation="{general["id"]}"]').click()
        await page.wait_for_function('document.querySelector("#agent-chat-log")?.textContent.includes("Ответ без привязки")')
        assert await page.locator('#agent-chat-log [data-chat-card-link]').count() == 0
        await page.locator('.lab-project-frame[data-project-id=demo]').focus()
        await page.keyboard.press('Enter')
        await page.locator('.research-program[data-focus-key=program-agents]').click()
        await page.locator(f'.research-chat-entries [data-conversation="{card_chat["id"]}"]').click()
        link = page.locator('#agent-chat-log [data-chat-card-link]')
        await link.wait_for(state='visible')
        assert await link.inner_text() == 'Открыть карточку'
        href = await link.get_attribute('href')
        assert parse_qs(urlparse(href).query) == {'project':['demo'], 'board':['board'], 'card':['card'], 'desktop':['1']}
        assert (await link.bounding_box())['height'] >= 24
        for theme in ('light','dark'):
            await page.evaluate('theme=>document.documentElement.dataset.theme=theme', theme)
            await page.screenshot(path=str(output/f'{theme}.png'))

        # A changed map selection must not change the message's card target.
        await page.locator('.lab-project-frame[data-project-id=comparison]').focus()
        await page.keyboard.press('Enter')
        await page.locator('.lab-project-frame[data-project-id=comparison][aria-pressed=true]').wait_for()
        await link.press('Enter')
        await page.locator('#card-report-modal:not(.hidden)').wait_for()
        assert await page.locator('#card-report-card-title').inner_text() == 'Проверка чатов'
        await page.wait_for_function('document.getElementById("card-report-card-title")===document.activeElement')
        await page.keyboard.press('Escape')
        await page.locator('#card-report-modal').wait_for(state='hidden')
        await page.locator('#kanban-modal:not(.hidden)').wait_for()
        assert await page.locator('#kanban-board [data-card-id=card] .card-title-display').inner_text() == 'Проверка чатов'
        await page.wait_for_function('document.activeElement?.matches("#kanban-board [data-card-id=card] .card-expand-report")')
        await page.screenshot(path=str(output/'kanban-return.png'))
        await page.locator('#kanban-modal .modal-close').click()
        await page.locator('#kanban-modal').wait_for(state='hidden')
        await link.wait_for(state='visible')

        async def slow_report(route):
            await asyncio.sleep(.5)
            await route.continue_()

        await page.route('**/api/projects/demo/boards/board/cards/card/report', slow_report)
        await link.click()
        await page.locator('#card-report-modal:not(.hidden)').wait_for()
        await page.keyboard.press('Escape')
        await page.wait_for_function('document.activeElement?.matches("#kanban-board [data-card-id=card] .card-expand-report")')
        await page.wait_for_timeout(800)
        assert await page.locator('#card-report-modal').is_hidden()
        assert await page.locator('#kanban-modal').is_visible()
        assert await page.locator('#kanban-board [data-card-id=card] .card-expand-report').evaluate('el=>el===document.activeElement')
        await page.locator('#kanban-modal .modal-close').click()
        await page.locator('#kanban-modal').wait_for(state='hidden')
        await page.unroute('**/api/projects/demo/boards/board/cards/card/report', slow_report)

        # Moving the chat preserves the originating card on historical messages.
        response = await page.request.patch(url+f'api/agent-conversations/{card_chat["id"]}', data={'project_id':None})
        assert response.ok
        await page.wait_for_timeout(1700)
        assert await link.get_attribute('href') == href
        await link.click()
        await page.locator('#card-report-modal:not(.hidden)').wait_for()
        await page.keyboard.press('Escape')
        await page.locator('#kanban-modal:not(.hidden)').wait_for()
        await page.locator('#kanban-modal .modal-close').click()

        copied = await browser.new_page()
        copied.on('pageerror', lambda error: errors.append(str(error)))
        await copied.goto(url+href, wait_until='networkidle')
        await copied.locator('#card-report-modal:not(.hidden)').wait_for()
        assert await copied.locator('#card-report-card-title').inner_text() == 'Проверка чатов'
        await copied.reload(wait_until='networkidle')
        await copied.locator('#card-report-modal:not(.hidden)').wait_for()
        await copied.keyboard.press('Escape')
        await copied.locator('#kanban-modal:not(.hidden)').wait_for()
        assert await copied.locator('#kanban-board [data-card-id=card] .card-title-display').inner_text() == 'Проверка чатов'
        await copied.close()

        # A deleted card must not open a similarly identified card in another tree.
        response = await page.request.delete(url+'api/projects/demo/boards/board/cards/card')
        assert response.ok
        missing = await browser.new_page()
        await missing.goto(url+href, wait_until='networkidle')
        await missing.wait_for_function('document.body.textContent.includes("Не удалось открыть карточку.")')
        assert await missing.locator('#card-report-modal').is_hidden()
        await missing.close()
        assert not errors, errors
        await browser.close()
    print('PASS: card link, underlying kanban, keyboard/focus, cross-tree selection, moved-chat history, copied link/reload, deleted card, both themes')


if __name__ == '__main__':
    fixture.smoke = smoke
    fixture.check()
