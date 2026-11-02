"""Contextual node actions use allowed children and preserve leaf actions."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

import pytest

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("with_workers", [False, True])
def test_node_actions_menu(with_workers):
    nodes = [
        {"id": "root", "parent_id": None, "node_type": "topic", "title": "Исследование"},
        {"id": "direction", "parent_id": "root", "node_type": "direction", "title": "Поиск решений"},
        {"id": "solution", "parent_id": "direction", "node_type": "program", "title": "Механизмы памяти"},
        {"id": "method", "parent_id": "solution", "node_type": "method", "title": "Проверка памяти",
         "has_kanban": True, "board_id": "board", "research_questions": [
             {"id": "q", "question": "Помогает ли память?", "narrative": "Нужна проверка.", "certainty": "tentative"}]},
    ]
    project = {"id": "actions", "title": "Исследование", "nodes": nodes, "boards": {
        "board": {"id": "board", "owner_node_id": "method", "cards": [], "columns": [
            {"id": "backlog", "title": "Backlog", "order": 0}]}}}

    if with_workers:
        project["boards"]["board"]["cards"] = [{"id": "work", "title": "Проверка", "column_id": "running"}]

    def api(route):
        path = urlparse(route.request.url).path
        data = {"/projects/grouped": {"groups": [], "ungrouped": [project]},
                "/projects": [project], "/projects/actions": project,
                "/meta/node-types": {}, "/desktop/archived-trees": {"ids": []},
                "/projects/actions/kanban/running-activity": {"items": [{"card_id": "work", "authors": ["Zoya", "Nikita", "Olga", "Anna", "Alex"]}]}}.get(path, {})
        route.fulfill(json=data, headers={"Access-Control-Allow-Origin": "*"})

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(ROOT / "web")))
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.route("http://127.0.0.1:8010/**", api)
            page.route("https://avatars.githubusercontent.com/**", lambda route: route.abort())
            page.add_init_script("localStorage.setItem('koi-view-mode','researcher'); localStorage.setItem('koi-app-variant','quick');")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}/?project=actions")
            expect(page.locator('.map-node.program .node-label')).to_have_text("Инженерное решение")
            menu = page.locator('.node-action-menu:popover-open')
            direction = page.locator('[data-node-id="direction"]')
            direction.hover()
            if with_workers:
                expect(page.locator('#node-workers-panel')).to_have_class("node-workers-panel is-visible")
                out = ROOT / ".run/ui-screenshots"
                out.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(out / "node-controls-workers.png"))
                assert page.evaluate("""() => {
                    const panel = document.querySelector('#node-workers-panel').getBoundingClientRect();
                    const viewport = document.querySelector('.mindmap-viewport').getBoundingClientRect();
                    const node = document.querySelector('[data-node-id=direction] .map-node').getBoundingClientRect();
                    const overlap = Math.max(0, Math.min(panel.right, node.right) - Math.max(panel.left, node.left))
                        * Math.max(0, Math.min(panel.bottom, node.bottom) - Math.max(panel.top, node.top));
                    return panel.width <= 240 && panel.height <= viewport.height / 3 + 1 && overlap === 0
                        && panel.left >= viewport.left && panel.right <= viewport.right && panel.bottom <= viewport.bottom;
                }""")
            assert page.locator('.node-actions').evaluate_all("els => els.filter(el => getComputedStyle(el).opacity === '1').length") == 1
            assert page.locator('.node-actions-trigger').evaluate_all("els => els.every(el => Math.abs(el.getBoundingClientRect().width - 28) < 0.2)")
            direction.get_by_role("button", name="Действия с узлом «Поиск решений»").click()
            expect(menu.get_by_role("button", name="Добавить: Метод", exact=True)).to_be_visible()
            expect(page.locator("#node-workers-panel")).to_be_hidden()
            expect(menu.get_by_role("button", name="Добавить: Инженерное решение", exact=True)).to_be_visible()
            expect(menu.get_by_role("button", name="Добавить: Причина", exact=True)).to_have_count(0)
            assert menu.evaluate("""el => {
                const divider = el.querySelector('[role=separator]');
                const help = el.querySelector('.node-type-help-trigger');
                const method = el.querySelector('[data-node-type=method]');
                const solution = el.querySelector('[data-node-type=program]');
                return !!(divider.compareDocumentPosition(help) & Node.DOCUMENT_POSITION_FOLLOWING)
                    && getComputedStyle(method, '::before').backgroundColor !== getComputedStyle(solution, '::before').backgroundColor;
            }""")
            page.keyboard.press("End")
            expect(menu.get_by_role("button", name="Удалить узел «Поиск решений»")).to_be_focused()
            page.keyboard.press("Escape")
            expect(menu).to_have_count(0)
            direction.hover()
            direction.locator('.node-actions-trigger').click()
            menu.get_by_role("button", name="Добавить: Инженерное решение", exact=True).click()
            expect(page.locator('#node-modal')).to_be_visible()
            expect(page.locator('#add-child-form select[name="node_type"]')).to_have_value("program")
            expect(page.locator('#add-child-form input[name="title"]')).to_have_attribute("placeholder", "Название инженерного решения")
            page.keyboard.press("Escape")
            method = page.locator('[data-node-id="method"]')
            expect(method.locator('.method-questions-trigger')).to_have_count(0)
            for theme in ("light", "dark"):
                page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
                method.hover()
                method.locator('.node-actions-trigger').click()
                expect(menu.get_by_role("button", name="Выводы по экспериментам")).to_have_count(0)
                expect(menu.get_by_role("button", name="Связь с родителем")).to_have_count(0)
                expect(menu.get_by_role("button", name="Добавить:", exact=False)).to_have_count(0)
                assert menu.bounding_box()["x"] >= 0
                out = ROOT / ".run/ui-screenshots"
                out.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(out / f"node-actions-{theme}.png"))
                page.keyboard.press("Escape")
                method.locator(".map-node").click()
                page.locator("#kanban-questions").click()
                expect(page.locator('#method-questions-modal')).to_be_visible()
                page.keyboard.press("Escape")
                direction.hover()
                direction.locator('.node-actions-trigger').click()
                expect(menu.get_by_role("button", name="Добавить: Метод", exact=True)).to_be_visible()
                page.screenshot(path=str(out / f"node-additions-{theme}.png"))
                page.keyboard.press("Escape")
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
