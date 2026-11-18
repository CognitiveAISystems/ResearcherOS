"""Main always opens Quick Navigation, including with legacy settings."""
from pathlib import Path
from playwright.async_api import async_playwright
import test_chat_conversations_e2e as fixture


async def smoke(url):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        await page.route("https://**/*", lambda route: route.abort())
        await page.goto(url + "?desktop=1&project=demo", wait_until="networkidle")
        await page.wait_for_function("document.documentElement.dataset.appVariant === 'quick'")
        await page.locator('.research-quick-tree[data-tree-id="demo"]').wait_for()
        await page.locator("#btn-app-variant").click()
        assert await page.locator('input[name="ui_variant"]').count() == 0
        await page.get_by_role('heading', name='Управление деревьями').wait_for()
        output = Path('.run/ui-screenshots/quick-only')
        output.mkdir(parents=True, exist_ok=True)
        for theme in ('dark', 'light'):
            await page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
            await page.screenshot(path=str(output / f'settings-{theme}.png'))
        await page.get_by_role('button', name='Готово', exact=True).click()
        assert await page.locator("#btn-app-variant").evaluate("el => el === document.activeElement")
        await page.evaluate("""async () => {
          const { initAppVariant } = await import('/app-variant.js');
          await initAppVariant({getSettings: async () => ({ui_variant: 'light'})},
            async () => {}, {refresh: async () => {}, groups: () => []});
        }""")
        assert await page.locator("html").get_attribute("data-app-variant") == "quick"
        await page.reload(wait_until="networkidle")
        assert await page.locator("html").get_attribute("data-app-variant") == "quick"
        await browser.close()
        print("PASS: Quick Navigation only, settings, keyboard focus, reload and legacy selection")


if __name__ == "__main__":
    fixture.smoke = smoke
    fixture.check()
