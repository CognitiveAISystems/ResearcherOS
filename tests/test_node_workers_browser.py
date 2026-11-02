"""The tree worker panel displays every contributor once."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

import pytest
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("variant", ["quick", "light"])
def test_node_workers_show_multiple_contributors(variant):
    project = {"id": "workers", "title": "Исследование", "nodes": [
        {"id": "p", "node_type": "problem", "title": "Повторение ошибок", "parent_id": None},
        {"id": "m", "node_type": "method", "title": "Память", "parent_id": "p", "has_kanban": True, "board_id": "b"},
    ], "boards": {"b": {"id": "b", "owner_node_id": "m", "columns": [
        {"id": "running", "title": "В работе", "order": 0}], "cards": [
        {"id": "first", "board_id": "b", "column_id": "running", "title": "Первый опыт"},
        {"id": "second", "board_id": "b", "column_id": "running", "title": "Второй опыт"},
    ]}}}
    activity = {"items": [
        {"card_id": "first", "authors": ["alice", "bob"], "author": "alice, bob"},
        {"card_id": "second", "authors": ["alice"], "author": "alice"},
    ]}

    def api(route):
        path = urlparse(route.request.url).path
        data = {
            "/projects/grouped": {"groups": [], "ungrouped": [project]},
            "/projects": [project], "/projects/workers": project,
            "/projects/workers/kanban/running-activity": activity,
            "/meta/node-types": {}, "/desktop/archived-trees": {"ids": []},
        }.get(path, {})
        route.fulfill(json=data, headers={"Access-Control-Allow-Origin": "*"})

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(ROOT / "web")))
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("http://127.0.0.1:8010/**", api)
            # Avoid relying on external GitHub availability for this UI check.
            page.route("https://avatars.githubusercontent.com/**", lambda route: route.fulfill(
                content_type="image/svg+xml", body='<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28"><circle cx="14" cy="14" r="14" fill="gray"/></svg>'
            ))
            page.add_init_script(f"localStorage.setItem('koi-view-mode','researcher'); localStorage.setItem('koi-app-variant','{variant}');")
            page.goto(f"http://127.0.0.1:{server.server_port}/?project=workers")
            node = page.locator('[data-node-id="p"] .map-node.problem').first
            expect(node).to_be_visible()
            node.hover()
            panel = page.locator('#node-workers-panel')
            expect(panel).to_be_visible()
            expect(panel.locator('.node-workers-panel__nick')).to_have_text(["@alice", "@bob"])
            expect(panel.locator('img')).to_have_count(2)
            for theme in ('light', 'dark'):
                page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
                out = ROOT / '.run/ui-screenshots'
                out.mkdir(parents=True, exist_ok=True)
                panel.screenshot(path=str(out / f'node-workers-{variant}-{theme}.png'))
            activity["items"] = [{"card_id": "first", "authors": [], "author": ""}]
            page.reload()
            node.hover()
            expect(panel.locator('.node-workers-panel__nick')).to_have_text(["Автор не указан"])
            expect(panel.locator('img')).to_have_count(0)
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
