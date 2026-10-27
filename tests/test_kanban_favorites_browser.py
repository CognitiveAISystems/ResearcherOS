"""Run directly to check favorites against an isolated desktop API and browser."""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def smoke(url: str) -> None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        page.set_default_timeout(10000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.route("https://**/*", lambda route: route.abort())
        await page.goto(url + "?desktop=1", wait_until="networkidle")

        async def open_board():
            await page.locator('.map-node.method.has-kanban').first.click()
            await page.locator('#kanban-modal:not(.hidden)').wait_for()

        await open_board()
        board = page.locator('#kanban-board')
        assert await board.locator('.kanban-col').count() == 3
        done = board.locator('[data-col="done"]')
        assert await done.locator('.kanban-card').count() == 2
        legacy = done.locator('[data-card-id="legacy"] .card-favorite')
        assert await legacy.get_attribute('aria-pressed') == 'true'

        star = board.locator('[data-card-id="plain"] .card-favorite')
        await star.focus()
        await page.keyboard.press('Space')
        await page.wait_for_function("document.querySelector('#kanban-board [data-card-id=plain] .card-favorite')?.getAttribute('aria-pressed') === 'true'")
        assert await star.evaluate('(el) => el === document.activeElement')
        await star.click()
        await page.wait_for_function("document.querySelector('#kanban-board [data-card-id=plain] .card-favorite')?.getAttribute('aria-pressed') === 'false'")

        await page.locator('#kanban-filters-toggle').click()
        favorites = page.locator('#kanban-favorites-filter')
        await favorites.click()
        assert await favorites.get_attribute('aria-pressed') == 'true'
        assert await done.locator('.kanban-card').count() == 1
        assert await done.locator('.col-count-inline').inner_text() == '1/2'
        for column in ('backlog', 'running'):
            assert await board.locator(f'[data-col="{column}"] .kanban-card').count() == 1
        assert await page.locator('#kanban-filter-count').inner_text() == '1'
        await page.keyboard.press('Escape')

        out = ROOT / '.run/ui-screenshots/kanban-favorites'
        out.mkdir(parents=True, exist_ok=True)
        for theme in ('light', 'dark'):
            await page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
            await page.wait_for_timeout(250)  # let the existing theme transitions finish
            await page.screenshot(path=str(out / f'{theme}.png'))
            await page.locator('#kanban-filters-toggle').click()
            await page.screenshot(path=str(out / f'{theme}-filters.png'))
            await page.keyboard.press('Escape')

        await page.reload(wait_until='networkidle')
        await open_board()
        assert await done.locator('.kanban-card').count() == 1
        assert await legacy.get_attribute('aria-pressed') == 'true'
        await legacy.click()
        await done.locator('.kanban-card').wait_for(state='detached')
        assert await page.locator('#kanban-filters-toggle').evaluate('(el) => el === document.activeElement')
        await page.locator('#kanban-filters-toggle').click()
        await page.locator('#kanban-filters-clear').click()
        assert await done.locator('.kanban-card').count() == 2
        assert await favorites.get_attribute('aria-pressed') == 'false'
        assert await page.locator('#kanban-filter-count').is_hidden()
        assert not errors, errors
        await browser.close()


def check() -> None:
    with tempfile.TemporaryDirectory(prefix='researcheros-favorites-') as directory:
        root = Path(directory)
        os.environ.update(KOI_DATA_DIR=str(root / 'runtime'),
                          KOI_DESKTOP_CONFIG_DIR=str(root / 'config'),
                          KOI_WORKSPACE=str(root), KOI_SCAN_ROOTS=str(root))
        from koi.adapters import project_mount
        project_mount.ENGINE_ROOT = root / 'engine'
        project_mount.ENGINE_ROOT.mkdir()
        from koi.adapters.desktop_workspace import set_workspace_root
        set_workspace_root(root)
        from koi.adapters.workspace import reset_workspace_cache
        reset_workspace_cache()
        research = root / 'demo/koi-structure'
        research.mkdir(parents=True)
        (research / 'project.md').write_text('''---
id: demo
title: Проверка избранного
---
# problem: root

Проверка избранного

#### method: method

Цикл дообучения по разметке эксперта

<!-- koi:kanban board-method -->
| backlog | running | done | successful |
| --- | --- | --- | --- |
| План <!-- id:plan desc:Проверяем новую гипотезу --> | Обучение <!-- id:run desc:Измеряем качество модели --> | Связь слов с картой <!-- id:plain desc:Проверки показали частичную связь слов с символами поля --> | Сильный прогон <!-- id:legacy desc:Модель устойчиво проходит проверку на новых картах --> |
''')
        (research / 'research.json').write_text('{"version":1,"questions":[]}')
        project_mount.rescan_projects()
        from koi.desktop.server import DesktopServer
        server = DesktopServer()
        try:
            asyncio.run(smoke(server.start()))
            saved = (research / 'project.md').read_text()
            assert 'successful' not in saved
            assert 'favorite:1' not in saved  # both stars were removed in the UI
            print('PASS: migration, star toggle, keyboard focus, Done filter, reload, reset, both themes')
        finally:
            server.stop()


if __name__ == '__main__':
    check()
