"""Run with .venv/bin/python tests/test_app_variant_browser.py (isolated data)."""
from pathlib import Path

from playwright.async_api import async_playwright
import test_chat_conversations_e2e as fixture


async def smoke(url):
    from koi.agent_chat import conversations
    from koi.adapters import agent_chat_queue

    screenshots = Path(__file__).resolve().parents[1] / ".run/ui-screenshots/app-variant"
    screenshots.mkdir(parents=True, exist_ok=True)
    initial_ids = {row["id"] for row in conversations.list_conversations()}
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(10000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.route("https://**/*", lambda route: route.abort())
        await page.goto(url + "?desktop=1&project=demo", wait_until="networkidle")
        await page.locator(".lab-project-frame").first.wait_for()
        assert await page.locator("html").get_attribute("data-app-variant") == "chats"
        assert await page.locator(".research-chat-browser").is_visible()
        assert await page.locator("#btn-app-variant").is_visible()

        # Both layouts keep keyboard access, cancel and draft preservation.
        await page.locator("#btn-app-variant").focus()
        await page.keyboard.press("Enter")
        await page.locator("#app-variant-dialog").wait_for(state="visible")
        await page.locator('input[value="light"]').check()
        await page.keyboard.press("Escape")
        assert not await page.locator("#app-variant-dialog").is_visible()
        assert await page.locator("#btn-app-variant").evaluate("el => el === document.activeElement")
        assert await page.locator("html").get_attribute("data-app-variant") == "chats"

        async with page.expect_response(lambda response: response.request.method == "POST" and response.url.endswith("/api/agent-conversations")) as created:
            await page.locator(".research-global-compose").click()
        general = (await (await created.value).json())["item"]
        question = agent_chat_queue.enqueue_question(None, "Общий вопрос", conversation_id=general["id"])
        agent_chat_queue.submit_answer(question["id"], "Общая история для двух режимов")
        await page.wait_for_function("document.querySelector('#agent-chat-log').textContent.includes('Общая история для двух режимов')")
        await page.locator("#agent-chat-input").fill("Черновик для обоих режимов")
        await page.locator("#btn-app-variant").click()
        await page.locator('input[value="light"]').check()
        await page.locator('#app-variant-dialog button[type="submit"]').click()
        await page.wait_for_function("document.documentElement.dataset.appVariant === 'light'")
        await page.locator(".lab-project-frame").first.wait_for()
        assert not await page.locator("#agent-chat-panel").is_visible()
        assert await page.locator(".research-chat-browser").count() == 0
        assert await page.locator("#btn-projects-toggle").is_visible()
        assert await page.locator("#btn-zoom-in").is_visible()
        assert await page.locator("#btn-zoom-fit-project").is_visible()
        assert await page.locator("#btn-agent-chat-welcome").is_visible()
        await page.locator("#btn-agent-chat").click()
        await page.locator("#agent-chat-panel").wait_for(state="visible")
        assert await page.locator("#agent-chat-title").inner_text() == "Агент проекта"
        assert await page.locator("#agent-chat-tab-activity").is_visible()
        await page.locator("#agent-chat-input").fill("Черновик классического интерфейса")
        await page.locator("#btn-agent-chat").click()

        for variant in ("light", "chats"):
            if variant == "chats":
                await page.locator("#btn-app-variant").click()
                await page.locator('input[value="chats"]').check()
                await page.locator('#app-variant-dialog button[type="submit"]').click()
                await page.wait_for_function("document.documentElement.dataset.appVariant === 'chats'")
                await page.locator(".lab-project-frame").first.wait_for()
                assert await page.locator("#agent-chat-input").input_value() == "Черновик для обоих режимов"
            for theme in ("dark", "light"):
                await page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
                await page.screenshot(path=str(screenshots / f"{variant}-{theme}.png"))
            await page.locator("#btn-app-variant").click()
            for theme in ("dark", "light"):
                await page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
                await page.screenshot(path=str(screenshots / f"{variant}-settings-{theme}.png"))
            for width in (320, 900, 1440):
                await page.set_viewport_size({"width": width, "height": 900})
                await page.screenshot(path=str(screenshots / f"{variant}-settings-{width}.png"))
                assert await page.locator("#app-variant-dialog").evaluate(
                    "el => { const r = el.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth && el.scrollWidth <= el.clientWidth; }")
                assert await page.locator('#app-variant-dialog button[type="submit"]').is_visible()
            await page.set_viewport_size({"width": 1440, "height": 900})
            await page.screenshot(path=str(screenshots / f"{variant}-settings.png"))
            await page.keyboard.press("Escape")

        # An unavailable settings endpoint leaves the current UI and draft intact.
        await page.route("**/api/settings/agent-chat", lambda route: route.fulfill(status=503, json={"detail": "Повторите попытку позже."}))
        await page.locator("#btn-app-variant").click()
        await page.locator('input[value="light"]').check()
        await page.locator('#app-variant-dialog button[type="submit"]').click()
        await page.wait_for_function("document.querySelector('#app-variant-dialog [role=status]').textContent.includes('Не удалось переключить режим')")
        assert await page.locator("html").get_attribute("data-app-variant") == "chats"
        assert await page.locator("#agent-chat-input").input_value() == "Черновик для обоих режимов"
        await page.locator('#app-variant-dialog [data-cancel]').click()
        await page.unroute("**/api/settings/agent-chat")

        # The same report and kanban remain available in both modes.
        for variant in ("light", "chats"):
            await page.request.put(url + "api/settings/agent-chat", data={"ui_variant": variant})
            await page.goto(url + "?desktop=1&project=demo", wait_until="networkidle")
            await page.locator('.map-node.method').click()
            report_button = page.locator('#kanban-board [data-card-id=card] .card-expand-report')
            await report_button.focus()
            await page.keyboard.press("Enter")
            await page.locator("#card-report-modal:not(.hidden)").wait_for()
            assert await page.locator("#card-report-card-title").inner_text() == "Проверка чатов"
            await page.locator("#report-agent-fab" if variant == "light" else "[data-research-create]").click()
            chat_input = "#agent-chat-input" if variant == "chats" else "#report-interview-input"
            await page.wait_for_function("id => document.activeElement === document.querySelector(id)", arg=chat_input)
            field = page.locator(chat_input)
            await field.fill("/")
            menu = page.locator(".chat-skills:popover-open")
            await menu.wait_for(state="visible")
            assert await menu.locator("[role=option] strong").all_text_contents() == ["grill-me", "prose", "question", "run"]
            await field.press("ArrowDown")
            await field.press("Enter")
            assert await field.input_value() == "/prose "
            await field.fill("/run")
            await menu.locator("[role=option]").click()
            assert await field.input_value() == "/run "
            await field.fill("/nothing")
            assert await menu.locator(".chat-skills-empty").inner_text() == "Скиллы не найдены"
            await field.press("Escape")
            assert await menu.count() == 0
            assert await page.locator("#card-report-modal").is_visible()
            for theme in ("dark", "light"):
                await page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
                await field.fill("/")
                await page.screenshot(path=str(screenshots / f"{variant}-skills-{theme}.png"))
                await field.press("Escape")
            await field.fill("")
            await page.screenshot(path=str(screenshots / f"{variant}-report-chat.png"))
            await page.locator('#card-report-modal > .modal-panel > .modal-close').click()
            await page.locator("#card-report-modal").wait_for(state="hidden")
            assert await page.locator("#kanban-modal").is_visible()
            await page.keyboard.press("Escape")

        # Persistence is server-side, not tied to browser storage or a desktop port.
        second = await browser.new_context()
        other = await second.new_page()
        await other.route("https://**/*", lambda route: route.abort())
        await other.goto(url + "?desktop=1", wait_until="networkidle")
        assert await other.locator("html").get_attribute("data-app-variant") == "chats"
        await second.close()
        await page.reload(wait_until="networkidle")
        assert await page.locator("html").get_attribute("data-app-variant") == "chats"
        assert initial_ids <= {row["id"] for row in conversations.list_conversations()}
        assert not errors, errors
        await browser.close()
    print("PASS: main's Light controls, settings, keyboard/cancel, Chats → Light → Chats, preserved history/drafts, kanban/reports and responsive dialog")


if __name__ == "__main__":
    fixture.smoke = smoke
    fixture.check()
