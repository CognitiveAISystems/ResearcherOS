"""Exercise real parallel subprocesses without paid model calls."""
import sys
from pathlib import Path

import pytest
from koi.agent_chat import research, research_runtime, research_tools, live
from koi.adapters import agent_chat_activity


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(research, 'PATH', tmp_path / 'runs.sqlite3')
    monkeypatch.setattr(agent_chat_activity, 'ACTIVITY_DIR', tmp_path / 'activity')
    run = research.create_run('chat-a', 'aq-123', 'demo', 'Develop method')
    research_tools.perform(run, 'contract', {'max_seconds':60, 'max_executors':4, 'stop_condition':'Compare two variants'})
    script = tmp_path / 'fake-codex'
    script.write_text(f'#!{sys.executable}\n' + '''
import json, pathlib, sys, time
sys.stdin.read()
cwd=pathlib.Path.cwd()
(cwd/'started').touch()
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'Evaluating'}}), flush=True)
deadline=time.monotonic()+5
while len(list(cwd.parent.glob('executor-*/started'))) < 2:
    if time.monotonic()>deadline: sys.exit(1)
    time.sleep(.01)
pathlib.Path(sys.argv[sys.argv.index('-o')+1]).write_text('Actual subprocess result')
''')
    script.chmod(0o755)
    monkeypatch.setenv('KOI_CODEX_BIN', str(script))
    tasks=[]
    for i in range(2):
        cwd=tmp_path/f'executor-{i}'; cwd.mkdir()
        tasks.append({'backend':'codex','cwd':str(cwd),'task':'Evaluate independently'})
    return run, tasks


def test_parallel_cli_executors_report_to_parent(state):
    run,tasks=state
    results=research_runtime.dispatch(run,tasks,timeout=10)
    assert len(results)==2
    assert all(r['status']=='completed' for r in results)
    assert all(r['result']=='Actual subprocess result' for r in results)
    for result in results:
        assert any(e['message']=='Evaluating' for e in research.events('chat-a',result['id']))


def test_duplicate_checkout_rejected_before_launch(state):
    run,tasks=state
    with pytest.raises(ValueError, match='different working'):
        research_runtime.dispatch(run,[tasks[0],tasks[0]])
    assert research.participants('chat-a')==[]


def test_cancelled_parent_prevents_launch(state):
    run,tasks=state
    live.request_cancel('aq-123')
    with pytest.raises(research_runtime.AgentCancelled):
        research_runtime.dispatch(run,tasks)
    assert research.participants('chat-a')==[]


def test_sandboxed_dispatch_requires_a_host(state, monkeypatch):
    run, tasks = state
    monkeypatch.setenv('CODEX_SANDBOX','seatbelt')
    with pytest.raises(RuntimeError, match='host launcher'):
        research_runtime.dispatch(run,tasks)


def test_sandboxed_client_dispatches_via_host_process(state):
    import json, subprocess
    run, tasks = state
    client = """
import json,sys,os
from pathlib import Path
from koi.agent_chat import research,research_runtime
research.PATH=Path(sys.argv[1])
os.environ['CODEX_SANDBOX']='seatbelt'
request=json.load(sys.stdin)
result=research_runtime.dispatch(request['run_id'],request['tasks'],timeout=10)
print(json.dumps(result))
"""
    with research_runtime.broker('aq-123'):
        result=subprocess.run([sys.executable,'-c',client,str(research.PATH)],
            input=json.dumps({'run_id':run,'tasks':tasks}),capture_output=True,text=True,timeout=20)
    assert result.returncode==0, result.stderr
    assert [a['status'] for a in json.loads(result.stdout)]==['completed','completed']
    with research._db() as db:
        assert db.execute('SELECT count(*) FROM brokers').fetchone()[0]==0
        assert db.execute('SELECT status FROM dispatches').fetchone()[0]=='completed'


def test_cancel_stops_actual_executor_groups_without_stopping_host(state):
    import os,time
    from concurrent.futures import ThreadPoolExecutor
    run,tasks=state
    script=Path(os.environ['KOI_CODEX_BIN'])
    script.write_text(script.read_text().replace('deadline=time.monotonic()+5', "while (cwd/'hold').exists(): time.sleep(.01)\ndeadline=time.monotonic()+5"))
    for task in tasks:
        (Path(task['cwd'])/'hold').touch()
    with ThreadPoolExecutor(max_workers=1) as pool:
        result=pool.submit(research_runtime.dispatch,run,tasks,timeout=10)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            with research._db() as db:
                handles=db.execute('SELECT pid,group_owner FROM handles').fetchall()
            if len(handles)==2 and all(h['group_owner'] for h in handles):
                break
            time.sleep(.01)
        assert len(handles)==2 and all(h['pid']!=os.getpid() and h['group_owner'] for h in handles)
        assert research.request_cancel('chat-a')
        assert all(agent['status']=='cancelled' for agent in result.result(timeout=5))


def test_concurrency_limit_does_not_end_research_after_first_wave(state, monkeypatch):
    import threading, time
    run, tasks = state
    run = research.create_run('chat-b', 'aq-waves', 'demo', 'Search until target or budget')
    research_tools.perform(run, 'contract', {'max_seconds':60, 'max_parallel':1,
        'max_executors':6, 'stop_condition':'Verified goal or deadline'})
    active = peak = 0
    lock = threading.Lock()
    def execute(*args, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(.02)
        with lock:
            active -= 1
        return {'status':'completed'}
    monkeypatch.setattr(research_runtime, 'execute', execute)
    for _ in range(3):
        assert len(research_runtime.dispatch(run, tasks, timeout=10)) == 2
    assert peak == 1
    with research._db() as db:
        assert db.execute('SELECT launched FROM budgets WHERE run_id=?',(run,)).fetchone()['launched'] == 6
    with pytest.raises(ValueError, match='exhausted'):
        research_runtime.dispatch(run,tasks,timeout=10)
