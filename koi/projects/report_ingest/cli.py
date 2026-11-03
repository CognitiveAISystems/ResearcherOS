#!/usr/bin/env python3
"""Авто-проверка гипотезы агентом: отчёт по шаблону → автоинтеграция в БЗ.

Запуск из корня репо:

    python -m koi.projects.report_ingest.cli <project_id> <card_id> \
        [--backend opencode|codex|claude|cursor] [--no-ingest] [--dry-run] [--timeout 1800]
    python -m koi.projects.report_ingest.cli <project_id> <card_id> \
        --ingest-only [путь/к/отчёту.run.md]

Конвейер:
1. По карточке канбана находится цепочка узлов: метод → доказательство/
   ремедиация → гипотеза (cause) → проблема.
2. Локальный агент (OpenCode, Codex, Claude Code или Cursor — koi/adapters/agent_backends.py)
   получает контекст + шаблон `agents/skills/koi-report-review/experiment-report.md` и пишет
   рабочий отчёт `<отчёт-карточки>.run.md` рядом с публичным отчётом.
3. `koi/projects/report_ingest/` разбирает «Заявку в БЗ» (§5): вердикт ставится на
   cause-узел, инсайты (§5.2, json) попадают в research.json, карточка едет
   в done — а хук save_project автоматически пересобирает KNOWLEDGE.md,
   knowledge/hypotheses.md и KNOWLEDGE_LOG.md.

`--ingest-only` пропускает шаг агента: интегрирует уже написанный отчёт
(свой путь можно передать аргументом; по умолчанию — ожидаемый .run.md).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from koi.adapters.agent_backends import backend_status, editable_backends, run_agent
from koi.core.models import NodeType, Project
from koi.projects.report_ingest import (
    ReportIngestError,
    expected_run_report_path,
    ingest_report,
)
from koi.adapters.repository import load_project
from koi.adapters.workspace import get_workspace

_ws = get_workspace()
TEMPLATE_PATH = _ws.experiment_report_template


def _find_card(project: Project, card_id: str):
    for board in project.boards:
        for card in board.cards:
            if card.id == card_id:
                return board, card
    return None, None


def _node_chain(project: Project, method_id: str) -> dict:
    """method → (cause_evidence|remediation) → cause → problem."""
    by_id = {n.id: n for n in project.nodes}
    chain: dict = {}
    node = by_id.get(method_id)
    while node is not None:
        chain[node.node_type.value] = node
        node = by_id.get(node.parent_id) if node.parent_id else None
    return chain


def _node_block(label: str, node) -> str:
    if node is None:
        return f"### {label}\n(нет)\n"
    head = f"### {label}: `{node.id}` — {node.title}\n"
    body = (node.description or "").strip()
    extra = ""
    if node.node_type == NodeType.CAUSE:
        extra = f"\nТекущий вердикт: {node.verdict.value}\n"
    return head + (body + "\n" if body else "") + extra


def build_prompt(project: Project, board, card, chain: dict, run_path: Path) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    parent = chain.get("cause_evidence") or chain.get("remediation")
    ctx = "\n".join(
        [
            f"## Проект: `{project.id}` — {project.title}",
            _node_block("Проблема", chain.get("problem")),
            _node_block("Гипотеза (cause)", chain.get("cause")),
            _node_block("Как проверяем", parent),
            _node_block("Метод", chain.get("method")),
            f"### Карточка эксперимента: `{card.id}` — {card.title}",
            (card.description or "").strip(),
        ]
    )
    from koi.adapters.glossary import prompt as glossary_prompt
    return glossary_prompt(project.id) + "\n\n" + f"""Ты — эксперимент-агент ResearchOS. Твоя задача — проверить гипотезу по карточке эксперимента и записать рабочий отчёт.

{ctx}

## Что сделать

1. Проведи проверку по правилу решения из описания гипотезы. Если в описании
   метода/карточки указаны команды или готовые сырые метрики (логи, jsonl) —
   используй их; недостающие прогоны запускай только если это явно описано.
   Если проверить нечем — честно зафиксируй это в отчёте (статус прогона,
   вердикт open).
2. Запиши рабочий отчёт СТРОГО по шаблону ниже в файл:

   Файл отчёта: `{run_path}`

3. Жёсткие требования к отчёту:
   - все секции §0–§5 заполнены; строки-подсказки с «>» удалены;
   - §0 «Привязка»: гипотеза `{(chain.get('cause').id if chain.get('cause') else '?')}`, метод/карточка `{chain['method'].id}` / `{card.id}`;
   - §3: вердикт обязан следовать из подстановки чисел в правило решения;
   - §5.2: ровно один fenced ```json блок — массив из ≤3 инсайтов с полями
     method_id, card_id, question, answer, narrative, certainty
     (definite|tentative), importance (1–5). Без него автоинтеграция не сработает.
4. НИЧЕГО кроме файла отчёта не меняй: project.md, research.json, KNOWLEDGE.md
   обновит пайплайн автоматически после твоего отчёта.

## Шаблон отчёта (agents/skills/koi-report-review/experiment-report.md)

{template}
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project_id")
    ap.add_argument("card_id")
    ap.add_argument("--backend", choices=editable_backends(), default=None)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--no-ingest", action="store_true",
                    help="только сгенерировать отчёт, без интеграции")
    ap.add_argument("--ingest-only", nargs="?", const="", metavar="REPORT",
                    default=None, help="не запускать агента; интегрировать готовый отчёт")
    ap.add_argument("--dry-run", action="store_true",
                    help="показать, что изменит интеграция, не меняя файлов")
    args = ap.parse_args()
    if args.backend is not None:
        row = backend_status().get(args.backend, {})
        if not row.get("available"):
            ap.error(f"Агент {args.backend} недоступен: {row.get('reason') or 'программа не найдена'}")

    project = load_project(args.project_id)
    if project is None:
        print(f"Проект не найден: {args.project_id}", file=sys.stderr)
        return 2
    board, card = _find_card(project, args.card_id)
    if card is None:
        print(f"Карточка не найдена: {args.card_id}", file=sys.stderr)
        return 2
    chain = _node_chain(project, board.owner_node_id)
    if "method" not in chain:
        print(f"У доски {board.id} нет узла-метода", file=sys.stderr)
        return 2

    run_path = expected_run_report_path(project, board.id, card.id, card.title)

    if args.ingest_only is None:
        prompt = build_prompt(project, board, card, chain, run_path)
        print(f"Бэкенды: {json.dumps(backend_status(), ensure_ascii=False)}")
        print(f"Запускаю агента; жду отчёт: {run_path}")
        text, backend = run_agent(
            prompt, cwd=_ws.agent_cwd(), timeout=args.timeout,
            allow_edits=True, backend=args.backend,
        )
        if text is None:
            print(
                "Ни один агент-бэкенд не доступен или не дал ответа. "
                "Нужен Claude Code CLI (claude login / ANTHROPIC_API_KEY) "
                "или CURSOR_API_KEY + cursor_sdk.",
                file=sys.stderr,
            )
            return 3
        print(f"Агент ({backend}) завершил работу.")
        if not run_path.is_file() or not run_path.read_text(encoding="utf-8").strip():
            print(f"Агент не записал отчёт: {run_path}", file=sys.stderr)
            print(f"Финальное сообщение агента:\n{text}", file=sys.stderr)
            return 4
        if args.no_ingest:
            print(f"Отчёт готов (интеграция пропущена): {run_path}")
            return 0
    else:
        run_path = Path(args.ingest_only) if args.ingest_only else run_path
        if not args.ingest_only and (
            not run_path.is_file() or not run_path.read_text(encoding="utf-8").strip()
        ):
            # рабочего .run.md нет — пробуем публичный отчёт карточки (из UI)
            public = run_path.with_name(run_path.name.replace(".run.md", ".md"))
            if public.is_file() and public.read_text(encoding="utf-8").strip():
                print(f"Рабочий .run.md не найден; интегрирую отчёт из UI: {public}")
                run_path = public

    try:
        summary = ingest_report(args.project_id, run_path, dry_run=args.dry_run)
    except ReportIngestError as e:
        print(f"Автоинтеграция не прошла: {e}", file=sys.stderr)
        return 5
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
