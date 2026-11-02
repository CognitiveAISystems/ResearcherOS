from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse

from api.deps import get_project, parse_project
from api.schemas import (
    LiteratureClusterBody,
    PaperQuestionAgentBody,
    ProjectPaperReviewBody,
    RelatedWorksAnswerBody,
    RelatedWorksBody,
    ReviewAgentBody,
)
from koi.literature import create_project_paper_review, search_library
from koi.literature.cluster_orch import (
    delete_literature_run,
    list_literature_runs,
    load_literature_run,
    run_literature_cluster,
    stage_literature_cluster,
)
from koi.related_work import (
    answer_related_work_item,
    claim_related_work_item,
    get_related_work_item,
    list_related_work_for_project,
    submit_related_work_request,
)
from koi.review import (
    load_latest_paper_answer_run,
    run_paper_question_agent,
    run_review_agent,
)

router = APIRouter(tags=["review"])


@router.post("/projects/{project_id}/paper-reviews")
def post_project_paper_review(project_id: str, body: ProjectPaperReviewBody) -> dict[str, object]:
    query = body.query.strip()
    if not query:
        raise HTTPException(400, "Query must not be empty")

    parse_project(project_id)
    results = body.papers or search_library(query, limit=body.limit)
    if not results:
        raise HTTPException(400, "No ranked papers available for this query")
    return create_project_paper_review(project_id, query, results)


@router.post("/projects/{project_id}/review-agent")
def post_project_review_agent(project_id: str, body: ReviewAgentBody) -> dict[str, object]:
    parse_project(project_id)
    try:
        return run_review_agent(
            project_id,
            query=body.query.strip() if body.query else None,
            limit=body.limit,
            force_refresh=body.refresh,
            download_pdfs=body.download_pdfs,
            selected_results=body.papers,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from e


@router.post("/projects/{project_id}/paper-question-agent")
def post_project_paper_question_agent(
    project_id: str,
    body: PaperQuestionAgentBody,
) -> dict[str, object]:
    parse_project(project_id)
    try:
        return run_paper_question_agent(
            project_id,
            question=body.question.strip(),
            limit=body.limit,
            force_refresh=body.refresh,
            download_pdfs=body.download_pdfs,
            selected_results=body.papers,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from e


@router.post("/projects/{project_id}/literature/cluster")
def post_project_literature_cluster(
    project_id: str,
    body: LiteratureClusterBody,
) -> dict[str, object]:
    parse_project(project_id)
    try:
        return run_literature_cluster(
            project_id,
            question=body.question.strip(),
            selected_results=body.papers,
            force_refresh=body.refresh,
            download_pdfs=body.download_pdfs,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from e


@router.post("/projects/{project_id}/literature/cluster/stage")
def post_project_literature_cluster_stage(
    project_id: str,
    body: LiteratureClusterBody,
) -> dict[str, object]:
    """Stage selected papers + question; return a Cursor chat prompt (no LLM API)."""
    parse_project(project_id)
    try:
        return stage_literature_cluster(
            project_id,
            question=body.question.strip(),
            selected_results=body.papers,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/projects/{project_id}/literature/cluster/agent")
def post_project_literature_cluster_agent(
    project_id: str, body: LiteratureClusterBody, background_tasks: BackgroundTasks,
) -> dict[str, object]:
    """Use the ordinary in-app conversation worker, including agent settings."""
    from api.routers.agents import create_conversation, post_agent_chat
    from api.schemas import AgentChatBody, ConversationCreateBody
    from koi.agent_chat import conversations
    from koi.literature.cluster_orch import literature_dir, _write_json
    parse_project(project_id)
    try:
        staged = stage_literature_cluster(
            project_id, question=body.question.strip(), selected_results=body.papers,
        )
        conversation = create_conversation(ConversationCreateBody(
            project_id=project_id, title=body.question[:80], backend=body.cli_agent,
        ))["item"]
        conversations.update(conversation["id"], kind="literature", literature_run_id=staged["run_id"])
        response = post_agent_chat(AgentChatBody(
            project_id=project_id, question=body.question.strip(),
            conversation_id=conversation["id"], cli_agent=body.cli_agent,
        ), background_tasks)
        _write_json(literature_dir(project_id) / staged["run_id"] / "chat.json",
                    {"conversation_id": conversation["id"]})
        return {**staged, "conversation_id": conversation["id"], "item": response["item"]}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/projects/{project_id}/literature")
def get_project_literature_history(project_id: str) -> dict[str, object]:
    parse_project(project_id)
    runs = list_literature_runs(project_id)
    return {"count": len(runs), "runs": runs}


@router.get("/projects/{project_id}/literature/{run_id}")
def get_project_literature_run(project_id: str, run_id: str) -> dict[str, object]:
    parse_project(project_id)
    payload = load_literature_run(project_id, run_id)
    if payload is None:
        raise HTTPException(404, f"Literature run '{run_id}' was not found.")
    return payload


@router.delete("/projects/{project_id}/literature/{run_id}")
def delete_project_literature_run(project_id: str, run_id: str, delete_report: bool = False) -> dict[str, object]:
    """Delete a run; deleting its report requires explicit opt-in."""
    parse_project(project_id)
    try:
        return delete_literature_run(project_id, run_id, delete_report=delete_report)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/projects/{project_id}/paper-question-agent/latest")
def get_latest_project_paper_question_agent(project_id: str) -> dict[str, object]:
    parse_project(project_id)
    payload = load_latest_paper_answer_run(project_id)
    if payload is None:
        # Prefer newest multi-agent literature run when legacy paper_answers are empty.
        runs = list_literature_runs(project_id)
        if runs:
            newest_id = str(runs[0].get("run_id") or runs[0].get("query_hash") or "")
            newest = load_literature_run(project_id, newest_id)
            if newest is not None:
                return newest
        raise HTTPException(404, "No saved paper answer run was found for this project.")
    return payload


@router.post("/projects/{project_id}/paper-question-agent/related-works")
def post_project_related_works(project_id: str, body: RelatedWorksBody) -> dict[str, object]:
    parse_project(project_id)
    try:
        return submit_related_work_request(
            project_id,
            problem=body.problem.strip(),
            cluster_keys=body.cluster_keys,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(500, str(e)) from e


@router.get("/projects/{project_id}/related-works")
def get_project_related_works(project_id: str) -> dict[str, object]:
    parse_project(project_id)
    return {"items": list_related_work_for_project(project_id)}


@router.get("/related-works/{item_id}")
def get_related_work_queue_item(item_id: str) -> dict[str, object]:
    try:
        return get_related_work_item(item_id)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/related-works/{item_id}/claim")
def post_related_work_claim(item_id: str) -> dict[str, object]:
    try:
        item = claim_related_work_item(item_id)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    return {"ok": True, "item": item}


@router.patch("/related-works/{item_id}")
def patch_related_work_queue_item(item_id: str, body: RelatedWorksAnswerBody) -> dict[str, object]:
    try:
        item = answer_related_work_item(item_id, body.markdown)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "item": item}
