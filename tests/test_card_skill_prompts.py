from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from api.schemas import AgentChatBody
from api.routers import agents
from koi.agent_chat import runner

@pytest.mark.parametrize('purpose,skill', [('run','koi-execute-card'), ('prose','koi-prose-style')])
def test_card_command_uses_its_skill(monkeypatch, purpose, skill):
    path = Path(__file__).resolve().parents[1] / 'agents/skills' / skill / 'SKILL.md'
    monkeypatch.setattr(runner, 'build_context', lambda _: {'purpose':purpose,'skill':str(path),'card':{'id':'card-42'},'user_question':'Задача пользователя'})
    prompt = runner._sdk_prompt('item')
    assert path.read_text() in prompt
    assert 'card-42' in prompt and 'Задача пользователя' in prompt
    assert ('Не запускай эксперимент' if purpose == 'prose' else 'Не ставь done') in prompt

@pytest.mark.parametrize('purpose', ['run', 'prose', 'compress'])
def test_mutating_card_commands_require_a_card(monkeypatch, purpose):
    monkeypatch.setattr(agents, 'load_project', lambda *a, **kw: SimpleNamespace())
    with pytest.raises(HTTPException) as error:
        agents.post_agent_chat(AgentChatBody(project_id='demo',question='test',purpose=purpose), None)
    assert error.value.status_code == 400

def test_question_stays_read_only(monkeypatch):
    monkeypatch.setattr(runner, 'build_context', lambda _: {'purpose':'question','card':{'id':'card-42'}})
    assert 'Не меняй файлы' in runner._sdk_prompt('item')


def test_compress_edits_report_with_reader_rewrite_and_preserves_evidence(monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'agents/skills/koi-reader-rewrite/SKILL.md'
    monkeypatch.setattr(runner, 'build_context', lambda _: {
        'purpose': 'compress', 'skill': str(path), 'card': {'id': 'card-42'},
        'user_question': 'Сожми отчёт'})
    prompt = runner._sdk_prompt('item')
    assert path.read_text() in prompt
    assert 'сохранить отчёт' in prompt
    assert 'все изображения и ссылки' in prompt
    assert 'чеклисты и их галочки' in prompt
    assert 'не меняй карточку' in prompt
    assert 'card-42' in prompt
