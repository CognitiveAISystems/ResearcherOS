"""Pydantic request/response bodies for the HTTP API."""

from __future__ import annotations

from typing import Optional, Literal

from pydantic import BaseModel, Field

from koi.core.models import NodeType, ResearchQuestionCertainty


class CreateProjectBody(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""
    tag: str = Field(min_length=1, max_length=48)
    program_id: Optional[str] = None
    program_title: Optional[str] = None


class DesktopWorkspaceBody(BaseModel):
    workspace_root: str = Field(min_length=1)


class CreateProgramBody(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""


class CreateNodeBody(BaseModel):
    parent_id: str
    node_type: NodeType
    title: str = Field(min_length=1)
    description: str = ""


class ResearchQuestionBody(BaseModel):
    id: Optional[str] = None
    question: str = Field(min_length=1)
    answer: str = ""
    narrative: str = ""
    certainty: ResearchQuestionCertainty = ResearchQuestionCertainty.DEFINITE
    importance: int = Field(default=3, ge=1, le=5)
    card_id: Optional[str] = None


class UpdateNodeBody(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    research_questions: Optional[list[ResearchQuestionBody]] = None


class UpdateTagBody(BaseModel):
    name: str
    color: str


class UpdateCardBody(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    column_id: Optional[str] = None
    tags: Optional[list[str]] = None
    depends_on: Optional[list[str]] = None
    pinned: Optional[bool] = None


class CreateCardBody(BaseModel):
    column_id: str = "backlog"
    title: str = Field(min_length=1)
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)


class CardReportBody(BaseModel):
    content: str = ""


class BoardPayload(BaseModel):
    id: str
    owner_node_id: str
    columns: list
    cards: list


class LiteratureSearchBody(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)


class LibraryDiscoverBody(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)


class ReviewSetBody(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)
    papers: list[dict] = Field(default_factory=list)


class ProjectPaperReviewBody(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)
    papers: list[dict] = Field(default_factory=list)


class ReviewAgentBody(BaseModel):
    query: Optional[str] = None
    limit: int = Field(default=10, ge=1, le=50)
    refresh: bool = False
    download_pdfs: bool = True
    papers: list[dict] = Field(default_factory=list)


class PaperQuestionAgentBody(BaseModel):
    question: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)
    refresh: bool = False
    download_pdfs: bool = True
    papers: list[dict] = Field(default_factory=list)


class LiteratureClusterBody(BaseModel):
    question: str = Field(min_length=1)
    refresh: bool = False
    download_pdfs: bool = True
    papers: list[dict] = Field(default_factory=list)


class MorphologyStageBody(BaseModel):
    paper: dict = Field(default_factory=dict)


class MorphologyExplainBody(BaseModel):
    prompt: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    node_id: str = Field(min_length=1)


class MortalCombatStageBody(BaseModel):
    primary: dict = Field(default_factory=dict)
    reviewer: dict = Field(default_factory=dict)
    question: str = ""


class RelatedWorksAnswerBody(BaseModel):
    markdown: str = Field(min_length=1)


class RelatedWorksBody(BaseModel):
    problem: str = Field(min_length=1)
    cluster_keys: list[str] = Field(default_factory=list)


class TranslateToEnglishBody(BaseModel):
    text: str = Field(min_length=1)


class ZoteroConnectBody(BaseModel):
    api_key: str = Field(min_length=1)
    user_id: Optional[str] = None


class ZoteroCollectionsBody(BaseModel):
    api_key: str = Field(min_length=1)
    user_id: Optional[str] = None


class ZoteroImportBody(BaseModel):
    api_key: str = Field(min_length=1)
    user_id: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=100)
    collection_key: Optional[str] = None


class AgentChatBody(BaseModel):
    project_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    method_id: Optional[str] = None
    node_id: Optional[str] = None
    purpose: Literal["question", "report_grill", "grill_me", "make_report"] = "question"
    board_id: Optional[str] = None
    card_id: Optional[str] = None
    report_markdown: str = Field(default="", max_length=200000)


class AgentChatAnswerBody(BaseModel):
    answer: str = Field(min_length=1)


class CursorApiKeyBody(BaseModel):
    cursor_api_key: str = ""


class AgentChatSettingsBody(BaseModel):
    agent_chat_mode: Optional[str] = None
    cursor_api_key: Optional[str] = None


class InboxConfiguredBody(BaseModel):
    configured: bool = True
    inbox_kind: str = "chat"
