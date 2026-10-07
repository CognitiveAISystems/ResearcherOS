from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from api.deps import get_project as require_project
from api.schemas import (
    CardReportBody,
    CreateCardBody,
    CreateNodeBody,
    CreateProjectBody,
    UpdateCardBody,
    UpdateTagBody,
    UpdateNodeBody,
)
from koi.laboratory.programs import list_project_summaries
from koi.projects import commands as project_commands
from koi.projects import live as live_queries
from koi.projects import reports as report_commands
from koi.projects.views import project_to_client

router = APIRouter(tags=["projects"])


@router.get("/projects")
def projects() -> list[dict]:
    return list_project_summaries()


@router.post("/projects")
def post_project(body: CreateProjectBody) -> dict:
    try:
        project = project_commands.create_project(
            project_commands.CreateProjectCommand(
                title=body.title,
                project_id=body.tag,
                description=body.description,
                program_id=body.program_id,
                program_title=body.program_title,
            )
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return project_to_client(project)


@router.get("/projects/{project_id}")
def read_project(project_id: str) -> dict:
    return project_to_client(require_project(project_id, sync_reports=False))


@router.get("/projects/{project_id}/kanban/running-activity")
def get_kanban_running_activity(project_id: str) -> dict:
    try:
        items = live_queries.running_activity(project_id)
    except live_queries.EntityNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    return {"ok": True, "items": items}


@router.get("/projects/{project_id}/kanban/live-monitor")
def get_kanban_live_monitor(project_id: str) -> dict:
    try:
        items = live_queries.live_monitor(project_id)
    except live_queries.EntityNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    return {"ok": True, "items": items}


@router.put("/projects/{project_id}")
def put_project(project_id: str, payload: dict) -> dict:
    try:
        project = project_commands.replace_project(project_id, payload)
    except project_commands.EntityNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    return project_to_client(project)


@router.post("/projects/{project_id}/nodes")
def post_node(project_id: str, body: CreateNodeBody) -> dict:
    try:
        project = project_commands.create_node(
            project_id,
            project_commands.CreateNodeCommand(
                parent_id=body.parent_id,
                node_type=body.node_type,
                title=body.title,
                description=body.description,
            ),
        )
    except project_commands.EntityNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return project_to_client(project)


@router.patch("/projects/{project_id}/nodes/{node_id}")
def patch_node(project_id: str, node_id: str, body: UpdateNodeBody) -> dict:
    research_questions = None
    if body.research_questions is not None:
        research_questions = [
            project_commands.ResearchQuestionInput(
                id=item.id,
                question=item.question,
                answer=item.answer,
                narrative=item.narrative,
                certainty=item.certainty,
                importance=item.importance,
                card_id=item.card_id,
            )
            for item in body.research_questions
        ]
    try:
        project = project_commands.update_node(
            project_id,
            node_id,
            project_commands.UpdateNodeCommand(
                title=body.title,
                description=body.description,
                research_questions=research_questions,
            ),
        )
    except project_commands.EntityNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return project_to_client(project)


@router.delete("/projects/{project_id}/nodes/{node_id}")
def remove_node(project_id: str, node_id: str) -> dict:
    try:
        project = project_commands.delete_node(project_id, node_id)
    except project_commands.EntityNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return project_to_client(project)


@router.post("/projects/{project_id}/boards/{board_id}/cards")
def post_card(project_id: str, board_id: str, body: CreateCardBody) -> dict:
    try:
        project = project_commands.create_card(
            project_id,
            board_id,
            project_commands.CreateCardCommand(
                column_id=body.column_id,
                title=body.title,
                description=body.description,
                tags=tuple(body.tags),
                depends_on=tuple(body.depends_on),
            ),
        )
    except project_commands.EntityNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return project_to_client(project)


@router.patch("/projects/{project_id}/boards/{board_id}/cards/{card_id}")
def patch_card(
    project_id: str, board_id: str, card_id: str, body: UpdateCardBody
) -> dict:
    try:
        project = project_commands.update_card(
            project_id,
            board_id,
            card_id,
            project_commands.UpdateCardCommand(
                title=body.title,
                description=body.description,
                column_id=body.column_id,
                tags=tuple(body.tags) if body.tags is not None else None,
                depends_on=tuple(body.depends_on) if body.depends_on is not None else None,
                pinned=body.pinned,
            ),
        )
    except project_commands.EntityNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return project_to_client(project)


@router.delete("/projects/{project_id}/boards/{board_id}/cards/{card_id}")
def delete_card(project_id: str, board_id: str, card_id: str) -> dict:
    try:
        project = project_commands.delete_card(project_id, board_id, card_id)
    except project_commands.EntityNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return project_to_client(project)


@router.get("/projects/{project_id}/boards/{board_id}/cards/{card_id}/report")
def get_card_report(project_id: str, board_id: str, card_id: str) -> dict:
    try:
        return report_commands.read_card_report(project_id, board_id, card_id)
    except report_commands.EntityNotFoundError as error:
        raise HTTPException(404, str(error)) from error


@router.get("/projects/{project_id}/boards/{board_id}/cards/{card_id}/report-path")
def get_card_report_path(project_id: str, board_id: str, card_id: str) -> dict:
    try:
        return report_commands.card_report_path(project_id, board_id, card_id)
    except report_commands.EntityNotFoundError as error:
        raise HTTPException(404, str(error)) from error


@router.put("/projects/{project_id}/boards/{board_id}/cards/{card_id}/report")
def put_card_report(
    project_id: str, board_id: str, card_id: str, body: CardReportBody
) -> dict:
    try:
        return report_commands.write_card_report(
            project_id,
            board_id,
            card_id,
            body.content,
        )
    except report_commands.EntityNotFoundError as error:
        raise HTTPException(404, str(error)) from error


@router.post("/projects/{project_id}/boards/{board_id}/cards/{card_id}/report/assets")
async def post_report_asset(
    project_id: str,
    board_id: str,
    card_id: str,
    file: UploadFile = File(...),
) -> dict:
    try:
        report_commands.ensure_report_card(project_id, board_id, card_id)
    except report_commands.EntityNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    try:
        return report_commands.store_report_asset(
            project_id,
            board_id,
            card_id,
            data,
            file.content_type or "application/octet-stream",
        )
    except report_commands.EntityNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.get("/projects/{project_id}/boards/{board_id}/cards/{card_id}/live")
def get_card_live(
    project_id: str,
    board_id: str,
    card_id: str,
    tail_lines: int = 100,
) -> dict:
    try:
        return live_queries.card_snapshot(
            project_id,
            board_id,
            card_id,
            tail_lines=tail_lines,
        )
    except live_queries.EntityNotFoundError as error:
        raise HTTPException(404, str(error)) from error


@router.get("/projects/{project_id}/live/file")
def get_live_file(project_id: str, path: str) -> FileResponse:
    try:
        resolved = live_queries.resolve_live_file(project_id, path)
    except live_queries.EntityNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(404, "File not found") from error
    return FileResponse(resolved)


@router.get(
    "/projects/{project_id}/boards/{board_id}/cards/{card_id}/report/assets/{asset_name:path}"
)
def get_report_asset(
    project_id: str,
    board_id: str,
    card_id: str,
    asset_name: str,
) -> FileResponse:
    try:
        path = report_commands.report_asset_path(
            project_id,
            board_id,
            card_id,
            asset_name,
        )
    except report_commands.EntityNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(404, "Asset not found") from error
    return FileResponse(path)


@router.patch("/projects/{project_id}/card-tags/{tag}")
def patch_card_tag(project_id: str, tag: str, body: UpdateTagBody) -> dict:
    try:
        return project_to_client(project_commands.update_card_tag(project_id, tag, body.name, body.color))
    except project_commands.EntityNotFoundError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.delete("/projects/{project_id}/card-tags/{tag}")
def delete_card_tag(project_id: str, tag: str) -> dict:
    try:
        return project_to_client(project_commands.delete_card_tag(project_id, tag))
    except project_commands.EntityNotFoundError as error:
        raise HTTPException(404, str(error)) from error
