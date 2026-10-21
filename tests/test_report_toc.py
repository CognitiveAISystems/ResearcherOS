"""Browser regression: .venv/bin/python tests/test_report_toc.py (requires Playwright)."""
import asyncio
import mimetypes
import re
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]

async def check():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 900})

        async def serve(route):
            from urllib.parse import urlparse
            name = urlparse(route.request.url).path.lstrip('/') or 'index.html'
            path = ROOT / 'web' / name
            if not path.is_file():
                await route.abort()
                return
            content = path.read_bytes()
            if name == 'index.html':
                content = re.sub(rb'<script\b[^>]*>.*?</script>', b'', content, flags=re.S)
            await route.fulfill(body=content, content_type=mimetypes.guess_type(name)[0] or 'text/javascript')

        await page.route('http://report.test/**', serve)
        await page.goto('http://report.test/', wait_until='domcontentloaded')
        await page.evaluate('''async () => {
            const {ReportEditor} = await import('./report-editor.js');
            const {renderMarkdown} = await import('./markdown.js');
            window.editor = new ReportEditor(document.querySelector('#card-report-preview'), {
                toc: document.querySelector('#report-toc'),
                render: text => renderMarkdown(text, {collapsibleSections:false}),
                onChange: () => {}, onAgent: () => {}, hookLinks: () => {}
            });
            document.querySelector('#card-report-modal').classList.remove('hidden');
            editor.setValue('## Начало\\n\\n' + 'Абзац.\\n\\n'.repeat(80) + '## Результаты\\n\\n### Подробности\\n\\nТекст.');
        }''')
        for width in [1280, 1440, 1920, 2560]:
            await page.set_viewport_size({'width': width, 'height': 900})
            before = await page.locator('.report-document').bounding_box()
            panel = await page.locator('#card-report-modal .modal-panel--report').bounding_box()
            toc = await page.locator('#report-toc').bounding_box()
            await page.evaluate("document.querySelector('#report-interview').hidden = false")
            assert await page.locator('.report-document').bounding_box() == before
            assert await page.locator('#card-report-modal .modal-panel--report').bounding_box() == panel
            assert await page.locator('#report-toc').bounding_box() == toc
            await page.evaluate("document.querySelector('#report-interview').hidden = true")
        await page.set_viewport_size({'width': 1440, 'height': 900})
        buttons = page.locator('#report-toc button')
        assert await buttons.all_text_contents() == ['Начало', 'Результаты', 'Подробности']
        await buttons.nth(1).click()
        assert await page.evaluate("document.activeElement.textContent.trim() === 'Результаты'")
        assert await page.locator('.report-document').evaluate('(e) => e.scrollTop > 0')
        await page.keyboard.press('Enter')
        field = page.locator('.report-block-input')
        await field.fill('## Новый результат')
        await field.press('Escape')
        assert 'Новый результат' in await buttons.all_text_contents()
        await page.set_viewport_size({'width': 390, 'height': 844})
        await page.wait_for_function("!document.querySelector('#report-toc').open")
        await page.locator('#report-toc summary').click()
        await buttons.first.click()
        await page.wait_for_function("!document.querySelector('#report-toc').open")
        assert await page.evaluate("document.activeElement.textContent.trim() === 'Начало'")
        await page.evaluate("editor.setValue('Обычный текст без заголовков.')")
        assert await page.locator('#report-toc').is_hidden()
        await page.evaluate("editor.setValue('## Повтор\\n\\nТекст\\n\\n## Повтор')")
        await page.locator('#report-toc summary').click()
        await buttons.nth(1).click()
        assert await page.evaluate("document.activeElement.dataset.blockIndex === '2'")
        await browser.close()
        print('PASS: navigation, heading edits, mobile collapse, empty and duplicate headings')

if __name__ == '__main__':
    asyncio.run(check())
