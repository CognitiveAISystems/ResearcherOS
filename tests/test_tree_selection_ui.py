"""Selection follows project ownership, survives redraws, and stays below nodes."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os
from threading import Thread
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def test_tree_selection_browser():
    # Shared node IDs deliberately catch selection leaking between projects.
    projects = {
        pid: {
            "id": pid, "title": title, "boards": {},
            "nodes": [
                {"id": "root", "parent_id": None, "node_type": "problem", "title": title},
                {"id": "cause", "parent_id": "root", "node_type": "cause", "title": "Недостаточно обучающих примеров"},
                {"id": "solution", "parent_id": "cause", "node_type": "remediation", "title": "Использовать сильную модель для разметки"},
                {"id": "method", "parent_id": "solution", "node_type": "method", "title": "Сравнить качество на новых задачах"},
            ],
        }
        for pid, title in (("alpha", "Как улучшить обучение агента"), ("beta", "Как проверить перенос навыков"))
    }
    projects["alpha"]["nodes"].extend([
        {"id": "evidence", "parent_id": "cause", "node_type": "cause_evidence", "title": "Проверить распознавание визуальных символов"},
        {"id": "memory", "parent_id": "cause", "node_type": "remediation", "title": "Правила из записи прохождения"},
        {"id": "reasoning", "parent_id": "cause", "node_type": "remediation", "title": "Правила сцены задаются в рассуждении напрямую"},
        {"id": "memory-method", "parent_id": "memory", "node_type": "method", "title": "Поиск эпизодов с соседними шагами"},
        {"id": "reasoning-method", "parent_id": "reasoning", "node_type": "method", "title": "Правила в рассуждении против самостоятельного разбора"},
    ])
    projects["alpha"]["nodes"][0]["title"] = "Языковые и зрительные модели плохо планируют в визуально-абстрактных средах со скрытыми закономерностями"
    grouped = {"groups": [], "ungrouped": list(projects.values())}

    def api(route):
        path = urlparse(route.request.url).path.removeprefix("/api")
        data = {
            "/projects/grouped": grouped,
            "/projects": list(projects.values()),
            "/meta/node-types": {},
            "/desktop/archived-trees": {"ids": []},
            **{f"/projects/{pid}": project for pid, project in projects.items()},
        }.get(path, {})
        route.fulfill(json=data, headers={"Access-Control-Allow-Origin": "*"})

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    external = os.environ.get("RESEARCHOS_TREE_TEST_URL", "").rstrip("/")
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(ROOT / "web")))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("http://127.0.0.1:8010/**", api)
            if external:
                page.route(external + "/api/**", api)
            page.add_init_script("localStorage.setItem('koi-view-mode', 'chief')")
            page.goto(f"{external or f'http://127.0.0.1:{server.server_port}'}/?project=alpha")
            expect(page.locator(".lab-tree-edges")).to_have_count(2)

            def selected(pid):
                expect(page.locator(".lab-tree-edges.is-active")).to_have_attribute("data-project-id", pid)
                expect(page.locator(".lab-project-nodes.is-active")).to_have_attribute("data-project-id", pid)
                expect(page.locator(f'.node-wrap.is-active-tree:not(.add-slot-wrap)[data-project-id="{pid}"]')).to_have_count(len(projects[pid]["nodes"]))
                expect(page.locator(f'.node-wrap.is-active-tree:not([data-project-id="{pid}"])')).to_have_count(0)
                expect(page.locator(f'.lab-project-frame[data-project-id="{pid}"]')).to_have_attribute("aria-pressed", "true")

            selected("alpha")
            out = ROOT / ".run/ui-screenshots/main-tree-focus"
            out.mkdir(parents=True, exist_ok=True)
            for theme in ("dark", "light"):
                page.evaluate("theme => document.documentElement.dataset.theme = theme", theme)
                page.wait_for_timeout(250)
                checks = page.evaluate("""() => {
                    const css = selector => getComputedStyle(document.querySelector(selector));
                    const active = css('.lab-tree-edges.is-active .edge:not(.edge-add)');
                    const idle = css('.lab-tree-edges:not(.is-active) .edge');
                    const frame = css('.lab-project-frame.is-active');
                    return {
                        behind: +css('.edges').zIndex < +css('.nodes-layer').zIndex,
                        stronger: parseFloat(active.strokeWidth) > parseFloat(idle.strokeWidth),
                        glow: active.filter !== 'none' && idle.filter === 'none',
                        noBox: frame.boxShadow === 'none' && frame.outlineStyle === 'none',
                        noRepeatedRings: css('.node-wrap.is-active-tree .cause').outlineStyle === 'none',
                        reducedMotion: css('.lab-project-nodes.is-active').transitionDuration === '0s',
                        lifted: css('.lab-project-nodes.is-active').transform !== 'none',
                        matchingLift: css('.lab-project-nodes.is-active').transform === css('.lab-tree-edges.is-active').transform,
                        nodeShadow: css('.lab-project-nodes.is-active .map-node').filter !== 'none',
                    };
                }""")
                assert all(checks.values()), checks
                contrast = page.evaluate("""() => {
                    const ctx = document.createElement('canvas').getContext('2d');
                    const rgb = color => {
                        ctx.fillStyle = color; ctx.fillRect(0, 0, 1, 1);
                        return [...ctx.getImageData(0, 0, 1, 1).data].slice(0, 3);
                    };
                    const luminance = rgb => rgb.map(v => v / 255)
                        .map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4)
                        .reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
                    const bg = rgb(getComputedStyle(document.querySelector('.mindmap-canvas')).backgroundColor);
                    return ['.is-active', ':not(.is-active)'].map(state => {
                        const css = getComputedStyle(document.querySelector(`.lab-tree-edges${state} .edge`));
                        const fg = rgb(css.stroke).map((v, i) => v * +css.opacity + bg[i] * (1 - +css.opacity));
                        const values = [luminance(bg), luminance(fg)].sort((a, b) => b - a);
                        return (values[0] + .05) / (values[1] + .05);
                    });
                }""")
                assert min(contrast) >= 3, (theme, contrast)
                page.locator("#mindmap").screenshot(path=str(out / f"tree-selection-{theme}.png"))

            # The frame is a native button and announces its selected state.
            page.locator('.lab-project-frame[data-project-id="beta"]').focus()
            page.keyboard.press("Enter")
            selected("beta")
            page.locator('#btn-projects-toggle').click()
            page.locator('#project-list .project-list__btn[data-project-id="alpha"]').click()
            selected("alpha")
            page.locator('#btn-projects-toggle').click()

            page.keyboard.press("Tab")
            page.locator('.node-wrap[data-project-id="alpha"] .map-node.problem').focus()
            assert page.locator('.node-wrap[data-project-id="alpha"] .map-node.problem').evaluate(
                "el => getComputedStyle(el).outlineWidth === '3px'")

            # Clicking a node uses the same selection path as the project list.
            page.locator('.node-wrap[data-project-id="beta"] .map-node.problem').click()
            selected("beta")
            page.keyboard.press("Escape")
            page.locator("#btn-zoom-fit-project").click()
            page.wait_for_timeout(450)
            selected("beta")
            page.locator("#mindmap").screenshot(path=str(out / "tree-selection-detail.png"))
            page.set_viewport_size({"width": 1280, "height": 900})
            page.wait_for_timeout(350)
            # Spatial attention may choose another tree when the overview is refitted.
            selected(page.locator(".lab-tree-edges.is-active").get_attribute("data-project-id"))
            page.locator("#btn-zoom-fit-lab").click()
            page.locator('.node-wrap[data-project-id="alpha"] .map-node.problem').click()
            selected("alpha")
            assert not errors, errors

            page.emulate_media(forced_colors="active")
            assert page.locator('.lab-project-nodes.is-active .map-node').first.evaluate(
                "el => getComputedStyle(el).filter === 'none'")
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    test_tree_selection_browser()
    print("PASS: tree focus, shared IDs, keyboard/list/node selection, zoom/redraw, contrast, themes, reduced motion and forced colors")
