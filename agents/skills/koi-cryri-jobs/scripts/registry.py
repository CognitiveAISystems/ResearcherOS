#!/usr/bin/env python3
"""Maintain the workspace-wide Cryri registry and its human-readable table."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import tempfile
import uuid

DEFAULT = Path(__file__).resolve().parents[5] / 'tree/cryri-jobs.json'
STATUSES = {'pending', 'running', 'cancel_requested', 'completed', 'failed', 'cancelled', 'unknown'}
REQUIRED = ('job_id', 'name', 'comment', 'project', 'card', 'purpose', 'status',
            'gpu_count', 'submitted_at', 'checked_at', 'ownership_evidence')


def validate(row):
    for field in REQUIRED:
        if field not in row or row[field] in (None, ''):
            raise ValueError('Missing registry field: ' + field)
    prefix = 'lm-mpi-job-'
    if not row['job_id'].startswith(prefix):
        raise ValueError('Use the exact service job ID')
    uuid.UUID(row['job_id'][len(prefix):])
    if not row.get('ownership_verified'):
        raise ValueError('Ownership must be verified before registration')
    if any('volovikova' not in row[k].lower() for k in ('name', 'comment')):
        raise ValueError('volovikova is required in both name and comment')
    if row['status'] not in STATUSES:
        raise ValueError('Unsupported status')
    if not isinstance(row['gpu_count'], int) or row['gpu_count'] < 1:
        raise ValueError('gpu_count must count devices, not jobs')


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def table(data):
    columns = [('Имя', 'name'), ('Тег / ID', 'job_id'), ('Комментарий', 'comment'),
               ('Проект', 'project'), ('Карточка', 'card'), ('Цель', 'purpose'),
               ('Статус', 'status'), ('GPU', 'gpu_count'), ('Проверено', 'checked_at'),
               ('Мониторинг', 'monitoring_note')]
    def cell(value):
        return str(value if value is not None else '').replace('&', '&amp;').replace('|', '&#124;').replace('\n', '<br>')
    lines = ['# Джобы Cryri', '',
             'Только подтверждённые наши запуски. Источник таблицы: `cryri-jobs.json`.', '',
             '| ' + ' | '.join(k for k, _ in columns) + ' |',
             '| ' + ' | '.join('---' for _ in columns) + ' |']
    for row in data['jobs']:
        lines.append('| ' + ' | '.join(cell(row.get(k, '')) for _, k in columns) + ' |')
    routers = [row for row in data['jobs'] if row.get('router_endpoint')]
    if routers:
        lines += ['', '## Подключение через роутеры']
        for row in routers:
            lines += ['', '### ' + cell(row['name']), '',
                      '- Задание: `' + cell(row['job_id']) + '`']
            for label, key in [('Адрес для запросов к роутеру', 'router_endpoint'), ('Модель', 'model'),
                               ('Локальный адрес для запросов', 'local_endpoint')]:
                if row.get(key):
                    lines.append('- ' + label + ': `' + cell(row[key]) + '`')
            if row.get('connection_note'):
                lines += ['', cell(row['connection_note'])]
            if row.get('tunnel_command'):
                lines += ['', 'Команда для открытия туннеля:', '', '```bash', row['tunnel_command'], '```']
    return '\n'.join(lines) + '\n'


def update(path, patch=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = json.loads(path.read_text()) if path.exists() else {'version': 1, 'jobs': []}
        if patch is not None:
            job_id = patch['job_id']
            current = next((j for j in data['jobs'] if j['job_id'] == job_id), None)
            row = dict(current or {}, **patch)
            validate(row)
            if current:
                if current['status'] in {'completed', 'failed', 'cancelled'} and row['status'] in {'pending', 'running'}:
                    raise ValueError('Refusing a stale terminal-to-active status regression')
                current.update(row)
            else:
                data['jobs'].append(row)
            data['jobs'].sort(key=lambda j: (j['submitted_at'], j['job_id']))
        for row in data['jobs']:
            validate(row)
        atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        atomic_write(path.with_suffix('.md'), table(data))
        return data


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['upsert', 'render'])
    p.add_argument('--registry', type=Path, default=DEFAULT)
    p.add_argument('--record', type=Path)
    args = p.parse_args()
    if args.action == 'upsert' and args.record is None:
        p.error('upsert requires --record (JSON object)')
    try:
        data = update(args.registry, json.loads(args.record.read_text()) if args.action == 'upsert' else None)
    except (ValueError, KeyError) as e:
        p.exit(2, str(e) + '\n')
    print(json.dumps({'registry': str(args.registry), 'jobs': len(data['jobs'])}))


if __name__ == '__main__':
    main()
