"""Contextual node actions use allowed children and preserve leaf actions."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def test_node_inline_rename():
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

    writes = []

    def api(route):
        if route.request.method == "PATCH":
            writes.append(route.request.post_data_json)
            target = next(n for n in nodes if n["id"] == urlparse(route.request.url).path.split("/")[-1])
            target.update(route.request.post_data_json)
        path = urlparse(route.request.url).path
        data = {"/projects/grouped": {"groups": [], "ungrouped": [project]},
                "/projects": [project], "/projects/actions": project,
                "/meta/node-types": {}, "/desktop/archived-trees": {"ids": []}}.get(path, {})
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
            page.add_init_script("localStorage.setItem('koi-view-mode','researcher'); localStorage.setItem('koi-app-variant','quick');")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}/?project=actions")
            for theme in ("light", "dark"):
                page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
                node = page.locator('[data-node-id="direction"] .map-node')
                node.dblclick()
                editor = node.get_by_role("textbox", name="Имя узла")
                expect(editor).to_be_focused()
                expect(page.locator('#node-modal')).to_be_hidden()
                editor.fill("Новое имя")
                editor.press("Escape")
                expect(node.locator('.node-title')).to_have_text(nodes[1]["title"])
                assert not writes
                node.dblclick()
                editor.fill(" ")
                editor.press("Enter")
                assert not writes
                node.dblclick()
                editor.fill(f"Имя {theme}")
                out = ROOT / ".run/ui-screenshots"
                out.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(out / f"node-inline-rename-{theme}.png"))
                editor.press("Enter")
                expect(node.locator('.node-title')).to_have_text(f"Имя {theme}")
                assert writes.pop() == {"title": f"Имя {theme}"}
                node.dblclick()
                editor.fill(f"Сохранение {theme}")
                editor.press("Tab")
                expect(node.locator('.node-title')).to_have_text(f"Сохранение {theme}")
                assert writes.pop() == {"title": f"Сохранение {theme}"}
            node.click()
            page.wait_for_timeout(450)
            expect(page.locator('#node-modal')).to_be_hidden()
            node.click(button="right")
            expect(page.locator('#node-modal')).to_be_hidden()
            node.focus()
            node.press("Enter")
            expect(page.locator('#node-modal')).to_be_hidden()
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
