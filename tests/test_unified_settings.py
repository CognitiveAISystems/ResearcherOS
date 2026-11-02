"""Unified settings and archive round trip with isolated desktop data."""
from pathlib import Path
from playwright.async_api import async_playwright
import test_chat_conversations_e2e as fixture

async def smoke(url):
    import os
    from koi.adapters import project_mount
    for i in range(24):
        folder = Path(os.environ['KOI_WORKSPACE']) / f'scroll-{i}/koi-structure'
        folder.mkdir(parents=True)
        (folder / 'project.md').write_text(f'---\nid: scroll-{i}\ntitle: Длинное название дерева исследования {i}\nprograms:\n- id: program-{i}\n  title: Программа {i:02}\n---\n\n# problem: root-{i}\n\nПроверка прокрутки\n')
        (folder / 'research.json').write_text('{"version":1,"questions":[]}')
    project_mount.rescan_projects()
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.route('https://**/*', lambda route: route.abort())
        await page.request.put(url + '/api/desktop/archived-trees', data={'ids': [f'scroll-{i}' for i in range(12)]})
        await page.goto(url + '?desktop=1', wait_until='networkidle')
        await page.locator('.research-program').first.wait_for()
        await page.locator('#btn-app-variant').click()
        dialog = page.locator('#app-variant-dialog')
        assert await dialog.get_by_role('button', name='Закрыть настройки', exact=True).is_visible()
        assert await dialog.get_by_role('button', name='Закрыть', exact=True).count() == 0
        assert await dialog.locator('legend').inner_text() == 'Интерфейс'
        assert await dialog.get_by_role('heading', name='Управление деревьями', exact=True).is_visible()
        assert await dialog.locator('small, #app-variant-description').count() == 0
        await dialog.locator('[value=chats]').focus()
        assert await dialog.locator('[value=chats]').evaluate('(el)=>el===document.activeElement')
        current = dialog.locator('section[data-archived=false]')
        archived = dialog.locator('section[data-archived=true]')
        await current.get_by_role('button', name='В архив: Проверка чатов', exact=True).click()
        await archived.get_by_role('button', name='Восстановить: Проверка чатов', exact=True).wait_for()
        assert await current.get_by_role('heading', name='Исследования агентов').is_visible()
        await page.reload(wait_until='networkidle')
        await page.locator('.research-program').first.wait_for()
        await page.locator('#btn-app-variant').click()
        await archived.get_by_role('button', name='Восстановить: Проверка чатов', exact=True).wait_for()
        output = Path('.run/ui-screenshots'); output.mkdir(parents=True, exist_ok=True)
        for theme in ['light', 'dark']:
            await page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
            await page.screenshot(path=str(output / f'settings-{theme}.png'))
            pairs = await dialog.evaluate("""el => {
              const rgb = value => {
                const canvas = document.createElement('canvas'); canvas.width = canvas.height = 1;
                const ctx = canvas.getContext('2d'); ctx.fillStyle = value; ctx.fillRect(0, 0, 1, 1);
                return [...ctx.getImageData(0, 0, 1, 1).data].slice(0, 3);
              };
              const background = rgb(getComputedStyle(el).backgroundColor);
              const pairs = ['h2', 'h5', '.settings-tree-count', 'label:not(:has(:checked)) strong'].map(selector => ({
                selector, foreground: rgb(getComputedStyle(el.querySelector(selector)).color), background,
              }));
              return pairs;
            }""")
            def luminance(rgb):
                linear = [value / 255 / 12.92 if value / 255 <= .04045 else ((value / 255 + .055) / 1.055) ** 2.4 for value in rgb]
                return sum(value * weight for value, weight in zip(linear, [.2126, .7152, .0722]))
            for pair in pairs:
                fg, bg = luminance(pair['foreground']), luminance(pair['background'])
                ratio = (max(fg, bg) + .05) / (min(fg, bg) + .05)
                assert ratio >= 4.5, (theme, pair, ratio)
            print(f'{theme}: text contrast >= 4.5:1', flush=True)
        await page.set_viewport_size({'width': 1440, 'height': 720})
        footer_before = await dialog.locator('.form-actions').bounding_box()
        scroller = archived.locator('.settings-program-scroll')
        assert await scroller.evaluate('(el)=>el.scrollHeight>el.clientHeight')
        await scroller.focus()
        await page.keyboard.press('End')
        await page.wait_for_function("document.querySelector('[data-archived=true] .settings-program-scroll').scrollTop>0")
        assert (await dialog.locator('.form-actions').bounding_box()) == footer_before
        assert footer_before['y'] + footer_before['height'] <= 720
        assert await current.locator('.settings-program-scroll').evaluate('(el)=>el.scrollTop') == 0
        await scroller.evaluate('(el)=>el.scrollTop=0')
        await page.screenshot(path=str(output / 'settings-many-programs.png'))
        for width in [320, 640, 1440]:
            await page.set_viewport_size({'width': width, 'height': 1000})
            assert await dialog.evaluate('(el)=>el.scrollWidth<=el.clientWidth+1')
            footer = await dialog.locator('.form-actions').bounding_box()
            assert footer['y'] >= 0 and footer['y'] + footer['height'] <= 1000
            if width == 320:
                assert not await archived.is_visible()
                await dialog.get_by_role('button', name='Архивированные', exact=True).click()
                assert await archived.is_visible()
                await page.screenshot(path=str(output / 'settings-mobile.png'))
                await archived.get_by_role('button', name='Восстановить: Проверка чатов', exact=True).click()
                await dialog.get_by_role('button', name='Текущие', exact=True).click()
                await current.get_by_role('button', name='В архив: Проверка чатов', exact=True).wait_for()
        await page.evaluate("document.documentElement.dir='rtl';document.documentElement.style.fontSize='200%'")
        assert await dialog.evaluate('(el)=>el.scrollWidth<=el.clientWidth+1')
        await page.evaluate("document.documentElement.dir='ltr';document.documentElement.style.fontSize=''")
        assert await dialog.locator('input[name="ui_variant"]').count() == 0
        await dialog.get_by_role('button', name='Готово', exact=True).click()
        await page.reload(wait_until='networkidle')
        await page.locator('#btn-app-variant').click()
        await current.get_by_role('button', name='В архив: Проверка чатов', exact=True).wait_for()
        assert not errors, errors
        await browser.close()
        print('PASS: archive round trip, persistence, modes, themes, 320/640/1440px, RTL and enlarged text')

if __name__ == '__main__':
    fixture.smoke = smoke
    fixture.check()
