"""Run directly: full Chats/Light UI with an offline, cancellable CLI process."""
import sys
from pathlib import Path

import pytest
from playwright.async_api import async_playwright
import test_chat_conversations_e2e as fixture


async def smoke(url):
    from test_agent_chat_streaming import SCRIPT
    from koi.adapters import agent_backends, agent_chat_queue as queue
    from koi.agent_chat import runner, live
    from koi.literature import cursor_agent_terminal

    workdir = runner._ws.agent_cwd()
    script = Path(workdir) / "cursor"
    script.write_text(f"#!{sys.executable}\n" + SCRIPT)
    script.chmod(0o755)
    screenshots = fixture.ROOT / ".run/ui-screenshots/chat-stop"
    screenshots.mkdir(parents=True, exist_ok=True)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(runner, "find_agent_bin", lambda: script)
        patch.setattr(cursor_agent_terminal, "find_agent_bin", lambda: script)
        patch.setattr(agent_backends, "_codex_bin", lambda: None)
        patch.setattr(agent_backends, "_claude_bin", lambda: None)
        patch.setattr(runner, "_sdk_prompt", lambda iid: "finish" if queue.find_item(iid)['question'] == 'Заверши проверку' else "wait")
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page(viewport={"width": 1440, "height": 900})
            page.set_default_timeout(12000)
            errors = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            await page.route("https://**/*", lambda route: route.abort())
            try:
                for variant in ("chats", "light"):
                    response = await page.request.put(url + "api/settings/agent-chat", data={"ui_variant": variant, "agent_chat_mode": "local"})
                    assert response.ok
                    await page.goto(url + "?desktop=1&project=demo", wait_until="networkidle")
                    await page.locator(".lab-project-frame").first.wait_for()
                    if variant == "chats":
                        await page.locator(".research-global-compose").click()
                    else:
                        await page.locator("#btn-agent-chat").click()

                    async def check_turn(prefix, name):
                        form = page.locator('#' + prefix + '-form')
                        field = form.locator('textarea')
                        button = form.locator('.agent-chat-send')
                        log = page.locator('#' + prefix + '-log')
                        await page.wait_for_function("id => document.activeElement === document.getElementById(id)", arg=prefix + '-input')
                        await field.fill('Проверь файлы')
                        await button.click()
                        await page.wait_for_function("id => document.getElementById(id).textContent.includes('Проверяю файлы.')", arg=prefix + '-log')
                        assert await button.get_attribute('aria-label') == 'Остановить'
                        assert await button.is_enabled()
                        assert await log.locator('.agent-chat-typing').count() == 1
                        assert await log.locator('.agent-chat-typing').inner_text() == 'Агент отвечает…'
                        await field.fill('Черновик следующего сообщения')
                        count = len(queue._load())
                        await field.press('Control+Enter')
                        await page.wait_for_timeout(100)
                        assert len(queue._load()) == count
                        assert await field.input_value() == 'Черновик следующего сообщения'
                        for theme in ('dark', 'light'):
                            await page.evaluate('theme => document.documentElement.dataset.theme = theme', theme)
                            await page.screenshot(path=str(screenshots / f'{name}-{theme}.png'))
                        await button.focus()
                        await page.keyboard.press('Space')
                        await page.wait_for_function("id => document.getElementById(id).textContent.includes('Остановлено пользователем.')", arg=prefix + '-log')
                        assert await field.input_value() == 'Черновик следующего сообщения'
                        assert await button.get_attribute('data-action') == 'send'
                        assert await log.locator('.agent-chat-typing').count() == 0
                        assert 'Проверяю файлы.' in await log.inner_text()
                        assert not any(i['status'] != 'answered' for i in queue._load())
                        # A completed turn must also clear the typing indicator.
                        await field.fill('Заверши проверку')
                        await button.click()
                        await log.locator('.agent-chat-typing').wait_for()
                        (Path(workdir) / 'finish').touch()
                        await page.wait_for_function("selector => document.querySelector(selector).dataset.action === 'send'", arg='#' + prefix + '-form .agent-chat-send')
                        assert await log.locator('.agent-chat-typing').count() == 0
                        assert 'Готово.' in await log.inner_text()
                        (Path(workdir) / 'finish').unlink()

                    await check_turn('agent-chat', variant + '-project')
                    if variant == 'light':
                        await page.locator('#btn-agent-chat').click()
                        await page.locator('.map-node.method').click()
                        await page.locator('#kanban-board [data-card-id=card] .card-expand-report').focus()
                        await page.keyboard.press('Enter')
                        await page.locator('#card-report-modal:not(.hidden)').wait_for()
                        await page.locator('#report-agent-fab').click()
                        await check_turn('report-interview', 'light-card')
                assert not errors, errors
            finally:
                for item in queue._load():
                    if item['status'] != 'answered':
                        live.request_cancel(item['id'])
                await browser.close()
    print('PASS: Chats and Light show typing after progress, clear it on stop/completion, preserve drafts and allow the next turn')


if __name__ == '__main__':
    fixture.smoke = smoke
    fixture.check()
