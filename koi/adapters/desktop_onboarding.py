"""First-run discovery and Git attachment for the desktop application."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import yaml

from koi.adapters.desktop_workspace import recent_workspace_roots, set_workspace_root
from koi.adapters.project_install import install_project
from koi.adapters.project_mount import rescan_projects
from koi.core.md_io import parse_project_md


DESKTOP_SYNC_BRANCH = "koi-project"
BRANCH_CANDIDATES = (DESKTOP_SYNC_BRANCH, "koi/research")


def _research_branch(branch: str) -> bool:
    return branch in BRANCH_CANDIDATES or bool(re.fullmatch(r"koi/research-(?:[2-9]|[1-9]\d+)", branch))


def find_existing_trees() -> list[dict]:
    """Try known locations, without crawling the person's disk."""
    roots = [*recent_workspace_roots(), Path.home() / "Documents"]
    found: dict[str, dict] = {}
    for root in roots:
        for name in ("tree", ".tree"):
            try:
                tree = inspect_existing_tree(str(root / name))
            except (ValueError, OSError):
                continue
            found[tree["tree_root"]] = tree
    return list(found.values())


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
    if _git(repo, "remote", "get-url", "origin").returncode != 0:
        return
    try:
        remote = _git(repo, "ls-remote", "--heads", "origin", *BRANCH_CANDIDATES, "koi/research-*")
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Не удалось проверить исследовательские ветки в удалённом репозитории (origin). Проверьте подключение и доступ к репозиторию, затем повторите выбор.") from exc
    if remote.returncode != 0:
        raise ValueError("Не удалось проверить исследовательские ветки в удалённом репозитории (origin). Проверьте подключение и доступ к репозиторию, затем повторите выбор.")
    for line in remote.stdout.splitlines():
        branch = line.split()[-1].removeprefix("refs/heads/")
        if not _research_branch(branch):
            continue
        remote_ref = f"refs/remotes/origin/{branch}"
        if _git(repo, "rev-parse", "--verify", remote_ref).stdout.strip() == line.split()[0]:
            continue
        try:
            fetched = _git(repo, "fetch", "origin", f"refs/heads/{branch}:refs/remotes/origin/{branch}")
        except subprocess.TimeoutExpired as exc:
            raise ValueError(f"Не удалось загрузить ветку {branch} из origin.") from exc
        if fetched.returncode != 0:
            raise ValueError(f"Не удалось загрузить ветку {branch} из origin.")


def inspect_git_project(raw: str, *, fetch_remote: bool = True) -> dict:
    repo = _directory(raw)
    try:
        top = _git(repo, "rev-parse", "--show-toplevel")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Не удалось проверить Git-репозиторий.") from exc
    if top.returncode != 0:
        raise ValueError("Эта папка пока не является Git-репозиторием. Создайте репозиторий и первый коммит или клонируйте существующий, затем выберите его снова.")
    if Path(top.stdout.strip()).resolve() != repo:
        raise ValueError("Выберите корневую папку Git-репозитория с кодом.")
    if _git(repo, "rev-parse", "--verify", "HEAD").returncode != 0:
        raise ValueError("В репозитории ещё нет коммитов. Сделайте первый коммит и выберите репозиторий снова.")
    current = _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
    current_branch = current.stdout.strip() if current.returncode == 0 else None
    if fetch_remote:
        _fetch_research_branch_if_needed(repo)

    refs = _git(repo, "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes/origin").stdout.splitlines()
    branches = {ref.removeprefix("refs/heads/").removeprefix("refs/remotes/origin/") for ref in refs}
    branches = {branch for branch in branches if _research_branch(branch)}
    ordered = [branch for branch in BRANCH_CANDIDATES if branch in branches]
    ordered += sorted(branches - set(BRANCH_CANDIDATES), key=lambda branch: int(branch.rsplit("-", 1)[1]))
    worktrees: dict[str, Path] = {}
    for block in _git(repo, "worktree", "list", "--porcelain").stdout.split("\n\n"):
        fields = dict(line.split(" ", 1) for line in block.splitlines() if " " in line)
        if "worktree" in fields and "branch" in fields:
            worktrees[fields["branch"].removeprefix("refs/heads/")] = Path(fields["worktree"])
    trees = []
    invalid_branch: str | None = None
    for branch in ordered:
        ref = _branch_ref(repo, branch)
        if ref is None:
            continue
        project = _git(repo, "show", f"{ref}:koi-structure/project.md")
        if project.returncode != 0:
            invalid_branch = branch
            continue
        if current_branch == branch:
            raise ValueError(
                "Исследовательская ветка сейчас открыта в репозитории с кодом. "
                "Переключитесь на ветку с кодом и выберите репозиторий снова."
            )
        working = worktrees.get(branch)
        content = project.stdout
        if working and (working / "koi-structure" / "project.md").is_file():
            content = (working / "koi-structure" / "project.md").read_text(encoding="utf-8")
        try:
            parsed = parse_project_md(content, project_id=repo.name)
        except (ValueError, TypeError, AttributeError, yaml.YAMLError):
            invalid_branch = branch
            continue
        tree = {"branch": branch, "title": parsed.title, "nodes": [
            {"id": node.id, "parent_id": node.parent_id, "type": node.node_type.value,
             "title": node.title, "description": node.description}
            for node in parsed.nodes
        ]}
        if working and working.parent.name in {"tree", ".tree"}:
            tree["worktree_path"] = str(working)
        trees.append(tree)

    if invalid_branch and not trees:
        raise ValueError(
            f"В ветке {invalid_branch} нет материалов исследования. "
            "Проверьте репозиторий или выберите другой."
        )

    number = 2
    while f"koi/research-{number}" in branches:
        number += 1
    return {
        "repo_path": str(repo),
        "repo_name": repo.name,
        "branch": trees[0]["branch"] if trees else DESKTOP_SYNC_BRANCH,
        "branch_exists": bool(trees),
        "trees": trees,
        "next_branch": f"koi/research-{number}",
    }


def new_tree_name(repo: Path, branch: str | None) -> str | None:
    if branch is None:
        return None
    if not _research_branch(branch) or branch in BRANCH_CANDIDATES:
        raise ValueError("Не удалось выбрать ветку для нового дерева. Выберите репозиторий снова.")
    if _branch_ref(repo, branch):
        raise ValueError("Эта исследовательская ветка уже существует. Выберите репозиторий снова, чтобы обновить список деревьев.")
    return f"{repo.name}-{branch.rsplit('-', 1)[1]}"


def connect_git_project(
    repo_raw: str, workspace_raw: str, *, require_existing: bool | None = None, branch: str | None = None
) -> dict:
    """Attach the selected code repo under a user-chosen research workspace."""
    project = inspect_git_project(repo_raw)
    repo = Path(project["repo_path"])
    tree_name = None
    if branch is not None:
        if require_existing is False:
            tree_name = new_tree_name(repo, branch)
            project = {**project, "branch": branch, "branch_exists": False}
        else:
            if branch not in {tree["branch"] for tree in project["trees"]}:
                raise ValueError("Выберите дерево для продолжения.")
            project = {**project, "branch": branch}
            if branch not in BRANCH_CANDIDATES:
                tree_name = f"{repo.name}-{branch.rsplit('-', 1)[1]}"
    if require_existing is not None and project["branch_exists"] != require_existing:
        if require_existing:
            raise ValueError("В выбранном репозитории нет исследовательской ветки. Выберите другой репозиторий.")
        raise ValueError("В выбранном репозитории уже есть исследовательская ветка. Вернитесь на предыдущий шаг.")
    existing = next((tree for tree in project["trees"] if tree["branch"] == project["branch"]), None)
    if project["branch_exists"] and existing and existing.get("worktree_path"):
        working = Path(existing["worktree_path"])
        workspace_raw = str(working.parent.parent)
        tree_name = working.name if working.name != repo.name else None
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
    target = workspace / "tree" / (tree_name or repo.name)
    if target.exists() and any(target.iterdir()):
        if not project["branch_exists"]:
            raise ValueError(f"Папка для нового дерева уже занята. Выберите репозиторий снова или освободите папку {target}.")
        target_git = _git(target, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
        repo_git = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
        if target_git != repo_git or _git(target, "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip() != project["branch"]:
            raise ValueError("В этой папке уже открыто другое дерево. Выберите папку tree, чтобы продолжить работу в нём.")
    code_link = workspace / (tree_name or repo.name)
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
        tree_name=tree_name,
    )
    if not result.get("ok"):
        raise ValueError(result.get("message") or "Не удалось подключить проект.")
    set_workspace_root(workspace)
    rescan_projects()
    project_id = parse_project_md((Path(result["tree_koi"]) / "project.md").read_text(encoding="utf-8")).id
    return {"workspace_root": str(workspace), "project_id": project_id, "project": project, "install": result}
