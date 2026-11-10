"""Delegation exercises the host, real CLI subprocesses and stdio MCP, without models."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from koi.adapters import agent_chat_activity
from koi.agent_chat import research, research_mcp, research_runtime


@pytest.fixture
def chat(tmp_path, monkeypatch):
    monkeypatch.setattr(research, 'PATH', tmp_path / 'runs.sqlite3')
    monkeypatch.setattr(agent_chat_activity, 'ACTIVITY_DIR', tmp_path / 'activity')
    monkeypatch.delenv('CODEX_SANDBOX', raising=False)
    item = {'id': 'aq-delegation', 'conversation_id': 'chat-normal', 'question': 'Review independently', 'project_id': 'demo'}
    context = research.prepare_delegation(item, allow_edits=False)
    binary = tmp_path / 'fake-codex'
    binary.write_text(f'#!{sys.executable}\n' + '''
import json, pathlib, subprocess, sys, time
prompt = sys.stdin.read()
assert sys.argv[sys.argv.index('-s') + 1] == 'read-only'
config = {}
for i, arg in enumerate(sys.argv[:-1]):
    if arg == '-c' and sys.argv[i+1].startswith('mcp_servers.researcheros.'):
        key, value = sys.argv[i+1].split('=', 1)
        config[key.rsplit('.', 1)[-1]] = json.loads(value)
if 'NESTED_PARENT' in prompt:
    requests = [
      {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05'}},
      {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'spawn_agents','arguments':{
        'tasks':[{'backend':'codex','task':'LEAF_REVIEW','cwd':str(pathlib.Path.cwd()),'readonly':False}], 'timeout':10}}}]
    proc = subprocess.run([config['command'], *config['args']],
        input=''.join(json.dumps(r)+'\\n' for r in requests), capture_output=True, text=True, timeout=15)
    assert proc.returncode == 0, proc.stderr
    response = json.loads(proc.stdout.splitlines()[-1])['result']
    assert not response.get('isError'), response
    child = json.loads(response['content'][0]['text'])[0]
    assert child['status'] == 'completed', child
    result = 'Nested result: ' + child['result']
elif (pathlib.Path.cwd() / 'hold').exists():
    (pathlib.Path.cwd() / 'leaf-started').touch()
    while True: time.sleep(.05)
else:
    result = 'Independent leaf review'
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':result}}), flush=True)
pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_text(result)
''')
    binary.chmod(0o755)
    monkeypatch.setenv('KOI_CODEX_BIN', str(binary))
    return item, context, tmp_path


@pytest.mark.parametrize('max_parallel', [1, 4])
def test_normal_chat_nested_readonly_mcp_and_visibility(chat, max_parallel):
    item, (run, parent), cwd = chat
    with research._db() as db:
        db.execute('UPDATE runs SET metadata=? WHERE id=?', (json.dumps({'delegation': True, 'max_parallel': max_parallel}), run))
    task = {'backend': 'codex', 'cwd': str(cwd), 'role': 'Критик', 'task': 'NESTED_PARENT', 'readonly': False}
    with research_runtime.broker(item['id']):
        result = research_runtime.dispatch(run, [task], timeout=20, parent_id=parent)
    assert result[0]['status'] == 'completed', result
    assert result[0]['result'] == 'Nested result: Independent leaf review'
    rows = research.participants(item['conversation_id'])
    assert len(rows) == 3
    root, child, grandchild = rows
    assert child['parent_id'] == root['id']
    assert grandchild['parent_id'] == child['id']
    assert all(not row['allow_edits'] for row in rows)
    assert all(research.events(item['conversation_id'], row['id']) for row in rows)
    assert research.participants('another-chat') == []
    assert research.continuation_run({**item, 'question': 'Продолжи'}) is None


def test_parallel_dispatches_share_the_run_concurrency_limit(chat, monkeypatch):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    item, (run, parent), cwd = chat
    with research._db() as db:
        db.execute('UPDATE runs SET metadata=? WHERE id=?', (json.dumps({'delegation': True, 'max_parallel': 1}), run))
    active = peak = 0
    lock = threading.Lock()
    def execute(*args, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(.15)
        with lock:
            active -= 1
        return 'reviewed', 'codex'
    monkeypatch.setattr(research_runtime, 'run_agent', execute)
    task = {'backend': 'codex', 'cwd': str(cwd), 'task': 'Review', 'readonly': True}
    with research_runtime.broker(item['id']), ThreadPoolExecutor(max_workers=4) as pool:
        jobs = [pool.submit(research_runtime.dispatch, run, [task], timeout=5, parent_id=parent) for _ in range(4)]
        assert all(job.result(timeout=8)[0]['status'] == 'completed' for job in jobs)
    assert peak == 1


def test_nested_cancel_stops_descendants(chat):
    from concurrent.futures import ThreadPoolExecutor
    import time
    item, (run, parent), cwd = chat
    (cwd / 'hold').touch()
    with research_runtime.broker(item['id']), ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(research_runtime.dispatch, run,
            [{'backend': 'codex', 'cwd': str(cwd), 'task': 'NESTED_PARENT'}], timeout=20, parent_id=parent)
        deadline = time.monotonic() + 10
        while not (cwd / 'leaf-started').exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert (cwd / 'leaf-started').exists()
        assert research.request_cancel(item['conversation_id'])
        with pytest.raises(research_runtime.AgentCancelled):
            result.result(timeout=5)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            children = research.participants(item['conversation_id'])[1:]
            if len(children) == 2 and all(row['status'] == 'cancelled' for row in children):
                break
            time.sleep(.02)
        assert [row['status'] for row in children] == ['cancelled', 'cancelled']


def test_failed_child_is_visible_and_not_a_review(chat, monkeypatch):
    item, (run, parent), cwd = chat
    monkeypatch.setattr(research_runtime, 'run_agent', lambda *a, **kw: (None, None))
    with research_runtime.broker(item['id']):
        result = research_runtime.dispatch(run,
            [{'backend': 'codex', 'cwd': str(cwd), 'task': 'Review'}], parent_id=parent, timeout=5)
    assert result[0]['status'] == 'failed'
    assert 'no result' in result[0]['result']
    assert research.participants(item['conversation_id'])[-1]['status'] == 'failed'


def test_finished_or_foreign_parent_cannot_launch(chat):
    item, (run, parent), cwd = chat
    other = research.create_run('other', 'aq-other', 'demo', 'Unrelated')
    task = {'backend': 'codex', 'cwd': str(cwd), 'task': 'Review'}
    with pytest.raises(ValueError, match='Parent'):
        research_runtime.dispatch(other, [task], parent_id=parent)
    research.update(parent, 'completed', 'Finished')
    with pytest.raises(RuntimeError, match='no longer active'):
        research_mcp.call(run, parent, 'spawn_agents', {'tasks': [task]})


def test_stdio_mcp_discovery_survives_bad_request(chat):
    _, context, _ = chat
    requests = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2024-11-05'}},
        {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
        {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'bad'}},
        {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'list_agents'}},
    ]
    proc = subprocess.run(research_mcp.command(context), input=''.join(json.dumps(r)+'\n' for r in requests),
                          capture_output=True, text=True, timeout=5)
    assert proc.returncode == 0, proc.stderr
    responses = [json.loads(line)['result'] for line in proc.stdout.splitlines()]
    assert {tool['name'] for tool in responses[1]['tools']} == {'spawn_agents', 'list_agents', 'request_approval'}
    assert responses[2]['isError']
    assert json.loads(responses[3]['content'][0]['text'])[0]['id'] == context[1]


@pytest.mark.parametrize('backend', ['codex', 'claude', 'cursor', 'opencode'])
def test_backend_receives_scoped_mcp_without_expanding_permissions(chat, monkeypatch, backend):
    from koi.adapters import agent_backends
    _, context, cwd = chat
    calls = []
    monkeypatch.setenv('OPENCODE_CONFIG_CONTENT', json.dumps({'mcp': {'servers': {'existing': {'type': 'local', 'command': ['existing']}}}}))
    def run(prompt, **kwargs):
        assert kwargs['allow_edits'] is False
        flags, env = kwargs['mcp_args'], kwargs['mcp_env']
        if backend == 'codex':
            assert any('mcp_servers.researcheros.command=' in arg for arg in flags)
        elif backend == 'claude':
            config = json.loads(flags[flags.index('--mcp-config') + 1])
            assert config['mcpServers']['researcheros']['args'][-3:-1] == list(context)
        elif backend == 'cursor':
            root = Path(flags[flags.index('--plugin-dir') + 1])
            assert (root / 'plugin.json').is_file()
            config = json.loads((root / 'mcp.json').read_text())
            assert config['mcpServers']['researcheros']['args'][-3:-1] == list(context)
            calls.append(root)
        else:
            config = json.loads(env['OPENCODE_CONFIG_CONTENT'])
            assert config['mcp']['servers']['existing']['command'] == ['existing']
            assert config['mcp']['servers']['researcheros']['command'][-3:-1] == list(context)
        return 'reviewed'
    monkeypatch.setitem(agent_backends._RUNNERS, backend, run)
    assert agent_backends.run_agent('Review', cwd=cwd, backend=backend, allow_edits=False, delegation=context) == ('reviewed', backend)
    assert not any(path.exists() for path in calls)
    assert 'researcheros' not in json.loads(__import__('os').environ['OPENCODE_CONFIG_CONTENT'])['mcp']['servers']


def test_frozen_mcp_entrypoint_does_not_start_http_server(chat, monkeypatch):
    from api import desktop_server
    _, context, _ = chat
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    command = research_mcp.command(context)
    assert command[:2] == [sys.executable, '--research-mcp']
    monkeypatch.setattr(sys, 'argv', command)
    calls = []
    monkeypatch.setattr(research_mcp, 'main', lambda argv: calls.append(argv))
    monkeypatch.setattr(desktop_server, 'DesktopServer', lambda **kw: pytest.fail('Unexpected HTTP server'))
    assert desktop_server.main() == 0
    assert calls == [[*context, str(research.PATH)]]
