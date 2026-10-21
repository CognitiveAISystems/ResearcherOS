"""Machine-local desktop application settings."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.schemas import DesktopWorkspaceBody
from koi.adapters.desktop_onboarding import (
    connect_git_project,
    inspect_existing_projects,
    inspect_existing_tree,
    inspect_git_project,
)
from koi.adapters.onboarding_interview import (
    InterviewError,
    attach_program,
    finish_interview,
    reply_interview,
    resolve_program,
    start_interview,
)
from koi.adapters.desktop_workspace import (
    archived_tree_ids,
    save_archived_tree_ids,
    selected_workspace_root,
    set_workspace_root,
)
from koi.adapters.project_mount import tree_dir_for
from koi.adapters.workspace import reset_workspace_cache


router = APIRouter(tags=["desktop"])


class DesktopFolderBody(BaseModel):
    path: str = Field(min_length=1)


class DesktopConnectBody(BaseModel):
    repo_path: str = Field(min_length=1)
    workspace_root: str = Field(min_length=1)
    require_existing: bool | None = None
    program_id: str | None = None
    program_title: str | None = None


class DesktopInterviewReplyBody(BaseModel):
    repo_path: str = Field(min_length=1)
    answer: str = Field(default="", max_length=12000)
    decision: str = "answer"


@router.get("/desktop/onboarding/default-location")
def get_default_research_location() -> dict:
    documents = Path.home() / "Documents"
    return {
        "workspace_root": str(documents),
        "research_root": str(documents / "tree"),
    }


@router.get("/desktop/workspace-root")
def get_desktop_workspace_root() -> dict:
    root = selected_workspace_root()
    return {"workspace_root": str(root) if root is not None else None}


@router.put("/desktop/workspace-root")
def put_desktop_workspace_root(body: DesktopWorkspaceBody) -> dict:
    try:
        requested = Path(body.workspace_root).expanduser().resolve(strict=True)
        if requested == (Path.home() / "Documents").resolve():
            tree_dir_for(requested).mkdir(parents=True, exist_ok=True)
        root = set_workspace_root(body.workspace_root)
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
    reset_workspace_cache()
    return {"workspace_root": str(root)}


@router.post("/desktop/onboarding/existing-projects")
def post_existing_projects(body: DesktopFolderBody) -> dict:
    try:
        return inspect_existing_projects(body.path)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/desktop/onboarding/existing-tree")
def post_existing_tree(body: DesktopFolderBody) -> dict:
    try:
        return inspect_existing_tree(body.path)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/desktop/onboarding/git-project")
def post_git_project(body: DesktopFolderBody) -> dict:
    try:
        return inspect_git_project(body.path)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/desktop/onboarding/connect")
def post_connect_project(body: DesktopConnectBody) -> dict:
    try:
        result = connect_git_project(
            body.repo_path, body.workspace_root, require_existing=body.require_existing
        )
        program = resolve_program(body.program_id, body.program_title)
        if program is not None:
            attach_program(body.repo_path, program)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    reset_workspace_cache()
    return result


@router.post("/desktop/onboarding/interview/start")
def post_start_interview(body: DesktopConnectBody) -> dict:
    try:
        return start_interview(
            body.repo_path,
            body.workspace_root,
            resolve_program(body.program_id, body.program_title),
        )
    except (ValueError, InterviewError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/desktop/onboarding/interview/reply")
def post_interview_reply(body: DesktopInterviewReplyBody) -> dict:
    try:
        return reply_interview(body.repo_path, body.answer, body.decision)
    except (ValueError, InterviewError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/desktop/onboarding/interview/finish")
def post_finish_interview(body: DesktopFolderBody) -> dict:
    try:
        result = finish_interview(body.path)
    except (ValueError, InterviewError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
    reset_workspace_cache()
    return result


class ArchivedTreesBody(BaseModel):
    ids: list[str] = Field(max_length=10000)


@router.get("/desktop/archived-trees")
def get_archived_trees() -> dict:
    try:
        return {"ids": archived_tree_ids()}
    except (OSError, ValueError) as exc:
        raise HTTPException(500, "Cannot read archived projects settings") from exc


@router.put("/desktop/archived-trees")
def put_archived_trees(body: ArchivedTreesBody) -> dict:
    try:
        return {"ids": save_archived_tree_ids(body.ids)}
    except OSError as exc:
        raise HTTPException(500, "Cannot save archived projects settings") from exc
