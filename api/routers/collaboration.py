"""Local collaboration session API (Spike A: same ResearcherOS instance)."""

from __future__ import annotations

import asyncio
import base64
from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from api.deps import parse_project
from koi.paper.catalog import get_paper_slot_dir, normalize_paper_slug
from koi.paper.generator import TEX_NAME
from koi.paper.collaboration.network import (
    git_document_state,
    issue_room_token,
    lan_ip,
    network_config,
    network_room_id,
)
from koi.paper.collaboration.session import (
    get_or_create_session,
    get_session,
    register_agent_task,
)

router = APIRouter(tags=["collaboration"])


class AgentTaskBody(BaseModel):
    task_id: str | None = None


class CollabEditBody(BaseModel):
    text: str = Field(default="")
    base_revision: int | None = None
    peer_id: str = "rest"


class ProposalResolutionBody(BaseModel):
    proposal_id: str


class ProposalHunkResolutionBody(ProposalResolutionBody):
    hunk_id: str


def _slot(project_id: str, slug: str):
    parse_project(project_id)
    normalized = normalize_paper_slug(slug)
    slot_dir = get_paper_slot_dir(project_id, normalized)
    if slot_dir is None:
        raise HTTPException(404, f"Статья «{normalized}» не найдена")
    return normalized, slot_dir


def _session(project_id: str, slug: str, *, create: bool = False):
    normalized, slot_dir = _slot(project_id, slug)
    tex_path = slot_dir / TEX_NAME
    if create:
        return get_or_create_session(project_id, normalized, tex_path)
    session = get_session(project_id, normalized)
    if session is None:
        raise HTTPException(404, "Нет активной collaborative session")
    return session


@router.get("/projects/{project_id}/papers/{slug}/collab")
def get_collab_status(project_id: str, slug: str) -> dict[str, Any]:
    parse_project(project_id)
    normalized = normalize_paper_slug(slug)
    session = get_session(project_id, normalized)
    if session is None:
        return {"active": False, "project_id": project_id, "slug": normalized, "peer_count": 0}
    return session.status()


@router.post("/projects/{project_id}/papers/{slug}/collab/open")
def open_collab_session(project_id: str, slug: str) -> dict[str, Any]:
    session = _session(project_id, slug, create=True)
    return session.status()


@router.post("/projects/{project_id}/papers/{slug}/collab/flush")
def flush_collab_session(project_id: str, slug: str) -> dict[str, Any]:
    session = _session(project_id, slug)
    return session.flush()


@router.post("/projects/{project_id}/papers/{slug}/collab/reload-from-disk")
def reload_collab_from_disk(project_id: str, slug: str) -> dict[str, Any]:
    """Force all peers to reset to the on-disk main.tex (new CRDT epoch)."""
    session = _session(project_id, slug, create=True)
    try:
        event = session.force_reload_from_disk()
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {
        "ok": True,
        "revision": event.get("revision"),
        "hash": event.get("hash"),
        "crdt_epoch": event.get("crdt_epoch"),
        "tex_mtime": event.get("tex_mtime"),
    }


@router.get("/projects/{project_id}/papers/{slug}/collab/network")
def get_collab_network(
    project_id: str,
    slug: str,
    peer: str = Query(..., min_length=3, max_length=128),
) -> dict[str, Any]:
    session = _session(project_id, slug, create=True)
    config = network_config()
    git = git_document_state(project_id, session.tex_path)
    room = network_room_id(git.repository_id, session.slug, git.relative_path)
    payload: dict[str, Any] = {
        "enabled": config.enabled,
        "signaling_url": config.signaling_url,
        "ice_servers": config.ice_servers(),
        "room_id": room,
        "repository_id": git.repository_id,
        "git_commit": git.commit,
        "base_document_hash": git.base_document_hash,
        "document_hash": session.document.content_hash(),
        "crdt_epoch": session.crdt_epoch,
        "lan_ip": lan_ip(),
    }
    if not config.enabled:
        return payload
    token, expires_at = issue_room_token(
        secret=config.token_secret,
        room=room,
        peer_id=peer,
        repository_id=git.repository_id,
        paper_id=session.slug,
    )
    payload.update({"token": token, "expires_at": expires_at})
    return payload


@router.get("/projects/{project_id}/papers/{slug}/collab/proposal")
def get_collab_proposal(project_id: str, slug: str) -> dict[str, Any]:
    session = _session(project_id, slug)
    return session.proposal_event()


@router.post("/projects/{project_id}/papers/{slug}/collab/proposal/accept")
def accept_collab_proposal(
    project_id: str,
    slug: str,
    body: ProposalResolutionBody,
) -> dict[str, Any]:
    session = _session(project_id, slug)
    try:
        return session.accept_proposal(body.proposal_id)
    except KeyError as exc:
        raise HTTPException(409, "Предложение уже изменилось или было обработано") from exc


@router.post("/projects/{project_id}/papers/{slug}/collab/proposal/reject")
def reject_collab_proposal(
    project_id: str,
    slug: str,
    body: ProposalResolutionBody,
) -> dict[str, Any]:
    session = _session(project_id, slug)
    try:
        return session.reject_proposal(body.proposal_id)
    except KeyError as exc:
        raise HTTPException(409, "Предложение уже изменилось или было обработано") from exc


@router.post("/projects/{project_id}/papers/{slug}/collab/proposal/hunk/accept")
def accept_collab_proposal_hunk(
    project_id: str,
    slug: str,
    body: ProposalHunkResolutionBody,
) -> dict[str, Any]:
    session = _session(project_id, slug)
    try:
        return session.resolve_proposal_hunk(body.proposal_id, body.hunk_id, accept=True)
    except KeyError as exc:
        raise HTTPException(409, "Фрагмент уже изменился; проверьте актуальный diff") from exc


@router.post("/projects/{project_id}/papers/{slug}/collab/proposal/hunk/reject")
def reject_collab_proposal_hunk(
    project_id: str,
    slug: str,
    body: ProposalHunkResolutionBody,
) -> dict[str, Any]:
    session = _session(project_id, slug)
    try:
        return session.resolve_proposal_hunk(body.proposal_id, body.hunk_id, accept=False)
    except KeyError as exc:
        raise HTTPException(409, "Фрагмент уже изменился; проверьте актуальный diff") from exc


@router.post("/projects/{project_id}/papers/{slug}/collab/agent-task")
def post_collab_agent_task(
    project_id: str,
    slug: str,
    body: AgentTaskBody | None = None,
) -> dict[str, Any]:
    normalized, slot_dir = _slot(project_id, slug)
    task = register_agent_task(
        project_id,
        normalized,
        slot_dir / TEX_NAME,
        task_id=body.task_id if body else None,
    )
    return {
        "task_id": task.task_id,
        "base_revision": task.base_revision,
        "base_hash": task.base_hash,
    }


@router.post("/projects/{project_id}/papers/{slug}/collab/edit")
def post_collab_edit(project_id: str, slug: str, body: CollabEditBody) -> dict[str, Any]:
    session = _session(project_id, slug, create=True)
    return session.apply_client_text(body.peer_id, body.text, body.base_revision)


@router.websocket("/projects/{project_id}/papers/{slug}/collab")
async def collab_ws(
    websocket: WebSocket,
    project_id: str,
    slug: str,
    peer: str | None = Query(default=None),
    user: str = Query(default="anonymous"),
    actor: str = Query(default="human"),
) -> None:
    try:
        parse_project(project_id)
        normalized = normalize_paper_slug(slug)
    except (ValueError, HTTPException):
        await websocket.close(code=1008)
        return
    slot_dir = get_paper_slot_dir(project_id, normalized)
    if slot_dir is None:
        await websocket.close(code=1008)
        return
    session = get_or_create_session(project_id, normalized, slot_dir / TEX_NAME)
    await websocket.accept()
    loop = asyncio.get_running_loop()

    def handler(event: dict[str, Any]) -> None:
        try:
            asyncio.run_coroutine_threadsafe(websocket.send_json(event), loop)
        except Exception:
            return

    joined = session.join(peer, user_name=user, actor_type=actor, handler=handler)
    await websocket.send_json(session.sync_event())
    await websocket.send_json({"type": "hello", "peer_id": joined.peer_id, **session.status()})
    if session.proposal is not None:
        await websocket.send_json(session.proposal_event())
    try:
        while True:
            message = await websocket.receive_json()
            kind = message.get("type")
            if kind == "crdt_update":
                try:
                    update = base64.b64decode(str(message.get("update") or ""), validate=True)
                except (ValueError, TypeError):
                    await websocket.close(code=1003)
                    return
                await websocket.send_json(session.apply_crdt_update(joined.peer_id, update))
            elif kind == "adopt_remote":
                try:
                    update = base64.b64decode(str(message.get("update") or ""), validate=True)
                    session.adopt_remote_state(
                        update,
                        crdt_epoch=str(message.get("crdt_epoch") or ""),
                        expected_hash=str(message.get("expected_hash") or ""),
                        origin=joined.peer_id,
                    )
                except (ValueError, TypeError) as exc:
                    await websocket.send_json(
                        {
                            "type": "network_error",
                            "code": "remote_state_rejected",
                            "reason": str(exc),
                        }
                    )
            elif kind == "op":
                session.apply_client_op(
                    joined.peer_id,
                    int(message.get("start") or 0),
                    int(message.get("delete_len") or 0),
                    str(message.get("insert") or ""),
                    message.get("base_revision"),
                    base_hash=message.get("base_hash"),
                )
            elif kind == "edit":
                session.apply_client_text(
                    joined.peer_id,
                    str(message.get("text") or ""),
                    message.get("base_revision"),
                )
            elif kind == "presence":
                session.update_presence(joined.peer_id, message)
            elif kind == "comments":
                session.broadcast_comments(
                    message.get("comments") or [],
                    message.get("deleted_ids") or [],
                    exclude=joined.peer_id,
                )
            elif kind == "flush":
                expected_hash = str(message.get("expected_hash") or "") or None
                force_text = message.get("text")
                result = session.flush(
                    expected_hash=expected_hash,
                    text=str(force_text) if force_text is not None else None,
                )
                request_id = str(message.get("request_id") or "")
                if request_id:
                    result = {**result, "request_id": request_id}
                await websocket.send_json(result)
            elif kind == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        session.leave(joined.peer_id)
    except Exception:
        session.leave(joined.peer_id)
        raise
