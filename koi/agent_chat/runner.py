"""Process one agent-chat queue item: research.json auto-answer, then LLM agent.

Порядок: сначала бесплатный авто-ответ из research.json; если база не
покрывает вопрос — локальный агент через koi.adapters.agent_backends (Claude Code
CLI и/или Cursor SDK, см. KOI_AGENT_BACKEND). Если ни один бэкенд не
доступен — в чат уходит предупреждение с инструкцией по настройке ключа.
"""

from __future__ import annotations

import json
import subprocess
from koi.adapters.agent_backends import backend_status, cli_agents, run_agent
from koi.agent_chat.cli import build_context
from koi.agent_chat.auto import try_auto_answer
from koi.agent_chat.formatting import ANSWER_FORMAT_INSTRUCTIONS, no_cursor_key_warning
from koi.adapters.agent_chat_queue import find_item, list_pending, mark_processing, clear_processing_pid, submit_answer
from koi.adapters.agent_process import AgentCancelled, run_json
from koi.agent_chat import live
from koi.agent_chat.activity import record
from koi.adapters.settings_store import is_api_agent_mode, is_cursor_manual_agent_mode, load_env_file
from koi.adapters.workspace import get_workspace
from koi.literature.cursor_agent_terminal import find_agent_bin
from koi.agent_chat.report_grill import SKILLS
from koi.adapters.report_grill_reply import parse_reply

_ws = get_workspace()


def _sdk_prompt(item_id: str) -> str:
    ctx = build_context(item_id)
    if "project_id" in ctx and ctx["project_id"] is None:
        from koi.agent_chat.context_routing import INSTRUCTIONS
        return (
            "Ты агент ResearcherOS. Дерево для этого чата ещё не выбрано. "
            + ("Программа уже выбрана; работай только с деревьями этой программы. " if ctx.get("program_id") else
               "Запрос может касаться всех исследований рабочего пространства. ")
            + "В контексте дан список проектов и пути "
            "к их исследовательским материалам. Изучи нужные research.json и отчёты, "
            "ссылайся на найденные результаты. Не приписывай вопрос текущему проекту интерфейса. "
            + INSTRUCTIONS + "\n"
            + "Ответь по-русски.\n\nКонтекст:\n" + json.dumps(ctx, ensure_ascii=False, indent=2)
        )
    if ctx.get("purpose") in ("report_grill", "grill_me"):
        from koi.agent_chat.report_grill import build_prompt
        return build_prompt(ctx)
    if ctx.get("purpose") in ("prose", "run") and ctx.get("skill"):
        from pathlib import Path
        task = (
            "Проверь и улучши текст текущей карточки и отчёта по koi-prose-style. "
            "Сохрани факты, числа, ссылки, статусы и структуру. Не запускай эксперимент."
            if ctx["purpose"] == "prose" else
            "Выполни текущую карточку по koi-execute-card: переведи в running, "
            "выполни план, фиксируй проверки и результаты, затем итоговый статус. "
            "Не ставь done, пока работа или удалённая джоба не завершена."
        )
        return f"{Path(ctx['skill']).read_text(encoding='utf-8')}\n\n{task}\n\nКонтекст:\n{json.dumps(ctx, ensure_ascii=False, indent=2)}"
    if ctx.get("purpose") == "make_report" and ctx.get("skill"):
        from pathlib import Path
        skill = Path(ctx["skill"]).read_text(encoding="utf-8")
        return (
            f"{skill}\n\nСобери отчёт по текущей задаче и сохрани его в документе карточки.\n\n"
            f"Контекст:\n{json.dumps(ctx, ensure_ascii=False, indent=2)}"
        )
    if ctx.get("purpose") == "question":
        return (
            "Ответь на вопрос по выбранному проекту и карточке. Сначала проверь "
            "research_database, затем при необходимости текущий отчёт и другие "
            "связанные материалы. Не меняй файлы. Если данных недостаточно, "
            "скажи об этом прямо. Ответь по-русски.\n\n"
            f"Контекст:\n{json.dumps(ctx, ensure_ascii=False, indent=2)}"
        )
    return (
        "Ты агент исследовательского проекта в ResearcherOS. Выполни запрос человека: "
        "это может быть вопрос, анализ, правка файла или другая работа в проекте. "
        "Не своди любой запрос к поиску готового вывода. Изучи нужные файлы и "
        "действуй в пределах выбранного проекта; прочитай его AGENTS.md и применимые "
        "skills перед правкой. Для постановки эксперимента используй koi-grill-experiment, "
        "koi-report-review и koi-prose-style. Если человек поручил подготовить или изменить "
        "постановку в карточке, сохраняй промежуточные версии прямо в её отчёте: "
        "первый содержательный черновик после чтения карточки и ближайшего контекста, "
        "затем обновления после разбора материалов, уточнения решений и замечаний критиков. "
        "Не откладывай первую запись до конца анализа или финального PASS. "
        "Применяй раздел «Живая постановка в карточке» из koi-report-review: "
        "помечай текст как рабочий черновик, явно указывай открытые вопросы, "
        "не выдумывай ответы, параметры и результаты. Сохраняй согласованные детали "
        "и существующие результаты; перед каждой записью перечитывай файл и учитывай "
        "правки человека. Используй файл отчёта в research_root; сообщения о ходе работы "
        "в чате не заменяют обновлений документа. Подготовка постановки не меняет колонку "
        "карточки и не запускает эксперимент. Финальную постановку сохраняй только после "
        "PASS всех нужных критиков; до этого сохраняй пометку черновика. "
        "Подсвечивай этапы этой работы в чате отдельными короткими сообщениями "
        "в fenced-блоке setup-progress, например:\n```setup-progress\n"
        "Предложил черновик постановки — 1\n```\n"
        "Нумеруй сохранённые черновики последовательно в рамках текущей задачи. "
        "О первом черновике и обновлениях («Обновил черновик постановки — 2») "
        "сообщай только после успешного сохранения файла. Перед уточнениями и ревью "
        "сообщай «Уточняю детали и исправляю стиль». После финального PASS и сохранения — "
        "«Постановка проверена и сохранена». Публикуй этап сразу, не собирай их в конце "
        "ответа; не повторяй одинаковый этап без нового действия. "
        "Для вопроса об уже полученных результатах начни с research_database, "
        "затем при необходимости открой связанный отчёт. Для изменения проекта "
        "выполни работу и назови изменённые файлы и проверку. Если запрос неясен, "
        "задай один уточняющий вопрос в ответе. Не заявляй о правках, которых не сделал. "
        "Верни итог или вопрос для панели чата на русском языке.\n\n"
        f"Контекст:\n{json.dumps(ctx, ensure_ascii=False, indent=2)}"
    )


def _any_backend_available() -> bool:
    status = backend_status()
    return any(
        status.get(name, {}).get("available") for name in status.get("order", [])
    )


def _cursor_print_command(agent_bin, *, mode: str | None, force: bool, model: str | None = None) -> list[str]:
    command = [str(agent_bin), "--print", "--trust"]
    if mode:
        command.extend(["--mode", mode])
    if force:
        command.append("--force")
    if model:
        command.extend(["--model", model])
    command.extend(["--output-format", "stream-json"])
    return command


def _note_chat(item_id: str, message: str) -> None:
    if not item_id.startswith("aq-"):
        return
    record(item_id, message)


def _stream_options(item_id):
    if not item_id.startswith("aq-") or not find_item(item_id):
        return {}
    output = ""
    message_id = None
    def receive(event):
        nonlocal output, message_id
        kind = event.get("type")
        if kind == "item.completed" and event.get("item", {}).get("type") == "agent_message":
            message = event["item"].get("text", "")
            output += ("\n\n" if output else "") + message
        elif kind == "assistant":
            message = "".join(p.get("text", "") for p in event.get("message", {}).get("content", []) if p.get("type") == "text")
            current_id = event.get("message", {}).get("id")
            if current_id and message_id and current_id != message_id and output:
                output += "\n\n"
            message_id = current_id
            output += message
        else:
            return
        if output:
            live.publish(item_id, output)
    return {"on_event": receive, "is_cancelled": lambda: live.cancelled(item_id)}


def _run_local_agent(
    prompt: str,
    item_id: str,
    *,
    mode: str | None = "ask",
    force: bool = False,
    cwd=None,
    timeout: int = 1800,
    model: str | None = None,
    fallback: bool = True,
    log_activity: bool = True,
    cli_agent: str | None = None,
    externally_sandboxed: bool = False,
) -> tuple[str | None, str | None]:
    """Prefer the same Cursor CLI used by literature, without opening Terminal.app."""
    workdir = cwd or _ws.agent_cwd()
    stream = _stream_options(item_id) if log_activity else {}
    if cli_agent in ("codex", "claude"):
        return run_agent(prompt, cwd=workdir, backend=cli_agent, timeout=timeout, allow_edits=force,
                         **stream,
                         **({"externally_sandboxed": True} if externally_sandboxed else {}))
    if cli_agent == "cursor":
        fallback = False
    agent_bin = find_agent_bin()
    if cli_agent == "cursor" and not agent_bin:
        return None, None
    if agent_bin:
        answer = ""
        result_text = ""
        def receive(event):
            nonlocal answer, result_text
            if stream:
                stream["on_event"](event)
            kind = event.get("type")
            if kind == "assistant":
                parts = event.get("message", {}).get("content", [])
                message = "".join(part.get("text", "") for part in parts if part.get("type") == "text")
                answer += message
                if message and log_activity:
                    _note_chat(item_id, f"Агент: {message[:500]}")
            elif kind == "tool_call" and event.get("subtype") == "started":
                calls = event.get("tool_call") or {}
                name = next((key.removesuffix("ToolCall") for key in calls if key.endswith("ToolCall")), "tool")
                if log_activity:
                    _note_chat(item_id, f"Агент использует инструмент: {name}.")
            elif kind == "result":
                result_text = str(event.get("result") or "").strip()
        try:
            code = run_json(_cursor_print_command(agent_bin, mode=mode, force=force, model=model),
                            prompt, cwd=workdir, timeout=timeout, on_event=receive,
                            is_cancelled=stream.get("is_cancelled"))
        except subprocess.TimeoutExpired:
            code = -1
        if code == 0 and (answer or result_text):
            return result_text or answer, "Cursor CLI"
        if log_activity:
            _note_chat(item_id, "Cursor CLI не вернул ответ; пробую другой локальный агент.")
        if not fallback:
            return None, None
    if agent_bin and not fallback:
        return None, None
    for backend in ("codex", "claude"):
        text, name = run_agent(prompt, cwd=workdir, backend=backend, timeout=timeout, allow_edits=force,
                         **stream,
                         **({"externally_sandboxed": True} if externally_sandboxed else {}))
        if text:
            return text, name
    return None, None


def _review_grill_proposal(item_id: str, proposal: dict[str, str], *, local_mode: bool, log_activity: bool = True, evidence: dict | None = None) -> tuple[bool, str]:
    """One read-only reviewer checks setup, then prose, before an update."""
    draft = json.dumps(proposal, ensure_ascii=False, indent=2)
    setup_skill = (SKILLS / "koi-report-review" / "SKILL.md").read_text(encoding="utf-8")
    prose_skill = (SKILLS / "koi-prose-style" / "SKILL.md").read_text(encoding="utf-8")
    prompt = (
        "Ты отдельный readonly агент-рецензент. Не редактируй файлы и не отвечай человеку. "
        "Это накопленный черновик редактора карточки с полями Цель, Постановка эксперимента, Задачи. "
        "Это ПРОМЕЖУТОЧНОЕ резюме живого интервью, а не финальная постановка перед прогоном. "
        "Сначала проверь, что подтверждённые решения переданы точно, неподтверждённые "
        "отмечены как открытые и нет выдуманных чисел или выводов. "
        "В истории ответ пользователя относится к ПРЕДЫДУЩЕМУ вопросу агента. "
        "Поле pending_question — новый вопрос без ответа; его рекомендация НЕ согласована. "
        "Затем проверь прозу: естественный русский язык, объяснение терминов, отсутствие AI-тона. "
        "Ссылки на историю диалога, статус ответа, рекомендацию агента, id карточки и backlog "
        "в видимом тексте — причина FAIL. "
        "Не требуй заголовков нумерованного шаблона. Первая строка ответа — ровно PASS "
        "или FAIL; после FAIL перечисли конкретные исправления для агента-писателя.\n\n"
        f"Правила постановки:\n{setup_skill}\n\nПравила прозы:\n{prose_skill}\n\n"
        "Приоритет для ЭТОГО промежуточного резюме: отсутствие пока не выбранной главной метрики, "
        "числового порога, контроля, формулы или полного списка артефактов НЕ является причиной FAIL, "
        "если пробел прямо назван открытым. Эти финальные ворота применяются после интервью. "
        "FAIL только если текст искажает ответы человека, выдаёт открытое решение за принятое, "
        "теряет ранее согласованные детали, нечитаем, не содержит трёх полей или задачи не имеют чекбоксов.\n\n"
        f"Черновик:\n{draft}\n\nИстория для проверки фактов:\n"
        f"{json.dumps({'history': (evidence or {}).get('history', []), 'pending_question': (evidence or {}).get('pending_question')}, ensure_ascii=False, indent=2)}"
    )
    if local_mode:
        answer, _ = _run_local_agent(prompt, item_id, mode="ask", force=False, log_activity=log_activity)
    else:
        answer, _ = run_agent(prompt, cwd=_ws.agent_cwd(), allow_edits=False)
    if not answer or not answer.strip() or answer.strip().splitlines()[0].strip() != "PASS":
        return False, (answer or "рецензент не ответил").strip()[:1000]
    if log_activity:
        _note_chat(item_id, "Проверка постановки и стиля: PASS.")
    return True, ""


def process_item(item_id: str) -> bool:
    try:
        return _process_item(item_id)
    except AgentCancelled:
        submit_answer(item_id, (live.text(item_id) + "\n\nОстановлено пользователем.").strip(), answer_kind="warning")
        record(item_id, "Остановлено пользователем.")
        return True
    finally:
        clear_processing_pid(item_id)


def _process_item(item_id: str) -> bool:
    """Auto-answer or LLM agent (claude/cursor). Returns True if answer saved."""
    item = find_item(item_id)
    if item is None or item.get("status") == "answered":
        return False

    if item.get("purpose") in ("git_notice", "git_chat"):
        from koi.agent_chat.git_changes import process
        return process(item)

    load_env_file()  # ключи из KOI/.env (настройки UI) — не перетирает уже заданные
    local_mode = not is_api_agent_mode() and not is_cursor_manual_agent_mode()
    if is_cursor_manual_agent_mode():
        return False

    mark_processing(item_id)
    if live.cancelled(item_id):
        raise AgentCancelled

    general_chat = item.get("purpose", "agent") in ("agent", "prose", "run")
    chosen = (item.get("cli_agent") or "").strip().lower() or None
    catalog = cli_agents() if local_mode and chosen else []
    chosen_row = next((row for row in catalog if row["id"] == chosen), None)
    available = (
        bool(chosen_row and chosen_row["available"])
        if local_mode and chosen else (
            bool(find_agent_bin() or any(backend_status()[name]["available"] for name in ("codex", "claude")))
            if local_mode else (
                any(backend_status().get(name, {}).get("available") for name in ("codex", "claude", "cursor"))
                if general_chat else _any_backend_available()
            )
        )
    )
    if chosen and chosen.startswith("acp:"):
        submit_answer(item_id, "ACP отложен. Выберите Cursor, Codex или Claude и повторите запрос.", answer_kind="warning")
        return True
    if not available:
        if local_mode:
            label = chosen_row["label"] if chosen_row else "Локальный агент"
            missing = (
                f"{label} сейчас недоступен. Проверьте, что CLI установлен, и повторите вопрос."
                if chosen else
                "Локальный агент не найден. Установите и авторизуйте Cursor, Codex или Claude CLI, затем повторите вопрос."
            )
            record(item_id, missing)
            submit_answer(item_id, missing, answer_kind="warning")
        else:
            submit_answer(item_id, no_cursor_key_warning(), answer_kind="warning")
        return True

    if local_mode:
        record(
            item_id,
            f"Вопрос принят. Запускаю {chosen_row['label']}."
            if chosen_row else
            "Вопрос принят. Ищу доступного локального агента.",
        )
    try:
        prompt = _sdk_prompt(item_id)
        if general_chat:
            prompt += ("\n\nПеред длительными действиями и по мере появления важных результатов "
                       "отправляй короткие промежуточные сообщения для пользователя. "
                       "В конце дай итоговый ответ.")
        allow_edits = general_chat and item.get("project_id") is not None
        local_kwargs = {"mode": None, "force": True} if allow_edits else {}
        if chosen:
            local_kwargs["cli_agent"] = chosen
        text, backend = (
            _run_local_agent(prompt, item_id, **local_kwargs) if local_mode
            else run_agent(prompt, cwd=_ws.agent_cwd(), allow_edits=allow_edits, **_stream_options(item_id))
        )
        if live.cancelled(item_id):
            raise AgentCancelled
    except AgentCancelled:
        raise
    except Exception as exc:
        if local_mode:
            record(item_id, f"Ошибка запуска: {type(exc).__name__}.")
            submit_answer(item_id, "Не удалось запустить агента. Подробности доступны в журнале работы.", answer_kind="warning")
            return True
        raise
    if text:
        progress = live.text(item_id)
        if progress.strip().endswith(text.strip()):
            text = progress
        if item.get("purpose") in ("report_grill", "grill_me"):
            text, _ = parse_reply(text)  # The interviewer never publishes writer output.
        if local_mode:
            record(item_id, f"Ответ получен от {backend or 'локального агента'}.")
        submit_answer(item_id, text)
        if item.get("purpose") in ("report_grill", "grill_me"):
            from koi.agent_chat.setup_pipeline import enqueue
            enqueue(item_id)
        if local_mode:
            record(item_id, "Ответ опубликован в чате.")
        return True
    if local_mode:
        record(item_id, "Агент не вернул текст ответа.")
        submit_answer(item_id, "Агент не вернул ответ. Проверьте локальную авторизацию и повторите вопрос.", answer_kind="warning")
        return True
    return False


def process_all_pending() -> int:
    done = 0
    for item in list(list_pending()):
        if process_item(item["id"]):
            done += 1
    return done
