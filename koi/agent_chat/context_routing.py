"""Route shared-chat work and suggest real contexts when the target is unclear."""
from __future__ import annotations

import json
import re

from koi.adapters.paths import project_md
from koi.core.md_io import _split_frontmatter, parse_project_md
from koi.laboratory.programs import parse_program_entries


INSTRUCTIONS = """
Этот чат общий: он не привязан к одному проекту. По явному поручению человека
можно редактировать деревья, карточки и отчёты проектов из context_catalog.
Если в контексте задана program_id, программа уже выбрана. Уточняй только дерево
и при необходимости метод внутри неё; не предлагай другие программы.
Сначала определи, к каким исследованиям из context_catalog относится запрос.
Если нужные деревья однозначно указаны в запросе или истории, выполни работу
без обязательной привязки чата. Запрос может относиться к нескольким деревьям.
Не запускай эксперимент без поручения человека и не выдумывай результаты.
Для общего вопроса просто ответь: НЕ спрашивай проект и НЕ предлагай привязку.
Для вопроса по исследованию можешь ответить по материалам и предложить 1–2
наиболее подходящих контекста. Не выдумывай второй вариант ради количества.
Если для работы непонятно, какое дерево менять, кратко опиши понимание задачи
и предложи выбрать контекст; до уточнения не меняй файлы.
Только в этом случае awaiting_selection=true; после нажатия кнопки запрос продолжится.
Метод/board_id предлагай только при явном совпадении, иначе укажи лишь project_id.
Если context_suggestions_dismissed=true, не повторяй предложения привязки.
При наличии вариантов в конце ответа добавь ровно один служебный блок:
```research_context
{"awaiting_selection":true,"options":[{"project_id":"id из каталога","board_id":null}]}
```
Для уже данного информационного ответа или выполненной работы awaiting_selection=false.
Используй только реальные id из context_catalog. Не вставляй JSON в основной текст.
""".strip()


def catalog() -> list[dict]:
    from koi.adapters.repository import list_projects
    rows = []
    for entry in list_projects():
        try:
            text = project_md(entry["id"]).read_text(encoding="utf-8")
            meta, _ = _split_frontmatter(text)
            # Parsing the catalogue must not run repository migrations or save files.
            project = parse_project_md(text, project_id=entry["id"])
        except (OSError, ValueError):
            continue
        nodes = {n.id: n for n in project.nodes}
        rows.append({
            "project_id": entry["id"], "tree_title": project.title,
            "program_ids": [p["id"] for p in parse_program_entries(meta.get("programs"))],
            "program_titles": [p["title"] for p in parse_program_entries(meta.get("programs"))],
            "methods": [{"board_id": b.id, "method_id": b.owner_node_id,
                         "method_title": nodes[b.owner_node_id].title}
                        for b in project.boards if b.owner_node_id in nodes],
        })
    return rows


def for_program(rows: list[dict], program_id: str | None) -> list[dict]:
    if not program_id:
        return rows
    return [r for r in rows if program_id in r.get("program_ids", []) or
            (program_id == "ungrouped" and not r.get("program_ids"))]


def parse_reply(text: str, *, program_id: str | None = None) -> tuple[str, dict | None]:
    pattern = r"```research_context\s*\n(.*?)```"
    blocks = re.findall(pattern, text, flags=re.S)
    clean = re.sub(pattern, "", text, flags=re.S).strip()
    if len(blocks) != 1:
        return clean or "Не удалось определить контекст вопроса.", None
    try:
        data = json.loads(blocks[0])
    except (ValueError, TypeError):
        return clean or "Не удалось определить контекст вопроса.", None
    if not isinstance(data, dict) or not isinstance(data.get("options"), list):
        return clean or "Не удалось определить контекст вопроса.", None
    projects = {r["project_id"]: r for r in for_program(catalog(), program_id)}
    options, seen = [], set()
    for candidate in data["options"][:2]:
        if not isinstance(candidate, dict):
            continue
        pid, bid = candidate.get("project_id"), candidate.get("board_id")
        if not isinstance(pid, str) or bid is not None and not isinstance(bid, str):
            continue
        project = projects.get(pid)
        if project is None or (pid, bid) in seen:
            continue
        method = next((m for m in project["methods"] if m["board_id"] == bid), None)
        if bid and method is None:
            continue
        seen.add((pid, bid))
        options.append({"project_id": pid, "board_id": bid or None,
                        "program_title": " / ".join(project["program_titles"]) or "Без программы",
                        "tree_title": project["tree_title"],
                        "method_title": method["method_title"] if method else None})
    return (clean or "Выберите контекст, чтобы продолжить."), (
        {"options": options, "awaiting_selection": data.get("awaiting_selection") is True}
        if options else None
    )
