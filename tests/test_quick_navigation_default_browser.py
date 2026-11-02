"""Fresh installations use Quick Navigation; saved choices still take priority."""
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
        assert await page.locator('input[value="quick"]').is_checked()
        await page.locator('input[value="chats"]').check()
        await page.locator('#app-variant-dialog button[type="submit"]').click()
        await page.wait_for_function("document.documentElement.dataset.appVariant === 'chats'")
        await page.reload(wait_until="networkidle")
        assert await page.locator("html").get_attribute("data-app-variant") == "chats"
        # The frontend fallback agrees with the server when settings cannot load.
        await page.evaluate("""async () => {
          const { initAppVariant } = await import('/app-variant.js');
          await initAppVariant({getSettings: async () => {throw Error('offline');}},
            async () => {}, {refresh: async () => {}, groups: () => []});
        }""")
        assert await page.locator("html").get_attribute("data-app-variant") == "quick"
        await browser.close()
        print("PASS: Quick Navigation default, saved selection and offline fallback")


if __name__ == "__main__":
    fixture.smoke = smoke
    fixture.check()
