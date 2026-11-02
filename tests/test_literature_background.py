"""Direct literature CLI launch and failure cleanup."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.routers import review
from api.schemas import LiteratureClusterBody


def test_literature_launch_uses_main_chat_worker(monkeypatch, tmp_path):
    from fastapi import BackgroundTasks
    from api.routers import agents
    from koi.agent_chat import conversations
    from koi.literature import cluster_orch
    from api.schemas import LiteratureClusterBody
    seen = {}
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    monkeypatch.setattr(review, "parse_project", lambda _: None)
    monkeypatch.setattr(review, "stage_literature_cluster", lambda *a, **kw: {"run_id": "run-1"})
    monkeypatch.setattr(cluster_orch, "literature_dir", lambda _: tmp_path)
    monkeypatch.setattr(agents, "create_conversation", lambda body: {"item": {"id": "chat-1"}})
    monkeypatch.setattr(conversations, "update", lambda cid, **fields: seen.update(cid=cid, **fields))
    def send(body, background_tasks):
        seen["body"] = body
        seen["tasks"] = background_tasks
        return {"item": {"id": "item-1"}}
    monkeypatch.setattr(agents, "post_agent_chat", send)
    tasks = BackgroundTasks()
    result = review.post_project_literature_cluster_agent("demo", LiteratureClusterBody(
        question="Question", papers=[{"title": "Paper"}], cli_agent="codex"), tasks)
    assert result["conversation_id"] == "chat-1"
    assert seen["kind"] == "literature"
    assert seen["literature_run_id"] == "run-1"
    assert seen["body"].question == "Question"
    assert seen["body"].cli_agent == "codex"
    assert seen["tasks"] is tasks
    assert (run_dir / "chat.json").read_text().find('chat-1') >= 0


def test_literature_prompt_uses_absolute_data_and_bundled_skill(monkeypatch, tmp_path):
    from koi.agent_chat import runner, conversations
    from koi.literature import cluster_orch
    monkeypatch.setattr(runner, "find_item", lambda _: {"project_id": "demo", "conversation_id": "chat-1"})
    monkeypatch.setattr(conversations, "find", lambda _: {"id": "chat-1", "kind": "literature", "literature_run_id": "run-1"})
    monkeypatch.setattr(conversations, "messages", lambda _: [{"question": "Question", "answer": None}])
    monkeypatch.setattr(cluster_orch, "load_literature_run", lambda *a: {"question": "Question"})
    monkeypatch.setattr(cluster_orch, "literature_dir", lambda _: tmp_path)
    prompt = runner._sdk_prompt("item-1")
    assert str(tmp_path / "run-1/input.json") in prompt
    assert str(tmp_path / "run-1") in prompt
    assert "agents/skills/literature-cluster-orchestrator/SKILL.md" in prompt
    assert "Do not open Terminal" in prompt


def test_search_form_sends_request_without_prompt_modal():
    from pathlib import Path
    from playwright.sync_api import sync_playwright

    source = (Path(__file__).resolve().parents[1] / "web/literature.js").read_text()
    handler = source[source.index("async function onLiteratureSearchSubmit("):source.index("function stopLiteratureClusterPoll()")]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_content('<button id="literature-search-button"></button>')
        page.evaluate('''() => {
            window.calls = [];
            window.selectedLiteratureLimit = () => 10;
            window.selectedProjectId = () => "demo";
            window.composeProjectSearchQuery = () => "query";
            window.composeClusterQuestion = () => "question";
            window.literatureResults = [{title: "Paper"}];
            window.getSelectedResults = () => literatureResults;
            window.normalizePaperRecord = p => p;
            window.shouldAutoTranslateQuestion = () => false;
            window.workspaceGenerating = false;
            for (const name of ["showLoader", "setLiteratureStatus", "hideKoiLoader",
                "setWorkspaceSplit", "renderRunPapersSidebar", "updateClustersQuestion",
                "watchLiteratureAgent", "setGeneratingMode", "refreshLiteratureHistory", "hideLoader"])
                window[name] = () => {};
            window.showClusterPromptModal = () => { throw Error("Unexpected prompt modal"); };
            window.KoiApi = {launchLiteratureCluster: async (project, payload) => {
                calls.push({project, payload}); return {run_id: "run-1", count: 1};
            }};
            window.setWorkspaceSplit = value => { if (value) throw Error("Must stay on question list"); };
            window.startLiteratureClusterPoll = () => { throw Error("Must not open report automatically"); };
        }''')
        page.add_script_tag(content=handler)
        page.evaluate('onLiteratureSearchSubmit({preventDefault() {}})')
        assert page.evaluate('calls') == [
            {"project": "demo", "payload": {"question": "question", "papers": [{"title": "Paper"}], "cli_agent": None}},
        ]
        browser.close()



def test_background_agent_shows_status_and_errors_without_chat():
    from pathlib import Path
    from playwright.sync_api import sync_playwright
    root = Path(__file__).resolve().parents[1]
    source = (root / "web/literature.js").read_text()
    functions = source[source.index("async function refreshLiteratureAgent()"):source.index("function watchLiteratureAgent(")]
    html = (root / "web/literature.html").read_text()
    assert 'id="literature-chat' not in html
    assert 'id="literature-cluster-prompt-modal"' not in html
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content('<section id="literature-agent-status" class="hidden"><p id="literature-agent-message"></p><div id="literature-agent-permission"></div><button id="literature-agent-stop" class="hidden"></button></section>')
        page.add_script_tag(content="""
            let literatureConversationId = 'job-1';
            let literatureAgentBusy = false;
            let literatureAgentTimer = null;
            window.stopped = false;
            window.generated = true;
            window.status = '';
            const stopLiteratureClusterPoll = () => stopped = true;
            const setGeneratingMode = value => generated = value;
            const setLiteratureStatus = text => window.status = text;
            window.snapshot = {items:[{question:'Question',status:'processing'}],live:{text:'Internal output'}};
            const KoiApi = {getConversation: async () => snapshot};
        """ + functions)
        page.evaluate('refreshLiteratureAgent()')
        assert page.locator('#literature-agent-message').inner_text() == 'Готовим обзор литературы…'
        assert 'Internal output' not in page.locator('body').inner_text()
        assert not page.locator('#literature-agent-stop').evaluate("e => e.classList.contains('hidden')")
        page.evaluate("snapshot = {items:[{question:'Question',status:'answered',answer:'Лимит исчерпан',answer_kind:'warning'}]}; refreshLiteratureAgent()")
        assert page.evaluate('stopped && !generated')
        assert page.locator('#literature-agent-message').inner_text() == 'Лимит исчерпан'
        browser.close()


def test_question_states_only_ready_report_can_open():
    from pathlib import Path
    from playwright.sync_api import sync_playwright
    root = Path(__file__).resolve().parents[1]
    source = (root / 'web/literature.js').read_text()
    render = source[source.index('function renderLiteratureHistory('):source.index('async function refreshLiteratureHistory(')]
    states = source[source.index('function literatureRunId('):source.index('function resetCancelledLiteratureRunUi(')]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1200, 'height': 800})
        page.set_content('<input id="literature-query"><div id="rw-history-list"></div>')
        page.add_style_tag(path=str(root / 'web/styles.css'))
        page.add_script_tag(content='''
            const escapeHtml = text => String(text).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
            window.opened = [];
            const openLiteratureHistoryRun = id => opened.push(id);
            const cancelLiteratureClusterRun = () => {};
            const setLiteratureStatus = () => {};
        ''' + states + render)
        page.evaluate('''renderLiteratureHistory([
            {run_id:'pending',question:'Какие платформы помогают написать научную статью?',status:'processing',count:10},
            {run_id:'ready',question:'Как оценивать качество обзора литературы?',status:'ready',count:8},
            {run_id:'error',question:'Какие источники доступны?',status:'failed',error:'Лимит агента исчерпан.',count:6}
        ])''')
        assert page.locator('.is-running [data-run-id]').count() == 0
        assert page.locator('.is-running .rw-history-open').count() == 0
        assert page.locator('.is-ready .rw-history-open').count() == 1
        page.locator('[data-run-id="ready"]').click()
        assert page.evaluate('opened') == ['ready']
        page.get_by_role('button', name='Редактировать вопрос').click()
        assert page.locator('#literature-query').input_value() == 'Какие источники доступны?'
        assert page.locator('#literature-query').evaluate('(e) => e === document.activeElement')
        assert page.evaluate('opened') == ['ready']
        page.emulate_media(reduced_motion='reduce')
        assert page.locator('.is-running .rw-history-indicator').evaluate('(e) => getComputedStyle(e).animationName') == 'none'
        page.set_viewport_size({'width':320, 'height':800})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        browser.close()


def test_history_reflects_worker_state_and_report_readiness(monkeypatch, tmp_path):
    import json
    from koi.literature import cluster_orch
    from koi.agent_chat import conversations
    monkeypatch.setattr(cluster_orch, 'literature_dir', lambda _: tmp_path)
    monkeypatch.setattr(cluster_orch, '_load_index', lambda _: [{'run_id':'run-1','status':'staged'}])
    run = tmp_path / 'run-1'
    run.mkdir()
    (run / 'chat.json').write_text(json.dumps({'conversation_id':'job-1'}))
    monkeypatch.setattr(conversations, 'messages', lambda _: [{'status':'processing'}])
    assert cluster_orch.list_literature_runs('demo')[0]['status'] == 'processing'
    monkeypatch.setattr(conversations, 'messages', lambda _: [{'status':'answered','answer':'Лимит исчерпан'}])
    assert cluster_orch.list_literature_runs('demo')[0]['status'] == 'failed'
    (run / 'report.md').write_text('Result')
    assert cluster_orch.list_literature_runs('demo')[0]['status'] == 'ready'


def test_delete_ready_review_requires_explicit_report_deletion(monkeypatch, tmp_path):
    import pytest
    from koi.literature import cluster_orch

    monkeypatch.setattr(cluster_orch, 'literature_dir', lambda _: tmp_path)
    run_dir = tmp_path / 'ready-review'
    run_dir.mkdir()
    report = run_dir / 'report.md'
    report.write_text('Saved review', encoding='utf-8')
    monkeypatch.setattr(cluster_orch, '_load_index', lambda _: [{'run_id': 'ready-review'}])
    saved = []
    monkeypatch.setattr(cluster_orch, '_save_index', lambda project, rows: saved.append(rows))
    with pytest.raises(ValueError):
        cluster_orch.delete_literature_run('demo', 'ready-review')
    assert report.read_text() == 'Saved review'
    assert not saved
    cluster_orch.delete_literature_run('demo', 'ready-review', delete_report=True)
    assert not run_dir.exists()
    assert saved == [[]]


def test_delete_review_confirmation_and_active_guard():
    from pathlib import Path
    from playwright.sync_api import sync_playwright

    source = (Path(__file__).resolve().parents[1] / 'web/literature.js').read_text()
    handler = source[source.index('async function deleteLiteratureHistoryRun('):source.index('function renderLiteratureHistory(')]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.add_script_tag(content='''
            let latestPaperAnswerRun = null;
            const selectedProjectId = () => 'demo';
            const literatureRunId = run => run?.run_id || '';
            const resetCancelledLiteratureRunUi = () => {};
            const setLiteratureStatus = () => {};
            const refreshLiteratureHistory = async () => {};
            window.deletions = [];
            window.allowDelete = false;
            window.runStatus = 'ready';
            window.confirm = () => allowDelete;
            const KoiApi = {
                getLiteratureRun: async () => ({status: runStatus, question: 'Review'}),
                deleteLiteratureRun: async (...args) => deletions.push(args)
            };
        ''' + handler)
        page.evaluate("deleteLiteratureHistoryRun('run-1')")
        assert page.evaluate('deletions') == []
        page.evaluate("allowDelete = true; runStatus = 'processing'")
        page.evaluate("deleteLiteratureHistoryRun('run-1')")
        assert page.evaluate('deletions') == []
        page.evaluate("runStatus = 'ready'")
        page.evaluate("deleteLiteratureHistoryRun('run-1')")
        assert page.evaluate('deletions') == [['demo', 'run-1', True]]
        browser.close()


def test_paper_analysis_badge_uses_ready_runs_and_current_project():
    from pathlib import Path
    from playwright.sync_api import sync_playwright

    source = (Path(__file__).resolve().parents[1] / 'web/literature.js').read_text()
    helpers = source[source.index('function paperMorphologyStatus('):source.index('function renderLiteratureResults(')]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content('''<div id="literature-results"><article class="rw-library-item">
          <button class="rw-library-item-morph" data-paper-url="https://arxiv.org/abs/1234.5678"></button>
          <span class="rw-library-analysis-ready hidden">✓ Разбор готов</span>
        </article></div>''')
        page.add_script_tag(content='''
            let paperMorphologyRuns = [], morphologyStatusProject = '', morphologyStatusRequest = 0;
            let project = 'demo';
            const selectedProjectId = () => project;
            const literatureResults = [{arxiv_url:'https://arxiv.org/abs/1234.5678',title:'A paper'}];
            let rows = [{status:'staged',paper_url:'http://arxiv.org/abs/1234.5678/'}];
            const KoiApi = {listMorphologyRuns: async () => ({runs:rows})};
        ''' + helpers)
        page.evaluate('refreshPaperMorphologyStatuses()')
        assert page.locator('.is-ready').count() == 0
        assert page.locator('button.is-pending').count() == 1
        assert page.locator('button').get_attribute('title') == 'Разбор запущен, ещё не готов'
        page.evaluate("rows.push({status:'ready', paper_url:'http://arxiv.org/abs/1234.5678/'})")
        page.locator('button').focus()
        page.evaluate('refreshPaperMorphologyStatuses()')
        assert page.locator('button.is-ready').count() == 1
        assert page.locator('button.is-pending').count() == 0
        assert page.locator('button').get_attribute('aria-label') == 'Открыть готовый разбор статьи'
        assert page.locator('button').evaluate('(e) => document.activeElement === e')
        page.evaluate("rows = []; project = 'another'")
        page.evaluate('refreshPaperMorphologyStatuses()')
        assert page.locator('.is-ready').count() == 0
        assert page.locator('button.is-pending').count() == 0
        browser.close()


def test_literature_worker_stays_in_run_directory(monkeypatch, tmp_path):
    from koi.agent_chat import runner, conversations
    from koi.literature import cluster_orch
    monkeypatch.setattr(runner, "find_item", lambda _: {"project_id": "demo", "conversation_id": "chat-1"})
    monkeypatch.setattr(conversations, "find", lambda _: {"id": "chat-1", "kind": "literature", "literature_run_id": "run-1"})
    monkeypatch.setattr(conversations, "messages", lambda _: [])
    monkeypatch.setattr(cluster_orch, "load_literature_run", lambda *a: {"question": "Question"})
    monkeypatch.setattr(cluster_orch, "literature_dir", lambda _: tmp_path)
    assert runner._artifact_task_cwd("item-1") == tmp_path / "run-1"
    prompt = runner._sdk_prompt("item-1")
    assert "Do not recursively search the home directory" in prompt
    assert "report the exact missing path instead of searching the disk" in prompt
