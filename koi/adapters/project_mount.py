"""Discover KOI projects via ``koi-structure/project.md``.

Canonical workspace layout (scan root = parent of engine)::

    workspace/
    ├── ReseachOS/                         # engine
    ├── tree/
    │   └── <repo>/koi-structure/          # sync branch koi/research (worktree)
    └── <repo>/                            # code, any branch

Legacy layouts still discovered:

- ``<repo>/koi-structure/``
- ``<repo>/.koi-sync-worktree/koi-structure/``
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ENGINE_ROOT = Path(__file__).resolve().parent.parent.parent

log = logging.getLogger(__name__)

KOI_STRUCTURE_DIR = "koi-structure"
PROJECT_MD = "project.md"
TREE_DIR = "tree"
DESKTOP_TREE_DIR = ".tree"

_SKIP_DIR_NAMES = frozenset(
    {
        "ReseachOS",
        "koi-workspace",
        TREE_DIR,
        "node_modules",
        ".venv",
        ".git",
        ".tools",
    }
)


DEFAULT_SYNC_BRANCH = "koi/research"
WORKTREE_DIR = ".koi-sync-worktree"
BOOTSTRAP_WORKTREE_DIR = ".koi-sync-bootstrap"


@dataclass(frozen=True)
class ProjectMount:
    project_id: str
    repo_root: Path
    koi_root: Path
    code_root: Path
    programs: tuple[str, ...]
    git_repo: bool = False
    git_sync_branch: str | None = None


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta = yaml.safe_load(parts[1]) or {}
    return meta, parts[2].lstrip("\n")


def _parse_programs(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (raw,)
    out: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            pid = item.get("id")
            if pid:
                out.append(str(pid))
        elif item:
            out.append(str(item))
    return tuple(out)


def is_under_tree(path: Path) -> bool:
    return bool({TREE_DIR, DESKTOP_TREE_DIR} & set(path.resolve().parts))


def tree_dir_for(scan_root: Path) -> Path:
    return scan_root.resolve() / TREE_DIR


def tree_worktree_for(scan_root: Path, repo_name: str) -> Path:
    return tree_dir_for(scan_root) / repo_name


def tree_koi_for(scan_root: Path, repo_name: str) -> Path:
    return tree_worktree_for(scan_root, repo_name) / KOI_STRUCTURE_DIR


def primary_scan_root() -> Path:
    roots = scan_roots()
    if not roots:
        raise RuntimeError("No scan roots configured")
    return roots[0]


def sync_worktree_path(mount: ProjectMount) -> Path:
    """Directory that holds the orphan sync-branch checkout."""
    if is_under_tree(mount.koi_root):
        return mount.koi_root.parent
    scan = mount.repo_root.parent
    tree_wt = tree_worktree_for(scan, mount.repo_root.name)
    if tree_wt.is_dir() and (tree_wt / ".git").exists():
        return tree_wt
    return mount.repo_root / WORKTREE_DIR


def _resolve_code_root(repo_root: Path, koi_root: Path, meta: dict[str, Any]) -> Path:
    raw = meta.get("code_root")
    if raw:
        p = Path(str(raw))
        if p.is_absolute():
            return p.resolve()
        return (koi_root / p).resolve()
    if is_under_tree(koi_root):
        projectcode = repo_root / "projectcode"
        if projectcode.is_dir():
            return projectcode.resolve()
        return repo_root.resolve()
    projectcode = repo_root / "projectcode"
    if projectcode.is_dir():
        return projectcode.resolve()
    return repo_root.resolve()


def scan_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    # The desktop shell chooses this folder during first run.  It takes
    # precedence so create-project and agent operations share the same home.
    from koi.adapters.desktop_workspace import selected_workspace_root

    selected = selected_workspace_root()
    if selected is not None:
        roots.append(selected)
    default = ENGINE_ROOT.parent.resolve()
    roots.append(default)
    extra = os.environ.get("KOI_SCAN_ROOTS", "").strip()
    if extra:
        for part in extra.split(","):
            part = part.strip()
            if part:
                roots.append(Path(part).expanduser().resolve())
    seen: set[Path] = set()
    unique: list[Path] = []
    for root in roots:
        if root not in seen and root.is_dir():
            seen.add(root)
            unique.append(root)
    return tuple(unique)


def _iter_repo_candidates(root: Path) -> list[Path]:
    if root.resolve() == ENGINE_ROOT.resolve():
        return []
    out: list[Path] = []
    try:
        children = sorted(root.iterdir())
    except OSError:
        return out
    for child in children:
        if not child.is_dir():
            continue
        name = child.name
        if name.startswith(".") or name in _SKIP_DIR_NAMES:
            continue
        if child.resolve() == ENGINE_ROOT.resolve():
            continue
        out.append(child)
    return out


def _parse_git_repo(meta: dict[str, Any]) -> bool:
    raw = meta.get("git_repo")
    if raw is None:
        return False
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _parse_git_sync_branch(meta: dict[str, Any], *, git_repo: bool) -> str | None:
    if not git_repo:
        return None
    raw = meta.get("git_sync_branch")
    if raw is not None and str(raw).strip():
        return str(raw).strip()
    return DEFAULT_SYNC_BRANCH


def _mount_from_paths(
    *,
    project_id: str,
    repo_root: Path,
    koi_root: Path,
    meta: dict[str, Any],
) -> ProjectMount:
    git_repo = _parse_git_repo(meta)
    using_legacy_wt = WORKTREE_DIR in koi_root.parts
    code_anchor = repo_root if (using_legacy_wt or is_under_tree(koi_root)) else koi_root
    return ProjectMount(
        project_id=project_id,
        repo_root=repo_root.resolve(),
        koi_root=koi_root.resolve(),
        code_root=_resolve_code_root(repo_root, code_anchor, meta),
        programs=_parse_programs(meta.get("programs")),
        git_repo=git_repo,
        git_sync_branch=_parse_git_sync_branch(meta, git_repo=git_repo),
    )


def _try_add_mount(
    mounts: dict[str, ProjectMount],
    *,
    repo_root: Path,
    koi_root: Path,
) -> None:
    md_path = koi_root / PROJECT_MD
    try:
        text = md_path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("Cannot read %s: %s", md_path, exc)
        return
    meta, _ = _split_frontmatter(text)
    project_id = str(meta.get("id") or repo_root.name)
    if project_id in mounts:
        log.warning(
            "Duplicate project id %r (%s vs %s); keeping first",
            project_id,
            mounts[project_id].repo_root,
            repo_root,
        )
        return
    mounts[project_id] = _mount_from_paths(
        project_id=project_id,
        repo_root=repo_root,
        koi_root=koi_root,
        meta=meta,
    )


def _iter_mount_candidates(scan_root: Path) -> list[tuple[Path, Path]]:
    """Yield ``(repo_root, koi_root)`` pairs under a scan root.

    Pickup rules for each immediate child of ``scan_root``:

    - if the folder is named ``tree`` → look one level deeper for
      ``tree/<name>/koi-structure/project.md`` (canonical);
    - otherwise → legacy ``<name>/koi-structure`` or
      ``<name>/.koi-sync-worktree/koi-structure``.
    """
    if scan_root.resolve() == ENGINE_ROOT.resolve():
        return []

    try:
        children = sorted(scan_root.iterdir())
    except OSError:
        return []

    pairs: list[tuple[Path, Path]] = []
    claimed_names: set[str] = set()

    # 1) Research worktrees: canonical tree/ and macOS Documents/.tree/.
    for child in children:
        if not child.is_dir() or child.name not in {TREE_DIR, DESKTOP_TREE_DIR}:
            continue
        try:
            projects = sorted(child.iterdir())
        except OSError:
            continue
        for proj in projects:
            if not proj.is_dir() or proj.name.startswith("."):
                continue
            koi = proj / KOI_STRUCTURE_DIR
            if not (koi / PROJECT_MD).is_file():
                continue
            code_sibling = scan_root / proj.name
            repo_root = code_sibling if code_sibling.is_dir() else proj
            pairs.append((repo_root, koi))
            claimed_names.add(proj.name)

    # 2) Legacy siblings (skipped when already claimed via tree/)
    for child in children:
        if not child.is_dir():
            continue
        name = child.name
        if name.startswith(".") or name in _SKIP_DIR_NAMES:
            continue
        if child.resolve() == ENGINE_ROOT.resolve():
            continue
        if name in claimed_names:
            continue
        koi: Path | None = None
        in_repo = child / KOI_STRUCTURE_DIR
        if (in_repo / PROJECT_MD).is_file():
            koi = in_repo
        else:
            wt_koi = child / WORKTREE_DIR / KOI_STRUCTURE_DIR
            if (wt_koi / PROJECT_MD).is_file():
                koi = wt_koi
        if koi is None:
            continue
        pairs.append((child, koi))
        claimed_names.add(name)

    return pairs


def discover_projects() -> list[ProjectMount]:
    mounts: dict[str, ProjectMount] = {}
    for root in scan_roots():
        for repo_root, koi_root in _iter_mount_candidates(root):
            _try_add_mount(mounts, repo_root=repo_root, koi_root=koi_root)
    return sorted(mounts.values(), key=lambda m: m.project_id)


@lru_cache(maxsize=1)
def _mount_index() -> dict[str, ProjectMount]:
    return {m.project_id: m for m in discover_projects()}


def rescan_projects() -> None:
    """Clear cached discovery (call after creating or attaching a project)."""
    _mount_index.cache_clear()


def list_mounts() -> list[ProjectMount]:
    return sorted(_mount_index().values(), key=lambda m: m.project_id)


def get_mount(project_id: str) -> ProjectMount | None:
    return _mount_index().get(project_id)


def get_mount_or_raise(project_id: str) -> ProjectMount:
    mount = get_mount(project_id)
    if mount is None:
        raise KeyError(f"Project not found: {project_id}")
    return mount


def repo_folder_name(title: str) -> str:
    """Filesystem folder name for a new project repo (sibling of engine)."""
    s = title.strip()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"[\s-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return (s[:48] or "project").lower()


__all__ = [
    "BOOTSTRAP_WORKTREE_DIR",
    "DEFAULT_SYNC_BRANCH",
    "ENGINE_ROOT",
    "KOI_STRUCTURE_DIR",
    "PROJECT_MD",
    "ProjectMount",
    "TREE_DIR",
    "WORKTREE_DIR",
    "discover_projects",
    "get_mount",
    "get_mount_or_raise",
    "is_under_tree",
    "list_mounts",
    "primary_scan_root",
    "repo_folder_name",
    "rescan_projects",
    "scan_roots",
    "sync_worktree_path",
    "tree_dir_for",
    "tree_koi_for",
    "tree_worktree_for",
]
