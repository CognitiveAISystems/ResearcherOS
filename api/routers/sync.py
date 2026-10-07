from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from koi.adapters.project_discovery_watch import discovery_status
from koi.adapters.project_sync import git_summary, push_projects
from koi.adapters.project_sync_queue import (
    get_last_rq_heads,
    get_last_rq_sigs,
    rq_sigs_initialized,
    set_rq_discovery_state,
)
from koi.adapters.rq_discoveries_feed import append_discoveries, list_feed
from koi.projects.discoveries import pending_rq_discoveries
from koi.projects.sync import ensure_discovery_state_initialized, pull_projects

router = APIRouter(tags=["sync"])


@router.get("/sync/status")
def get_sync_status(fetch: bool = Query(True)) -> dict:
    """Per-mount ahead/behind. ``fetch=false`` uses cached refs (faster UI poll)."""
    return git_summary(fetch=fetch)


@router.get("/sync/project-discovery")
def get_project_discovery(since: int = 0) -> dict:
    """Poll for new or changed ``tree/*/koi-structure/project.md`` mounts."""
    return discovery_status(since_revision=since)


@router.post("/sync/pull")
def post_sync_pull(project_id: Optional[str] = Query(None)) -> dict:
    return pull_projects(project_id=project_id)


@router.post("/sync/push")
def post_sync_push(project_id: Optional[str] = Query(None)) -> dict:
    return push_projects(project_id=project_id)


@router.get("/sync/rq-discoveries")
def get_sync_rq_discoveries() -> dict:
    ensure_discovery_state_initialized()
    last_heads = get_last_rq_heads()
    items, heads, sigs, _initialized = pending_rq_discoveries(
        last_heads,
        get_last_rq_sigs(),
        sigs_initialized=rq_sigs_initialized(),
    )
    if items:
        append_discoveries(items)
    return {
        "ok": True,
        "heads": heads,
        "last_rq_heads": last_heads,
        "discoveries": items,
    }


@router.get("/sync/rq-discoveries/feed")
def get_sync_rq_discoveries_feed(limit: int = 50) -> dict:
    return {"ok": True, "items": list_feed(limit=limit)}


@router.post("/sync/rq-discoveries/ack")
def post_sync_rq_discoveries_ack() -> dict:
    from koi.projects.discoveries import _filesystem_signature_snapshot, current_heads

    heads = current_heads() or get_last_rq_heads()
    sigs = _filesystem_signature_snapshot()
    set_rq_discovery_state(heads=heads, sigs=sigs)
    return {"ok": True, "last_rq_heads": heads, "last_rq_sigs": sigs}
