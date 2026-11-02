"""Verify morphology's process/report flow without launching a paid agent."""
from pathlib import Path
from threading import Thread
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from functools import partial

from playwright.sync_api import sync_playwright


def test_process_progress_and_report_transition():
    root = Path(__file__).resolve().parents[1]
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(root / "web")))
    Thread(target=server.serve_forever, daemon=True).start()
    state = {"ready": False, "failed": False, "explanation": False, "explain_calls": 0}
    paper = {"title": "Example paper", "url": "https://example.org/paper"}
    run = {"run_id": "run-1", "paper": paper, "conversation_id": "chat-1"}
    def respond(route):
        path = route.request.url.split("/api", 1)[-1]
        data = {}
        if path.endswith("/activity"):
            data = {"items": [{"events": [{"at": "2026-11-01T12:00:00Z", "message": "Текст статьи загружен"}]}]}
        elif path.endswith("/morphology/explain"):
            state["explain_calls"] += 1
            data = {"conversation_id": "chat-e"}
        elif "/agent-conversations/chat-e" in path:
            data = {"items": [{"status": "answered" if state["explanation"] else "processing", "answer": "Связка объяснена."}]}
        elif "/agent-conversations/" in path:
            data = {"items": [{"status": "answered" if state["failed"] else "processing",
                               "answer_kind": "warning", "answer": "Запуск прерван"}],
                    "live": {"text": "Проверяю дословные цитаты."}}
        elif path.endswith("/morphology/run-1"):
            data = {**run, "status": "ready" if state["ready"] else "staged", "has_article": True,
                    "claims": {"claims": []}}
            if state["ready"]:
                data.update(morphology={"nodes": [{"id": "n1", "role": "problem", "statement": "Проверяемая проблема", "grounding": "quoted"}], "edges": []}, report_markdown="# Готовый отчёт")
        elif path.endswith("/morphology"):
            data = {"runs": [{**run, "status": "staged"}]}
        elif path.endswith("/backends"):
            data = {"cli": []}
        route.fulfill(json=data)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.add_init_script("window.__KOI_API_BASE__='/api'; sessionStorage.setItem('koi-morph-paper', " + repr(__import__('json').dumps(paper)) + ");")
            page.route("**/api/**", respond)
            url = f"http://127.0.0.1:{server.server_port}/morphology.html?project=demo&run=run-1"
            page.goto(url)
            page.locator("#morph-panel-process").wait_for(state="visible")
            page.wait_for_function("document.querySelector('#morph-process-message').textContent.includes('цитаты')")
            assert not page.locator(".morph-inspector").is_visible()
            assert page.locator(".morph-main").evaluate("(e)=>getComputedStyle(e).backgroundColor") == "rgb(255, 255, 255)"
            assert "Текст статьи загружен" in page.locator("#morph-process-events").inner_text()
            page.screenshot(path=str(root / ".run/ui-screenshots/morphology-process.png"))
            state["ready"] = True
            page.locator("#morph-panel-report").wait_for(state="visible", timeout=10000)
            assert "Готовый отчёт" in page.locator("#morph-report-body").inner_text()
            page.screenshot(path=str(root / ".run/ui-screenshots/morphology-report.png"))
            page.locator('[data-tab="graph"]').click()
            original_width = page.locator(".morph-main").bounding_box()["width"]
            page.locator("#morph-toggle-sidebar").click()
            assert not page.locator(".morph-side").is_visible()
            assert page.locator(".morph-main").bounding_box()["width"] > original_width
            page.locator("#morph-toggle-inspector").click()
            assert not page.locator(".morph-inspector").is_visible()
            assert page.locator("#morph-toggle-sidebar").is_visible()
            assert page.locator("#morph-toggle-inspector").is_visible()
            page.reload()
            page.locator('[data-tab="graph"]').click()
            assert not page.locator(".morph-side").is_visible()
            assert not page.locator(".morph-inspector").is_visible()
            page.locator("#morph-toggle-sidebar").click()
            page.locator("#morph-toggle-inspector").click()
            assert page.locator(".morph-side").is_visible()
            assert page.locator(".morph-inspector").is_visible()
            page.locator('.morph-node').click()
            page.locator('#morph-explain-node').wait_for(state="visible")
            page.locator('#morph-explain-node').hover()
            assert page.locator('#morph-explain-tooltip').is_visible()
            page.locator('#morph-explain-node').click()
            page.wait_for_function("document.querySelector('#morph-explain-note-text').textContent.includes('готовит')")
            assert state["explain_calls"] == 1
            assert page.locator('#morph-explain-node').is_disabled()
            state["explanation"] = True
            page.wait_for_function("document.querySelector('#morph-explain-note-text').textContent.includes('Связка объяснена')")
            assert page.locator('#morph-explain-node').is_enabled()
            graph_bounds = page.locator("#morph-canvas").bounding_box()
            legend_bounds = page.locator("#morph-legend").bounding_box()
            page.locator("#morph-explain-note-text").evaluate("e => e.textContent = 'Длинное пояснение связки. '.repeat(200)")
            assert page.locator("#morph-canvas").bounding_box() == graph_bounds
            assert page.locator("#morph-legend").bounding_box() == legend_bounds
            assert page.locator(".morph-explain-content").evaluate("e => e.scrollHeight > e.clientHeight")
            assert page.locator("#morph-explain-note").bounding_box()["height"] <= 352
            page.screenshot(path=str(root / ".run/ui-screenshots/morphology-node-explanation.png"))
            page.locator(".morph-explain-content").focus()
            page.keyboard.press("Escape")
            assert not page.locator("#morph-explain-note").is_visible()

            page.locator("#morph-canvas").evaluate("""svg => {
                for (let n = 0; n < 20; n++) svg.dispatchEvent(new WheelEvent('wheel', {deltaY: -100, cancelable: true}));
            }""")
            transform = page.locator("#morph-viewport").get_attribute("transform")
            assert float(transform.split("scale(")[1].split(")")[0]) > 2.2
            state.update(ready=False, failed=True)
            page.reload()
            page.wait_for_function("document.querySelector('#morph-status').textContent.includes('прерван')")
            assert page.locator("#morph-panel-process").is_visible()
            assert page.locator("#morph-run").is_enabled()
            for width in [768, 390, 320]:
                page.set_viewport_size({"width": width, "height": 1000})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            browser.close()
    finally:
        server.shutdown()


def test_graph_pan_tracks_pointer_at_different_svg_and_graph_scales():
    source = (Path(__file__).resolve().parents[1] / "web/morphology.js").read_text()
    coordinates = source[source.index("function toSvgPoint("):source.index("function attachNodeInteractions(")]
    interactions = source[source.index("function attachCanvasInteractions("):source.index("function renderLegend(")]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 800, "height": 600})
        for svg_ratio, graph_scale in [(0.2, 1), (0.5, 4), (1, 0.3), (2, 2)]:
            page.set_content('<svg id="canvas" width="600" height="400" viewBox="0 0 '
                             + str(600 / svg_ratio) + ' ' + str(400 / svg_ratio)
                             + '"><g id="morph-viewport"></g></svg>')
            page.add_script_tag(content="""
                var selectedNodeId = "";
                var viewTransform = {x: 40, y: 40, k: 1};
                function clearInspector() { throw Error("Pan must not clear selection"); }
                function applyTransform() {
                    document.getElementById("morph-viewport").setAttribute("transform",
                        "translate(" + viewTransform.x + " " + viewTransform.y + ") scale(" + viewTransform.k + ")");
                }
            """ + coordinates + interactions)
            page.evaluate("(k) => { viewTransform.k = k; applyTransform(); attachCanvasInteractions(document.getElementById('canvas')); }", graph_scale)
            before = page.locator("#morph-viewport").evaluate("e => ({x:e.getScreenCTM().e, y:e.getScreenCTM().f})")
            page.mouse.move(120, 120)
            page.mouse.down()
            page.mouse.move(240, 160, steps=12)
            page.mouse.up()
            after = page.locator("#morph-viewport").evaluate("e => ({x:e.getScreenCTM().e, y:e.getScreenCTM().f})")
            assert abs(after["x"] - before["x"] - 120) < 0.1
            assert abs(after["y"] - before["y"] - 40) < 0.1
        browser.close()
