"""Real API + UI regression, using the isolated desktop fixture."""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
import test_chat_conversations_e2e as fixture


async def smoke(url):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.route("https://**/*", lambda route: route.abort())
        await page.goto(url + "?desktop=1", wait_until="networkidle")
        page.set_default_timeout(10000)
        await page.locator("#global-glossary-settings").click()
        await page.locator("#glossary-scope:enabled").wait_for()
        assert await page.locator("#glossary-scope").input_value() == "global"
        await page.keyboard.press("Escape")
        await page.locator("#glossary-dialog").wait_for(state="detached")
        await page.locator("#global-glossary-settings").click()
        await page.locator("#glossary-scope:enabled").wait_for()
        await page.locator("#glossary-text").fill("пайплайн > процесс\nпостановка — описание эксперимента")
        await page.locator('#glossary-dialog [type="submit"]').click()
        await page.locator("#glossary-dialog").wait_for(state="detached")
        data = await page.evaluate("fetch('/api/glossary').then(r=>r.json())")
        assert data["effective"][0]["replacement"] == "процесс"
        assert Path(data["global"]["path"]).read_text() == data["global"]["text"]

        method = page.locator('.node-wrap[data-project-id="demo"][data-node-id="method"] .node-kanban-below')
        await method.click(force=True)
        await page.locator("#kanban-filters-toggle").click()
        await page.locator("#kanban-glossary-settings").click()
        await page.locator("#glossary-scope:enabled").wait_for()
        assert await page.locator("#glossary-scope").input_value() == "tree"
        assert "пайплайн" in await page.locator("[data-inherited] pre").text_content()
        await page.locator("#glossary-scope").select_option("global")
        assert "пайплайн" in await page.locator("#glossary-text").input_value()
        await page.locator("#glossary-scope").select_option("tree")
        await page.locator("#glossary-text").fill("пайплайн > последовательность")
        screenshots = fixture.ROOT / ".run/ui-screenshots/glossary"
        screenshots.mkdir(parents=True, exist_ok=True)
        for theme in ("light", "dark"):
            await page.evaluate("theme => document.documentElement.dataset.theme=theme", theme)
            await page.screenshot(path=str(screenshots / f"editor-{theme}.png"))
        await page.locator('#glossary-dialog [type="submit"]').click()
        await page.locator("#glossary-dialog").wait_for(state="detached")
        local = await page.evaluate("fetch('/api/glossary?project_id=demo').then(r=>r.json())")
        assert local["effective"][0]["replacement"] == "последовательность"
        assert local["global"]["text"] == data["global"]["text"]
        assert await page.locator("#kanban-modal").is_visible()

        await page.locator('#kanban-board [data-card-id="card"] .card-expand-report').evaluate("button => button.click()")
        await page.locator("#card-report-modal:not(.hidden)").wait_for()
        await page.locator("#card-report-preview .report-block").first.wait_for()
        # Select a real rendered report phrase and exercise the existing editor menu.
        await page.evaluate("""() => {
          const host = document.querySelector('#card-report-preview');
          const block = host.querySelector('.report-block');
          const range = document.createRange(); range.selectNodeContents(block);
          const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
          host.dispatchEvent(new MouseEvent('mouseup', {bubbles:true, clientX:650, clientY:300}));
        }""")
        before = await page.locator("#card-report-editor").input_value()
        await page.get_by_role("button", name="В словарь…", exact=True).click()
        await page.locator("#glossary-scope:enabled").wait_for()
        await page.locator("#glossary-term").fill("эпизод")
        await page.locator("#glossary-replacement").fill("попытка")
        assert not await page.locator("[data-editor-label]").is_visible()
        await page.screenshot(path=str(screenshots / "selection-dark.png"))
        await page.set_viewport_size({"width": 390, "height": 844})
        bounds = await page.locator("#glossary-dialog").bounding_box()
        assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= 390
        await page.screenshot(path=str(screenshots / "selection-mobile.png"))
        await page.set_viewport_size({"width": 1440, "height": 900})
        await page.locator('#glossary-dialog [type="submit"]').click()
        await page.locator("#glossary-dialog").wait_for(state="detached")
        assert await page.locator("#card-report-editor").input_value() == before
        current = await page.evaluate("fetch('/api/glossary?project_id=demo').then(r=>r.json())")
        assert "эпизод > попытка" in current["tree"]["text"]
        # A keyboard selection opens the same action; Enter opens the dialog.
        await page.evaluate("""() => {
          const host = document.querySelector('#card-report-preview');
          const block = host.querySelector('.report-block');
          block.focus();
          const range = document.createRange(); range.selectNodeContents(block);
          const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range);
          block.dispatchEvent(new KeyboardEvent('keyup', {key:'ArrowRight',shiftKey:true,bubbles:true}));
        }""")
        assert await page.get_by_role("button", name="В словарь…", exact=True).evaluate("e => e === document.activeElement")
        await page.keyboard.press("Enter")
        await page.locator("#glossary-scope:enabled").wait_for()
        await page.keyboard.press("Escape")
        assert await page.locator("#card-report-modal").is_visible()
        assert not errors, errors
        await browser.close()
        print("PASS: global/tree vocabulary, persistence, selection, keyboard and both themes")


if __name__ == "__main__":
    fixture.smoke = smoke
    fixture.check()
