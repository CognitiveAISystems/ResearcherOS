"""Resolve per-project paths through discovered ``ProjectMount`` entries."""

from __future__ import annotations

from pathlib import Path

from koi.adapters.project_mount import get_mount_or_raise

PAPER_DIRNAME = "paper"
PAPER_REVIEWS_DIRNAME = "paper_reviews"


def koi_root(project_id: str) -> Path:
    return get_mount_or_raise(project_id).koi_root


def repo_root(project_id: str) -> Path:
    return get_mount_or_raise(project_id).repo_root


def code_root(project_id: str) -> Path:
    return get_mount_or_raise(project_id).code_root


def project_md(project_id: str) -> Path:
    return koi_root(project_id) / "project.md"


def research_json(project_id: str) -> Path:
    return koi_root(project_id) / "research.json"


def reports_dir(project_id: str) -> Path:
    return koi_root(project_id) / "reports"


def pages_dir(project_id: str) -> Path:
    return koi_root(project_id) / "pages"


def knowledge_path(project_id: str) -> Path:
    return koi_root(project_id) / "KNOWLEDGE.md"


def knowledge_dir(project_id: str) -> Path:
    return koi_root(project_id) / "knowledge"


def knowledge_log_path(project_id: str) -> Path:
    return koi_root(project_id) / "KNOWLEDGE_LOG.md"


def paper_dir(project_id: str) -> Path:
    return koi_root(project_id) / PAPER_DIRNAME


def paper_reviews_dir(project_id: str) -> Path:
    return koi_root(project_id) / PAPER_REVIEWS_DIRNAME


def literature_dir(project_id: str) -> Path:
    return koi_root(project_id) / "literature"


def paper_morphology_dir(project_id: str) -> Path:
    return koi_root(project_id) / "paper_morphology"


def paper_answers_dir(project_id: str) -> Path:
    return koi_root(project_id) / "paper_answers"


def agent_bundles_dir(project_id: str) -> Path:
    return koi_root(project_id) / "agent_bundles"
