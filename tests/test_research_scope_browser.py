"""Focused browser regression; run with .venv/bin/python tests/test_research_scope_browser.py."""
import asyncio
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]


async def check():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={'width': 1440, 'height': 900})

        async def serve(route):
            name = urlparse(route.request.url).path.lstrip('/') or 'index.html'
            path = ROOT / 'web' / name
            if not path.is_file():
                await route.abort()
                return
            content = path.read_bytes()
            if name == 'index.html':
                content = re.sub(rb'<script\b[^>]*>.*?</script>', b'', content, flags=re.S)
            await route.fulfill(body=content, content_type=mimetypes.guess_type(name)[0] or 'text/javascript')

        await page.route('http://research.test/**', serve)
        await page.goto('http://research.test/', wait_until='domcontentloaded')
        await page.evaluate('''async () => {
            const {attachSkillMenu, reportChatCommand} = await import('./chat-skills.js');
            const {confirmResearchScope, isResearchStart} = await import('./research-scope.js');
            document.querySelector('#card-report-modal').classList.remove('hidden');
            document.querySelector('#report-interview').hidden = false;
            window.context = {project: 'demo', card: null, method: null};
            window.sent = [];
            window.scopeModule = {confirmResearchScope, isResearchStart};
            const input = document.querySelector('#report-interview-input');
            attachSkillMenu(input, {getProjectId: () => context.project, getCardId: () => context.card});
            input.form.addEventListener('submit', async event => {
                event.preventDefault();
                const research_scope = isResearchStart(input.value) ? await confirmResearchScope({
                    methodTitle: context.method, projectTitle: 'Исследование обучения',
                }) : null;
                if (isResearchStart(input.value) && !research_scope) return;
                sent.push({...reportChatCommand(input.value), research_scope});
            });
        }''')
        field = page.locator('#report-interview-input')
        options = page.locator('.chat-skills [role="option"]')
        # Tree and method chats expose research without the card-only run command.
        for method in [None, 'Обучение по примерам']:
            await page.evaluate('(method) => context.method = method', method)
            await field.fill('/')
            assert await options.locator('strong').all_text_contents() == ['Автоисследование']
            await field.fill('/koi-arbor')
            assert await options.count() == 1
            await field.press('Enter')
            assert await field.input_value() == '/koi-arbor-autoresearch '
            assert await page.evaluate('sent.length') == 0

        # Card menu retains run as an independent action.
        await page.evaluate("context.card = 'card'")
        await field.fill('/')
        assert await options.locator('strong').all_text_contents() == ['Автоисследование', 'grill-me', 'prose', 'Сжать отчёт', 'question', 'run']
        await field.fill('/compress')
        await field.press('Enter')
        assert await field.input_value() == '/compress '
        assert await page.evaluate('sent.length') == 0
        await page.evaluate("document.querySelector('#report-interview-form').requestSubmit()")
        assert await page.evaluate('sent.pop().purpose') == 'compress'
        await field.fill('/koi-arbor-autoresearch Улучшить метод')
        await field.press('Escape')
        await page.evaluate("document.querySelector('#report-interview-form').requestSubmit()")
        dialog = page.get_by_role('dialog', name='Масштаб автоисследования')
        await dialog.wait_for()
        assert await page.evaluate('sent.length') == 0
        assert 'Обучение по примерам' in await dialog.inner_text()
        await dialog.get_by_role('button', name='Отмена', exact=True).click()
        assert await page.evaluate('sent.length') == 0
        assert await field.input_value() == '/koi-arbor-autoresearch Улучшить метод'
        assert await field.evaluate('(el) => document.activeElement === el')

        for choice, level in [('В рамках метода', 'method'), ('На уровне дерева', 'tree')]:
            await page.evaluate("document.querySelector('#report-interview-form').requestSubmit()")
            await dialog.get_by_role('button', name=choice, exact=True).click()
            assert await page.evaluate('sent.at(-1).research_scope') == level

        # Escape cancels and returns focus. Tree launch has no method choice.
        await page.evaluate("context.method = null; context.card = null; document.querySelector('#report-interview-form').requestSubmit()")
        await dialog.wait_for()
        assert await dialog.get_by_role('button').all_text_contents() == ['Отмена', 'Начать исследование']
        await page.keyboard.press('Escape')
        assert await page.evaluate('sent.length') == 2
        assert await field.evaluate('(el) => document.activeElement === el')

        # All dialog choices remain visible and keyboard focus stays inside, in both themes.
        out = ROOT / '.run/research-scope'
        out.mkdir(parents=True, exist_ok=True)
        for width in [390, 1440]:
            await page.set_viewport_size({'width': width, 'height': 900})
            for theme in ['light', 'dark']:
                await page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                for method in [None, 'Обучение по примерам']:
                    await page.evaluate('''method => {
                        context.method = method;
                        document.querySelector('#report-interview-form').requestSubmit();
                    }''', method)
                    await dialog.wait_for()
                    for button in await dialog.get_by_role('button').all():
                        rect = await button.bounding_box()
                        assert rect['x'] >= 0 and rect['x'] + rect['width'] <= width
                        assert rect['height'] >= 44
                    for _ in range(4):
                        await page.keyboard.press('Tab')
                        assert await dialog.evaluate('(el) => el.contains(document.activeElement)'), await page.evaluate('document.activeElement.outerHTML.slice(0, 150)')
                    await page.screenshot(path=str(out / f'{width}-{theme}-{"method" if method else "tree"}.png'))
                    await page.keyboard.press('Escape')
        await page.evaluate("context.method = null; document.querySelector('#report-interview-form').requestSubmit()")
        await dialog.get_by_role('button', name='Начать исследование', exact=True).click()
        assert await page.evaluate('sent.at(-1).research_scope') == 'tree'
        assert not await page.evaluate("scopeModule.isResearchStart('/koi-arbor-autoresearch resume run-1')")
        await browser.close()
        print('PASS: tree/method/card menus, both scope choices, cancel/Escape, draft/focus, eight layouts')


if __name__ == '__main__':
    asyncio.run(check())
