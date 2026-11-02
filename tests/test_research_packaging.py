import sys
import pytest
from api import desktop_server
from koi.agent_chat import research,research_tools,research_runtime


@pytest.mark.parametrize('flag,module', [('--research-tools',research_tools),('--research-runtime',research_runtime)])
def test_bundled_tool_entrypoint_does_not_start_server(monkeypatch,flag,module):
    called=[]
    monkeypatch.setattr(sys,'argv',['researchos-server',flag])
    monkeypatch.setattr(module,'main',lambda:called.append(flag))
    monkeypatch.setattr(desktop_server,'DesktopServer',lambda **kw:pytest.fail('Unexpected server start'))
    assert desktop_server.main()==0
    assert called==[flag]


def test_frozen_commands_use_server_flags(monkeypatch):
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    assert research.tool_commands()['project']==[sys.executable,'--research-tools']
    assert research.tool_commands()['dispatch']==[sys.executable,'--research-runtime']


@pytest.mark.parametrize('allow_edits', [False, True])
def test_desktop_codex_registry_is_writable_only_for_editing_agents(monkeypatch, tmp_path, allow_edits):
    from types import SimpleNamespace
    from koi.adapters import agent_backends
    registry = tmp_path / 'Application Support' / '.run'
    monkeypatch.setattr(agent_backends, 'get_workspace', lambda: SimpleNamespace(run_dir=registry))
    monkeypatch.setattr(agent_backends, '_codex_bin', lambda: '/test/codex')
    monkeypatch.delenv('KOI_CODEX_ARGS', raising=False)
    calls = []
    def execute(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout='ok')
    monkeypatch.setattr(agent_backends.subprocess, 'run', execute)
    assert agent_backends.run_codex_exec('task', cwd=tmp_path, allow_edits=allow_edits) == 'ok'
    command = calls[0]
    assert ('--add-dir' in command) is allow_edits
    if allow_edits:
        assert command[command.index('--add-dir') + 1] == str(registry.resolve())
        assert registry.is_dir()
        assert command[command.index('-s') + 1] == 'workspace-write'
