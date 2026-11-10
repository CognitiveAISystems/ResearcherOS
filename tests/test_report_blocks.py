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
        await page.evaluate("editor.setValue('## Цель\\n\\n')")
        await page.locator('.report-block-placeholder').last.click()
        field = page.locator('.report-block-input')
        await page.get_by_role('option', name='Маркированный список', exact=True).click()
        assert await field.input_value() == '- '
        await field.fill('- Первый')
        await field.press('Escape')
        assert await page.evaluate("editor.getValue()") == '## Цель\n\n- Первый\n\n'
        await page.locator('.report-block-placeholder').last.click()
        await field.press('Escape')
        await field.fill('/заголовок 2')
        assert await page.get_by_role('option').count() == 1
        await field.press('Enter')
        assert await field.input_value() == '## '
        await field.type('Новый раздел')
        await field.press('Escape')
        assert 'Новый раздел' in await page.locator('#report-toc button').all_text_contents()
        await page.locator('.report-block-placeholder').last.click()
        await field.press('Escape')
        await field.fill('/unknown')
        assert await page.get_by_text('Блоки не найдены').is_visible()
        await field.press('Escape')
        assert await field.input_value() == '/unknown'
        await field.fill(' ')
        assert await page.locator('.report-block-menu').count() == 0
        await field.fill('/code')
        await field.press('Enter')
        await field.type('print(1)')
        await field.press('Enter')
        assert await page.locator('.report-block-input').count() == 1
        assert 'print(1)\n' in await field.input_value()
        await field.press('Escape')
        await page.locator('.report-block-placeholder').last.click()
        await page.get_by_role('option', name='Список задач', exact=True).click()
        task = page.get_by_role('textbox', name='Текст задачи 1', exact=True)
        await task.fill('Проверить результат')
        await task.press('Enter')
        task2 = page.get_by_role('textbox', name='Текст задачи 2', exact=True)
        await task2.fill('Записать вывод')
        await page.get_by_role('checkbox').first.check()
        saved = await page.evaluate('editor.getValue()')
        assert '- [x] Проверить результат\n- [ ] Записать вывод' in saved
        await page.evaluate('editor.setValue(editor.getValue())')
        assert await page.get_by_role('checkbox').first.is_checked()
        second = page.get_by_role('textbox', name='Текст задачи 2', exact=True)
        await second.press('Enter')
        extra = page.get_by_role('textbox', name='Текст задачи 3', exact=True)
        await extra.press('Backspace')
        assert await page.locator('.report-task-text').count() == 2
        assert await second.evaluate('(e) => e === document.activeElement')
        assert await second.input_value() == 'Записать вывод'
        await page.get_by_role('textbox', name='Текст задачи 2', exact=True).press('Enter')
        await page.get_by_role('textbox', name='Текст задачи 3', exact=True).press('Enter')
        await field.fill('/table')
        await field.press('Enter')
        assert await page.locator('.report-table-block table').count() == 1
        await page.get_by_role('textbox', name='Строка 1, столбец 1', exact=True).fill('a | b')
        await page.get_by_role('button', name='Добавить колонку', exact=True).click()
        assert await page.locator('.report-table-block th').count() == 3
        await page.get_by_role('textbox', name='Строка 1, столбец 3', exact=True).press('Tab')
        assert await page.locator('.report-table-block tr').count() == 3
        await page.get_by_role('textbox', name='Строка 2, столбец 3', exact=True).press('Tab')
        assert await page.locator('.report-table-block tr').count() == 4
        assert r'a \| b' in await page.evaluate('editor.getValue()')
        await page.evaluate('editor.setValue(editor.getValue())')
        assert await page.get_by_role('textbox', name='Строка 1, столбец 1', exact=True).input_value() == 'a | b'
        await page.evaluate("document.documentElement.dataset.theme = 'light'")
        await page.screenshot(path='/tmp/report-table-refined-light.png')
        await page.evaluate("document.documentElement.dataset.theme = 'dark'")
        await page.screenshot(path='/tmp/report-table-refined-dark.png')
        await page.get_by_role('button', name='Продолжить под таблицей', exact=True).click()
        await page.locator('.report-block-plus').click()
        await page.get_by_role('option', name='Формула', exact=True).click()
        formula = page.get_by_role('textbox', name='Формула LaTeX', exact=True)
        assert await formula.is_visible()
        await formula.fill(r'\sum_{i=1}^{n} i = \frac{n(n+1)}{2}')
        assert await page.locator('.report-formula-preview math').count() == 1
        assert await page.locator('.report-formula-preview mfrac').count() == 1
        await formula.press('Enter')
        await formula.type(r'+ \alpha')
        await formula.press('Control+Enter')
        assert await formula.is_hidden()
        await page.screenshot(path='/tmp/report-formula.png')
        saved_math = await page.evaluate('editor.getValue()')
        assert r'\sum_{i=1}^{n}' in saved_math and r'+ \alpha' in saved_math
        await page.evaluate('editor.setValue(editor.getValue())')
        assert await page.locator('.report-formula-preview math').count() == 1
        await page.locator('.report-formula').focus()
        await page.keyboard.press('Enter')
        assert r'+ \alpha' in await formula.input_value()
        await formula.fill(r'\unknown{bad}')
        assert 'unknown' in await page.locator('.report-formula-preview').text_content()
        await formula.fill(r'E = mc^2')
        await page.get_by_role('button', name='Продолжить под формулой', exact=True).click()
        await page.locator('.report-block-plus').click()
        await page.set_viewport_size({'width': 390, 'height': 844})
        for theme in ['dark', 'light']:
            await page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
            await page.locator('.report-block-plus').click()
            menu = page.locator('.report-block-menu')
            await menu.scroll_into_view_if_needed()
            bounds = await menu.bounding_box()
            assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= 390
            await page.screenshot(path=f'/tmp/report-block-menu-{theme}.png')
        await page.evaluate("editor.setValue('- [ ] Первая\\n- [ ] Вторая\\n\\n')")
        second = page.get_by_role('textbox', name='Текст задачи 2', exact=True)
        await second.focus()
        await second.press('Home')
        await second.press('Backspace')
        assert await page.locator('.report-task-text').count() == 1
        assert await page.get_by_role('textbox', name='Текст задачи 1', exact=True).input_value() == 'ПерваяВторая'
        await page.evaluate("editor.setValue('- [ ] \\n\\n')")
        await page.get_by_role('textbox', name='Текст задачи 1', exact=True).press('Backspace')
        assert await page.locator('.report-task-text').count() == 0
        assert await field.evaluate('(e) => e === document.activeElement')
        await browser.close()
        print('PASS: picker, tasks, checkboxes, Enter, table cells, rows/columns, Tab, formula preview/reload and mobile themes')

if __name__ == '__main__':
    asyncio.run(check())
