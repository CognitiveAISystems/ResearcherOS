"""Answer-format rules for the ResearcherOS agent-chat capability."""

from __future__ import annotations

from koi.adapters.settings_store import CURSOR_API_KEY_URL

ANSWER_FORMAT_INSTRUCTIONS = """
Формат ответа для панели UI:
1. Основная часть — свободный связный текст по-русски: раскрой тему, свяжи факты,
   поясни нюансы и ограничения. Не ограничивайся одним предложением.
2. Опирайся на narrative и answer из research_database; отчёт читай только при нехватке деталей.
3. В конце обязательно блок источников (после пустой строки):

Источники:
• Метод «…» → эксперимент «…»
• …

Укажи все методы и эксперименты, на которых основан ответ. Если эксперимента нет — только метод.
""".strip()


def format_sources_block(records: list[dict]) -> str:
    """Build trailing sources list from research_database records."""
    lines: list[str] = []
    seen: set[tuple[str, str]] = set()
    for rec in records:
        method = (rec.get("method_title") or "").strip()
        exp = (
            rec.get("experiment_title")
            or (rec.get("experiment") or {}).get("card_title")
            or ""
        ).strip()
        key = (method, exp)
        if not method or key in seen:
            continue
        seen.add(key)
        if exp:
            lines.append(f"• Метод «{method}» → эксперимент «{exp}»")
        else:
            lines.append(f"• Метод «{method}»")
    if not lines:
        return ""
    return "Источники:\n" + "\n".join(lines)


def append_sources(body: str, records: list[dict]) -> str:
    text = body.strip()
    sources = format_sources_block(records)
    if not sources:
        return text
    return f"{text}\n\n{sources}"


def no_cursor_key_warning() -> str:
    return (
        "⚠️ Ключ Cursor API не настроен.\n\n"
        "Сейчас агент может ответить только по готовым выводам из базы research.json. "
        "Для полноценных ответов на произвольные вопросы укажите ключ в настройках ResearcherOS "
        "(кнопка «Настройки» в верхней панели).\n\n"
        f"Как получить ключ: {CURSOR_API_KEY_URL}"
    )
