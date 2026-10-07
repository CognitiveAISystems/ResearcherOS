"""Papers picked from the shared Zotero library for one project."""

from __future__ import annotations

import json

from koi.adapters.paths import literature_dir

SELECTION_FILENAME = "selection.json"
MAX_PAPERS = 400


def _clean(value: object, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def selection_path(project_id: str):
    return literature_dir(project_id) / SELECTION_FILENAME


def _papers_from_data(data: object) -> list[dict[str, str]]:
    raw = data.get("papers") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    papers: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        url = _clean(item.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        papers.append(
            {
                "url": url,
                "title": _clean(item.get("title")),
                "authors": _clean(item.get("authors")),
                "year": _clean(item.get("year"), 16),
            }
        )
        if len(papers) >= MAX_PAPERS:
            break
    return papers


def read_selection(project_id: str) -> list[dict[str, str]]:
    path = selection_path(project_id)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return _papers_from_data(data)


def write_selection(project_id: str, papers: list[dict]) -> list[dict[str, str]]:
    cleaned = _papers_from_data({"papers": papers})
    path = selection_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"papers": cleaned}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return cleaned
