"""Render new node/edge roles, edit a hypothesis, and preserve method navigation."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

import pytest

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("legacy", [False, True])
def test_research_tree_render(legacy):
    project = {"id": "new-tree", "title": "Малые языковые агенты", "nodes": [
        {"id": "t", "parent_id": None, "node_type": "topic", "title": "Малые языковые агенты"},
        {"id": "p", "parent_id": "t", "node_type": "problem", "title": "Повторение ошибок"},
        {"id": "d", "parent_id": "t", "node_type": "direction", "title": "Непрерывное обучение"},
        {"id": "pr", "parent_id": "d", "node_type": "program", "title": "Обучение на опыте", "edge_type": "direction", "edge_label": "Скрытая подпись направления"},
        {"id": "m", "parent_id": "p", "node_type": "method", "title": "Память ошибок", "edge_type": "hypothesis", "edge_label": "Память уменьшит повторы", "has_kanban": True, "board_id": "b"},
        {"id": "e", "parent_id": "p", "node_type": "method", "title": "Измерение повторов", "edge_type": "evidence", "edge_label": "Проверить частоту"},
    ], "boards": {"b": {"id": "b", "owner_node_id": "m", "cards": [], "columns": [{"id": "backlog", "title": "Backlog", "order": 0}]}}}

    if legacy:
        project["nodes"].append({"id": "c", "parent_id": "p", "node_type": "cause", "title": "Старая причина", "description": "Описание причины"})
        project["nodes"][4]["parent_id"] = "h"
        project["nodes"][4].pop("edge_type")
        project["nodes"][4].pop("edge_label")
        project["nodes"][5]["parent_id"] = "proof"
        project["nodes"].extend([
            {"id": "h", "parent_id": "c", "node_type": "remediation", "title": "Память уменьшит повторы", "description": "Исходное описание гипотезы"},
            {"id": "m2", "parent_id": "h", "node_type": "method", "title": "Сравнение вариантов памяти"},
            {"id": "proof", "parent_id": "c", "node_type": "cause_evidence", "title": "Проверить частоту"},
        ])

    def api(route):
        path = urlparse(route.request.url).path
        if route.request.method == "PATCH":
            next(n for n in project["nodes"] if n["id"] == path.split("/")[-1]).update(route.request.post_data_json)
        data = {"/projects/grouped": {"groups": [], "ungrouped": [project]},
                "/projects": [project], "/projects/new-tree": project,
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
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("http://127.0.0.1:8010/**", api)
            page.add_init_script("localStorage.setItem('koi-view-mode','researcher'); localStorage.setItem('koi-app-variant','quick');")
            page.goto(f"http://127.0.0.1:{server.server_port}/?project=new-tree")
            expect(page.locator('.map-node.topic')).to_have_count(1)
            expect(page.locator('.map-node.program')).to_have_count(2 if legacy else 1)
            caption = page.get_by_role("button", name="Гипотеза: Память уменьшит повторы", exact=True)
            expect(caption).to_be_visible()
            expect(page.get_by_role("button", name="Направление: Скрытая подпись направления", exact=True)).to_have_count(0)
            expect(page.get_by_role("button", name="Доказательство: Проверить частоту", exact=True)).to_have_count(0)
            caption.click()
            expect(page.locator('.modal:not(.hidden)')).to_have_count(0)
            caption.dblclick()
            editor = page.get_by_role("textbox", name="Комментарий связи")
            expect(editor).to_be_focused()
            editor.fill("Отменённое изменение")
            editor.press("Escape")
            expect(caption).to_contain_text("Память уменьшит повторы")
            caption.dblclick()
            editor.fill("Память уменьшит повторение ошибок")
            for theme in ("light", "dark"):
                page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
                out = ROOT / ".run/ui-screenshots"
                out.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(out / f"edge-inline-comment-{theme}.png"))
            editor.press("Enter")
            updated = page.get_by_role("button", name="Гипотеза: Память уменьшит повторение ошибок", exact=True)
            expect(updated).to_be_visible()
            page.reload()
            expect(updated).to_be_visible()
            updated.dblclick()
            editor.fill("Проверяем память")
            editor.press("Tab")
            expect(page.get_by_role("button", name="Гипотеза: Проверяем память", exact=True)).to_be_visible()
            if not legacy:
                assert project["nodes"][4]["edge_type"] == "hypothesis"
            for theme in ("light", "dark"):
                page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
                assert page.evaluate("""() => {
                    const css = s => getComputedStyle(document.querySelector(s));
                    return css('.map-node.problem').backgroundImage === css('.map-node.direction').backgroundImage
                      && css('.map-node.topic').backgroundImage !== css('.map-node.problem').backgroundImage
                      && css('.map-node.program').backgroundImage !== css('.map-node.method').backgroundImage
                      && css('.tree-edge-evidence').strokeDasharray !== 'none';
                }""")
                assert page.evaluate("""() => {
                    const viewport = document.querySelector('#mindmap-viewport').getBoundingClientRect();
                    return [...document.querySelectorAll('.tree-edge-caption')].every(label => {
                        const rect = label.getBoundingClientRect();
                        return rect.left >= viewport.left && rect.right <= viewport.right
                          && label.scrollHeight <= label.closest('foreignObject').getBoundingClientRect().height / (rect.width / 180) + 1;
                    });
                }""")
                out = ROOT / ".run/ui-screenshots"
                out.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(out / f"research-tree-{'legacy' if legacy else 'new'}-{theme}.png"))
            page.get_by_role("button", name="Метод Память ошибок", exact=True).click()
            expect(page.locator('#kanban-modal')).to_be_visible()
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
