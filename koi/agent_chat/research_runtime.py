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

from koi.adapters.agent_backends import CLI_AGENTS, run_agent
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


def _acquire_slot(run_id, agent_id, deadline):
    """Waiting parents release their slot so a nested child can run at limit=1."""
    while time.monotonic() < deadline:
        with research._db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM participants WHERE id=? AND run_id=?', (agent_id, run_id)).fetchone()
            if row is None or row['status'] in research.TERMINAL:
                raise AgentCancelled
            metadata = json.loads(db.execute('SELECT metadata FROM runs WHERE id=?', (run_id,)).fetchone()[0])
            active = db.execute("SELECT count(*) FROM participants WHERE run_id=? AND parent_id IS NOT NULL AND status='running' AND id<>?", (run_id, agent_id)).fetchone()[0]
            ready = row['parent_id'] is None or active < metadata.get('max_parallel', 4)
            if ready:
                db.execute("UPDATE participants SET status='running' WHERE id=?", (agent_id,))
        if research.participant_cancelled(run_id, row['parent_id']):
            raise AgentCancelled
        if ready:
            return
        time.sleep(.05)
    raise TimeoutError('Executor timed out waiting for a concurrency slot')


def execute(run_id, task, *, timeout=1800):
    """One independent executor; a successful process never closes a card itself."""
    with research._db() as db:
        row = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        run = dict(row)
    parent_id = task.get('parent_id')
    if research.participant_cancelled(run_id, parent_id):
        raise AgentCancelled
    backend = task['backend']
    if backend not in dict(CLI_AGENTS):
        raise ValueError('Executor backend must be an installed CLI agent')
    cwd = Path(task['cwd']).resolve(strict=True)
    if not cwd.is_dir():
        raise ValueError('Executor cwd must be a directory')
    if not 0 < timeout <= 86400:
        raise ValueError('Executor timeout must be between 1 and 86400 seconds')
    agent_id = research.register(run_id, task.get('role', 'Исследователь'), task['task'], backend,
                                 board_id=task.get('board_id'), card_id=task.get('card_id'),
                                 parent_id=parent_id, allow_edits=not task.get('readonly', False))
    with research._db() as db:
        allow_edits = bool(db.execute('SELECT allow_edits FROM participants WHERE id=?', (agent_id,)).fetchone()[0])
    metadata = json.loads(run['metadata'])
    arbor = not metadata.get('delegation') and bool(task.get('card_id'))
    from koi.agent_chat.project_skills import context as skill_context, POLICY as SKILL_POLICY
    scope = task
    if not any(task.get(key) for key in ('method_id', 'board_id', 'card_id')):
        if metadata.get('delegation'):
            from koi.adapters.agent_chat_queue import find_item
            scope = find_item(run['item_id']) or {}
        else:
            scope = metadata.get('research_scope', {})
    project_skills = skill_context(run['project_id'], method_id=scope.get('method_id'),
                                   board_id=scope.get('board_id'), card_id=scope.get('card_id'))
    if metadata.get('skill_execution_scope'):
        project_skills['skill_execution_scope'] = metadata['skill_execution_scope']
        project_skills['selected_project_skill'] = metadata.get('selected_project_skill')
    prompt = (
        ((SKILLS / 'koi-arbor-autoresearch' / 'SKILL.md').read_text(encoding='utf-8')
        + '\n\nРоль: ИСПОЛНИТЕЛЬ. Не меняй общее дерево. '
        'Веди свою карточку через research_tools: после КАЖДОЙ выполненной подзадачи '
        'вызови complete_subtask ДО следующей работы или ожидания job, не в конце эксперимента. '
        'Публикуй картинки через publish_image по мере появления данных: он копирует их '
        'из изолированного каталога в assets отчёта, встраивает и настраивает metrics_dir. '
        'Не меняй главный узел и файлы дерева напрямую. '
        'Не считай отрицательный результат ошибкой запуска. '
        'Факты и результаты сохраняй в отчёте; координатор проверит завершение.\n' if arbor else
        'Выполни только переданную подзадачу. Верни результат родителю. '
        'Прочитай применимые AGENTS.md и skills.\n')
        + ('Работай только на чтение; не меняй файлы и состояние проекта.\n' if not allow_edits else '')
        + SKILL_POLICY + '\n'
        + json.dumps({**task, **project_skills, 'run_id': run_id, 'agent_id': agent_id, 'project_id': run['project_id'],
                      'engine_root': str(SKILLS.parents[1]), 'python': sys.executable,
                      'tool_commands': research.tool_commands()}, ensure_ascii=False)
    ) + research.delegation_prompt(run_id, agent_id)
    research.attach_handle(agent_id)
    research.update(agent_id, 'waiting', 'Исполнитель ожидает свободного места')
    try:
        with research._db() as db:
            budget = db.execute('SELECT deadline FROM budgets WHERE run_id=?', (run_id,)).fetchone()
        if budget is not None:
            timeout = min(timeout, budget['deadline'] - time.time())
            if timeout <= 0:
                raise RuntimeError('Research deadline reached before queued task could start')
        deadline = time.monotonic() + timeout
        _acquire_slot(run_id, agent_id, deadline)
        timeout = deadline - time.monotonic()
        research.update(agent_id, 'running', 'Исполнитель запущен')
        def receive(message):
            if message:
                research.update(agent_id, 'running', message)
        result, _ = run_agent(prompt, cwd=cwd, timeout=timeout, allow_edits=allow_edits, backend=backend,
                              delegation=(run_id, agent_id),
                              on_started=lambda pid: research.attach_handle(agent_id, pid, group_owner=True),
                              on_event=lambda event: receive(_message(event)),
                              is_cancelled=lambda: research.participant_cancelled(run_id, parent_id))
        if research.participant_cancelled(run_id, parent_id):
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
    if any(a == b and not (tasks[i].get('readonly') is True and tasks[j].get('readonly') is True)
           for i, a in enumerate(directories) for j, b in enumerate(directories) if i < j):
        raise ValueError('Parallel executors require different working directories')
    timeout = research.reserve_executors(run_id, len(tasks), timeout)
    with research._db() as db:
        metadata = json.loads(db.execute('SELECT metadata FROM runs WHERE id=?', (run_id,)).fetchone()['metadata'])
    with ThreadPoolExecutor(max_workers=min(len(tasks), metadata.get('max_parallel', 4))) as pool:
        return list(pool.map(lambda task: execute(run_id, task, timeout=timeout), tasks))



def dispatch(run_id, tasks, *, timeout=1800, parent_id=None):
    if type(timeout) not in (int, float) or not 0 < timeout <= 86400:
        raise ValueError('Executor timeout must be between 1 and 86400 seconds')
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 4 or not all(isinstance(t, dict) for t in tasks):
        raise ValueError('Dispatch requires between one and four independent tasks')
    if any(type(t.get('readonly', False)) is not bool for t in tasks):
        raise ValueError('readonly must be a boolean')
    with research._db() as db:
        broker_row = db.execute('SELECT * FROM brokers WHERE run_id=?', (run_id,)).fetchone()
        if parent_id is None:
            root = db.execute("SELECT id FROM participants WHERE run_id=? AND parent_id IS NULL AND status IN ('running','waiting') ORDER BY rowid DESC LIMIT 1", (run_id,)).fetchone()
            parent_id = root['id'] if root else None
        parent = db.execute('SELECT * FROM participants WHERE run_id=? AND id=?', (run_id, parent_id)).fetchone() if parent_id else None
        if parent_id and (parent is None or parent['status'] in research.TERMINAL):
            raise ValueError('Parent must be an active participant in this run')
    tasks = [{**t, 'parent_id': parent_id,
              'readonly': bool(parent and not parent['allow_edits']) or t.get('readonly', False)} for t in tasks]
    if parent:
        research.update(parent_id, 'waiting', 'Ожидает результатов подагентов')
    deadline = time.monotonic() + timeout + 10
    try:
        return _submit(run_id, tasks, timeout, parent_id, broker_row)
    finally:
        if parent and not research.participant_cancelled(run_id, parent_id):
            _acquire_slot(run_id, parent_id, deadline)
            research.update(parent_id, 'running', 'Продолжает работу после подагентов')


def _submit(run_id, tasks, timeout, parent_id, broker_row):
    if broker_row and research._process_start(broker_row['pid']) != broker_row['started']:
        raise RuntimeError('ResearcherOS host is unavailable; restart the request from the app')
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
        if research.participant_cancelled(run_id, parent_id):
            raise AgentCancelled
        with research._db() as db:
            job = db.execute('SELECT * FROM dispatches WHERE id=?', (job_id,)).fetchone()
        if job['status'] == 'completed':
            return json.loads(job['result'])
        if job['status'] == 'failed':
            raise RuntimeError(job['result'])
        time.sleep(.1)
    with research._db() as db:
        db.execute("UPDATE dispatches SET status='failed',result='Dispatch timed out' WHERE id=? AND status='pending'", (job_id,))
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
        db.execute("UPDATE tool_requests SET status='failed',result='Host was interrupted; inspect state before retrying' WHERE run_id=? AND status IN ('pending','running')", (run_id,))
        db.execute('INSERT OR REPLACE INTO brokers VALUES (?,?,?)',
                   (run_id, os.getpid(), research._process_start(os.getpid())))
    stopping = threading.Event()

    def launch(job):
        try:
            payload = json.loads(job['payload'])
            result = _dispatch_local(run_id, payload['tasks'], timeout=payload['timeout'])
            status, result = 'completed', json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            status, result = 'failed', f'{type(exc).__name__}: {exc}'
        with research._db() as db:
            db.execute('UPDATE dispatches SET status=?,result=? WHERE id=?', (status, result, job['id']))

    launches = []
    def work():
        while not stopping.wait(.1):
            with research._db() as db:
                db.execute('BEGIN IMMEDIATE')
                job = db.execute("SELECT * FROM dispatches WHERE run_id=? AND status='pending' ORDER BY rowid LIMIT 1", (run_id,)).fetchone()
                if job:
                    db.execute("UPDATE dispatches SET status='running' WHERE id=?", (job['id'],))
            if job is None:
                continue
            # Keep accepting requests while parents wait for nested children.
            launches[:] = [thread for thread in launches if thread.is_alive()]
            thread = threading.Thread(target=launch, args=(job,), daemon=True)
            launches.append(thread)
            thread.start()
    worker = threading.Thread(target=work, name='research-cli-launcher', daemon=True)
    def tools():
        from koi.agent_chat import research_tools
        while not stopping.wait(.1):
            with research._db() as db:
                db.execute('BEGIN IMMEDIATE')
                job = db.execute("SELECT * FROM tool_requests WHERE run_id=? AND status='pending' ORDER BY rowid LIMIT 1", (run_id,)).fetchone()
                if job:
                    db.execute("UPDATE tool_requests SET status='running' WHERE id=?", (job['id'],))
            if job is None:
                continue
            try:
                if research.cancelled(run_id):
                    raise AgentCancelled('Research was cancelled')
                payload = json.loads(job['payload'])
                result = research_tools.perform(run_id, payload['operation'], payload['args'])
                status, result = 'completed', json.dumps(result, ensure_ascii=False)
            except Exception as exc:
                status, result = 'failed', f'{type(exc).__name__}: {exc}'
            with research._db() as db:
                db.execute('UPDATE tool_requests SET status=?,result=? WHERE id=?', (status, result, job['id']))
    tool_worker = threading.Thread(target=tools, name='research-project-tools', daemon=True)
    worker.start()
    tool_worker.start()
    try:
        yield
    finally:
        stopping.set()
        with research._db() as db:
            active = db.execute("SELECT id FROM dispatches WHERE run_id=? AND status='running'", (run_id,)).fetchone()
        if active:
            live.request_cancel(item_id)
        worker.join(timeout=5)
        tool_worker.join(timeout=5)
        deadline = time.monotonic() + 5
        for thread in launches:
            thread.join(timeout=max(0, deadline - time.monotonic()))
        with research._db() as db:
            db.execute("UPDATE dispatches SET status='failed',result='Host stopped; inspect state before retrying' WHERE run_id=? AND status IN ('pending','running')", (run_id,))
            db.execute("UPDATE tool_requests SET status='failed',result='Host stopped; inspect state before retrying' WHERE run_id=? AND status IN ('pending','running')", (run_id,))
            db.execute('DELETE FROM brokers WHERE run_id=? AND pid=?', (run_id, os.getpid()))


def main():
    request = json.load(sys.stdin)
    result = dispatch(request['run_id'], request['tasks'], timeout=request.get('timeout', 1800), parent_id=request.get('parent_id'))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
