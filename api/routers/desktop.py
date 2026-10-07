"""Machine-local desktop application settings."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.schemas import DesktopWorkspaceBody
from koi.adapters.desktop_workspace import selected_workspace_root, set_workspace_root
from koi.adapters.workspace import reset_workspace_cache


router = APIRouter(tags=["desktop"])


@router.get("/desktop/workspace-root")
def get_desktop_workspace_root() -> dict:
    root = selected_workspace_root()
    return {"workspace_root": str(root) if root is not None else None}


@router.put("/desktop/workspace-root")
def put_desktop_workspace_root(body: DesktopWorkspaceBody) -> dict:
    try:
        root = set_workspace_root(body.workspace_root)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    reset_workspace_cache()
    return {"workspace_root": str(root)}
