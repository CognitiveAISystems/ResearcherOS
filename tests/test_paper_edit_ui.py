"""Browser contract for the edit-task panel, with deterministic agent responses."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def test_paper_edit_panel_browser(tmp_path):
    html = (ROOT / "web/index.html").read_text()
    start = html.index('<details id="paper-edit-panel"')
    stop = html.index('<div id="paper-tex-scroll"', start)
    app_source = (ROOT / "web/app.js").read_text()
    anchor = app_source[app_source.index('function paperProposalAnchorHtml('):app_source.index('function bindPaperCommentMarginEvents(')]
    diff = app_source[app_source.index('function paperProposalDiffHtml('):app_source.index('function paperProposalAnchorHtml(')]
    harness = f'''<!doctype html><html data-theme="dark"><head>
      <link rel="stylesheet" href="/web/styles.css"><style>#proposal-fixture {{position:relative;margin-top:1rem}} #proposal-fixture .paper-proposal-anchor {{position:relative}}</style></head><body>
      <main style="max-width:900px;margin:24px auto"><h1>Правки статьи</h1>{html[start:stop]}
      <div id="proposal-fixture"></div></main><script type="module">
      import {{ createPaperEditPanel }} from '/web/paper-edit-tasks.js';
      window.tasks = []; window.calls = []; window.reviews = []; window.fail = false;
      window.panel = createPaperEditPanel({{
        api: {{
          paperEditTasks: async () => ({{tasks: window.tasks}}),
          startPaperEdit: async (project, slug, prompt, backend) => {{
            if (window.fail) throw Error('Тестовая ошибка запуска');
            window.calls.push({{project, slug, prompt, backend}});
            window.tasks = [{{id:'edit-0123456789abcdef', title:prompt, status:'running'}}];
          }},
          resolvePaperEdit: async () => {{ window.tasks[0].status = 'review'; }},
        }},
        save: async () => {{ window.saved = true; return true; }},
        onReview: async (project, slug) => window.reviews.push([project, slug]),
      }});
      window.panel.open('demo', 'paper');
      const paperState = {{collabProposalResolving:false}};
      const measurePaperLineTop = () => 0;
      const paperCommentAgentBusy = () => false;
      const escapeHtml = text => String(text).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
      {diff}
      {anchor}
      window.showProposal = conflict => {{
        document.getElementById('proposal-fixture').innerHTML = paperProposalAnchorHtml(
          {{id:'p',source:'paper-edit-agent',conflict}},
          {{id:'h',line_start:1,line_end:1,old_text:'Old intro',new_text:'New intro'}});
      }};
      </script></body></html>'''
    class Handler(SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/test-paper':
                self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.end_headers()
                self.wfile.write(harness.encode()); return
            super().do_GET()
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(ROOT)))
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={'width':1440, 'height':900})
            errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}/test-paper')
            page.get_by_text('Попросить агента', exact=True).click()
            page.get_by_label('Что изменить в статье?').fill('Уточнить введение')
            page.get_by_label('Агент', exact=True).select_option('codex')
            page.get_by_role('button', name='Предложить правки').click()
            expect(page.get_by_text('Агент работает с копией…', exact=True)).to_be_visible()
            assert page.evaluate('window.saved')
            assert page.evaluate('window.calls[0].backend') == 'codex'
            expect(page.get_by_role('button', name='Предложить правки')).to_be_disabled()
            page.evaluate("window.tasks[0].status='review'; window.tasks[0].answer='Уточнён вклад работы'; window.panel.refresh()")
            expect(page.get_by_text('Правки готовы к проверке', exact=True)).to_be_visible()
            assert page.evaluate('window.reviews.length') > 0
            page.evaluate('window.showProposal(true)')
            expect(page.locator('[data-proposal-hunk-accept]')).to_be_disabled()
            expect(page.locator('[data-proposal-hunk-reject]')).to_be_enabled()
            page.evaluate('window.showProposal(false)')
            expect(page.locator('[data-proposal-hunk-accept]')).to_be_enabled()
            screenshots = ROOT / '.run/ui-screenshots'
            screenshots.mkdir(parents=True, exist_ok=True)
            for theme in ('dark', 'light'):
                page.evaluate('(theme) => document.documentElement.dataset.theme=theme', theme)
                page.screenshot(path=str(screenshots / f'paper-edit-tasks-{theme}.png'), full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            # A refresh after navigation must not show the previous paper's task.
            page.evaluate("window.tasks=[]; window.panel.open('other', 'second')")
            expect(page.get_by_text('Уточнён вклад работы', exact=True)).to_have_count(0)
            page.get_by_label('Что изменить в статье?').fill('Правка')
            page.evaluate('window.fail=true')
            page.get_by_role('button', name='Предложить правки').click()
            expect(page.get_by_role('status')).to_contain_text('Тестовая ошибка запуска')
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown(); server.server_close(); thread.join()
