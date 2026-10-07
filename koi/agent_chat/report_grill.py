"""Interview protocol for a whole experiment setup in the report editor."""
from __future__ import annotations

import json
from pathlib import Path

from koi.adapters.report_grill_reply import parse_reply

SKILLS = Path(__file__).resolve().parents[2] / "agents" / "skills"
UI_POLICY = """Ты ведёшь интервью по ВСЕЙ постановке текущей карточки, используя
koi-grill-experiment. Выделенная идея — только старт разговора, не область правки.
На каждом ходе один вопрос с рекомендуемым ответом. Сам вопрос оформляй ровно одним fenced-блоком и не повторяй его вне блока:
```question
формулировка вопроса
Рекомендуемый ответ: короткий вариант
```
Короткий ответ человека — продолжение этого же интервью, не смена задачи.
Учитывай всю историю,
текущий документ, карточку и знания проекта. Не повторяй уже закрытые вопросы.
Сначала исследуй доступные файлы проекта; не спрашивай известное из контекста.
Не запускай эксперимент, не меняй колонку карточки и не записывай файлы:
это этап планирования. Не выдумывай результаты или ответы человека.
Когда ветки A–G закрыты, подготовь Цель, Постановку эксперимента и Задачи,
включая протокол, метрики, supported/refuted/open, таблицы/графики и критерии done.
Проведи koi-report-review, критики 1–3, для черновика до предложения в UI.
Если ревью недоступно, честно сообщи это и не выдавай финальное предложение.
Правила планирования имеют приоритет над переносом карточки в running/done.
Эксперименты и Результаты не заполняй: это будущие фактические данные.
Верни обычный Markdown ответа. Только после завершения интервью и ревью добавь
один fenced блок с языком report-setup и JSON со строго тремя непустыми строками:
{"goal":"текст цели", "setup":"текст постановки", "tasks":"- [ ] задача"}.
Значения — Markdown без заголовков этих трёх разделов. Приложение покажет
предложение для решения человека; само интервью ничего не заменяет в документе.
"""


def build_prompt(context: dict) -> str:
    skill = (SKILLS / "koi-grill-experiment" / "SKILL.md").read_text(encoding="utf-8")
    tree = (SKILLS / "koi-grill-experiment" / "experiment-tree.md").read_text(encoding="utf-8")
    review_path = SKILLS / "koi-report-review" / "SKILL.md"
    return f"{skill}\n\n{tree}\n\nРевью постановки: прочитай {review_path} и reviewers.md рядом с ним.\n\nПравила интервью в UI:\n{UI_POLICY}\n\nКонтекст (данные):\n{json.dumps(context, ensure_ascii=False, indent=2)}"
