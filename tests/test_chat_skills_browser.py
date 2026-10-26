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
            const {attachSkillMenu} = await import('./chat-skills.js');
            document.querySelector('#card-report-modal').classList.remove('hidden');
            document.querySelector('#report-interview').hidden = false;
            document.querySelector('#report-interview .agent-chat-composer').classList.add('has-voice');
            document.querySelector('#card-report-card-title').textContent = 'Проверка гипотезы';
            document.querySelector('#card-report-preview').textContent = 'Результаты эксперимента и план следующих шагов.';
            document.querySelector('#report-toc').hidden = true;
            window.sent = 0;
            const input = document.querySelector('#report-interview-input');
            input.form.addEventListener('submit', e => { e.preventDefault(); window.sent++; });
            attachSkillMenu(input, {getProjectId:()=> 'demo'});
            input.addEventListener('keydown', e => { if(e.key === 'Enter') input.form.requestSubmit(); });
            document.querySelector('#report-interview-log').innerHTML = '<div class="agent-chat-thread"><div class="agent-chat-q-row"><p class="agent-chat-q">Что проверяем в этом эксперименте?</p></div><div class="agent-chat-reply">Проверяем, улучшает ли новый метод результат на отложенной выборке.</div></div>';
        }''')
        await page.evaluate("""async () => {
            const {attachReportChatResize} = await import('./report-chat-resize.js');
            attachReportChatResize(document.querySelector('#report-interview'));
        }""")
        panel = page.locator('#report-interview')
        before = await panel.bounding_box()
        handle = page.locator('.report-chat-resize')
        box = await handle.bounding_box()
        await page.mouse.move(box['x'] + 4, box['y'] + 100)
        await page.mouse.down()
        await page.mouse.move(box['x'] - 96, box['y'] + 100)
        await page.mouse.up()
        after = await panel.bounding_box()
        assert after['width'] > before['width'] + 90, (before, after)
        await handle.focus()
        await page.keyboard.press('ArrowRight')
        narrower = await panel.bounding_box()
        assert narrower['width'] < after['width'] - 20
        await page.evaluate("document.querySelector('.report-workspace').style.removeProperty('--report-chat-width')")
        typography = await page.evaluate("""() => ['#report-interview-input', '#report-interview .agent-chat-q', '#report-interview .agent-chat-reply'].map(selector => {const s=getComputedStyle(document.querySelector(selector));return [s.fontFamily,s.fontSize,s.lineHeight];})""")
        assert all(style[:2] == typography[0][:2] for style in typography), typography
        assert all(float(style[2].removesuffix("px")) / float(style[1].removesuffix("px")) >= 1.5 for style in typography), typography
        field = page.locator('#report-interview-input')
        await field.fill('/')
        options = page.locator('.chat-skills [role="option"]')
        assert await options.locator('strong').all_text_contents() == ['grill-me','prose','question','run']
        await field.press('ArrowDown')
        await field.press('Enter')
        assert await field.input_value() == '/prose '
        assert await page.evaluate('sent') == 0
        await field.fill('/run')
        await options.first.click()
        assert await field.input_value() == '/run '
        await field.fill('/nothing')
        assert await page.locator('.chat-skills-empty').inner_text() == 'Скиллы не найдены'
        await field.press('Escape')
        assert not await page.locator('.chat-skills').is_visible()
        out = ROOT / '.run/chat-skills'
        out.mkdir(parents=True, exist_ok=True)
        for width in [390, 1440, 2560]:
            await page.set_viewport_size({'width':width, 'height':900})
            for theme in ['light','dark']:
                await page.evaluate('(theme)=>document.documentElement.dataset.theme=theme', theme)
                await field.fill('/')
                await field.scroll_into_view_if_needed()
                await page.screenshot(path=str(out / f'{width}-{theme}.png'))
                rect = await page.locator('.chat-skills').bounding_box()
                assert 0 <= rect['x'] and rect['x'] + rect['width'] <= width + 1
                assert 0 <= rect['y'] and rect['y'] + rect['height'] <= 901
        await browser.close()
        print('PASS: four commands, keyboard/mouse selection, no automatic send, filtering, Escape, six layouts')

if __name__ == '__main__':
    asyncio.run(check())
