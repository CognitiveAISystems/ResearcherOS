"""OpenCode backend: та же схема, что у Codex и Claude Code.

Программа берётся из системы, вход живёт внутри неё, режим задаётся флагом,
модель и доп. аргументы — переменными, поток событий — `--format json`.
"""

import json
import sys

import pytest

from koi.adapters import agent_backends as backends
from koi.agent_chat import runner

FAKE = r'''
import json, pathlib, sys
argv = sys.argv[1:]
pathlib.Path("argv.json").write_text(json.dumps(argv))
assert argv[:2] == ["--standalone", "run"], argv
assert "--dir" not in argv, "OpenCode 2.2 does not support --dir; use subprocess cwd"
assert sys.stdin.read() == "", "prompt must arrive as an argument, not on stdin"
prompt = argv[-1]
if prompt == "boom":
    raise SystemExit(1)
if prompt == "limit":
    print(json.dumps({"type": "error", "error": {"message": "Free usage limit reached"}}), flush=True)
    raise SystemExit(1)
if prompt == "slow":
    import time; time.sleep(20)
if "--format" in argv:
    print(json.dumps({"type": "step_start", "part": {"type": "step-start"}}), flush=True)
    print(json.dumps({"type": "tool_use", "part": {"type": "tool", "tool": "bash"}}), flush=True)
    print(json.dumps({"type": "text", "part": {"type": "text", "text": "Ответ "}}), flush=True)
    print(json.dumps({"type": "text", "part": {"type": "text", "text": "агента."}}), flush=True)
    print(json.dumps({"type": "step_finish", "part": {"reason": "stop"}}), flush=True)
else:
    print("Ответ агента.")
'''


@pytest.fixture
def binary(tmp_path, monkeypatch):
    path = tmp_path / "opencode"
    path.write_text(f"#!{sys.executable}\n" + FAKE)
    path.chmod(0o755)
    monkeypatch.setenv("KOI_OPENCODE_BIN", str(path))
    return path


def launched(tmp_path) -> list:
    return json.loads((tmp_path / "argv.json").read_text())


def test_runs_read_only_by_default(binary, tmp_path):
    """ROS-AGENT-05: по умолчанию — встроенный агент `plan`, без правок файлов."""
    from koi.adapters.agent_backends import run_opencode

    assert run_opencode("Вопрос", cwd=tmp_path, timeout=10) == "Ответ агента."
    argv = launched(tmp_path)
    assert argv[:4] == ["--standalone", "run", "--agent", "plan"]
    assert "--auto" not in argv
    assert argv[-1] == "Вопрос"


def test_edits_mode_auto_approves(binary, tmp_path):
    """Разрешённые правки — тот же `--auto`, что и ручной запуск, без выбора агента."""
    from koi.adapters.agent_backends import run_opencode

    assert run_opencode("Задание", cwd=tmp_path, timeout=10, allow_edits=True) == "Ответ агента."
    argv = launched(tmp_path)
    assert "--auto" in argv
    assert "--agent" not in argv


def test_model_and_extra_args_reach_the_cli(binary, tmp_path, monkeypatch):
    from koi.adapters.agent_backends import run_opencode

    monkeypatch.setenv("KOI_OPENCODE_MODEL", "opencode/glm-5.3-flash-free")
    monkeypatch.setenv("KOI_OPENCODE_ARGS", "--thinking 2")
    run_opencode("Вопрос", cwd=tmp_path, timeout=10)
    argv = launched(tmp_path)
    assert argv[argv.index("--model") + 1] == "opencode/glm-5.3-flash-free"
    assert "--thinking" in argv and "2" in argv


def test_streaming_joins_text_parts(binary, tmp_path):
    """Поток — как `--json` у Codex: ответ собирается из частей `text`."""
    from koi.adapters.agent_backends import run_opencode

    events = []
    text = run_opencode("Вопрос", cwd=tmp_path, timeout=10, on_event=events.append)
    assert text == "Ответ агента."
    assert "--format" in launched(tmp_path)
    assert [event["type"] for event in events][:2] == ["step_start", "tool_use"]


def test_chat_shows_opencode_work_before_any_text(monkeypatch):
    from koi.agent_chat import live, research

    monkeypatch.setattr(runner, "find_item", lambda iid: {"id": iid})
    monkeypatch.setattr(research, "coordinator_for_item", lambda iid: None)
    published = []
    monkeypatch.setattr(live, "publish", lambda iid, text: published.append(text))
    receive = runner._stream_options("aq-progress")["on_event"]
    receive({"type": "step_start", "part": {}})
    assert published[-1] == "OpenCode обрабатывает запрос…"
    receive({"type": "tool_use", "part": {"tool": "read"}})
    assert published[-1] == "OpenCode читает файлы…"
    receive({"type": "text", "part": {"text": "Итог.", "messageID": "one"}})
    assert published[-1] == "Итог."
    receive({"type": "text", "part": {"text": "Продолжение.", "messageID": "two"}})
    assert published[-1] == "Итог.\n\nПродолжение."


def test_research_executor_uses_opencode_cli(binary, tmp_path, monkeypatch):
    from koi.agent_chat import research, research_runtime
    from koi.adapters import agent_chat_activity

    monkeypatch.setattr(research, "PATH", tmp_path / "runs.sqlite3")
    monkeypatch.setattr(agent_chat_activity, "ACTIVITY_DIR", tmp_path / "activity")
    run = research.create_run("chat-opencode", "aq-opencode", "demo", "Check CLI executor")
    result = research_runtime.execute(run, {
        "backend": "opencode", "cwd": str(tmp_path), "task": "Write report",
    }, timeout=10)
    assert result["status"] == "completed"
    assert result["result"] == "Ответ агента."
    assert "--auto" in launched(tmp_path)
    assert any(event["message"] == "Ответ " for event in research.events("chat-opencode", result["id"]))


def test_cursor_sdk_does_not_receive_process_callbacks(monkeypatch):
    def sdk(prompt, *, cwd, timeout, allow_edits):
        return "SDK answer"

    monkeypatch.setitem(backends._RUNNERS, "cursor", sdk)
    assert backends.run_agent("Question", backend="cursor", on_started=lambda pid: None) == ("SDK answer", "cursor")


def test_nonzero_exit_yields_no_answer(binary, tmp_path):
    from koi.adapters.agent_backends import run_opencode

    assert run_opencode("boom", cwd=tmp_path, timeout=10) is None


def test_provider_error_is_not_reported_as_missing_auth(binary, tmp_path):
    with pytest.raises(backends.AgentBackendError, match="OpenCode: Free usage limit reached"):
        backends.run_opencode("limit", cwd=tmp_path, timeout=10, on_event=lambda event: None)


def test_timeout_yields_no_answer(binary, tmp_path):
    from koi.adapters.agent_backends import run_opencode

    assert run_opencode("slow", cwd=tmp_path, timeout=1) is None


def test_bin_comes_from_the_system(monkeypatch):
    """Программа ищется в PATH — своего установщика у бэкенда нет, как у codex/claude."""
    monkeypatch.delenv("KOI_OPENCODE_BIN", raising=False)
    monkeypatch.setattr(backends.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert backends._opencode_bin() == "/usr/bin/opencode"
    assert backends._opencode_ready() is True


def test_explicit_path_overrides_the_system_binary(tmp_path, monkeypatch):
    """Свой путь принимается, даже когда в PATH есть другой OpenCode."""
    original_which = backends.shutil.which

    path = tmp_path / "my-opencode"
    path.write_text(f"#!{sys.executable}\n")
    path.chmod(0o755)
    monkeypatch.setenv("KOI_OPENCODE_BIN", str(path))

    def fake_which(name):
        return "/usr/bin/opencode" if name == "opencode" else original_which(name)

    monkeypatch.setattr(backends.shutil, "which", fake_which)
    assert backends._opencode_bin() == str(path)


def test_missing_binary_yields_no_answer(monkeypatch):
    monkeypatch.delenv("KOI_OPENCODE_BIN", raising=False)
    monkeypatch.setattr(backends.shutil, "which", lambda name: None)
    assert backends._opencode_bin() is None
    assert backends._opencode_ready() is False
    assert backends.run_opencode("Вопрос", timeout=5) is None


def test_one_registry_drives_order_labels_and_streams():
    """Реестр — единственный перечень: порядок, подписи, поток, запуск, проверка."""
    names = [row[0] for row in backends._BACKENDS]
    assert names == backends.DEFAULT_BACKEND_ORDER.split(",")
    assert backends.CLI_AGENTS[-1] == ("opencode", "OpenCode")
    assert "opencode" in backends.STREAMING_BACKENDS
    assert backends._RUNNERS["opencode"] is backends.run_opencode
    assert backends.known_backend("opencode") is True
    assert backends.known_backend("gpt-shell") is False


def test_opencode_is_the_last_automatic_choice(monkeypatch):
    monkeypatch.delenv("KOI_AGENT_BACKEND", raising=False)
    assert backends.backend_order()[-1] == "opencode"
    assert runner._LOCAL_AGENT_CHAIN[-1] == "opencode"


def test_explicit_agent_list_is_a_closed_set(monkeypatch):
    """Настроенный список не дополняется новым агентом — только порядок по умолчанию."""
    monkeypatch.setenv("KOI_AGENT_BACKEND", "claude,codex")
    assert backends.backend_order() == ["claude", "codex"]


def test_local_chain_follows_the_configured_order(monkeypatch):
    monkeypatch.setenv("KOI_AGENT_BACKEND", "claude,codex")
    assert runner._local_agent_chain() == ("claude", "codex")
    monkeypatch.setenv("KOI_AGENT_BACKEND", "cursor")
    assert runner._local_agent_chain() == runner._LOCAL_AGENT_CHAIN


def test_status_has_the_same_shape_as_other_agents(monkeypatch):
    monkeypatch.setattr(backends.shutil, "which", lambda name: f"/usr/bin/{name}")
    row = backends.backend_status()["opencode"]
    assert set(row) == {"available", "bin", "model"}
    assert row["available"] is True


def test_unknown_backend_name_is_not_ready():
    assert backends._ready("nope") is False


def test_editable_backends_exclude_text_models(monkeypatch):
    assert "openrouter" not in backends.editable_backends()
    monkeypatch.setattr(backends.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert "opencode" in backends.editable_backends()


def test_any_agent_available_with_opencode_only(monkeypatch):
    """Наличие агента считается по реестру, а не по одному списку для UI."""
    monkeypatch.setattr(backends, "_ready", lambda name: name == "opencode")
    assert backends.any_agent_available() is True
    monkeypatch.setattr(backends, "_ready", lambda name: False)
    assert backends.any_agent_available() is False


def test_explicit_choice_is_not_replaced(monkeypatch):
    """ROS-AGENT-07: явный выбор не подменяется порядком."""
    calls = []

    def fake(prompt, **kwargs):
        calls.append(kwargs)
        return "Ответ."

    monkeypatch.setitem(backends._RUNNERS, "opencode", fake)
    monkeypatch.setitem(backends._RUNNERS, "claude", lambda *_a, **_kw: pytest.fail("выбран не тот агент"))
    text, name = backends.run_agent("Вопрос", backend="opencode", allow_edits=True)
    assert (text, name) == ("Ответ.", "opencode")
    assert calls


def test_run_agent_forwards_cancellation(monkeypatch):
    seen = {}

    def fake(prompt, **kwargs):
        seen.update(kwargs)
        return "Ответ."

    monkeypatch.setitem(backends._RUNNERS, "opencode", fake)
    backends.run_agent("Вопрос", backend="opencode", is_cancelled=lambda: False)
    assert callable(seen.get("is_cancelled"))


def _api_item(monkeypatch, item):
    """Wire the runner for API mode, where no desktop journal exists."""
    monkeypatch.setattr(runner, "find_item", lambda _id: item)
    monkeypatch.setattr(runner, "is_api_agent_mode", lambda: True)
    monkeypatch.setattr(runner, "is_cursor_manual_agent_mode", lambda: False)
    monkeypatch.setattr(runner, "mark_processing", lambda _id: None)
    monkeypatch.setattr(runner, "record", lambda *_args: None)
    monkeypatch.setattr(runner, "build_context", lambda _id: {"project_id": None})
    monkeypatch.setattr(runner, "_stream_options", lambda _id: {})
    monkeypatch.setattr(runner, "backend_status", lambda: {"opencode": {"available": True}})
    monkeypatch.setattr(runner, "cli_agents", list)


def test_api_mode_honours_the_chosen_backend(monkeypatch):
    """ROS-AGENT-07: в API-режиме выбор человека доходит до запуска."""
    item = {"id": "aq-choice", "project_id": None, "question": "Что известно?",
            "status": "pending", "purpose": "agent", "cli_agent": "opencode"}
    _api_item(monkeypatch, item)
    seen = {}
    answers = []

    def fake(prompt, **kwargs):
        seen.update(kwargs)
        return ("Ответ агента.", "opencode")

    monkeypatch.setattr(runner, "run_agent", fake)
    monkeypatch.setattr(runner, "submit_answer", lambda _id, answer, **_kw: answers.append(answer))
    assert runner.process_item(item["id"]) is True
    assert seen["backend"] == "opencode"
    assert answers == ["Ответ агента."]


def test_api_mode_failure_still_answers_the_chat(monkeypatch):
    """ROS-AGENT-06: отказ агента виден в чате, а не только в журнале."""
    item = {"id": "aq-silent", "project_id": None, "question": "Что известно?",
            "status": "pending", "purpose": "agent", "cli_agent": "opencode"}
    _api_item(monkeypatch, item)
    answers = []
    monkeypatch.setattr(runner, "run_agent", lambda *_a, **_kw: (None, None))
    monkeypatch.setattr(runner, "submit_answer",
                        lambda _id, answer, **kw: answers.append((answer, kw.get("answer_kind"))))
    assert runner.process_item(item["id"]) is True
    assert answers == [("Агент не вернул ответ. Проверьте локальную авторизацию и повторите вопрос.", "warning")]


def test_provider_failure_is_shown_in_chat(monkeypatch):
    item = {"id": "aq-limit", "project_id": None, "question": "Question",
            "status": "pending", "purpose": "agent", "cli_agent": "opencode"}
    _api_item(monkeypatch, item)
    answers = []

    def fail(*args, **kwargs):
        raise backends.AgentBackendError("OpenCode: Free usage limit reached")

    monkeypatch.setattr(runner, "run_agent", fail)
    monkeypatch.setattr(runner, "submit_answer",
                        lambda _id, answer, **kw: answers.append((answer, kw.get("answer_kind"))))
    assert runner.process_item(item["id"]) is True
    assert answers == [("OpenCode: Free usage limit reached", "warning")]


def test_unexpected_failure_still_answers_the_chat(monkeypatch):
    item = {"id": "aq-crash", "project_id": None, "question": "Что известно?",
            "status": "pending", "purpose": "agent", "cli_agent": "opencode"}
    _api_item(monkeypatch, item)
    notes, answers = [], []
    monkeypatch.setattr(runner, "run_agent", lambda *_a, **_kw: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(runner, "record", lambda _id, text: notes.append(text))
    monkeypatch.setattr(runner, "submit_answer",
                        lambda _id, answer, **kw: answers.append((answer, kw.get("answer_kind"))))
    assert runner.process_item(item["id"]) is True
    assert notes == ["Ошибка запуска: RuntimeError."]
    assert answers[0][1] == "warning"


def test_api_mode_honours_a_choice_outside_the_auto_order(monkeypatch):
    item = {"id": "aq-outside", "project_id": None, "question": "Что известно?",
            "status": "pending", "purpose": "agent", "cli_agent": "opencode"}
    _api_item(monkeypatch, item)
    monkeypatch.setenv("KOI_AGENT_BACKEND", "claude")
    monkeypatch.setattr(runner, "cli_agents",
                        lambda: [{"id": "opencode", "label": "OpenCode", "available": True}])
    monkeypatch.setattr(runner, "backend_status",
                        lambda: {"opencode": {"available": True}, "claude": {"available": False}})
    answers = []
    monkeypatch.setattr(runner, "run_agent", lambda *_a, **_kw: ("Ответ агента.", "opencode"))
    monkeypatch.setattr(runner, "submit_answer", lambda _id, answer, **_kw: answers.append(answer))
    assert runner.process_item(item["id"]) is True
    assert answers == ["Ответ агента."]


def test_card_run_accepts_opencode(capsys, monkeypatch, tmp_path):
    """Карточку можно прогнать явно выбранным агентом — как Claude или Cursor."""
    from koi.projects.report_ingest import cli

    monkeypatch.setenv("KOI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(backends.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(sys, "argv", ["cli", "demo", "card-1", "--backend", "opencode"])
    assert cli.main() == 2  # аргументы приняты; до проекта дело не дошло
    capsys.readouterr()
    monkeypatch.setattr(sys, "argv", ["cli", "demo", "card-1", "--backend", "nope"])
    with pytest.raises(SystemExit) as excinfo:
        cli.main()
    assert excinfo.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_card_auto_run_reaches_opencode(monkeypatch, tmp_path):
    """ROS-AGENT-01: автопрогон карточки доходит до нового агента."""
    from koi.adapters import agent_backends
    from koi.projects import done_research_auto as auto

    monkeypatch.setattr(auto, "_cursor_cli", lambda *_a, **_kw: None)
    monkeypatch.setattr(auto, "build_context", lambda *_a, **_kw: {})
    monkeypatch.setattr(auto, "_prompt", lambda *_a, **_kw: "Задание")
    monkeypatch.setattr(auto, "_log", lambda *_a, **_kw: None)
    taken = []
    monkeypatch.setattr(auto, "dequeue", lambda project, board, card: taken.append((project, board, card)))
    monkeypatch.setitem(agent_backends._RUNNERS, "codex", lambda *_a, **_kw: None)
    monkeypatch.setitem(agent_backends._RUNNERS, "claude", lambda *_a, **_kw: None)
    monkeypatch.setitem(agent_backends._RUNNERS, "opencode", lambda *_a, **_kw: '{"skip": true}')
    assert auto.process_card("demo", "board", "card-1") is True
    assert taken == [("demo", "board", "card-1")]


def test_local_chat_walks_the_agent_chain(monkeypatch):
    """Без Cursor CLI локальный чат идёт по цепочке и доходит до OpenCode."""
    monkeypatch.setattr(runner, "find_agent_bin", lambda: None)
    monkeypatch.setattr(runner, "run_agent", lambda prompt, **kwargs: ("Ответ.", kwargs.get("backend")))
    text, name = runner._run_local_agent("Вопрос", "aq-chain", log_activity=False)
    assert text == "Ответ."
    assert name in runner._local_agent_chain()


def test_acp_backend_without_sdk_names_the_missing_protocol(monkeypatch):
    """Без SDK протокола выбор `acp:*` даёт понятный отказ, а не запуск."""
    item = {"id": "aq-acp", "project_id": None, "question": "Что известно?",
            "status": "pending", "purpose": "agent", "cli_agent": "acp:test"}
    monkeypatch.setattr(runner, "find_item", lambda _id: item)
    monkeypatch.setattr(runner, "is_api_agent_mode", lambda: False)
    monkeypatch.setattr(runner, "is_cursor_manual_agent_mode", lambda: False)
    monkeypatch.setattr(runner, "mark_processing", lambda _id: None)
    monkeypatch.setattr(runner, "record", lambda *_args: None)
    monkeypatch.setattr(runner, "build_context", lambda _id: {"project_id": None})
    monkeypatch.setattr(runner, "_stream_options", lambda _id: {})
    monkeypatch.setattr(runner, "cli_agents", list)
    monkeypatch.setattr(runner, "backend_status", dict)
    monkeypatch.setattr(runner, "acp_agents", list)
    answers = []
    monkeypatch.setattr(runner, "submit_answer",
                        lambda _id, answer, **kw: answers.append((answer, kw.get("answer_kind"))))
    assert runner.process_item(item["id"]) is True
    expected = ("acp:test сейчас недоступен. Проверьте, что установлен агент ACP "
                "и SDK протокола, и повторите вопрос.")
    assert answers == [(expected, "warning")]


def test_local_chat_names_an_unavailable_backend(monkeypatch):
    """Отказ называет того агента, которого выбрал человек."""
    item = {"id": "aq-nolabel", "project_id": None, "question": "Что известно?",
            "status": "pending", "purpose": "agent", "cli_agent": "claude"}
    monkeypatch.setattr(runner, "find_item", lambda _id: item)
    monkeypatch.setattr(runner, "is_api_agent_mode", lambda: False)
    monkeypatch.setattr(runner, "is_cursor_manual_agent_mode", lambda: False)
    monkeypatch.setattr(runner, "mark_processing", lambda _id: None)
    monkeypatch.setattr(runner, "build_context", lambda _id: {"project_id": None})
    monkeypatch.setattr(runner, "_stream_options", lambda _id: {})
    monkeypatch.setattr(runner, "cli_agents", lambda: [{"id": "claude", "label": "Claude", "available": False}])
    monkeypatch.setattr(runner, "backend_status", lambda: {"claude": {"available": False}})
    notes, answers = [], []
    monkeypatch.setattr(runner, "record", lambda _id, text: notes.append(text))
    monkeypatch.setattr(runner, "submit_answer",
                        lambda _id, answer, **kw: answers.append((answer, kw.get("answer_kind"))))
    assert runner.process_item(item["id"]) is True
    assert notes == ["Claude сейчас недоступен. Проверьте, что CLI установлен, и повторите вопрос."]
    assert answers[0][1] == "warning"


def test_card_run_refuses_an_unavailable_backend(capsys, monkeypatch, tmp_path):
    """Недоступный агент не запускается молча: карточка говорит причину."""
    from koi.projects.report_ingest import cli

    monkeypatch.setenv("KOI_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(backends.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cli, "backend_status",
                        lambda: {"opencode": {"available": False, "reason": "OpenCode не найден"}})
    monkeypatch.setattr(sys, "argv", ["cli", "demo", "card-1", "--backend", "opencode"])
    with pytest.raises(SystemExit) as excinfo:
        cli.main()
    assert excinfo.value.code == 2
    assert "OpenCode не найден" in capsys.readouterr().err


def test_acp_client_degrades_without_the_sdk():
    """Без SDK протокола ACP-вызовы тихо не работают, а не падают трейсбеком."""
    from koi.agent_chat import acp_client

    if acp_client.AVAILABLE:  # SDK стоит: деградацию не проверить
        pytest.skip("ACP SDK установлен")
    assert acp_client.snapshot("cid") is None
    assert acp_client.decide("cid", "perm", "opt") is False
    assert acp_client.cancel("cid") is False
    assert acp_client.run("cid", "aq-1", "prompt", ".", "acp:test") is None
    assert acp_client.run_executor("agent", "aq-1", "prompt", ".", "acp:test", lambda _m: None) is None


def test_acp_catalog_appears_when_the_sdk_is_present(monkeypatch):
    """С SDK каталог показывает ACP-агентов рядом с CLI, без SDK — не показывает."""
    from koi.adapters import acp_agents as discovery

    monkeypatch.setattr(backends.importlib.util, "find_spec", lambda name: object() if name == "acp" else None)
    monkeypatch.setattr(discovery, "agents", lambda: [{"id": "acp:test", "label": "ACP", "available": True}])
    assert backends.acp_agents() == [{"id": "acp:test", "label": "ACP", "available": True}]


def test_acp_catalog_survives_a_broken_discovery_module(monkeypatch):
    """Сломанное обнаружение ACP не роняет каталог агентов."""
    import sys
    import types

    monkeypatch.setattr(backends.importlib.util, "find_spec", lambda name: object() if name == "acp" else None)
    monkeypatch.setitem(sys.modules, "koi.adapters.acp_agents", types.ModuleType("koi.adapters.acp_agents"))
    assert backends.acp_agents() == []


def test_acp_turn_is_handed_to_the_client(monkeypatch):
    """Выбранный ACP-агент уходит в клиент протокола, а не в CLI-запуск."""
    from koi.agent_chat import acp_client

    item = {"id": "aq-fade99", "project_id": None, "question": "Что известно?",
            "status": "pending", "purpose": "agent", "cli_agent": "acp:test"}
    monkeypatch.setattr(runner, "find_item", lambda _id: item)
    monkeypatch.setattr(runner, "is_api_agent_mode", lambda: False)
    monkeypatch.setattr(runner, "is_cursor_manual_agent_mode", lambda: False)
    monkeypatch.setattr(runner, "mark_processing", lambda _id: None)
    monkeypatch.setattr(runner, "record", lambda *_args: None)
    monkeypatch.setattr(runner, "build_context", lambda _id: {"project_id": None})
    monkeypatch.setattr(runner, "_stream_options", lambda _id: {})
    monkeypatch.setattr(runner, "cli_agents", list)
    monkeypatch.setattr(runner, "backend_status", dict)
    monkeypatch.setattr(runner, "acp_agents", lambda: [{"id": "acp:test", "label": "ACP", "available": True}])
    seen = []
    monkeypatch.setattr(acp_client, "run", lambda *args, **kwargs: seen.append(args) or None)
    answers = []
    monkeypatch.setattr(runner, "submit_answer",
                        lambda _id, answer, **kw: answers.append((answer, kw.get("answer_kind"))))
    assert runner.process_item(item["id"]) is True
    assert seen and seen[0][4] == "acp:test"
    assert answers == [("Агент не вернул ответ. Проверьте локальную авторизацию и повторите вопрос.", "warning")]
