"""Run Arbor executors through existing CLI transports, visible in the parent chat."""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from koi.adapters.agent_backends import run_agent
from koi.adapters.agent_process import AgentCancelled
from koi.agent_chat import live, research

SKILLS = Path(__file__).resolve().parents[2] / 'agents' / 'skills'


def _message(event):
    kind = event.get('type')
    if kind == 'text' and isinstance(event.get('part'), dict):
        return event['part'].get('text', '')
    if kind == 'item.completed':
        item = event.get('item', {})
        if item.get('type') == 'agent_message':
            return item.get('text', '')
        if item.get('type') == 'command_execution':
            return 'Команда завершена: ' + str(item.get('exit_code', ''))
    if kind == 'assistant':
        return ''.join(p.get('text', '') for p in event.get('message', {}).get('content', []) if p.get('type') == 'text')
    return ''


def execute(run_id, task, *, timeout=1800):
    """One independent executor; a successful process never closes a card itself."""
    with research._db() as db:
        row = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        run = dict(row)
    if research.cancelled(run_id):
        raise AgentCancelled
    backend = task['backend']
    if backend not in ('codex', 'claude', 'opencode'):
        raise ValueError('Executor backend must be codex, claude or opencode')
    cwd = Path(task['cwd']).resolve(strict=True)
    if not cwd.is_dir():
        raise ValueError('Executor cwd must be a directory')
    if not 0 < timeout <= 86400:
        raise ValueError('Executor timeout must be between 1 and 86400 seconds')
    agent_id = research.register(run_id, task.get('role', 'Исследователь'), task['task'], backend,
                                 board_id=task.get('board_id'), card_id=task.get('card_id'))
    prompt = (
        (SKILLS / 'koi-arbor-autoresearch' / 'SKILL.md').read_text(encoding='utf-8')
        + '\n\nРоль: ИСПОЛНИТЕЛЬ. Не запускай новых исполнителей и не меняй общее дерево. '
        'Веди свою карточку через research_tools: после КАЖДОЙ выполненной подзадачи '
        'вызови complete_subtask ДО следующей работы или ожидания job, не в конце эксперимента. '
        'Публикуй картинки через publish_image по мере появления данных: он копирует их '
        'из изолированного каталога в assets отчёта, встраивает и настраивает metrics_dir. '
        'Не меняй главный узел и файлы дерева напрямую. '
        'Не считай отрицательный результат ошибкой запуска. '
        'Факты и результаты сохраняй в отчёте; координатор проверит завершение.\n'
        + json.dumps({**task, 'run_id': run_id, 'agent_id': agent_id, 'project_id': run['project_id'],
                      'engine_root': str(SKILLS.parents[1]), 'python': sys.executable,
                      'tool_commands': research.tool_commands()}, ensure_ascii=False)
    )
    research.attach_handle(agent_id)
    research.update(agent_id, 'running', 'Исполнитель запущен')
    try:
        with research._db() as db:
            budget = db.execute('SELECT deadline FROM budgets WHERE run_id=?', (run_id,)).fetchone()
        if budget is not None:
            timeout = min(timeout, budget['deadline'] - time.time())
            if timeout <= 0:
                raise RuntimeError('Research deadline reached before queued task could start')
        def receive(message):
            if message:
                research.update(agent_id, 'running', message)
        result, _ = run_agent(prompt, cwd=cwd, timeout=timeout, allow_edits=True, backend=backend,
                              on_started=lambda pid: research.attach_handle(agent_id, pid, group_owner=True),
                              on_event=lambda event: receive(_message(event)),
                              is_cancelled=lambda: research.cancelled(run_id))
        if research.cancelled(run_id):
            raise AgentCancelled
        if not result:
            raise RuntimeError('Executor returned no result')
        research.update(agent_id, 'completed', 'Исполнитель вернул результат; требуется проверка координатора', result=result)
    except AgentCancelled:
        research.update(agent_id, 'cancelled', 'Исполнитель остановлен')
    except Exception as exc:
        research.update(agent_id, 'failed', f'Ошибка исполнителя: {type(exc).__name__}', result=str(exc))
    return next(p for p in research.participants(run['conversation_id']) if p['id'] == agent_id)


def _dispatch_local(run_id, tasks, *, timeout=1800):
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 4:
        raise ValueError('Dispatch requires between one and four independent tasks')
    # Callers provide disjoint workdirs; never run two writers in the same checkout.
    directories = [str(Path(t['cwd']).resolve(strict=True)) for t in tasks]
    if len(set(directories)) != len(directories):
        raise ValueError('Parallel executors require different working directories')
    timeout = research.reserve_executors(run_id, len(tasks), timeout)
    with research._db() as db:
        metadata = json.loads(db.execute('SELECT metadata FROM runs WHERE id=?', (run_id,)).fetchone()['metadata'])
    with ThreadPoolExecutor(max_workers=min(len(tasks), metadata.get('max_parallel', 4))) as pool:
        return list(pool.map(lambda task: execute(run_id, task, timeout=timeout), tasks))



def dispatch(run_id, tasks, *, timeout=1800):
    with research._db() as db:
        broker_row = db.execute('SELECT * FROM brokers WHERE run_id=?', (run_id,)).fetchone()
    if broker_row is None:
        if os.environ.get('CODEX_SANDBOX'):
            raise RuntimeError('Start this research from ResearcherOS; a host launcher is required')
        return _dispatch_local(run_id, tasks, timeout=timeout)
    job_id = 'dispatch-' + uuid4().hex
    with research._db() as db:
        db.execute('INSERT INTO dispatches VALUES (?,?,?,?,?)',
                   (job_id, run_id, json.dumps({'tasks':tasks, 'timeout':timeout}), 'pending', ''))
    deadline = time.monotonic() + timeout + 10
    while time.monotonic() < deadline:
        if research.cancelled(run_id):
            raise AgentCancelled
        with research._db() as db:
            job = db.execute('SELECT * FROM dispatches WHERE id=?', (job_id,)).fetchone()
        if job['status'] == 'completed':
            return json.loads(job['result'])
        if job['status'] == 'failed':
            raise RuntimeError(job['result'])
        time.sleep(.1)
    raise TimeoutError('Host executor did not return within the dispatch deadline')


@contextmanager
def broker(item_id):
    """Service only this coordinator's requests in the existing host process."""
    if not research.PATH.exists():
        yield
        return
    with research._db() as db:
        run = db.execute('SELECT * FROM runs WHERE item_id=? ORDER BY created_at DESC LIMIT 1', (item_id,)).fetchone()
        if run is None:
            yield
            return
        run_id = run['id']
        previous = db.execute('SELECT * FROM brokers WHERE run_id=?', (run_id,)).fetchone()
        if previous and research._process_start(previous['pid']) == previous['started']:
            raise RuntimeError('This research already has a live host launcher')
        db.execute("UPDATE dispatches SET status='failed',result='Host process was interrupted; inspect participants before retry' WHERE run_id=? AND status='running'", (run_id,))
        db.execute('INSERT OR REPLACE INTO brokers VALUES (?,?,?)',
                   (run_id, os.getpid(), research._process_start(os.getpid())))
    stopping = threading.Event()

    def work():
        while not stopping.wait(.1):
            with research._db() as db:
                db.execute('BEGIN IMMEDIATE')
                job = db.execute("SELECT * FROM dispatches WHERE run_id=? AND status='pending' ORDER BY rowid LIMIT 1", (run_id,)).fetchone()
                if job:
                    db.execute("UPDATE dispatches SET status='running' WHERE id=?", (job['id'],))
            if job is None:
                continue
            try:
                payload = json.loads(job['payload'])
                result = _dispatch_local(run_id, payload['tasks'], timeout=payload['timeout'])
                status, result = 'completed', json.dumps(result, ensure_ascii=False)
            except Exception as exc:
                status, result = 'failed', f'{type(exc).__name__}: {exc}'
            with research._db() as db:
                db.execute('UPDATE dispatches SET status=?,result=? WHERE id=?', (status, result, job['id']))
    worker = threading.Thread(target=work, name='research-cli-launcher', daemon=True)
    worker.start()
    try:
        yield
    finally:
        stopping.set()
        with research._db() as db:
            active = db.execute("SELECT id FROM dispatches WHERE run_id=? AND status='running'", (run_id,)).fetchone()
        if active:
            live.request_cancel(item_id)
        worker.join(timeout=5)
        with research._db() as db:
            db.execute('DELETE FROM brokers WHERE run_id=? AND pid=?', (run_id, os.getpid()))


def main():
    request = json.load(sys.stdin)
    result = dispatch(request['run_id'], request['tasks'], timeout=request.get('timeout', 1800))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
