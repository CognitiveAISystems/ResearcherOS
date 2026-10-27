"""Run directly: done card -> short Git notice -> stale approval -> commit + push."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


async def smoke(url, mount, remote):
    from playwright.async_api import async_playwright
    from koi.agent_chat import git_changes as changes
    before = git(mount.repo_root, "rev-parse", "HEAD")
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(15000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        await page.route("https://**/*", lambda route: route.abort())
        await page.goto(url + "?desktop=1", wait_until="networkidle")
        report = mount.koi_root / "reports" / "check.md"
        report.parent.mkdir(exist_ok=True)
        report.write_text("# Проверка\n\nДобавлен результат проверки.\n")
        response = await page.request.patch(url + 'api/projects/demo/boards/b/cards/c-memory',
                                            data={"column_id": "done"})
        assert response.ok, await response.text()
        chat = None
        for _ in range(100):
            response = await page.request.get(url + 'api/agent-conversations?project_id=demo')
            data = await response.json()
            chat = next((r for r in data.get('items', []) if r.get('kind') == 'git_sync'
                         and r.get('git_digest_version') == changes.NOTICE_VERSION and not r['pending']), None)
            if chat:
                break
            await asyncio.sleep(.1)
        assert chat, 'Git notice was not delivered to the tree chat'
        button = page.locator(f'button.conversation-entry[data-conversation="{chat["id"]}"]')
        await button.wait_for(state='attached')
        if not await button.is_visible():
            await page.locator('.research-chat-section-toggle').filter(has_text="Проверка Git").click()
        await button.click()
        controls = page.locator('#agent-chat-panel .conversation-controls')
        await page.locator('#agent-chat-log').get_by_text('В отчёте добавлен результат проверки.').wait_for()
        assert await controls.locator('button').count() == 0
        assert git(mount.repo_root, "rev-parse", "HEAD") == before
        assert git(remote, "rev-parse", "koi/research") == before
        text = await page.locator('#agent-chat-log .agent-chat-thread').last.inner_text()
        assert 'Проверить сокращение памяти' in text and len(text) < 450
        assert await page.locator('#agent-chat-log .agent-chat-q').count() == 0
        assert 'Старая подробная сводка' not in await page.locator('#agent-chat-log').inner_text()
        # Stop further notices to prove that the command itself checks new edits.
        changes.stop()
        out = ROOT / '.run/ui-screenshots/git-changes'
        out.mkdir(parents=True, exist_ok=True)
        for theme in ('light', 'dark'):
            await page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
            await page.wait_for_timeout(300)
            await page.screenshot(path=str(out / f'{theme}.png'))
        report.write_text("# Проверка\n\nРезультат уточнён после предложения.\n")
        composer = page.locator('#agent-chat-input')
        await composer.fill('да')
        await composer.press('Enter')
        await page.wait_for_function("document.querySelector('#agent-chat-log').textContent.includes('Появились новые правки')")
        assert git(mount.repo_root, 'rev-parse', 'HEAD') == before
        await composer.fill('сохрани и отправь')
        await composer.press('Enter')
        await page.wait_for_function("document.querySelector('#agent-chat-log').textContent.includes('Изменения сохранены и отправлены')")
        committed = git(mount.repo_root, 'rev-parse', 'HEAD')
        assert committed != before
        assert git(remote, 'rev-parse', 'koi/research') == committed
        assert not errors, errors
        await browser.close()


def check():
    with tempfile.TemporaryDirectory(prefix='researcheros-git-chat-') as directory:
        root = Path(directory)
        os.environ.update(KOI_DATA_DIR=str(root / 'runtime'), KOI_DESKTOP_CONFIG_DIR=str(root / 'config'),
                          KOI_WORKSPACE=str(root), KOI_SCAN_ROOTS=str(root))
        from koi.adapters import project_mount
        project_mount.ENGINE_ROOT = root / 'engine'
        project_mount.ENGINE_ROOT.mkdir()
        from koi.adapters.desktop_workspace import set_workspace_root
        set_workspace_root(root)
        remote = root / 'remote.git'
        remote.mkdir()
        git(remote, 'init', '--bare')
        repo = root / 'tree/demo'
        research = repo / 'koi-structure'
        research.mkdir(parents=True)
        (research / 'project.md').write_text('''---
id: demo
title: Проверка Git
git_repo: true
git_sync_branch: koi/research
---
# problem: root

Проверка Git

#### method: m

Проверка памяти

<!-- koi:kanban b -->
| backlog | running | done |
| --- | --- | --- |
| | Проверить сокращение памяти <!-- id:c-memory --> | |
''')
        (research / 'research.json').write_text('{"version":1,"questions":[]}')
        git(repo, 'init', '-b', 'koi/research')
        git(repo, 'config', 'user.name', 'Research test')
        git(repo, 'config', 'user.email', 'test@example.invalid')
        git(repo, 'add', '.')
        git(repo, 'commit', '-m', 'initial')
        git(repo, 'remote', 'add', 'origin', str(remote))
        git(repo, 'push', '-u', 'origin', 'koi/research')
        project_mount.rescan_projects()
        mount = project_mount.get_mount('demo')
        from koi.agent_chat import git_changes as changes
        changes.POLL_SECONDS = .2
        changes._suggest = lambda *_a: 'Завершена задача «Проверить сокращение памяти».\nВ отчёте добавлен результат проверки.'
        changes._save_schedule({"last_daily": datetime.now().astimezone().date().isoformat()})
        from koi.agent_chat import conversations
        from koi.adapters import agent_chat_queue
        chat = conversations.create('demo', title='Изменения исследования')
        conversations.update(chat['id'], kind='git_sync')
        old = agent_chat_queue.enqueue_question('demo', 'Старая сводка', purpose='git_notice', conversation_id=chat['id'])
        agent_chat_queue.submit_answer(old['id'], 'Старая подробная сводка.\n' * 200)
        from koi.projects import done_research_auto
        done_research_auto.kick_recent = lambda: None
        from koi.desktop.server import DesktopServer
        server = DesktopServer()
        try:
            asyncio.run(smoke(server.start(), mount, remote))
            print('PASS: done trigger, short tree notice, stale approval, text command commit + push, no Git buttons or legacy lists, both themes')
        finally:
            server.stop()


if __name__ == '__main__':
    check()
