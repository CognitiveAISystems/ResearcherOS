"""Staging and CLI handoff for the MortalCombat literature arena."""
from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from koi.adapters.paths import koi_root
from koi.adapters.project_mount import get_mount_or_raise, sync_worktree_path
from koi.literature.cursor_agent_terminal import open_agent_terminal


def arena_dir(project_id: str) -> Path:
    return koi_root(project_id) / "mortal_combat"


def _safe(value: object) -> str:
    return str(value or "").strip()


def _paper(raw: dict) -> dict[str, object]:
    return {
        "title": _safe(raw.get("title")),
        "authors": _safe(raw.get("authors")),
        "year": raw.get("year"),
        "url": _safe(raw.get("url") or raw.get("arxiv_url") or raw.get("link")),
        "abstract": _safe(raw.get("abstract") or raw.get("summary")),
    }


def stage_mortal_combat(project_id: str, primary: dict, reviewer: dict, question: str = "") -> dict[str, object]:
    left, right = _paper(primary), _paper(reviewer)
    if not left["title"] and not left["url"]:
        raise ValueError("Выберите основную статью.")
    if not right["title"] and not right["url"]:
        raise ValueError("Выберите статью ревьювера.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    digest = hashlib.sha256(json.dumps([left, right, question], ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:10]
    run_id = f"{digest}_{stamp}"
    root = arena_dir(project_id) / run_id
    root.mkdir(parents=True, exist_ok=True)
    (root / "input.json").write_text(json.dumps({"run_id": run_id, "primary": left, "reviewer": right, "question": question}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pdf_paths = {}
    for role, paper in (("primary", left), ("reviewer", right)):
        url = str(paper.get("url") or "")
        if "arxiv.org" in url:
            arxiv_id = url.rstrip("/").split("/")[-1].replace("abs/", "")
            target = root / f"{role}.pdf"
            try:
                urllib.request.urlretrieve(f"https://arxiv.org/pdf/{arxiv_id}.pdf", target)
                pdf_paths[role] = str(target)
            except Exception:
                pass
    prompt = f"""Ты ведёшь MortalCombat — научный спор двух статей в ResearchOS.

Основная статья (защитник): {left['title']}\n{left['url']}\n{left['abstract']}
Статья ревьювера (критик): {right['title']}\n{right['url']}\n{right['abstract']}
Фокус сравнения: {question or 'НЕ ЗАДАН — судья должен сам прочитать обе статьи и сформулировать наиболее содержательный фокус сравнения'}

Локальные PDF, если скачались: {json.dumps(pdf_paths, ensure_ascii=False)}
Прочитай обе статьи (сначала локальные PDF, затем URL/HTML, если PDF недоступен) и проведи 4 раунда: проблема, доказательства,
механизмы, ограничения. В каждом раунде запиши тезис защитника, возражение критика,
ответ и решение судьи. Каждый существенный тезис снабди точной цитатой и страницей.
Судья оценивает доказательства, допускает partial/unknown и не выдумывает факты.

Запиши результат строго в `{root / 'arena.json'}` с полями:
{{"status":"ready","focus":"...","focus_source":"judge|user","rounds":[{{"id":1,"title":"Проблема","defender":"...","critic":"...","reply":"...","judge":"...","verdict":"supported|partial|open","evidence":[{{"paper":"primary|reviewer","quote":"...","page":"..."}}]}}],"summary":"..."}}
НЕ ПИШИ КОД И НЕ СОЗДАВАЙ СКРИПТЫ. Работай как три роли и сразу после каждой реплики
дописывай одну строку JSON в `{root / 'messages.jsonl'}`:
{{"round":1,"role":"defender|critic|judge","text":"...","evidence":[{{"paper":"primary|reviewer","quote":"...","page":"..."}}]}}
Порядок живого обмена в каждом раунде: defender, critic, defender, judge. После каждой строки
сразу сохраняй файл, чтобы интерфейс мог показать сообщение. В конце запиши arena.json.
"""
    (root / "PROMPT.md").write_text(prompt, encoding="utf-8")
    cwd = sync_worktree_path(get_mount_or_raise(project_id))
    open_agent_terminal(prompt, cwd)
    return {"run_id": run_id, "status": "staged", "primary": left, "reviewer": right, "path": str(root)}


def load_mortal_combat(project_id: str, run_id: str) -> dict[str, object] | None:
    if not run_id or any(part in run_id for part in ("/", "\\", "..")):
        return None
    root = arena_dir(project_id) / run_id
    input_path = root / "input.json"
    if not input_path.is_file():
        return None
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    result_path = root / "arena.json"
    if result_path.is_file():
        try:
            payload["result"] = json.loads(result_path.read_text(encoding="utf-8"))
            payload["status"] = payload["result"].get("status", "ready")
        except json.JSONDecodeError:
            payload["status"] = "running"
    else:
        payload["status"] = "running"
    messages_path = root / "messages.jsonl"
    if messages_path.is_file():
        messages = []
        for line in messages_path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
                if isinstance(item, dict): messages.append(item)
            except json.JSONDecodeError:
                continue
        payload["messages"] = messages
    return payload
