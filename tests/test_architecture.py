"""Dependency-boundary checks for the transitional KOI package layout."""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRS = (
    ".cursor",
    "agents",
    "api",
    "hub",
    "koi",
    "scripts",
    "tests",
)
LEGACY_MODULES = {
    "koi.agent_backends",
    "koi.agent_chat_auto",
    "koi.agent_chat_format",
    "koi.agent_chat_inbox",
    "koi.agent_chat_queue",
    "koi.agent_chat_runner",
    "koi.agent_chat_worker_ctl",
    "koi.api_helpers",
    "koi.card_reports",
    "koi.done_research_queue",
    "koi.hooks_paths",
    "koi.md_io",
    "koi.migrate",
    "koi.models",
    "koi.programs",
    "koi.paper_generator",
    "koi.project_sync",
    "koi.project_sync_queue",
    "koi.repository",
    "koi.report_ingest",
    "koi.review_agent",
    "koi.review.analysis",
    "koi.research_store",
    "koi.rq_discoveries",
    "koi.rq_discoveries_feed",
    "koi.settings_store",
    "koi.workspace",
    "koi.application.live_queries",
    "koi.application.literature_commands",
    "koi.application.project_commands",
    "koi.application.project_views",
    "koi.application.report_commands",
    "koi.services.dag_layout",
    "koi.services.dag_suggest",
    "koi.services.card_live",
    "koi.services.cursor_app",
    "koi.services.cursor_usage",
    "koi.services.agent_chat_auto",
    "koi.services.agent_chat_format",
    "koi.services.agent_chat_inbox",
    "koi.services.agent_chat_runner",
    "koi.services.agent_chat_worker_ctl",
    "koi.services.knowledge",
    "koi.services.literature",
    "koi.services.paper_catalog",
    "koi.services.paper_comments",
    "koi.services.paper_generator",
    "koi.services.paper_inbox",
    "koi.services.paper_page_counts",
    "koi.services.paper_runner",
    "koi.services.report_ingest",
    "koi.services.related_work",
    "koi.services.related_work_inbox",
    "koi.services.review",
    "koi.services.review_agent",
    "koi.services.rq_discoveries",
    "koi.services.composite",
    "koi.services.programs",
}


def _imported_modules(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported_modules: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported = [node.module] if node.module else []
            if node.module:
                imported.extend(f"{node.module}.{alias.name}" for alias in node.names)
        else:
            continue
        imported_modules.extend(
            (node.lineno, module) for module in imported if module
        )
    return imported_modules


def test_internal_code_uses_canonical_koi_imports() -> None:
    legacy_names = {
        path.stem
        for path in (ROOT / "koi").glob("*.py")
        if path.name != "__init__.py"
    }
    legacy_modules = {f"koi.{name}" for name in legacy_names}
    legacy_modules.update(LEGACY_MODULES)
    violations: list[str] = []

    for directory in SOURCE_DIRS:
        for path in (ROOT / directory).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            for lineno, module in _imported_modules(path):
                if any(
                    module == legacy or module.startswith(f"{legacy}.")
                    for legacy in legacy_modules
                ):
                    relative = path.relative_to(ROOT)
                    violations.append(f"{relative}:{lineno}: {module}")

    assert not violations, (
        "Use canonical KOI package imports instead of compatibility modules:\n"
        + "\n".join(violations)
    )


def test_foundation_layers_do_not_import_capabilities() -> None:
    forbidden_for_core = ("koi.adapters", "koi.application", "koi.services")
    forbidden_for_adapters = (
        "koi.agent_chat",
        "koi.application",
        "koi.cursor",
        # repository.save_project still refreshes the derived knowledge artifact.
        # This known exception needs save orchestration before it can be removed.
        "koi.laboratory",
        "koi.literature",
        "koi.paper",
        "koi.projects",
        "koi.related_work",
        "koi.review",
        "koi.services",
    )
    violations: list[str] = []

    for layer, forbidden in (("core", forbidden_for_core), ("adapters", forbidden_for_adapters)):
        for path in (ROOT / "koi" / layer).rglob("*.py"):
            for lineno, module in _imported_modules(path):
                if any(module == prefix or module.startswith(f"{prefix}.") for prefix in forbidden):
                    violations.append(f"{path.relative_to(ROOT)}:{lineno}: {module}")

    assert not violations, (
        "Foundation layers must not depend on application capabilities:\n"
        + "\n".join(violations)
    )


def test_sync_adapters_do_not_import_project_discovery_workflows() -> None:
    adapter_paths = (
        ROOT / "koi/adapters/project_sync.py",
        ROOT / "koi/adapters/project_sync_queue.py",
    )
    forbidden = ("koi.projects", "koi.services.rq_discoveries")
    violations: list[str] = []

    for path in adapter_paths:
        for lineno, module in _imported_modules(path):
            if any(
                module == prefix or module.startswith(f"{prefix}.")
                for prefix in forbidden
            ):
                violations.append(f"{path.relative_to(ROOT)}:{lineno}: {module}")

    assert not violations, (
        "Sync adapters must receive discovery behavior from project orchestration:\n"
        + "\n".join(violations)
    )


def test_repository_adapter_does_not_import_laboratory_policy() -> None:
    path = ROOT / "koi/adapters/repository.py"
    forbidden = ("koi.laboratory", "koi.services.programs")
    violations = [
        f"{path.relative_to(ROOT)}:{lineno}: {module}"
        for lineno, module in _imported_modules(path)
        if any(
            module == prefix or module.startswith(f"{prefix}.")
            for prefix in forbidden
        )
    ]

    assert not violations, (
        "Repository adapter must return stored project data without laboratory policy:\n"
        + "\n".join(violations)
    )


def test_scripts_contains_only_bootstrap_entrypoints() -> None:
    scripts = {
        path.name for path in (ROOT / "scripts").iterdir() if path.is_file()
    }

    assert scripts == {"koi-install-tectonic.sh", "koi-serve.sh"}


def test_cli_entrypoints_are_importable() -> None:
    modules = (
        "api.web_proxy",
        "koi.agent_chat.cli",
        "koi.agent_chat.inbox_cli",
        "koi.agent_chat.worker",
        "koi.cursor.widget",
        "koi.widgets.base.cli",
        "koi.paper.cli",
        "koi.paper.inbox_cli",
        "koi.projects.done_research_cli",
        "koi.projects.report_ingest.cli",
        "koi.projects.sync_cli",
        "koi.related_work.cli",
        "koi.related_work.inbox_cli",
    )

    for module_name in modules:
        assert callable(import_module(module_name).main)
