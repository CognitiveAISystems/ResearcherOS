"""Per-agent stdio MCP bridge to the existing host launcher (stdlib only)."""
from __future__ import annotations

import json
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from koi.agent_chat import research, research_runtime


def command(context):
    run_id, parent_id = context
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--research-mcp', run_id, parent_id, str(research.PATH)]
    engine = str(Path(__file__).resolve().parents[2])
    code = f'import sys; sys.path.insert(0, {engine!r}); from koi.agent_chat.research_mcp import main; main()'
    return [sys.executable, '-c', code, run_id, parent_id, str(research.PATH)]


@contextmanager
def configuration(backend, context):
    """Launch-scoped configuration; never edit the user's agent settings."""
    if context is None:
        yield [], {}
        return
    cmd = command(context)
    server = {'command': cmd[0], 'args': cmd[1:]}
    config = {'mcpServers': {'researcheros': {'type': 'stdio', **server}}}
    if backend == 'codex':
        args = []
        for key, value in {**server, 'tool_timeout_sec': 1800, 'default_tools_approval_mode': 'approve'}.items():
            args += ['-c', f'mcp_servers.researcheros.{key}={json.dumps(value, ensure_ascii=False)}']
        yield args, {}
    elif backend == 'claude':
        yield ['--mcp-config', json.dumps(config)], {'MCP_TOOL_TIMEOUT': '1800000'}
    elif backend == 'cursor':
        with tempfile.TemporaryDirectory(prefix='researcheros-mcp-') as directory:
            root = Path(directory)
            (root / 'plugin.json').write_text(json.dumps({
                '$schema': 'https://agent-plugins.org/schemas/1.0.0/plugin.schema.json',
                'name': 'researcheros', 'version': '1.0.0',
                'description': 'Visible subagents for the current ResearcherOS chat'}))
            (root / 'mcp.json').write_text(json.dumps(config))
            yield ['--plugin-dir', directory, '--approve-mcps'], {}
    elif backend == 'opencode':
        import os
        config = json.loads(os.environ.get('OPENCODE_CONFIG_CONTENT', '{}'))
        mcp = config.setdefault('mcp', {}).setdefault('servers', {})
        mcp['researcheros'] = {'type': 'local', 'command': cmd, 'codemode': False}
        config.setdefault('permissions', []).append({'action': 'researcheros_*', 'resource': '*', 'effect': 'allow'})
        yield [], {'OPENCODE_CONFIG_CONTENT': json.dumps(config)}
    else:
        yield [], {}


TOOLS = [
    {'name': 'request_approval', 'description': 'Ask for explicit user consent in the chat permission UI. Blocks until the user approves, rejects, or cancels. Use whenever a skill requires confirmation; do not ask only in prose. Continue the proposed action only if approved is true.',
     'inputSchema': {'type': 'object', 'properties': {
         'title': {'type': 'string', 'minLength': 1}, 'details': {'type': 'string'}},
         'required': ['title'], 'additionalProperties': False}},
    {'name': 'spawn_agents', 'description': 'Run independent subagents in this chat, including nested reviewers. Returns statuses and actual results. Readonly parents cannot grant write access.',
     'inputSchema': {'type': 'object', 'properties': {
         'tasks': {'type': 'array', 'minItems': 1, 'maxItems': 4, 'items': {
             'type': 'object', 'properties': {
                 'task': {'type': 'string'}, 'role': {'type': 'string'},
                 'backend': {'type': 'string', 'enum': ['codex', 'claude', 'cursor', 'opencode']},
                 'cwd': {'type': 'string'}, 'readonly': {'type': 'boolean'},
                 'board_id': {'type': 'string'}, 'card_id': {'type': 'string'}},
             'required': ['task', 'backend', 'cwd'], 'additionalProperties': False}},
         'timeout': {'type': 'number', 'minimum': 1, 'maximum': 1800}},
         'required': ['tasks'], 'additionalProperties': False}},
    {'name': 'list_agents', 'description': 'Show participants, parent links, statuses and results for this run.',
     'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}},
]


def call(run_id, parent_id, name, args):
    if research.participant_cancelled(run_id, parent_id):
        raise RuntimeError('Parent is no longer active')
    if name == 'request_approval':
        from koi.agent_chat import approvals
        return approvals.request(run_id, parent_id, args['title'], args.get('details', ''))
    if name == 'spawn_agents':
        return research_runtime.dispatch(run_id, args['tasks'], timeout=args.get('timeout', 300), parent_id=parent_id)
    if name == 'list_agents':
        with research._db() as db:
            return [dict(row) for row in db.execute('SELECT * FROM participants WHERE run_id=? ORDER BY rowid', (run_id,))]
    raise ValueError('Unknown tool')


def main(argv=None):
    run_id, parent_id, registry = (sys.argv[1:] if argv is None else argv)
    research.PATH = Path(registry)
    for line in sys.stdin:
        request = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError('Expected a JSON-RPC object')
            if 'id' not in request:
                continue
            method, params = request.get('method'), request.get('params', {})
            if method == 'initialize':
                result = {'protocolVersion': params.get('protocolVersion', '2024-11-05'),
                          'capabilities': {'tools': {}}, 'serverInfo': {'name': 'researcheros', 'version': '1.0.0'}}
            elif method == 'ping':
                result = {}
            elif method == 'tools/list':
                result = {'tools': TOOLS}
            elif method == 'tools/call':
                try:
                    value = call(run_id, parent_id, params['name'], params.get('arguments', {}))
                    result = {'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}]}
                except Exception as exc:
                    result = {'isError': True, 'content': [{'type': 'text', 'text': f'{type(exc).__name__}: {exc}'}]}
            else:
                raise ValueError('Unsupported method')
            response = {'jsonrpc': '2.0', 'id': request['id'], 'result': result}
        except (ValueError, KeyError, TypeError) as exc:
            response = {'jsonrpc': '2.0', 'id': request.get('id') if isinstance(request, dict) else None,
                        'error': {'code': -32600, 'message': str(exc)}}
        print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
