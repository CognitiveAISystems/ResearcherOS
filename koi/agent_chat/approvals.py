"""Blocking CLI consent requests, rendered by the existing permission controls."""
import json
import time
from uuid import uuid4

from koi.agent_chat import research


def _requests(db):
    db.execute('''CREATE TABLE IF NOT EXISTS approvals (
        id TEXT PRIMARY KEY, run_id TEXT NOT NULL, agent_id TEXT NOT NULL,
        payload TEXT NOT NULL, decision TEXT)''')


def snapshot(cid):
    with research._db() as db:
        _requests(db)
        row = db.execute('''SELECT a.payload, r.item_id FROM approvals a
            JOIN runs r ON r.id=a.run_id JOIN participants p ON p.id=a.agent_id
            WHERE r.conversation_id=? AND a.decision IS NULL AND p.status='running'
            ORDER BY a.rowid LIMIT 1''', (cid,)).fetchone()
    return {"item_id": row['item_id'], "permission": json.loads(row['payload'])} if row else None


def decide(cid, permission_id, option_id):
    with research._db() as db:
        _requests(db)
        row = db.execute('''SELECT a.payload FROM approvals a JOIN runs r ON r.id=a.run_id
            WHERE a.id=? AND r.conversation_id=? AND a.decision IS NULL''', (permission_id, cid)).fetchone()
        if row is None:
            return False
        if option_id not in {o['optionId'] for o in json.loads(row['payload'])['options']}:
            raise ValueError('Unknown permission option')
        db.execute('UPDATE approvals SET decision=? WHERE id=? AND decision IS NULL', (option_id, permission_id))
    return True


def request(run_id, agent_id, title, details=''):
    if not isinstance(title, str) or not title.strip() or not isinstance(details, str):
        raise ValueError('A consent question and text details are required')
    permission_id = uuid4().hex
    payload = {'id': permission_id, 'title': title,
               'tool_call': {'rawInput': {'details': details}},
               'options': [{'optionId': 'approve', 'name': 'Согласовать', 'kind': 'allow_once'},
                           {'optionId': 'reject', 'name': 'Отклонить', 'kind': 'reject_once'}]}
    with research._db() as db:
        _requests(db)
        db.execute('INSERT INTO approvals VALUES (?,?,?,?,NULL)',
                   (permission_id, run_id, agent_id, json.dumps(payload, ensure_ascii=False)))
    try:
        while not research.participant_cancelled(run_id, agent_id):
            with research._db() as db:
                decision = db.execute('SELECT decision FROM approvals WHERE id=?', (permission_id,)).fetchone()[0]
            if decision is not None:
                return {'approved': decision == 'approve', 'decision': decision}
            time.sleep(0.25)
        return {'approved': False, 'decision': 'cancelled'}
    finally:
        with research._db() as db:
            db.execute('UPDATE approvals SET decision=COALESCE(decision, ?) WHERE id=?', ('cancelled', permission_id))
