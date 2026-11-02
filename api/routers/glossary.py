"""Vocabulary editor endpoints; clients use revisions to avoid lost edits."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from api.deps import enqueue_sync, get_project
from koi.adapters import glossary

router = APIRouter(tags=["glossary"])


class GlossaryBody(BaseModel):
    text: str = Field(max_length=glossary.MAX_LENGTH)
    revision: str


@router.get("/glossary")
def get_glossary(project_id: str | None = None):
    if project_id:
        get_project(project_id)
    return glossary.context(project_id)


@router.put("/glossary")
def put_glossary(body: GlossaryBody, project_id: str | None = None):
    if project_id:
        get_project(project_id)
    try:
        result = glossary.write(body.text, body.revision, project_id)
    except FileExistsError as error:
        raise HTTPException(409, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    if project_id:
        enqueue_sync(project_id, "glossary", "Обновлён словарь дерева")
    return result
