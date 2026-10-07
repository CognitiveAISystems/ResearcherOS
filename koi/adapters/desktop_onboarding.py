"""First-run discovery and Git attachment for the desktop application."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from koi.adapters.desktop_workspace import set_workspace_root
from koi.adapters.project_install import install_project
from koi.adapters.project_mount import rescan_projects


DESKTOP_SYNC_BRANCH = "koi-project"
BRANCH_CANDIDATES = (DESKTOP_SYNC_BRANCH, "koi/research")


def _directory(raw: str) -> Path:
    try:
        path = Path(raw).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("Папка не найдена.") from exc
    if not path.is_dir():
        raise ValueError("Выберите папку.")
    return path


def _projects_in(root: Path) -> list[str]:
    names: set[str] = set()
    for tree_name in ("tree", ".tree"):
        tree = root / tree_name
        if tree.is_dir():
            for child in tree.iterdir():
                if child.is_dir() and (child / "koi-structure" / "project.md").is_file():
                    names.add(child.name)
    for child in root.iterdir():
        if child.name.startswith(".") or not child.is_dir() or child.name == "tree":
            continue
        if (child / "koi-structure" / "project.md").is_file() or (
            child / ".koi-sync-worktree" / "koi-structure" / "project.md"
        ).is_file():
            names.add(child.name)
    return sorted(names)


def inspect_existing_projects(raw: str) -> dict:
    """Accept a workspace, tree, project, or koi-structure folder selection."""
    selected = _directory(raw)
    for root in (selected, *list(selected.parents)[:3]):
        if root.name in {"tree", ".tree"}:
            root = root.parent
        projects = _projects_in(root)
        if projects:
            return {"workspace_root": str(root), "projects": projects}
    raise ValueError(
        "В этой папке нет проектов ResearcherOS. Выберите папку, "
        "в которой хранятся ваши исследования."
    )


def inspect_existing_tree(raw: str) -> dict:
    """Attach an already checked-out research tree without moving its files."""
    tree = _directory(raw)
    if tree.name not in {"tree", ".tree"}:
        raise ValueError("Выберите папку tree, в которой лежат проекты исследования.")
    projects = sorted(
        child.name for child in tree.iterdir()
        if child.is_dir() and (child / "koi-structure" / "project.md").is_file()
    )
    if not projects:
        raise ValueError("В этой папке tree не найдены проекты исследования.")
    return {"workspace_root": str(tree.parent), "tree_root": str(tree), "projects": projects}


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        timeout=15,
        check=False,
    )


def _branch_ref(repo: Path, branch: str) -> str | None:
    for ref in (f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"):
        if _git(repo, "show-ref", "--verify", "--quiet", ref).returncode == 0:
            return ref
    return None


def _fetch_research_branch_if_needed(repo: Path) -> None:
    if any(_branch_ref(repo, branch) for branch in BRANCH_CANDIDATES):
        return
    if _git(repo, "remote", "get-url", "origin").returncode != 0:
        return
    try:
        remote = _git(repo, "ls-remote", "--heads", "origin", *BRANCH_CANDIDATES)
    except subprocess.TimeoutExpired:
        return
    if remote.returncode != 0:
        return
    for branch in BRANCH_CANDIDATES:
        if not any(line.endswith(f"refs/heads/{branch}") for line in remote.stdout.splitlines()):
            continue
        try:
            fetched = _git(repo, "fetch", "origin", f"refs/heads/{branch}:refs/remotes/origin/{branch}")
        except subprocess.TimeoutExpired as exc:
            raise ValueError(f"Не удалось загрузить ветку {branch} из origin.") from exc
        if fetched.returncode != 0:
            raise ValueError(f"Не удалось загрузить ветку {branch} из origin.")


def inspect_git_project(raw: str) -> dict:
    repo = _directory(raw)
    try:
        top = _git(repo, "rev-parse", "--show-toplevel")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Не удалось проверить Git-репозиторий.") from exc
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != repo:
        raise ValueError("Выберите корневую папку Git-репозитория с кодом.")
    current = _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
    current_branch = current.stdout.strip() if current.returncode == 0 else None
    _fetch_research_branch_if_needed(repo)

    invalid_branch: str | None = None
    for branch in BRANCH_CANDIDATES:
        ref = _branch_ref(repo, branch)
        if ref is None:
            continue
        project = _git(repo, "cat-file", "-e", f"{ref}:koi-structure/project.md")
        if project.returncode != 0:
            invalid_branch = branch
            continue
        if current_branch == branch:
            raise ValueError(
                "Исследовательская ветка сейчас открыта в репозитории с кодом. "
                "Переключитесь на ветку с кодом и выберите репозиторий снова."
            )
        return {"repo_path": str(repo), "repo_name": repo.name, "branch": branch, "branch_exists": True}

    if invalid_branch:
        raise ValueError(
            f"В ветке {invalid_branch} нет материалов исследования. "
            "Проверьте репозиторий или выберите другой."
        )

    return {
        "repo_path": str(repo),
        "repo_name": repo.name,
        "branch": DESKTOP_SYNC_BRANCH,
        "branch_exists": False,
    }


def connect_git_project(
    repo_raw: str, workspace_raw: str, *, require_existing: bool | None = None
) -> dict:
    """Attach the selected code repo under a user-chosen research workspace."""
    project = inspect_git_project(repo_raw)
    if require_existing is not None and project["branch_exists"] != require_existing:
        if require_existing:
            raise ValueError("В выбранном репозитории нет исследовательской ветки. Выберите другой репозиторий.")
        raise ValueError("В выбранном репозитории уже есть исследовательская ветка. Вернитесь на предыдущий шаг.")
    repo = Path(project["repo_path"])
    requested_workspace = Path(workspace_raw).expanduser()
    if requested_workspace == Path.home() / "Documents":
        requested_workspace.mkdir(parents=True, exist_ok=True)
    workspace = _directory(str(requested_workspace))
    if workspace == repo or repo in workspace.parents:
        raise ValueError("Выберите папку для исследований вне Git-репозитория с кодом.")
    unfinished_koi = repo / "koi-structure"
    if unfinished_koi.exists() and not (unfinished_koi / "project.md").is_file():
        raise ValueError(
            "В репозитории уже есть папка koi-structure без проекта. "
            "Проверьте её содержимое перед подключением."
        )
    code_link = workspace / repo.name
    if code_link.exists() or code_link.is_symlink():
        if code_link.resolve() != repo:
            raise ValueError(f"В выбранной папке уже есть другой проект с именем {repo.name}.")
    elif repo.parent != workspace:
        try:
            code_link.symlink_to(repo, target_is_directory=True)
        except OSError as exc:
            raise ValueError("Не удалось создать ссылку на репозиторий в выбранной папке.") from exc

    result = install_project(
        repo,
        scan_root=workspace,
        sync_branch=project["branch"],
        push=False,
    )
    if not result.get("ok"):
        raise ValueError(result.get("message") or "Не удалось подключить проект.")
    set_workspace_root(workspace)
    rescan_projects()
    return {"workspace_root": str(workspace), "project": project, "install": result}
