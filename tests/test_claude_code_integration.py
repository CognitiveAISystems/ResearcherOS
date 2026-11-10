"""Claude Code in ResearcherOS: IDE files, the onboarding choice and the backend registry."""
from __future__ import annotations

import json
import re
from pathlib import Path

from koi.adapters import agent_backends

ROOT = Path(__file__).resolve().parents[1]


def test_claude_md_imports_agents_md():
    text = (ROOT / 'CLAUDE.md').read_text(encoding='utf-8')
    assert re.search(r'^@AGENTS\.md\s*$', text, re.M)
    assert (ROOT / 'AGENTS.md').is_file()


def test_claude_settings_template_points_at_existing_hook():
    settings = json.loads((ROOT / 'agents' / 'claude-settings.json').read_text(encoding='utf-8'))
    commands = [hook['command'] for group in settings['hooks']['SessionStart'] for hook in group['hooks']]
    assert commands
    for command in commands:
        relative = command.replace('"$CLAUDE_PROJECT_DIR"/', '')
        assert (ROOT / relative).is_file(), command


def test_claude_dir_is_local_only():
    assert re.search(r'^\.claude/\s*$', (ROOT / '.gitignore').read_text(encoding='utf-8'), re.M)


def test_onboarding_window_offers_claude():
    source = (ROOT / 'web' / 'onboarding-interview.js').read_text(encoding='utf-8')
    assert '<option value="claude">Claude</option>' in source
    assert "['codex', 'claude'].includes(saved)" in source


def test_claude_is_a_streaming_editable_cli_backend():
    assert 'claude' in agent_backends.editable_backends()
    assert {'id': 'claude', 'label': 'Claude'} == next({'id': row['id'], 'label': row['label']} for row in agent_backends.cli_agents() if row['id'] == 'claude')
    assert 'claude' in agent_backends.STREAMING_BACKENDS


def test_claude_docs_name_every_setting():
    docs = (ROOT / 'docs' / 'agents.md').read_text(encoding='utf-8')
    for name in ('KOI_CLAUDE_BIN', 'KOI_CLAUDE_MODEL', 'KOI_CLAUDE_ARGS', 'KOI_CLAUDE_ALLOWED_TOOLS', 'agents/claude-settings.json', 'koi-project-onboard'):
        assert name in docs, name
    assert 'Claude Code' in (ROOT / 'README.md').read_text(encoding='utf-8')
