"""Both desktop entry points use the same repository and interview screens."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("existing", ["git", "local"])
def test_new_tree_uses_onboarding(theme, existing):
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(ROOT / "web")))
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/api/**", lambda route: route.fulfill(json={
                "workspace_root": None,
            }))
            page.route("**/api/desktop/onboarding/default-location", lambda route: route.fulfill(json={
                "workspace_root": "/tmp/research",
            }))
            page.route(f"http://127.0.0.1:{server.server_port}/", lambda route: route.fulfill(
                content_type="text/html",
                body='<html><head><link rel="stylesheet" href="/styles.css"><link rel="stylesheet" href="/desktop-onboarding.css"><link rel="stylesheet" href="/onboarding-interview.css"></head><body></body></html>',
            ))
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            page.evaluate("""async theme => {
                document.body.replaceChildren();
                document.documentElement.dataset.theme = theme;
                window.researchOSDesktop = { chooseDirectory: async () => '/tmp/repo' };
                const wizard = await import('/desktop-onboarding.js');
                await window.researchOSOnboardingReady;
                window.openWizard = wizard.openNewProjectWizard;
            }""", theme)
            page.get_by_role("button", name="Нет", exact=True).click()
            shell = page.locator(".desktop-onboarding__shell--entry")
            original = shell.inner_html()
            page.get_by_role("button", name="Выбрать репозиторий", exact=True).focus()
            # Finish first-run setup, then enter through the sidebar action.
            page.route("**/api/desktop/workspace-root", lambda route: route.fulfill(json={
                "workspace_root": "/tmp/research",
            }))
            page.evaluate("""() => {
                document.querySelector('.desktop-onboarding').remove();
                window.openWizard();
            }""")
            expect(page.get_by_role("button", name="Закрыть настройку")).to_be_visible()
            # The only addition to the onboarding repository screen is its close button.
            assert shell.inner_html().removesuffix(shell.locator(".desktop-onboarding__close").evaluate("(el) => el.outerHTML")) == original
            output = ROOT / ".run/ui-screenshots"
            output.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(output / f"new-tree-{theme}.png"))
            page.keyboard.press("Escape")
            expect(shell).to_have_count(0)
            page.evaluate("window.openWizard()")
            page.route("**/api/desktop/onboarding/git-project", lambda route: route.fulfill(json={
                "repo_path": "/tmp/repo", "branch_exists": existing == "git", "branch": "koi/research",
                "tree_folder_occupied": True,
                "local_tree": {"branch": None, "project_id": "old-repo", "title": "Локальное исследование", "workspace_root": "/tmp/research", "nodes": [
                    {"id": "root", "parent_id": None, "type": "direction", "title": "Локальное направление", "description": "Описание"},
                    {"id": "method", "parent_id": "root", "type": "method", "title": "Первый метод", "description": "Проверка"},
                ]} if existing == "local" else None,
                "next_branch": "koi/research-2" if existing == "git" else "koi/research-4",
                "trees": [{"title": "Исследование", "branch": "koi/research", "nodes": []}] if existing == "git" else [],
            }))
            page.get_by_role("button", name="Выбрать репозиторий", exact=True).click()
            expect(page.get_by_role("button", name="Продолжить в этом дереве")).to_be_visible()
            if existing == "local":
                expect(page.locator('.desktop-onboarding__tree-preview .map-node')).to_have_count(2)
                expect(page.get_by_text('Локальное направление', exact=True)).to_be_visible()
                expect(page.get_by_role('button', name='Показать целиком')).to_be_visible()
                page.get_by_role('button', name='Увеличить дерево').click()
                page.get_by_role('button', name='Показать целиком').click()
                assert not errors
                for node in page.locator('.desktop-onboarding__tree-preview .map-node').all():
                    assert node.evaluate('(el) => getComputedStyle(el).position') == 'absolute'
                page.screenshot(path=str(output / f'existing-local-tree-{theme}.png'))
            expect(page.get_by_role("button", name="Создать новое дерево")).to_be_visible()
            page.get_by_role("button", name="Назад", exact=True).click()
            expect(page.get_by_role("button", name="Выбрать репозиторий")).to_be_visible()
            starts = []
            def start_interview(route):
                starts.append(route.request.post_data_json)
                route.fulfill(json={"phase": "description", "nodes": [], "messages": [{"role": "assistant", "text": "Опиши проект своими словами."}], "complete": False, "question_count": 1, "confirmation_count": 0})
            page.route("**/api/desktop/onboarding/interview/start", start_interview)
            page.get_by_role("button", name="Выбрать репозиторий", exact=True).click()
            page.get_by_role("button", name="Создать новое дерево", exact=True).click()
            expect(page.get_by_role("textbox", name="Ваш ответ", exact=True)).to_be_visible()
            expect(page.get_by_text("Опиши проект своими словами.", exact=True)).to_be_visible()
            assert starts[0]['branch'] == ('koi/research-2' if existing == 'git' else 'koi/research-4')
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
