from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from datetime import datetime, timezone
from pathlib import Path

from api.deps import parse_project
from koi.paper.catalog import (
    DEFAULT_PAPER_SLUG,
    get_paper_slot_dir,
    list_project_papers,
    normalize_paper_slug,
    find_pdf,
    update_paper_progress,
)
from koi.paper.page_counts import analyze_paper_pages
from koi.adapters.settings_store import is_cursor_inbox_agent_mode
from koi.paper.generator import (
    PDF_NAME,
    TEX_NAME,
    compile_paper_slot,
    generate_paper,
    paper_status,
)
from koi.paper.runner import submit_paper_request
from koi.paper.versions import (
    commit_and_push_paper,
    list_paper_versions,
    paper_tex_at_commit,
    pull_paper_versions,
)
from koi.paper.comment_agent import launch as launch_comment_agent
from koi.paper.comment_agent import status as comment_agent_status
from koi.paper.comments import (
    add_reply,
    apply_comment_merge,
    create_comment,
    delete_comment,
    extract_anchor_text,
    load_comments,
    set_comment_resolved,
)

router = APIRouter(tags=["paper"])


class PaperGenerateBody(BaseModel):
    slug: str = Field(default=DEFAULT_PAPER_SLUG)


class PaperCommentCreateBody(BaseModel):
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    body: str = Field(min_length=1)
    author: str = Field(default="reviewer")
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    selected_text: str | None = None


class PaperCommentReplyBody(BaseModel):
    body: str = Field(min_length=1)
    author: str = Field(default="reviewer")


class PaperCommentResolveBody(BaseModel):
    resolved: bool = True


class PaperCommentAgentBody(BaseModel):
    pass


class PaperCommentsMergeBody(BaseModel):
    comments: list[dict] = Field(default_factory=list)
    deleted_ids: list[str] = Field(default_factory=list)


class PaperTexUpdateBody(BaseModel):
    content: str = Field(default="")


class PaperProgressUpdateBody(BaseModel):
    main_pages: int | None = Field(default=None, ge=1)
    references_pages: int | None = Field(default=None, ge=1)
    appendix_pages: int | None = Field(default=None, ge=1)
    deadline: str | None = None


def _resolve_slot(project_id: str, slug: str | None) -> tuple[str, Path | None]:
    papers = list_project_papers(project_id)
    if slug is None:
        if not papers:
            return DEFAULT_PAPER_SLUG, None
        preferred = next((item for item in papers if item["slug"] == DEFAULT_PAPER_SLUG), papers[0])
        slug = preferred["slug"]
    try:
        normalized = normalize_paper_slug(slug)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    slot_dir = get_paper_slot_dir(project_id, normalized)
    return normalized, slot_dir


@router.get("/projects/{project_id}/papers")
def get_project_papers(project_id: str) -> dict:
    parse_project(project_id)
    papers = list_project_papers(project_id)
    return {"papers": papers, "default_slug": DEFAULT_PAPER_SLUG}


@router.post("/projects/{project_id}/paper")
def post_project_paper(
    project_id: str,
    background_tasks: BackgroundTasks,
    slug: str | None = Query(default=None),
    body: PaperGenerateBody | None = None,
) -> dict:
    """Сгенерировать (или перегенерировать) статью NeurIPS по графу исследования."""
    parse_project(project_id)
    paper_slug = normalize_paper_slug((body.slug if body else None) or slug)
    try:
        result = submit_paper_request(project_id, paper_slug=paper_slug)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    except KeyError as e:
        raise HTTPException(404, str(e)) from e

    if result.get("mode") == "background":
        background_tasks.add_task(generate_paper, project_id, paper_slug)

    return {
        "ok": True,
        "slug": paper_slug,
        "mode": result.get("mode"),
        "status": result.get("paper_status") or paper_status(project_id, paper_slug),
        "item_id": result.get("item_id"),
        "inbox_message": result.get("inbox_message") if is_cursor_inbox_agent_mode() else None,
    }


@router.get("/projects/{project_id}/paper/status")
def get_project_paper_status_legacy(
    project_id: str,
    slug: str | None = Query(default=None),
) -> dict:
    parse_project(project_id)
    return paper_status(project_id, normalize_paper_slug(slug))


@router.get("/projects/{project_id}/papers/{slug}/status")
def get_project_paper_status(project_id: str, slug: str) -> dict:
    parse_project(project_id)
    normalized = normalize_paper_slug(slug)
    return paper_status(project_id, normalized)


@router.get("/projects/{project_id}/paper/pdf")
def get_project_paper_pdf_legacy(
    project_id: str,
    slug: str | None = Query(default=None),
) -> FileResponse:
    parse_project(project_id)
    normalized, slot_dir = _resolve_slot(project_id, slug)
    if slot_dir is None:
        raise HTTPException(404, "PDF статьи ещё не сгенерирован")
    path = find_pdf(slot_dir)
    if path is None or not path.is_file():
        raise HTTPException(404, "PDF статьи ещё не сгенерирован")
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{path.name}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/projects/{project_id}/papers/{slug}/pdf")
def get_project_paper_pdf(project_id: str, slug: str) -> FileResponse:
    parse_project(project_id)
    normalized = normalize_paper_slug(slug)
    slot_dir = get_paper_slot_dir(project_id, normalized)
    if slot_dir is None:
        raise HTTPException(404, f"Статья «{normalized}» не найдена")
    path = find_pdf(slot_dir)
    if path is None or not path.is_file():
        raise HTTPException(404, "PDF статьи ещё не сгенерирован")
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{path.name}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/projects/{project_id}/paper/tex")
def get_project_paper_tex_legacy(
    project_id: str,
    slug: str | None = Query(default=None),
):
    parse_project(project_id)
    normalized, slot_dir = _resolve_slot(project_id, slug)
    if slot_dir is None:
        raise HTTPException(404, "main.tex ещё не сгенерирован")
    path = slot_dir / TEX_NAME
    if not path.is_file():
        raise HTTPException(404, "main.tex ещё не сгенерирован")
    return PlainTextResponse(
        path.read_text(encoding="utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/projects/{project_id}/papers/{slug}/tex/meta")
def get_project_paper_tex_meta(project_id: str, slug: str) -> dict:
    _, slot_dir = _require_paper_slot(project_id, slug)
    path = slot_dir / TEX_NAME
    if not path.is_file():
        raise HTTPException(404, "main.tex ещё не сгенерирован")
    stat = path.stat()
    return {"tex_exists": True, "tex_mtime": stat.st_mtime, "size": stat.st_size}


@router.get("/projects/{project_id}/papers/{slug}/versions")
def get_project_paper_versions(project_id: str, slug: str) -> dict:
    normalized, slot_dir = _require_paper_slot(project_id, slug)
    path = slot_dir / TEX_NAME
    if not path.is_file():
        raise HTTPException(404, "main.tex ещё не сгенерирован")
    return list_paper_versions(project_id, path)


@router.post("/projects/{project_id}/papers/{slug}/versions/pull")
def post_project_paper_versions_pull(project_id: str, slug: str) -> dict:
    normalized, slot_dir = _require_paper_slot(project_id, slug)
    path = slot_dir / TEX_NAME
    if not path.is_file():
        raise HTTPException(404, "main.tex ещё не сгенерирован")
    try:
        versions = pull_paper_versions(project_id, path)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    from koi.paper.collaboration.session import drop_session

    drop_session(project_id, normalized)
    return {"ok": True, **versions}


@router.post("/projects/{project_id}/papers/{slug}/versions/push")
def post_project_paper_versions_push(project_id: str, slug: str) -> dict:
    normalized, slot_dir = _require_paper_slot(project_id, slug)
    path = slot_dir / TEX_NAME
    if not path.is_file():
        raise HTTPException(404, "main.tex ещё не сгенерирован")
    try:
        return commit_and_push_paper(project_id, path, slug=normalized)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/projects/{project_id}/papers/{slug}/tex")
def get_project_paper_tex(
    project_id: str,
    slug: str,
    at: str | None = Query(default=None),
):
    parse_project(project_id)
    normalized = normalize_paper_slug(slug)
    slot_dir = get_paper_slot_dir(project_id, normalized)
    if slot_dir is None:
        raise HTTPException(404, f"Статья «{normalized}» не найдена")
    path = slot_dir / TEX_NAME
    if at:
        try:
            text = paper_tex_at_commit(project_id, path, at)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        return PlainTextResponse(
            text,
            media_type="text/plain; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )
    if not path.is_file():
        raise HTTPException(404, "main.tex ещё не сгенерирован")
    from koi.paper.collaboration.session import live_text

    text = live_text(project_id, normalized)
    if text is None:
        text = path.read_text(encoding="utf-8")
    return PlainTextResponse(
        text,
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@router.put("/projects/{project_id}/papers/{slug}/tex")
def put_project_paper_tex(project_id: str, slug: str, body: PaperTexUpdateBody) -> dict:
    normalized, slot_dir = _require_paper_slot(project_id, slug)
    slot_dir.mkdir(parents=True, exist_ok=True)
    path = slot_dir / TEX_NAME
    from koi.paper.collaboration.session import get_session

    session = get_session(project_id, normalized)
    if session is not None and not session.closed:
        if body.content == session.document.to_string():
            flushed = session.flush()
            return {"ok": True, "tex_mtime": flushed.get("tex_mtime") or path.stat().st_mtime}
        imported = session.import_external(body.content, source="api")
        if imported.conflict:
            raise HTTPException(
                409,
                imported.reason or "Не удалось применить изменение поверх collaborative session",
            )
        flushed = session.flush()
        return {"ok": True, "tex_mtime": flushed.get("tex_mtime") or path.stat().st_mtime}
    path.write_text(body.content, encoding="utf-8")
    return {"ok": True, "tex_mtime": path.stat().st_mtime}


@router.patch("/projects/{project_id}/papers/{slug}/meta")
def patch_project_paper_meta(project_id: str, slug: str, body: PaperProgressUpdateBody) -> dict:
    _, slot_dir = _require_paper_slot(project_id, slug)
    progress = update_paper_progress(
        slot_dir,
        body.model_dump(exclude_unset=True),
    )
    return {"ok": True, "progress": progress}


@router.post("/projects/{project_id}/papers/{slug}/compile")
def post_project_paper_compile(project_id: str, slug: str) -> dict:
    _, slot_dir = _require_paper_slot(project_id, slug)
    tex_path = slot_dir / TEX_NAME
    if not tex_path.is_file():
        raise HTTPException(404, "main.tex ещё не сгенерирован")
    ok, engine, log_tail = compile_paper_slot(slot_dir)
    if not ok:
        raise HTTPException(422, log_tail or "Не удалось собрать PDF")
    pdf_path = find_pdf(slot_dir)
    pdf_mtime = (
        datetime.fromtimestamp(pdf_path.stat().st_mtime, tz=timezone.utc).isoformat(
            timespec="seconds"
        )
        if pdf_path and pdf_path.is_file()
        else None
    )
    page_counts = analyze_paper_pages(slot_dir) if pdf_path and pdf_path.is_file() else None
    return {
        "ok": True,
        "engine": engine,
        "log_tail": log_tail,
        "pdf_mtime": pdf_mtime,
        "page_counts": page_counts,
    }


def _require_paper_slot(project_id: str, slug: str) -> tuple[str, Path]:
    parse_project(project_id)
    normalized = normalize_paper_slug(slug)
    slot_dir = get_paper_slot_dir(project_id, normalized)
    if slot_dir is None:
        raise HTTPException(404, f"Статья «{normalized}» не найдена")
    return normalized, slot_dir


@router.get("/projects/{project_id}/papers/{slug}/comments")
def get_project_paper_comments(project_id: str, slug: str) -> dict:
    _, slot_dir = _require_paper_slot(project_id, slug)
    return load_comments(slot_dir)


@router.put("/projects/{project_id}/papers/{slug}/comments")
def put_project_paper_comments(project_id: str, slug: str, body: PaperCommentsMergeBody) -> dict:
    _, slot_dir = _require_paper_slot(project_id, slug)
    return apply_comment_merge(slot_dir, body.comments, body.deleted_ids)


@router.post("/projects/{project_id}/papers/{slug}/comments")
def post_project_paper_comment(project_id: str, slug: str, body: PaperCommentCreateBody) -> dict:
    _, slot_dir = _require_paper_slot(project_id, slug)
    try:
        comment = create_comment(
            slot_dir,
            line_start=body.line_start,
            line_end=body.line_end,
            body=body.body,
            author=body.author,
            char_start=body.char_start,
            char_end=body.char_end,
            selected_text=body.selected_text,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "comment": comment}


@router.post("/projects/{project_id}/papers/{slug}/comments/{comment_id}/replies")
def post_project_paper_comment_reply(
    project_id: str,
    slug: str,
    comment_id: str,
    body: PaperCommentReplyBody,
) -> dict:
    _, slot_dir = _require_paper_slot(project_id, slug)
    try:
        message = add_reply(slot_dir, comment_id, body=body.body, author=body.author)
    except KeyError as e:
        raise HTTPException(404, "Comment not found") from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "message": message}


@router.patch("/projects/{project_id}/papers/{slug}/comments/{comment_id}")
def patch_project_paper_comment(
    project_id: str,
    slug: str,
    comment_id: str,
    body: PaperCommentResolveBody,
) -> dict:
    _, slot_dir = _require_paper_slot(project_id, slug)
    try:
        comment = set_comment_resolved(slot_dir, comment_id, resolved=body.resolved)
    except KeyError as e:
        raise HTTPException(404, "Comment not found") from e
    return {"ok": True, "comment": comment}


@router.post("/projects/{project_id}/papers/{slug}/comments/{comment_id}/agent")
def post_project_paper_comment_agent(
    project_id: str,
    slug: str,
    comment_id: str,
    body: PaperCommentAgentBody,
) -> dict:
    _, slot_dir = _require_paper_slot(project_id, slug)
    store = load_comments(slot_dir)
    comment = next((item for item in store.get("comments") or [] if item.get("id") == comment_id), None)
    if comment is None:
        raise HTTPException(404, "Comment not found")
    anchor = comment.get("anchor") or {}
    thread = comment.get("thread") or []
    note = thread[0].get("body", "").strip() if thread else ""
    line = max(1, int(anchor.get("line_start") or 1))
    end_line = max(line, int(anchor.get("line_end") or line))
    char_start = anchor.get("char_start")
    char_end = anchor.get("char_end")
    tex_lines = (slot_dir / "main.tex").read_text(encoding="utf-8").splitlines()
    selected = anchor.get("selected_text") or extract_anchor_text(
        "\n".join(tex_lines), line, end_line, char_start, char_end
    )
    location = f"строки {line}–{end_line}" if end_line != line else f"строка {line}"
    if line == end_line and char_start is not None and char_end is not None:
        location += f", символы {char_start + 1}–{char_end}"
    excerpt = "\n".join(
        f"{index + 1}: {tex_lines[index]}"
        for index in range(max(0, line - 6), min(len(tex_lines), end_line + 5))
    )
    prompt = (
        f"Замечание к main.tex ({location}): {note}\n"
        f"Выделенный текст, к которому относится замечание:\n{selected}\n\n"
        f"Строки статьи вокруг выделения:\n{excerpt}\n\n"
        "Исправь прежде всего выделенный текст в указанном месте. Меняй соседние фразы "
        "только если без этого правка не будет связной. Если выделенный текст уже изменился, "
        "не правь другое место наугад, а сообщи об этом. Работай только с main.tex; "
        "не читай всю статью и не запускай внешние инструменты. Кратко объясни предложенную правку."
    )
    try:
        job = launch_comment_agent(project_id, slug, comment_id, prompt, slot_dir)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, **job}


@router.get("/projects/{project_id}/papers/{slug}/comments/{comment_id}/agent")
def get_project_paper_comment_agent(project_id: str, slug: str, comment_id: str) -> dict:
    _require_paper_slot(project_id, slug)
    return comment_agent_status(project_id, slug, comment_id)


@router.delete("/projects/{project_id}/papers/{slug}/comments/{comment_id}")
def delete_project_paper_comment(project_id: str, slug: str, comment_id: str) -> dict:
    _, slot_dir = _require_paper_slot(project_id, slug)
    try:
        delete_comment(slot_dir, comment_id)
    except KeyError as e:
        raise HTTPException(404, "Comment not found") from e
    return {"ok": True}
