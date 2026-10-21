"""Coalesced, card-scoped queue for live grill-me report summaries."""

from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from koi.adapters.agent_chat_queue import find_item
from koi.adapters.card_reports import read_report, write_report
from koi.adapters.repository import load_project
from koi.adapters.report_grill_reply import parse_reply
from koi.adapters.settings_store import is_api_agent_mode
from koi.adapters.workspace import get_workspace
from koi.agent_chat.activity import record
from koi.agent_chat.cli import build_context
from koi.agent_chat.report_grill import SKILLS

QUEUE_PATH = get_workspace().run_dir / "report-setup-queue.json"
_lock = threading.RLock()
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="report-setup")
_active: set[str] = set()


def _key(item: dict) -> str:
    return "/".join((item["project_id"], item["board_id"], item["card_id"]))


def _read() -> dict[str, str]:
    try:
        value = json.loads(QUEUE_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(items: dict[str, str]) -> None:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = QUEUE_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(QUEUE_PATH)


def enqueue(item_id: str) -> None:
    item = find_item(item_id)
    if not item or not item.get("card_id") or item.get("purpose") not in ("grill_me", "report_grill"):
        return
    key = _key(item)
    with _lock:
        pending = _read()
        pending[key] = item_id  # New turns replace unprocessed snapshots.
        _write(pending)
        if key not in _active:
            _active.add(key)
            _pool.submit(_drain, key)


def resume_pending() -> None:
    """Resume the latest unfinished snapshot for each card after app restart."""
    with _lock:
        for key in _read():
            if key not in _active:
                _active.add(key)
                _pool.submit(_drain, key)


def _latest(key: str, item_id: str) -> bool:
    with _lock:
        return _read().get(key) == item_id


def _drain(key: str) -> None:
    try:
        while True:
            with _lock:
                item_id = _read().get(key)
            if not item_id:
                return
            try:
                _process(key, item_id)
            except Exception:
                record(item_id, "Не удалось обновить постановку; следующий ответ продолжит с последней истории.")
            with _lock:
                pending = _read()
                if pending.get(key) == item_id:
                    pending.pop(key, None)
                    _write(pending)
                    return
    finally:
        with _lock:
            _active.discard(key)
            if _read().get(key):
                _active.add(key)
                _pool.submit(_drain, key)


def _run_private_agent(prompt: str, item_id: str) -> str:
    if is_api_agent_mode():
        from koi.adapters.agent_backends import run_agent
        text, _ = run_agent(prompt, allow_edits=False)
    else:
        from koi.agent_chat.runner import _run_local_agent
        text, _ = _run_local_agent(prompt, item_id, mode="ask", force=False, log_activity=False)
    return (text or "").strip()


def _writer_prompt(context: dict, feedback: str = "") -> str:
    skill = (SKILLS / "koi-grill-experiment" / "SKILL.md").read_text(encoding="utf-8")
    return (
        "Ты отдельный агент-писатель постановки. Не отвечай пользователю и не меняй файлы. "
        "Возьми последнюю реплику, всю историю карточки и текущий документ. "
        "Обнови накопленное резюме по известным решениям; неизвестное явно отметь как открытое. "
        "Не выдумывай ответы. Сохрани уже согласованные детали. История ответов человека "
        "важнее текущего документа: исправь в нём любую преждевременно записанную договорённость. "
        "Не включай в текст "
        "служебные id, путь файла, колонку канбана и историю переписки: пиши содержание эксперимента. "
        "Не используй фразы «по истории ответов», «текущая рекомендация», «без ответа», "
        "«карточка в backlog» — читатель видит только постановку эксперимента. "
        "Цель может оставаться промежуточной, пока человек уточняет гипотезу. "
        "Каждый ответ пользователя относится к ПРЕДЫДУЩЕМУ вопросу интервьюера. "
        "pending_question — новый вопрос без ответа: его рекомендацию НЕ считай принятой. "
        "Верни только один fenced "
        "блок report-setup с JSON и ровно полями goal, setup, tasks. "
        "Все три значения — СТРОКИ, tasks — одна строка Markdown с несколькими строками '- [ ]', "
        "переносы внутри JSON экранируй как \\n. Не возвращай массив tasks.\n\n"
        f"Правила:\n{skill}\n\nЗамечания предыдущей проверки:\n{feedback or 'нет'}\n\n"
        f"Контекст:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
    )


def _replace_sections(source: str, proposal: dict[str, str]) -> str:
    result = source
    for heading, key in (("Цель", "goal"), ("Постановка эксперимента", "setup"), ("Задачи", "tasks")):
        pattern = rf"(?ms)^## {re.escape(heading)}\s*\n.*?(?=^## |\Z)"
        replacement = f"## {heading}\n\n{proposal[key].strip()}\n\n"
        if re.search(pattern, result):
            result = re.sub(pattern, lambda _: replacement, result, count=1)
        else:
            result += "\n" + replacement
    return result


def _setup_would_shrink(source: str, proposal: dict[str, str]) -> bool:
    match = re.search(r"(?ms)^## Постановка эксперимента\s*\n(.*?)(?=^## |\Z)", source)
    old = re.sub(r"\s+", " ", match.group(1)).strip() if match else ""
    new = re.sub(r"\s+", " ", proposal["setup"]).strip()
    return len(old) > 200 and len(new) < len(old) * 0.75


def _contains_process_text(proposal: dict[str, str]) -> bool:
    visible = "\n".join(proposal.values())
    return bool(re.search(r"по истории|текущая рекомендация|без ответа|\bbacklog\b|\bboard-[\w-]+\b|\bc-[0-9a-f]{8}\b", visible, re.I))


def _process(key: str, item_id: str) -> None:
    if not _latest(key, item_id):
        return
    item = find_item(item_id)
    if not item:
        return
    project = load_project(item["project_id"], sync_reports=False)
    if not project:
        return
    board = next((b for b in project.boards if b.id == item["board_id"]), None)
    card = next((c for c in board.cards if c.id == item["card_id"]), None) if board else None
    if not card:
        return
    current = read_report(project, board.id, card.id, card.title)["content"]
    context = build_context(item_id)
    context["current_document"] = current
    context["history"] = [*context.get("history", []), {"user": item["question"], "assistant": None}]
    context["pending_question"] = item.get("answer")
    feedback = ""
    for _ in range(3):
        if not _latest(key, item_id):
            return
        text = _run_private_agent(_writer_prompt(context, feedback), item_id)
        _, proposal = parse_reply(text)
        if not proposal:
            feedback = "Верни один корректный report-setup блок с тремя непустыми полями."
            continue
        if _setup_would_shrink(current, proposal):
            feedback = "Сохрани подробности уже записанной постановки; новый setup заметно короче."
            continue
        if _contains_process_text(proposal):
            feedback = "Убери из видимого текста служебные ссылки на историю, рекомендации и статус ответа; оставь только постановку эксперимента."
            continue
        from koi.agent_chat.runner import _review_grill_proposal
        passed, feedback = _review_grill_proposal(
            item_id, proposal, local_mode=not is_api_agent_mode(),
            log_activity=False, evidence=context,
        )
        if not passed:
            continue
        if not _latest(key, item_id):
            return
        latest_content = read_report(project, board.id, card.id, card.title)["content"]
        if latest_content != current:
            # Another writer or the human changed the document; a newer turn will retry.
            record(item_id, "Документ изменился во время подготовки; постановка не заменена.")
            return
        write_report(project, board.id, card.id, card.title, _replace_sections(current, proposal))
        record(item_id, "Постановка обновлена и доступна в карточке.")
        return
    record(item_id, "Постановка пока не обновлена: требуется уточнение в интервью.")
