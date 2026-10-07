"""Read-only KOI API routes so the main ResearchOS web UI works on Hub."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse

from hub.app.auth import get_session
from hub.app.config import HubConfig
from hub.app.access import can_view_project_with_store
from hub.app.hub_composite import list_hub_composites, load_hub_composite
from hub.app.hub_programs import hub_project_programs, program_ids
from hub.app.project_identity import dedupe_hub_projects, project_rank
from hub.app.running_activity import running_activity_for_project
from hub.app.store import HubProject, HubStore
from koi.projects.views import allowed_children
from koi.core.models import NodeType

router = APIRouter(tags=["koi-readonly"])


def _viewer_id(request: Request, config: HubConfig, store: HubStore) -> Optional[int]:
    session = get_session(request, config, store)
    return session.github_id if session else None


def _request_share_token(request: Request) -> Optional[str]:
    """Secret token from ``?token=`` (unlisted share links)."""
    params = getattr(request, "query_params", None)
    if params is None:
        return None
    raw = params.get("token") if hasattr(params, "get") else None
    if raw is None:
        return None
    token = str(raw).strip()
    return token or None


def _can_view(
    request: Request,
    hub_project: HubProject,
    config: HubConfig,
    store: HubStore,
) -> bool:
    return can_view_project_with_store(
        hub_project,
        _viewer_id(request, config, store),
        store,
        token=_request_share_token(request),
    )


def _viewable_members(
    request: Request, config: HubConfig, store: HubStore
) -> list[tuple[HubProject, dict[str, Any]]]:
    members: list[tuple[HubProject, dict[str, Any]]] = []
    for hub_project in dedupe_hub_projects(store.list_projects()):
        if not hub_project.enabled:
            continue
        if not _can_view(request, hub_project, config, store):
            continue
        project = _snapshot_project(store, hub_project.slug)
        if project:
            members.append((hub_project, project))
    return members


def _viewable_projects(
    request: Request, config: HubConfig, store: HubStore
) -> list[HubProject]:
    return [hub_project for hub_project, _project in _viewable_members(request, config, store)]


def _snapshot_project(store: HubStore, slug: str) -> Optional[dict[str, Any]]:
    snap = store.get_snapshot(slug)
    if not snap:
        return None
    project = snap.get("project")
    return project if isinstance(project, dict) else None


def _find_slug_by_project_id(store: HubStore, project_id: str) -> Optional[str]:
    best_slug: Optional[str] = None
    best_rank: tuple[int, str, str] = (-1, "", "")
    for hub_project in store.list_projects():
        if not hub_project.enabled:
            continue
        project = _snapshot_project(store, hub_project.slug)
        if project and str(project.get("id") or "") == project_id:
            rank = project_rank(hub_project)
            if rank > best_rank:
                best_rank = rank
                best_slug = hub_project.slug
    return best_slug


def _resolve_hub_project(
    request: Request, project_id: str
) -> tuple[HubConfig, HubStore, HubProject]:
    config: HubConfig = request.app.state.hub_config
    store: HubStore = request.app.state.hub_store

    slug = project_id
    hub_project = store.get_project(slug)
    if hub_project is None:
        slug = _find_slug_by_project_id(store, project_id) or ""
        hub_project = store.get_project(slug) if slug else None
    if hub_project is None:
        raise HTTPException(404, "Project not found")

    if not _can_view(request, hub_project, config, store):
        raise HTTPException(403, "Not allowed to view this project")
    return config, store, hub_project


def _load_reports_index(store: HubStore, slug: str) -> dict[str, str]:
    path = store.resolve_report_file(slug, "index.json")
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(k): str(v)
        for k, v in data.items()
        if isinstance(k, str) and isinstance(v, str)
    }


def _find_card(
    project: dict[str, Any], board_id: str, card_id: str
) -> Optional[dict[str, Any]]:
    boards = project.get("boards") or {}
    board = boards.get(board_id) if isinstance(boards, dict) else None
    if not isinstance(board, dict):
        return None
    return next(
        (c for c in board.get("cards") or [] if c.get("id") == card_id),
        None,
    )


def _read_hub_card_report(
    store: HubStore, slug: str, project: dict[str, Any], board_id: str, card_id: str
) -> dict[str, Any]:
    card = _find_card(project, board_id, card_id)
    index = _load_reports_index(store, slug)
    rel = index.get(card_id)
    if rel:
        path = store.resolve_report_file(slug, rel)
        if path is not None:
            try:
                content = path.read_text(encoding="utf-8")
            except OSError:
                content = ""
            if content.strip():
                return {
                    "content": content,
                    "filename": path.name,
                    "relative_path": f"reports/{rel}",
                    "hypothesis_dir": rel.split("/")[0] if "/" in rel else "",
                    "source": "saved",
                    "path": f"reports/{rel}",
                    "readonly": True,
                }
            run_rel = str(Path(rel).with_name(Path(rel).stem + ".run.md"))
            run_path = store.resolve_report_file(slug, run_rel)
            if run_path is not None:
                try:
                    run_text = run_path.read_text(encoding="utf-8")
                except OSError:
                    run_text = ""
                if run_text.strip():
                    return {
                        "content": run_text,
                        "filename": run_path.name,
                        "relative_path": f"reports/{rel}",
                        "run_relative_path": f"reports/{run_rel}",
                        "hypothesis_dir": rel.split("/")[0] if "/" in rel else "",
                        "source": "run",
                        "path": f"reports/{rel}",
                        "readonly": True,
                    }

    if card is None:
        raise HTTPException(404, "Card not found")
    desc = str(card.get("description") or "").strip()
    content = (
        desc
        or f"_Отчёт ещё не синхронизирован в Hub. Карточка: {card.get('title', card_id)}._"
    )
    return {
        "content": content,
        "filename": None,
        "relative_path": None,
        "path": None,
        "source": "description",
        "readonly": True,
    }


def _project_summary(
    hub_project: HubProject,
    project: dict[str, Any],
    *,
    programs: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    summary = {
        "id": project.get("id") or hub_project.slug,
        "title": project.get("title") or hub_project.title,
        "description": project.get("description") or "",
        "hub_slug": hub_project.slug,
        "owner_login": hub_project.owner_login,
        "programs": program_ids(programs or hub_project_programs(hub_project)),
    }
    if hub_project.composite_id:
        summary["composite_id"] = hub_project.composite_id
    return summary


def _member_program_entries(
    store: HubStore, hub_project: HubProject
) -> list[dict[str, str]]:
    snap = store.get_snapshot(hub_project.slug)
    return hub_project_programs(hub_project, snapshot=snap)


@router.get("/health")
def koi_health() -> dict[str, str]:
    return {"status": "ok", "storage": "hub-snapshot"}


@router.get("/meta/node-types")
def node_types_meta() -> dict[str, Any]:
    return {
        "types": [t.value for t in NodeType],
        "labels": {
            NodeType.PROBLEM.value: "Проблема",
            NodeType.CAUSE.value: "Причина",
            NodeType.CAUSE_EVIDENCE.value: "Доказательство причины",
            NodeType.REMEDIATION.value: "Гипотеза устранения",
            NodeType.METHOD.value: "Метод",
            NodeType.EXPERIMENT.value: "Эксперимент",
        },
        "kanban_owners": ["method"],
        "allowed_children": {
            "problem": allowed_children("problem"),
            "cause": allowed_children("cause"),
            "cause_evidence": allowed_children("cause_evidence"),
            "remediation": allowed_children("remediation"),
            "method": allowed_children("method"),
            "experiment": allowed_children("experiment"),
            None: allowed_children(None),
        },
    }


@router.get("/laboratory")
def get_laboratory() -> dict[str, str]:
    return {
        "id": "researchos-hub",
        "title": "ResearchOS Hub",
        "description": "Публичные и сетевые исследовательские проекты",
    }


@router.get("/projects")
def list_projects(request: Request) -> list[dict[str, Any]]:
    config: HubConfig = request.app.state.hub_config
    store: HubStore = request.app.state.hub_store
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for hub_project in _viewable_projects(request, config, store):
        project = _snapshot_project(store, hub_project.slug)
        if not project:
            continue
        pid = str(project.get("id") or hub_project.slug)
        if pid in seen_ids:
            continue
        seen_ids.add(pid)
        programs = _member_program_entries(store, hub_project)
        items.append(_project_summary(hub_project, project, programs=programs))
    items.sort(key=lambda x: str(x.get("title") or ""))
    return items


@router.get("/projects/grouped")
def projects_grouped(request: Request) -> dict[str, Any]:
    config: HubConfig = request.app.state.hub_config
    store: HubStore = request.app.state.hub_store
    members = _viewable_members(request, config, store)

    # Attach programs (HubProject field, else snapshot meta) for grouping + composites.
    enriched: list[tuple[HubProject, dict[str, Any], list[dict[str, str]]]] = []
    for hub_project, project in members:
        programs = _member_program_entries(store, hub_project)
        if programs and not hub_project.programs:
            hub_project.programs = programs
        enriched.append((hub_project, project, programs))

    composites = list_hub_composites([(hp, proj) for hp, proj, _programs in enriched])
    hidden_member_ids: set[str] = set()
    for composite in composites:
        hidden_member_ids.update(composite.get("member_ids") or [])

    program_meta: dict[str, dict[str, str]] = {}
    membership: dict[str, list[dict[str, Any]]] = {}
    all_summaries: dict[str, dict[str, Any]] = {}

    for hub_project, project, programs in enriched:
        summary = _project_summary(hub_project, project, programs=programs)
        pid = str(summary["id"])
        if pid in all_summaries:
            continue
        all_summaries[pid] = summary
        for entry in programs:
            program_id = entry["id"]
            existing = program_meta.get(program_id)
            if existing is None or (
                entry["title"] != program_id and existing["title"] == program_id
            ):
                program_meta[program_id] = {
                    "title": entry["title"],
                    "description": entry.get("description") or "",
                }
            membership.setdefault(program_id, []).append(summary)

    lab = get_laboratory()
    groups: list[dict[str, Any]] = []
    assigned: set[str] = set()

    for program_id in sorted(membership.keys()):
        projects = []
        for summary in membership[program_id]:
            pid = str(summary["id"])
            if pid in hidden_member_ids:
                continue
            projects.append(summary)
            assigned.add(pid)
        program_composites = [
            comp for comp in composites if program_id in (comp.get("programs") or [])
        ]
        meta = program_meta.get(program_id) or {
            "title": program_id,
            "description": "",
        }
        groups.append(
            {
                "id": program_id,
                "title": meta["title"],
                "description": meta.get("description") or "",
                "composites": program_composites,
                "projects": projects,
            }
        )

    ungrouped = [
        summary
        for pid, summary in sorted(all_summaries.items())
        if pid not in assigned and pid not in hidden_member_ids
    ]

    return {
        "laboratory": lab,
        "composites": composites,
        "groups": groups,
        "ungrouped": ungrouped,
    }


@router.get("/composites")
def list_composites(request: Request) -> list[dict[str, Any]]:
    config: HubConfig = request.app.state.hub_config
    store: HubStore = request.app.state.hub_store
    return list_hub_composites(_viewable_members(request, config, store))


@router.get("/composites/{composite_id}")
def get_composite(request: Request, composite_id: str) -> dict[str, Any]:
    config: HubConfig = request.app.state.hub_config
    store: HubStore = request.app.state.hub_store
    members = _viewable_members(request, config, store)
    payload = load_hub_composite(store, composite_id, members)
    if payload is None:
        raise HTTPException(404, "Composite not found or fewer than two members")
    return payload


@router.get("/projects/{project_id}")
def get_project(request: Request, project_id: str) -> dict[str, Any]:
    config: HubConfig = request.app.state.hub_config
    store: HubStore = request.app.state.hub_store

    slug = project_id
    hub_project = store.get_project(slug)
    if hub_project is None:
        slug = _find_slug_by_project_id(store, project_id) or ""
        hub_project = store.get_project(slug) if slug else None

    if hub_project is None:
        raise HTTPException(404, "Project not found")

    if not _can_view(request, hub_project, config, store):
        raise HTTPException(403, "Not allowed to view this project")

    project = _snapshot_project(store, hub_project.slug)
    if project is None:
        raise HTTPException(404, "Snapshot missing")
    return project


@router.get("/projects/{project_id}/kanban/running-activity")
def kanban_running_activity(request: Request, project_id: str) -> dict[str, Any]:
    # Virtual composite ids are resolved client-side from member projects.
    if project_id.startswith("composite:") or project_id == "composite":
        return {"ok": True, "project_id": project_id, "items": []}
    _config, store, hub_project = _resolve_hub_project(request, project_id)
    project = _snapshot_project(store, hub_project.slug)
    if project is None:
        raise HTTPException(404, "Snapshot missing")
    snap = store.get_snapshot(hub_project.slug) or {}
    cached = snap.get("running_activity")
    if isinstance(cached, list) and cached:
        items = cached
    else:
        items = running_activity_for_project(
            project, author=hub_project.owner_login or "коллега"
        )
    return {"ok": True, "project_id": project_id, "items": items}


@router.get("/projects/{project_id}/kanban/live-monitor")
def kanban_live_monitor(_request: Request, project_id: str) -> dict[str, Any]:
    return {"ok": True, "project_id": project_id, "items": [], "boards": {}}


@router.get("/projects/{project_id}/pages")
def list_pages_readonly(request: Request, project_id: str) -> dict[str, Any]:
    """Pins from snapshot; page catalog from stored pages/index.json when present."""
    _config, store, hub_project = _resolve_hub_project(request, project_id)
    project = _snapshot_project(store, hub_project.slug) or {}
    pins = project.get("page_pins") if isinstance(project.get("page_pins"), dict) else {}
    pages: list[dict[str, Any]] = []
    index_path = store.resolve_pages_path(hub_project.slug, "index.json")
    if index_path is not None:
        try:
            data = json.loads(index_path.read_text(encoding="utf-8"))
            raw_pages = data.get("pages") if isinstance(data, dict) else None
            if isinstance(raw_pages, dict):
                for page_id, meta in raw_pages.items():
                    if not isinstance(meta, dict):
                        continue
                    item = dict(meta)
                    item["id"] = str(meta.get("id") or page_id)
                    pages.append(item)
                pages.sort(key=lambda p: (str(p.get("title") or "").lower(), p["id"]))
        except (json.JSONDecodeError, OSError):
            pages = []
    return {"pages": pages, "pins": pins, "readonly": True}


@router.get("/projects/{project_id}/pages/{page_id}/file/{file_path:path}")
def get_page_file_readonly(
    request: Request,
    project_id: str,
    page_id: str,
    file_path: str = "index.html",
) -> FileResponse:
    _config, store, hub_project = _resolve_hub_project(request, project_id)
    path = store.resolve_page_file(
        hub_project.slug, page_id, file_path or "index.html"
    )
    if path is None:
        raise HTTPException(404, "Page file not found")
    return FileResponse(path)


@router.get("/projects/{project_id}/nodes/{node_id}/pages")
def get_node_pages_readonly(
    request: Request, project_id: str, node_id: str
) -> dict[str, Any]:
    """Hub is view-only: no attach/detach UI; return empty attachments."""
    _resolve_hub_project(request, project_id)
    return {"attachments": [], "readonly": True}


@router.get("/projects/{project_id}/boards/{board_id}/cards/{card_id}/report")
def card_report(
    request: Request, project_id: str, board_id: str, card_id: str
) -> dict[str, Any]:
    _config, store, hub_project = _resolve_hub_project(request, project_id)
    project = _snapshot_project(store, hub_project.slug)
    if project is None:
        raise HTTPException(404, "Snapshot missing")
    return _read_hub_card_report(store, hub_project.slug, project, board_id, card_id)


@router.get("/projects/{project_id}/boards/{board_id}/cards/{card_id}/report-path")
def card_report_path(
    request: Request, project_id: str, board_id: str, card_id: str
) -> dict[str, Any]:
    data = card_report(request, project_id, board_id, card_id)
    return {
        "card_id": card_id,
        "relative_path": data.get("relative_path"),
        "path": data.get("relative_path") or data.get("path"),
        "readonly": True,
    }


@router.get(
    "/projects/{project_id}/boards/{board_id}/cards/{card_id}/report/assets/{asset_name:path}"
)
def card_report_asset(
    request: Request,
    project_id: str,
    board_id: str,
    card_id: str,
    asset_name: str,
) -> FileResponse:
    _config, store, hub_project = _resolve_hub_project(request, project_id)
    project = _snapshot_project(store, hub_project.slug)
    if project is None:
        raise HTTPException(404, "Snapshot missing")
    index = _load_reports_index(store, hub_project.slug)
    rel = index.get(card_id)
    if not rel:
        raise HTTPException(404, "Report not found")
    owner_dir = rel.rsplit("/", 1)[0] if "/" in rel else ""
    safe = asset_name.strip().lstrip("/")
    if not safe or ".." in Path(safe).parts:
        raise HTTPException(400, "Invalid asset path")
    candidates = [
        f"{owner_dir}/assets/{safe}" if owner_dir else f"assets/{safe}",
        f"{owner_dir}/{safe}" if owner_dir else safe,
    ]
    for candidate in candidates:
        path = store.resolve_report_file(hub_project.slug, candidate)
        if path is not None:
            return FileResponse(path)
    raise HTTPException(404, "Asset not found")


@router.get("/projects/{project_id}/knowledge/asset")
def knowledge_asset(
    request: Request,
    project_id: str,
    path: str = Query(..., min_length=1),
) -> FileResponse:
    _config, store, hub_project = _resolve_hub_project(request, project_id)
    raw = path.strip().lstrip("/")
    if not raw or ".." in Path(raw).parts:
        raise HTTPException(400, "Invalid path")
    if not raw.startswith("reports/"):
        raise HTTPException(404, f"Файл не найден: {path}")
    rel = raw[len("reports/") :]
    file_path = store.resolve_report_file(hub_project.slug, rel)
    if file_path is None:
        raise HTTPException(404, f"Файл не найден: {path}")
    return FileResponse(file_path)


@router.get("/projects/{project_id}/knowledge/file")
def knowledge_file(
    request: Request,
    project_id: str,
    path: str = Query(..., min_length=1),
) -> PlainTextResponse:
    _config, store, hub_project = _resolve_hub_project(request, project_id)
    raw = path.strip().lstrip("/")
    if not raw or ".." in Path(raw).parts or not raw.endswith(".md"):
        raise HTTPException(400, "Invalid path")
    if not raw.startswith("reports/"):
        raise HTTPException(404, f"Файл не найден: {path}")
    rel = raw[len("reports/") :]
    file_path = store.resolve_report_file(hub_project.slug, rel)
    if file_path is None:
        raise HTTPException(404, f"Файл не найден: {path}")
    return PlainTextResponse(
        file_path.read_text(encoding="utf-8"),
        media_type="text/markdown; charset=utf-8",
    )


@router.get("/settings")
def settings_stub() -> dict[str, Any]:
    return {
        "agent_chat_mode": "cursor_inbox",
        "cursor_api_key_configured": False,
        "inbox_configured": False,
        "hub_readonly": True,
    }


@router.get("/sync/status")
def sync_status_stub() -> dict[str, Any]:
    return {"ok": True, "behind": 0, "hub_readonly": True}


@router.get("/sync/project-discovery")
def project_discovery_stub(since: int = 0) -> dict[str, Any]:
    return {"ok": True, "revision": since, "changes": {"added": [], "removed": [], "changed": []}}


@router.get("/sync/rq-discoveries/feed")
def rq_feed_stub(limit: int = 50) -> dict[str, Any]:
    return {"items": [], "limit": limit}


@router.get("/sync/rq-discoveries")
def rq_discoveries_stub() -> dict[str, Any]:
    return {"pending": [], "items": []}


@router.get("/agent-chat")
def agent_chat_stub(project_id: str = "") -> dict[str, Any]:
    return {"items": [], "project_id": project_id}


@router.get("/cursor/usage")
def cursor_usage_stub() -> dict[str, Any]:
    return {"available": False, "hub_readonly": True}
