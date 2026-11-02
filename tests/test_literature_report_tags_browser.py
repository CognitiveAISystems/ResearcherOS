"""Report scopes switch without altering the set used for synthesis."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import sync_playwright


def test_report_tags_and_back_navigation():
    root = Path(__file__).resolve().parents[1]
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(SimpleHTTPRequestHandler, directory=str(root / 'web')))
    Thread(target=server.serve_forever, daemon=True).start()
    source = (root / 'web/literature.js').read_text().split('init().catch(')[0]
    source += '''window.reportTest = (run) => {
      latestPaperAnswerRun = run;
      activeReadingView = READING_VIEW_RESUME;
      bindLiteratureUiEvents();
      setWorkspaceSplit(true);
      renderClusterResults(run);
      renderLiteratureHistory([{...run, run_id: "demo-run", status: "ready"}]);
      document.getElementById("rw-related-pane").classList.remove("hidden");
    };'''
    run = {'question': 'Как методы учитывают ограничения?', 'papers': [], 'clusters': [
        {'key': 'a', 'label': 'Явные ограничения', 'answer': 'Ограничения заданы в оптимизации.', 'rationale': 'Общая целевая функция.'},
        {'key': 'b', 'label': 'Проверка результата', 'answer': 'Ограничения проверяются после генерации.'}],
        'report_markdown': '# Общий ответ\nСравнение всех подходов.'}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.route('**/literature.js*', lambda route: route.fulfill(body=source, content_type='text/javascript'))
            page.route('**/api/**', lambda route: route.fulfill(json={}))
            page.goto(f'http://127.0.0.1:{server.server_port}/literature.html')
            page.wait_for_function('!!window.reportTest')
            page.evaluate('(run) => window.reportTest(run)', run)
            nav = page.locator('#rw-cluster-nav')
            assert nav.locator('button').all_text_contents() == ['#General', '#Cluster-1', '#Cluster-2']
            assert nav.locator('input').count() == 0
            assert page.evaluate("""() => {
              const diagram = document.getElementById('rw-cluster-venn-slot');
              const related = document.getElementById('rw-related-pane');
              const tags = document.getElementById('rw-cluster-nav');
              return !!(diagram.compareDocumentPosition(related) & Node.DOCUMENT_POSITION_FOLLOWING)
                && !!(related.compareDocumentPosition(tags) & Node.DOCUMENT_POSITION_FOLLOWING);
            }""")
            assert not page.locator('#rw-report-markdown').is_visible()
            nav.get_by_text('#Cluster-1', exact=True).click()
            detail = page.locator('#rw-cluster-detail')
            assert 'Ограничения заданы в оптимизации.' in detail.inner_text()
            assert 'Общая целевая функция.' in detail.inner_text()
            assert page.locator('.rw-cluster-answer').is_visible()
            page.screenshot(path=str(root / '.run/ui-screenshots/report-answer-light.png'))
            page.evaluate("document.documentElement.dataset.theme = 'dark'")
            page.screenshot(path=str(root / '.run/ui-screenshots/report-answer-dark.png'))
            nav.get_by_text('#Cluster-2', exact=True).click()
            assert 'Основание группировки не указано' in detail.inner_text()
            nav.get_by_text('#General', exact=True).click()
            assert not detail.is_visible()
            for theme in ['light', 'dark']:
                page.evaluate('(theme) => document.documentElement.dataset.theme = theme', theme)
                for width in [2048, 1440, 768, 390, 320]:
                    page.set_viewport_size({'width': width, 'height': 1000})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (theme, width)
                    assert page.locator('#rw-report-back').is_visible()
                    assert page.locator('#rw-reading-page').bounding_box()['width'] <= 1024
                    diagram = page.locator('#rw-cluster-venn-slot').bounding_box()
                    related = page.locator('#rw-related-pane').bounding_box()
                    assert abs(diagram['width'] - related['width']) < 2
                    page.screenshot(path=str(root / f'.run/ui-screenshots/report-tags-{theme}-{width}.png'))
            page.locator('#rw-report-back').click()
            assert not page.locator('#rw-workspace').evaluate('(el) => el.classList.contains("is-split")')
            assert page.locator('#rw-browser .rw-history-inline').count() == 1
            # General also covers runs which have cluster answers but no synthesis yet.
            run['report_markdown'] = ''
            page.evaluate('(run) => window.reportTest(run)', run)
            assert not page.locator('#rw-report-markdown').is_visible()
            assert not page.locator('#rw-library-column').is_visible()
            assert not page.locator('.rw-clusters-top-actions').is_visible()
            browser.close()
    finally:
        server.shutdown()
