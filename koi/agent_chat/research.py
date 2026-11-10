"""Durable research-run participants; reuses the existing chat activity journal.

SQLite serializes writes from independent CLI workers without a new service.
Scientific state remains in project.md and card reports, never in this registry.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from koi.adapters.workspace import get_workspace
from koi.agent_chat import activity

PATH = get_workspace().run_dir / "research-runs.sqlite3"
TERMINAL = {"completed", "failed", "cancelled"}
STATES = {"pending", "running", "waiting", "unknown", *TERMINAL}


def _now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _db():
    PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(PATH, timeout=15)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript('''
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
                item_id TEXT NOT NULL, project_id TEXT NOT NULL,
                goal TEXT NOT NULL, created_at TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS participants (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                role TEXT NOT NULL, task TEXT NOT NULL, backend TEXT NOT NULL,
                status TEXT NOT NULL, card_id TEXT, board_id TEXT,
                updated_at TEXT NOT NULL, result TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS budgets (
                run_id TEXT PRIMARY KEY REFERENCES runs(id),
                deadline REAL NOT NULL, max_executors INTEGER NOT NULL,
                launched INTEGER NOT NULL DEFAULT 0, stop_condition TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS handles (
                agent_id TEXT PRIMARY KEY REFERENCES participants(id),
                pid INTEGER NOT NULL, started TEXT NOT NULL, group_owner INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS brokers (
                run_id TEXT PRIMARY KEY REFERENCES runs(id),
                pid INTEGER NOT NULL, started TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS dispatches (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                payload TEXT NOT NULL, status TEXT NOT NULL,
                result TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS tool_requests (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                payload TEXT NOT NULL, status TEXT NOT NULL,
                result TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, agent_id TEXT NOT NULL REFERENCES participants(id),
                at TEXT NOT NULL, message TEXT NOT NULL);
        ''')
        if "metadata" not in {row[1] for row in db.execute("PRAGMA table_info(runs)")}:
            db.execute("ALTER TABLE runs ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'")
        if "group_owner" not in {row[1] for row in db.execute("PRAGMA table_info(handles)")} :
            db.execute("ALTER TABLE handles ADD COLUMN group_owner INTEGER NOT NULL DEFAULT 0")
        columns = {row[1] for row in db.execute("PRAGMA table_info(participants)")}
        if "parent_id" not in columns:
            db.execute("ALTER TABLE participants ADD COLUMN parent_id TEXT REFERENCES participants(id)")
        if "allow_edits" not in columns:
            db.execute("ALTER TABLE participants ADD COLUMN allow_edits INTEGER NOT NULL DEFAULT 1")
        yield db


def create_run(conversation_id, item_id, project_id, goal):
    if not all(isinstance(v, str) and v.strip() for v in (conversation_id, item_id, project_id, goal)):
        raise ValueError("Conversation, question, project and goal are required")
    # Validate the journal identity before persisting a run.
    if not item_id.startswith("aq-") or not item_id[3:].isalnum():
        raise ValueError("Invalid question id")
    run_id = "run-" + uuid4().hex
    with _db() as db:
        db.execute("INSERT INTO runs (id,conversation_id,item_id,project_id,goal,created_at) VALUES (?, ?, ?, ?, ?, ?)",
                   (run_id, conversation_id, item_id, project_id, goal, _now()))
    return run_id


def register(run_id, role, task, backend, *, card_id=None, board_id=None, parent_id=None, allow_edits=True):
    if not all(isinstance(v, str) and v.strip() for v in (role, task, backend)):
        raise ValueError("Role, task and backend are required")
    if bool(card_id) != bool(board_id):
        raise ValueError("Card and board must be specified together")
    agent_id = "agent-" + uuid4().hex
    with _db() as db:
        if parent_id:
            parent = db.execute("SELECT * FROM participants WHERE id=? AND run_id=?", (parent_id, run_id)).fetchone()
            if parent is None or parent["status"] in TERMINAL:
                raise ValueError("Parent must be an active participant in this run")
            allow_edits = bool(allow_edits and parent["allow_edits"])
        db.execute("INSERT INTO participants (id,run_id,role,task,backend,status,card_id,board_id,updated_at,parent_id,allow_edits) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                   (agent_id, run_id, role, task, backend, "pending", card_id, board_id, _now(), parent_id, int(allow_edits)))
    return agent_id


def update(agent_id, status, message, *, result=None):
    if status not in STATES:
        raise ValueError("Unknown participant status")
    with _db() as db:
        row = db.execute("SELECT p.*, r.item_id FROM participants p JOIN runs r ON r.id=p.run_id WHERE p.id=?", (agent_id,)).fetchone()
        if row is None:
            raise KeyError(agent_id)
        if row["status"] in TERMINAL and status != row["status"]:
            raise ValueError("A finished participant cannot be restarted; register a new attempt")
        now = _now()
        db.execute("UPDATE participants SET status=?, updated_at=?, result=? WHERE id=?",
                   (status, now, row["result"] if result is None else result, agent_id))
        db.execute("INSERT INTO events(agent_id,at,message) VALUES (?,?,?)", (agent_id, now, message))
    activity.record(row["item_id"], f"{row['role']}: {message}")


def participants(conversation_id):
    if not PATH.exists():
        return []
    reconcile(conversation_id)
    with _db() as db:
        return [dict(row) for row in db.execute(
            "SELECT p.*,r.project_id FROM participants p JOIN runs r ON r.id=p.run_id WHERE r.conversation_id=? ORDER BY r.created_at,p.rowid", (conversation_id,))]


def events(conversation_id, agent_id):
    if not PATH.exists():
        raise KeyError(agent_id)
    with _db() as db:
        row = db.execute("SELECT p.id FROM participants p JOIN runs r ON r.id=p.run_id WHERE p.id=? AND r.conversation_id=?", (agent_id, conversation_id)).fetchone()
        if row is None:
            raise KeyError(agent_id)
        return [dict(row) for row in db.execute("SELECT id,at,message FROM (SELECT * FROM events WHERE agent_id=? ORDER BY id DESC LIMIT 200) ORDER BY id", (agent_id,))]


def continuation_run(item):
    """A reply to research intake must retain the original coordinator run."""
    if not PATH.exists() or not item.get('project_id'):
        return None
    from koi.agent_chat.conversations import item_conversation
    with _db() as db:
        row = db.execute('SELECT r.id,b.run_id AS budget_run FROM runs r LEFT JOIN budgets b ON b.run_id=r.id '
                         "WHERE r.conversation_id=? AND r.project_id=? AND json_extract(r.metadata, '$.delegation') IS NOT 1 ORDER BY r.created_at DESC LIMIT 1",
                         (item_conversation(item), item['project_id'])).fetchone()
    first = item.get('question', '').lower().strip().split(maxsplit=1)
    explicit = first and first[0].rstrip(',.!') in ('продолжи', 'продолжай', 'продолжить', 'resume')
    return row['id'] if row and (row['budget_run'] is None or explicit) else None


def coordinator_prompt(item, context, *, resume_id=None):
    """Idempotent intake for a slash invocation in an existing chat."""
    import json
    import sys
    from pathlib import Path
    from koi.agent_chat.conversations import item_conversation
    if not context.get('project_id'):
        raise ValueError('Выберите проект перед запуском автоисследования')
    if item.get('research_scope') not in (None, 'tree', 'method'):
        raise ValueError('Unknown research scope')
    cid = item_conversation(item)
    words = item['question'].strip().split()
    resume_id = resume_id or (words[2] if len(words) >= 3 and words[1].lower() in ('resume', 'продолжи') else None)
    if resume_id:
        reconcile(cid)
        with _db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM runs WHERE id=? AND conversation_id=? AND project_id=?',
                             (resume_id, cid, context['project_id'])).fetchone()
            if row is None:
                raise ValueError('Исследование не найдено в этом чате и проекте')
            active = db.execute("SELECT id FROM participants WHERE run_id=? AND role='Координатор' AND status IN ('running','waiting')", (resume_id,)).fetchone()
            if active and row['item_id'] != item['id']:
                raise ValueError('Координатор ещё работает; повторный запуск не создан')
            db.execute('UPDATE runs SET item_id=? WHERE id=?', (item['id'], resume_id))
        run_id = resume_id
    else:
        with _db() as db:
            row = db.execute('SELECT * FROM runs WHERE item_id=? ORDER BY created_at DESC LIMIT 1', (item['id'],)).fetchone()
        run_id = row['id'] if row else create_run(cid, item['id'], context['project_id'], item['question'])
    with _db() as db:
        metadata = json.loads(db.execute('SELECT metadata FROM runs WHERE id=?', (run_id,)).fetchone()['metadata'])
        if 'research_scope' not in metadata:
            level = item.get('research_scope')
            method = context.get('scope_method') if item.get('board_id') else None
            if level == 'method' and not method:
                raise ValueError('Для исследования метода откройте его канбан или карточку')
            metadata['research_scope'] = {'level': level, 'method_id': method['id'] if method and level != 'tree' else None}
            db.execute('UPDATE runs SET metadata=? WHERE id=?', (json.dumps(metadata, ensure_ascii=False), run_id))
    agents = participants(cid)
    coordinator = next((a for a in agents if a['run_id'] == run_id and a['role'] == 'Координатор'
                        and a['status'] in ('pending', 'running', 'waiting')), None)
    agent_id = coordinator['id'] if coordinator else register(run_id, 'Координатор', item['question'], item.get('cli_agent') or 'auto')
    if coordinator is None:
        update(agent_id, 'running', 'Координатор восстанавливает исследование' if resume_id else 'Координатор изучает цель и контекст проекта')
    attach_handle(agent_id)
    with _db() as db:
        original = dict(db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone())
        budget = db.execute('SELECT * FROM budgets WHERE run_id=?', (run_id,)).fetchone()
        checkpoint = {'run': original, 'budget': dict(budget) if budget else None,
                      'participants': [a for a in agents if a['run_id'] == run_id]}
    engine = Path(__file__).resolve().parents[2]
    skill = engine / 'agents' / 'skills' / 'koi-arbor-autoresearch' / 'SKILL.md'
    ideation = engine / 'agents' / 'skills' / 'arbor-agent-ideate' / 'SKILL.md'
    return (ideation.read_text(encoding='utf-8') + '\n\n'
            + skill.read_text(encoding='utf-8')) + '\n\n' + json.dumps({
        **context, 'run_id': run_id, 'coordinator_id': agent_id, 'checkpoint': checkpoint,
        'engine_root': str(engine), 'python': sys.executable, 'tool_commands': tool_commands(),
        'instruction': 'Выполни цель по этому протоколу. Все изменения дерева проводи через адаптер.'
    }, ensure_ascii=False)


def finish_coordinator(item_id, status, message):
    if not PATH.exists():
        return
    with _db() as db:
        rows = db.execute("SELECT p.id FROM participants p JOIN runs r ON r.id=p.run_id WHERE r.item_id=? AND p.role='Координатор' AND p.status NOT IN ('completed','failed','cancelled')", (item_id,)).fetchall()
    for row in rows:
        update(row['id'], status, message)



def _process_start(pid):
    import subprocess
    import sys
    if sys.platform == 'darwin':
        # A sandboxed process can inspect itself, while spawning ps to inspect
        # its parent is denied. Read the same kernel birth time directly.
        import ctypes
        import struct
        try:
            libproc = ctypes.CDLL('/usr/lib/libproc.dylib')
            libproc.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
            info = ctypes.create_string_buffer(136)
            if libproc.proc_pidinfo(pid, 3, 0, info, len(info)) == 136:
                seconds, micros = struct.unpack_from('=QQ', info.raw, 120)
                return f'darwin:{seconds}:{micros}'
        except (OSError, ValueError):
            pass
    try:
        return subprocess.check_output(['ps', '-p', str(pid), '-o', 'lstart='],
                                       text=True, stderr=subprocess.DEVNULL, timeout=2).strip()
    except (OSError, subprocess.SubprocessError):
        return ''


def attach_handle(agent_id, pid=None, *, group_owner=False):
    import os
    pid = os.getpid() if pid is None else pid
    started = _process_start(pid)
    if not started:
        started = 'unavailable'  # Reconciliation must report unknown, never infer completion.
    with _db() as db:
        db.execute('INSERT OR REPLACE INTO handles VALUES (?,?,?,?)', (agent_id, pid, started, int(group_owner)))


def reconcile(conversation_id):
    """A missing process is unknown, never an implicitly successful experiment."""
    with _db() as db:
        rows = db.execute("SELECT p.id,h.pid,h.started FROM participants p JOIN runs r ON r.id=p.run_id JOIN handles h ON h.agent_id=p.id WHERE r.conversation_id=? AND p.status IN ('running','waiting')", (conversation_id,)).fetchall()
    checked = {}
    for row in rows:
        pid = row['pid']
        if pid not in checked:
            checked[pid] = _process_start(pid)
        if checked[pid] != row['started']:
            try:
                update(row['id'], 'unknown', 'Процесс больше не найден. Проверьте артефакты перед повторным запуском.')
            except ValueError:
                pass  # The owner may have recorded completion during the process check.


def owns_live_turn(item_id):
    if not PATH.exists():
        return False
    with _db() as db:
        rows = db.execute("SELECT h.pid,h.started FROM handles h JOIN participants p ON p.id=h.agent_id JOIN runs r ON r.id=p.run_id WHERE r.item_id=? AND p.status IN ('running','waiting')", (item_id,)).fetchall()
    return any(_process_start(row['pid']) == row['started'] for row in rows)



def reserve_executors(run_id, count, timeout):
    import time
    with _db() as db:
        db.execute('BEGIN IMMEDIATE')
        budget = db.execute('SELECT * FROM budgets WHERE run_id=?', (run_id,)).fetchone()
        if budget is None:
            raise ValueError('Record the research contract and budget before dispatch')
        remaining = budget['deadline'] - time.time()
        if remaining < 1 or budget['launched'] + count > budget['max_executors']:
            raise ValueError('Research budget exhausted')
        db.execute('UPDATE budgets SET launched=launched+? WHERE run_id=?', (count, run_id))
        return min(timeout, remaining)



def cancelled(run_id):
    from koi.agent_chat import live
    with _db() as db:
        row = db.execute('SELECT item_id FROM runs WHERE id=?', (run_id,)).fetchone()
    return row is None or live.cancelled(row['item_id'])



def request_cancel(conversation_id):
    from koi.agent_chat import live
    if not PATH.exists():
        return False
    with _db() as db:
        rows = db.execute("SELECT DISTINCT r.item_id FROM runs r JOIN participants p ON p.run_id=r.id WHERE r.conversation_id=? AND p.status IN ('pending','running','waiting','unknown')", (conversation_id,)).fetchall()
    for row in rows:
        live.request_cancel(row['item_id'])
    # Only groups created by our launchers may be signalled. Never target the
    # application process or an unverified/reused PID.
    import os, signal
    with _db() as db:
        handles = db.execute("SELECT h.* FROM handles h JOIN participants p ON p.id=h.agent_id JOIN runs r ON r.id=p.run_id WHERE r.conversation_id=? AND h.group_owner=1 AND p.status IN ('pending','running','waiting','unknown')", (conversation_id,)).fetchall()
    for handle in handles:
        if handle['pid'] > 1 and handle['started'] != 'unavailable' and _process_start(handle['pid']) == handle['started'] and os.name != 'nt':
            try:
                os.killpg(handle['pid'], signal.SIGTERM)
            except ProcessLookupError:
                pass
    return bool(rows)


def coordinator_for_item(item_id):
    if not PATH.exists():
        return None
    with _db() as db:
        row = db.execute("SELECT p.id FROM participants p JOIN runs r ON r.id=p.run_id WHERE r.item_id=? AND p.role='Координатор' AND p.status IN ('pending','running','waiting') ORDER BY p.rowid DESC LIMIT 1", (item_id,)).fetchone()
    return row['id'] if row else None


def prepare_delegation(item, *, allow_edits):
    """Host-owned turn identity and permissions, shared by all CLI agents."""
    import json
    import time
    from koi.agent_chat.conversations import item_conversation
    with _db() as db:
        row = db.execute('SELECT * FROM runs WHERE item_id=? ORDER BY created_at DESC LIMIT 1', (item['id'],)).fetchone()
    if row is None:
        run_id = create_run(item_conversation(item), item['id'], item.get('project_id') or '__workspace__', item['question'])
        with _db() as db:
            db.execute('UPDATE runs SET metadata=? WHERE id=?',
                       (json.dumps({'delegation': True, 'max_parallel': 4}), run_id))
            # ponytail: bounded per-turn delegation; Arbor keeps its agreed contract.
            db.execute('INSERT INTO budgets VALUES (?,?,?,0,?)',
                       (run_id, time.time() + 1800, 32, 'Finish the current chat request'))
    else:
        run_id = row['id']
    if item.get('project_id'):
        from koi.agent_chat.project_skills import context as skill_context
        skills = skill_context(item['project_id'], method_id=item.get('method_id'),
                               board_id=item.get('board_id'), card_id=item.get('card_id'),
                               question=item['question'])
        if skills.get('selected_project_skill'):
            with _db() as db:
                metadata = json.loads(db.execute('SELECT metadata FROM runs WHERE id=?', (run_id,)).fetchone()[0])
                metadata['skill_execution_scope'] = skills['skill_execution_scope']
                metadata['selected_project_skill'] = skills['selected_project_skill']
                db.execute('UPDATE runs SET metadata=? WHERE id=?', (json.dumps(metadata, ensure_ascii=False), run_id))
    agent_id = coordinator_for_item(item['id'])
    if agent_id is None:
        agent_id = register(run_id, 'Координатор', item['question'], item.get('cli_agent') or 'auto', allow_edits=allow_edits)
        attach_handle(agent_id)
        update(agent_id, 'running', 'Агент выполняет запрос')
    with _db() as db:
        db.execute('UPDATE participants SET allow_edits=? WHERE id=?', (int(allow_edits), agent_id))
    return run_id, agent_id


def delegation_prompt(run_id, agent_id):
    import json
    from pathlib import Path
    from koi.adapters.agent_backends import cli_agents
    return ('\n\nПодагенты ResearcherOS: для независимого критика или другой подзадачи '
            'используй MCP-инструмент researcheros.spawn_agents, если он доступен. '
            'Иначе вызови tool_commands.dispatch из engine_root с JSON на stdin. '
            'Это общий сервис ResearcherOS; не полагайся на встроенный сервис подагентов провайдера. '
            'Вложенные вызовы разрешены. Указывай parent_id из контекста. '
            'Для критика указывай readonly=true; не выдавай самопроверку за независимое ревью. '
            'Все участники, их статусы, журнал и результат видны в исходном чате. '
            'Если нужно явное согласие пользователя, в том числе после третьего FAIL '
            'koi-prose-style, вызови researcheros.request_approval с вопросом в title '
            'и конкретными правками и замечаниями в details. Вызов ждёт ответа пользователя. '
            'Один текстовый вопрос не создаёт запрос согласования. '
            'Продолжай согласуемое действие только при approved=true; отказ, отмена '
            'и ошибка инструмента не являются согласием. '
            'Результат status=failed/cancelled означает, что задача не выполнена. '
            'Не запускай параллельных писателей в одном каталоге.\n'
            + json.dumps({'engine_root': str(Path(__file__).resolve().parents[2]),
                          'run_id': run_id, 'parent_id': agent_id, 'tool_commands': tool_commands(),
                          'available_cli_agents': cli_agents(),
                          'dispatch_example': {'run_id': run_id, 'parent_id': agent_id,
                              'tasks': [{'backend': 'codex', 'cwd': '<absolute project directory>',
                                         'role': 'Критик', 'task': '<independent review task>', 'readonly': True}],
                              'timeout': 300}}, ensure_ascii=False))


def participant_cancelled(run_id, parent_id=None):
    if cancelled(run_id):
        return True
    if parent_id:
        with _db() as db:
            parent = db.execute('SELECT status FROM participants WHERE id=? AND run_id=?', (parent_id, run_id)).fetchone()
        return parent is None or parent['status'] in TERMINAL
    return False



def tool_commands():
    import sys
    if getattr(sys, 'frozen', False):
        return {'project':[sys.executable, '--research-tools'],
                'dispatch':[sys.executable, '--research-runtime']}
    return {'project':[sys.executable, '-m', 'koi.agent_chat.research_tools'],
            'dispatch':[sys.executable, '-m', 'koi.agent_chat.research_runtime']}
