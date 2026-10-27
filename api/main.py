"""FastAPI application — thin HTTP layer over koi services."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import agents, collaboration, composites, cursor, desktop, knowledge, library, meta, morphology, pages, paper, programs, projects, review, sync, voice, widgets

app = FastAPI(
    title="KOI API",
    description="Agile for Science — hypothesis tree + kanban, persisted as Markdown",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (
    meta.router,
    library.router,
    programs.router,
    composites.router,
    projects.router,
    pages.router,
    knowledge.router,
    paper.router,
    collaboration.router,
    review.router,
    morphology.router,
    agents.router,
    voice.router,
    cursor.router,
    desktop.router,
    sync.router,
    widgets.router,
):
    app.include_router(router)


@app.on_event("startup")
def _startup() -> None:
    from koi.adapters.project_discovery_watch import start_project_discovery_watch
    from koi.adapters.settings_store import load_env_file

    load_env_file()
    from koi.adapters.agent_chat_queue import _load, submit_answer
    for item in _load():
        if item.get("conversation_id") and item.get("status") in ("pending", "processing"):
            submit_answer(item["id"], "Запуск прерван перезапуском приложения. Продолжите работу новым сообщением.", answer_kind="warning")
    start_project_discovery_watch()
    from koi.agent_chat.git_changes import start as start_git_changes

    start_git_changes()
    from koi.projects.done_research_auto import kick_recent

    kick_recent()
    from koi.agent_chat.setup_pipeline import resume_pending

    resume_pending()


@app.on_event("shutdown")
def _shutdown() -> None:
    from koi.adapters.project_discovery_watch import stop_project_discovery_watch

    stop_project_discovery_watch()
    from koi.agent_chat.git_changes import stop as stop_git_changes

    stop_git_changes()
    from koi.paper.collaboration.session import shutdown_all_sessions

    shutdown_all_sessions()
