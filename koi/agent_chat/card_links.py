"""Attach real cards mentioned by the agent without changing the chat scope."""
from __future__ import annotations

import json
import re

INSTRUCTIONS = """
Если ты создал, изменил или обсуждал конкретные карточки, обязательно прикрепи
ссылки на них к своему ответу, в том числе при работе из основного чата проекта
или метода. Не ограничивайся карточкой, к которой уже привязан чат.
В конце ответа добавь служебный блок с реальными идентификаторами всех этих
карточек (после создания перечитай project.md, не угадывай id):
```research_cards
[{"project_id":"реальный id проекта","board_id":"реальный id доски","card_id":"реальный id карточки"}]
```
Интерфейс покажет этот блок как ссылки на карточки. Если карточек нет, блок не
добавляй. Блок не меняет привязку чата и не разрешает работу вне его контекста.
""".strip()


def parse_reply(text: str, item: dict) -> tuple[str, list[dict]]:
    pattern = r"```research_cards\s*\n(.*?)```"
    blocks = re.findall(pattern, text, flags=re.S)
    if not blocks:
        return text, []
    clean = re.sub(pattern, "", text, flags=re.S).strip()
    from koi.adapters.repository import load_project
    from koi.agent_chat.context_routing import catalog, for_program
    from koi.agent_chat.conversations import find

    chat = find(item.get("conversation_id")) or {}
    allowed = {item["project_id"]} if item.get("project_id") else {
        row["project_id"] for row in for_program(catalog(), chat.get("program_id"))
    }
    links, seen, projects = [], set(), {}
    for block in blocks:
        try:
            candidates = json.loads(block)
        except ValueError:
            continue
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            key = tuple(candidate.get(k) for k in ("project_id", "board_id", "card_id"))
            if not all(isinstance(v, str) and v for v in key):
                continue
            pid, bid, cid = key
            if pid not in allowed or key in seen:
                continue
            if pid not in projects:
                projects[pid] = load_project(pid, sync_reports=False)
            project = projects[pid]
            board = next((b for b in project.boards if b.id == bid), None) if project else None
            card = next((c for c in board.cards if c.id == cid), None) if board else None
            if card:
                seen.add(key)
                links.append({"project_id": pid, "board_id": bid, "card_id": cid, "title": card.title})
    return clean or ("Карточки прикреплены." if links else "Не удалось прикрепить карточки."), links
