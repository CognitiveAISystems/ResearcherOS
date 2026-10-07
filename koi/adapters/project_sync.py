"""Git sync for project ``koi-structure/`` via dedicated orphan branches."""

from __future__ import annotations

import shutil
import subprocess
import tarfile
import io
import os
from pathlib import Path
from typing import Callable

from koi.adapters.project_mount import (
    BOOTSTRAP_WORKTREE_DIR,
    DEFAULT_SYNC_BRANCH,
    KOI_STRUCTURE_DIR,
    WORKTREE_DIR,
    ProjectMount,
    get_mount,
    is_under_tree,
    list_mounts,
    sync_worktree_path,
)
from koi.adapters.project_sync_queue import (
    list_pending_push,
    load_state,
    should_periodic_pull,
    touch_pull_check,
)

KOI_STRUCTURE_PREFIX = "koi-structure/"
GIT_COMMAND_TIMEOUT_SEC = 30
RefChangeDiscovery = Callable[[str, str, Path], list[dict]]


def _run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=GIT_COMMAND_TIMEOUT_SEC,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            ["git", *args],
            124,
            stdout=exc.stdout or "",
            stderr=(exc.stderr or "")
            + f"git command timed out after {GIT_COMMAND_TIMEOUT_SEC}s",
        )


def _git_error(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or "git command failed").strip()


def _is_git_repo(path: Path) -> bool:
    return (path / ".git").exists()


def _koi_rel(mount: ProjectMount) -> str:
    """Path of koi-structure relative to the git cwd that owns it."""
    try:
        return mount.koi_root.relative_to(mount.repo_root).as_posix()
    except ValueError:
        # tree/<repo>/koi-structure — lives outside the code working tree
        return KOI_STRUCTURE_DIR


def _koi_git_cwd(mount: ProjectMount) -> Path:
    """Directory where ``git status`` / checkout for koi-structure should run."""
    if is_under_tree(mount.koi_root):
        return sync_worktree_path(mount)
    return mount.repo_root


def _path_under(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def sync_mounts() -> list[ProjectMount]:
    mounts: list[ProjectMount] = []
    for mount in list_mounts():
        if not mount.git_repo or not mount.git_sync_branch:
            continue
        if not _is_git_repo(mount.repo_root):
            continue
        mounts.append(mount)
    return mounts


def _repo_git_roots() -> list[Path]:
    roots: list[Path] = []
    for mount in sync_mounts():
        if mount.repo_root not in roots:
            roots.append(mount.repo_root)
    return roots


def git_available() -> bool:
    return bool(_repo_git_roots())


def _fetch_branch(repo: Path, branch: str) -> subprocess.CompletedProcess[str]:
    return _run_git(repo, "fetch", "--quiet", "origin", branch)


def _resolve_sync_ref(repo: Path, branch: str, *, fetch: bool = True) -> str | None:
    """Return tip SHA for origin/<branch> (preferred) or local <branch>."""
    if fetch:
        _fetch_branch(repo, branch)
    for ref in (f"origin/{branch}", branch):
        r = _run_git(repo, "rev-parse", "--verify", ref)
        if r.returncode == 0:
            return r.stdout.strip()
    return None


def _remote_sync_ref(repo: Path, branch: str) -> str | None:
    return _resolve_sync_ref(repo, branch, fetch=True)


def _local_worktree_ref(repo: Path, branch: str) -> str | None:
    r = _run_git(repo, "rev-parse", "--verify", branch)
    if r.returncode == 0:
        return r.stdout.strip()
    return None


def _ahead_behind(repo: Path, local: str | None, remote: str | None) -> tuple[int, int]:
    if not local or not remote:
        return 0, 0
    counts = _run_git(repo, "rev-list", "--left-right", "--count", f"{local}...{remote}")
    if counts.returncode != 0:
        return 0, 0
    parts = counts.stdout.strip().split()
    if len(parts) != 2:
        return 0, 0
    return int(parts[0]), int(parts[1])


def _sync_branch_counts(
    repo: Path, branch: str, *, fetch: bool = True
) -> tuple[int, int]:
    """Return (ahead, behind) for local worktree branch vs origin."""
    local = _local_worktree_ref(repo, branch)
    remote = _resolve_sync_ref(repo, branch, fetch=fetch)
    return _ahead_behind(repo, local, remote)


def _dirty_koi_paths(mount: ProjectMount) -> list[str]:
    cwd = _koi_git_cwd(mount)
    if not cwd.is_dir():
        return []
    koi_rel = _koi_rel(mount)
    st = _run_git(
        cwd,
        "status",
        "--porcelain",
        "--ignore-submodules=dirty",
        "--",
        koi_rel,
    )
    if st.returncode != 0:
        return []
    paths: list[str] = []
    prefix = f"{mount.repo_root.name}/"
    for line in st.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if path == koi_rel or path.startswith(f"{koi_rel}/"):
            paths.append(f"{prefix}{path}")
    return paths


def project_dirty_paths() -> list[str]:
    paths: list[str] = []
    for mount in sync_mounts():
        paths.extend(_dirty_koi_paths(mount))
    return paths


def _mount_summary(mount: ProjectMount, *, fetch: bool = True) -> dict:
    repo = mount.repo_root
    branch = mount.git_sync_branch or DEFAULT_SYNC_BRANCH
    if fetch:
        _fetch_branch(repo, branch)
    code_branch = _run_git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    local_ref = _local_worktree_ref(repo, branch)
    remote_ref = _resolve_sync_ref(repo, branch, fetch=False)
    ahead, behind = _ahead_behind(repo, local_ref, remote_ref)
    dirty = _dirty_koi_paths(mount)
    return {
        "project_id": mount.project_id,
        "repo_root": str(repo),
        "code_branch": code_branch,
        "sync_branch": branch,
        "sync_remote_ref": remote_ref,
        "sync_local_ref": local_ref,
        "ahead": ahead,
        "behind": behind,
        "dirty_koi_paths": dirty,
        "koi_path": _koi_rel(mount),
    }


def git_summary(*, project_id: str | None = None, fetch: bool = True) -> dict:
    mounts = sync_mounts()
    if project_id:
        mounts = [m for m in mounts if m.project_id == project_id]
    if not mounts:
        return {"ok": False, "error": "no git-sync projects discovered"}

    if len(mounts) == 1:
        projects = [_mount_summary(mounts[0], fetch=fetch)]
    else:
        from concurrent.futures import ThreadPoolExecutor

        workers = min(8, len(mounts))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            projects = list(
                pool.map(lambda m: _mount_summary(m, fetch=fetch), mounts)
            )
    first = projects[0]
    pending = list_pending_push()
    state = load_state()
    total_ahead = sum(int(p.get("ahead") or 0) for p in projects)
    total_behind = sum(int(p.get("behind") or 0) for p in projects)

    return {
        "ok": True,
        "projects": projects,
        "branch": first["sync_branch"],
        "code_branch": first["code_branch"],
        "upstream": f"origin/{first['sync_branch']}",
        "ahead": total_ahead,
        "behind": total_behind,
        "dirty_project_paths": project_dirty_paths(),
        "pending_push": pending,
        "last_pull_at": state.get("last_pull_at"),
        "last_pull_check_at": state.get("last_pull_check_at"),
        "should_periodic_pull": should_periodic_pull(),
        "git_roots": [str(m.repo_root) for m in mounts],
    }


def pull_needs_console(stderr: str) -> bool:
    text = (stderr or "").lower()
    markers = (
        "conflict",
        "unmerged",
        "not possible to fast-forward",
        "divergent branches",
        "merge conflict",
        "automatic merge failed",
    )
    return any(m in text for m in markers)


def _remove_worktree(repo: Path, path: Path) -> None:
    if not path.exists():
        return
    _run_git(repo, "worktree", "remove", "--force", str(path))


def ensure_sync_branch(
    mount: ProjectMount,
    *,
    dry_run: bool = False,
    push: bool = True,
) -> dict:
    branch = mount.git_sync_branch
    if not branch:
        return {"ok": False, "project_id": mount.project_id, "error": "no sync branch configured"}

    repo = mount.repo_root
    koi_rel = _koi_rel(mount)
    if not mount.koi_root.is_dir():
        return {
            "ok": False,
            "project_id": mount.project_id,
            "error": f"missing {koi_rel}",
        }

    if _remote_sync_ref(repo, branch) or _local_worktree_ref(repo, branch):
        return {
            "ok": True,
            "project_id": mount.project_id,
            "action": "exists",
            "branch": branch,
        }

    if dry_run:
        return {
            "ok": True,
            "project_id": mount.project_id,
            "action": "would_create",
            "branch": branch,
        }

    bootstrap = repo / BOOTSTRAP_WORKTREE_DIR
    _remove_worktree(repo, bootstrap)
    created = _run_git(repo, "worktree", "add", "-b", branch, "--orphan", str(bootstrap))
    if created.returncode != 0:
        return {
            "ok": False,
            "project_id": mount.project_id,
            "action": "failed",
            "error": _git_error(created),
        }

    target = bootstrap / koi_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(mount.koi_root, target, dirs_exist_ok=True)
    added = _run_git(bootstrap, "add", koi_rel)
    if added.returncode != 0:
        _remove_worktree(repo, bootstrap)
        return {
            "ok": False,
            "project_id": mount.project_id,
            "action": "failed",
            "error": _git_error(added),
        }

    committed = _run_git(
        bootstrap,
        "commit",
        "-m",
        f"chore(koi): init sync branch {branch}",
    )
    if committed.returncode != 0:
        _remove_worktree(repo, bootstrap)
        return {
            "ok": False,
            "project_id": mount.project_id,
            "action": "failed",
            "error": _git_error(committed),
        }

    result = {
        "ok": True,
        "project_id": mount.project_id,
        "action": "created",
        "branch": branch,
        "commit": _run_git(bootstrap, "rev-parse", "HEAD").stdout.strip(),
    }
    if push:
        pushed = _run_git(bootstrap, "push", "-u", "origin", branch)
        if pushed.returncode != 0:
            result["ok"] = False
            result["action"] = "push_failed"
            result["error"] = _git_error(pushed)
    _remove_worktree(repo, bootstrap)
    return result


def _worktree_active(path: Path) -> bool:
    return (path / ".git").exists()


def _ensure_push_worktree(mount: ProjectMount) -> tuple[Path | None, str | None]:
    repo = mount.repo_root
    branch = mount.git_sync_branch or DEFAULT_SYNC_BRANCH
    wt = sync_worktree_path(mount)

    if _worktree_active(wt):
        return wt, None

    # Prefer canonical tree/ worktree; fall back to legacy in-repo path only if
    # tree/ parent cannot be created (should not happen for normal scan roots).
    if not is_under_tree(wt):
        legacy = repo / WORKTREE_DIR
        if _worktree_active(legacy):
            return legacy, None
        wt = tree_preferred_worktree(mount)

    ensure = ensure_sync_branch(mount, push=True)
    if not ensure.get("ok") and ensure.get("action") != "exists":
        return None, ensure.get("error", "failed to ensure sync branch")

    wt.parent.mkdir(parents=True, exist_ok=True)
    if wt.exists() and not _worktree_active(wt):
        # Empty or leftover dir — remove so git worktree add can succeed
        if any(wt.iterdir()):
            return None, f"refusing to overwrite non-empty path: {wt}"
        wt.rmdir()

    if _local_worktree_ref(repo, branch):
        added = _run_git(repo, "worktree", "add", str(wt), branch)
    elif _remote_sync_ref(repo, branch):
        added = _run_git(repo, "worktree", "add", "-b", branch, str(wt), f"origin/{branch}")
    else:
        added = _run_git(repo, "worktree", "add", "-b", branch, "--orphan", str(wt))
    if added.returncode != 0:
        return None, _git_error(added)
    return wt, None


def tree_preferred_worktree(mount: ProjectMount) -> Path:
    from koi.adapters.project_mount import tree_worktree_for

    return tree_worktree_for(mount.repo_root.parent, mount.repo_root.name)


def _copy_koi_tree(mount: ProjectMount, target_root: Path) -> None:
    koi_rel = _koi_rel(mount)
    dst = target_root / koi_rel
    if _path_under(mount.koi_root, target_root) and mount.koi_root.resolve() == dst.resolve():
        # Working copy already is the sync worktree — nothing to copy.
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(mount.koi_root, dst)


def pull_mount(
    mount: ProjectMount,
    *,
    dry_run: bool = False,
    discover_ref_changes: RefChangeDiscovery | None = None,
) -> dict:
    repo = mount.repo_root
    branch = mount.git_sync_branch or DEFAULT_SYNC_BRANCH
    koi_rel = _koi_rel(mount)
    ref_before = _remote_sync_ref(repo, branch)
    dirty = _dirty_koi_paths(mount)

    if not ref_before:
        ensured = ensure_sync_branch(mount, dry_run=dry_run, push=not dry_run)
        if not ensured.get("ok"):
            return {
                "ok": False,
                "project_id": mount.project_id,
                "action": "failed",
                "message": ensured.get("error", "sync branch missing"),
                "rq_discoveries": [],
            }
        if ensured.get("action") in {"created", "would_create"}:
            return {
                "ok": True,
                "project_id": mount.project_id,
                "action": ensured["action"],
                "message": f"Создана sync-ветка {branch}.",
                "rq_discoveries": [],
            }
        ref_before = _remote_sync_ref(repo, branch)

    if not ref_before:
        return {
            "ok": False,
            "project_id": mount.project_id,
            "action": "failed",
            "message": f"Ветка {branch} не найдена на origin.",
            "rq_discoveries": [],
        }

    if dirty and not dry_run:
        return {
            "ok": False,
            "project_id": mount.project_id,
            "action": "blocked",
            "needs_console": True,
            "message": (
                f"Есть незакоммиченные изменения в {koi_rel} ({len(dirty)} файлов). "
                "Сначала push или stash, затем pull."
            ),
            "rq_discoveries": [],
        }

    if dry_run:
        return {
            "ok": True,
            "project_id": mount.project_id,
            "action": "would_pull",
            "message": f"Можно обновить {koi_rel} из origin/{branch}.",
            "rq_discoveries": [],
        }

    project_md = mount.koi_root / "project.md"
    pre_pull_project_md = (
        project_md.read_text(encoding="utf-8") if project_md.is_file() else None
    )

    if is_under_tree(mount.koi_root):
        wt = sync_worktree_path(mount)
        if not _worktree_active(wt):
            wt, err = _ensure_push_worktree(mount)
            if wt is None:
                return {
                    "ok": False,
                    "project_id": mount.project_id,
                    "action": "failed",
                    "message": err or "tree worktree missing",
                    "rq_discoveries": [],
                }
        fetched = _run_git(wt, "fetch", "--quiet", "origin", branch)
        if fetched.returncode != 0:
            err = _git_error(fetched)
            return {
                "ok": False,
                "project_id": mount.project_id,
                "action": "failed",
                "needs_console": pull_needs_console(err),
                "message": err,
                "rq_discoveries": [],
            }
        merged = _run_git(wt, "merge", "--ff-only", f"origin/{branch}")
        if merged.returncode != 0:
            err = _git_error(merged)
            return {
                "ok": False,
                "project_id": mount.project_id,
                "action": "failed",
                "needs_console": pull_needs_console(err),
                "message": err,
                "rq_discoveries": [],
            }
    else:
        checkout = _run_git(repo, "checkout", f"origin/{branch}", "--", koi_rel)
        if checkout.returncode != 0:
            checkout = _run_git(repo, "checkout", branch, "--", koi_rel)
        if checkout.returncode != 0:
            err = _git_error(checkout)
            return {
                "ok": False,
                "project_id": mount.project_id,
                "action": "failed",
                "needs_console": pull_needs_console(err),
                "message": err,
                "rq_discoveries": [],
            }

    if pre_pull_project_md and project_md.is_file():
        from koi.adapters.repository import merge_org_frontmatter

        post_pull_project_md = project_md.read_text(encoding="utf-8")
        merged_md = merge_org_frontmatter(pre_pull_project_md, post_pull_project_md)
        if merged_md != post_pull_project_md:
            project_md.write_text(merged_md, encoding="utf-8")

    ref_after = _remote_sync_ref(repo, branch) or ref_before
    discoveries: list[dict] = []
    if ref_before != ref_after and discover_ref_changes is not None:
        discoveries = discover_ref_changes(ref_before, ref_after, repo)

    return {
        "ok": True,
        "project_id": mount.project_id,
        "action": "pulled",
        "message": f"Обновлён {koi_rel} из origin/{branch}.",
        "rq_discoveries": discoveries,
    }


def _extract_tar_bytes(data: bytes, dest: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as tar:
        tar.extractall(dest)


def _koi_needs_push(mount: ProjectMount) -> bool:
    if _dirty_koi_paths(mount):
        return True
    repo = mount.repo_root
    branch = mount.git_sync_branch or DEFAULT_SYNC_BRANCH
    koi_rel = _koi_rel(mount)
    if not mount.koi_root.is_dir():
        return False
    if not _remote_sync_ref(repo, branch):
        return True

    proc = subprocess.run(
        ["git", "archive", f"origin/{branch}", koi_rel],
        cwd=repo,
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout:
        return True

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        _extract_tar_bytes(proc.stdout, tmp_path)
        remote_koi = tmp_path / koi_rel
        if not remote_koi.is_dir():
            return True
        cmp = subprocess.run(
            ["git", "diff", "--quiet", "--no-index", str(remote_koi), str(mount.koi_root)],
            capture_output=True,
        )
        return cmp.returncode != 0


def push_mount(
    mount: ProjectMount,
    *,
    dry_run: bool = False,
    message: str | None = None,
) -> dict:
    repo = mount.repo_root
    branch = mount.git_sync_branch or DEFAULT_SYNC_BRANCH
    koi_rel = _koi_rel(mount)
    if not _koi_needs_push(mount):
        return {
            "ok": True,
            "project_id": mount.project_id,
            "action": "none",
            "message": "Нет изменений в koi-structure для push.",
        }

    if dry_run:
        return {
            "ok": True,
            "project_id": mount.project_id,
            "action": "would_push",
            "message": f"Можно отправить изменения {koi_rel} в origin/{branch}.",
        }

    wt, err = _ensure_push_worktree(mount)
    if wt is None:
        return {
            "ok": False,
            "project_id": mount.project_id,
            "action": "failed",
            "message": err or "worktree setup failed",
        }

    _copy_koi_tree(mount, wt)
    added = _run_git(wt, "add", "-A", koi_rel)
    if added.returncode != 0:
        return {
            "ok": False,
            "project_id": mount.project_id,
            "action": "failed",
            "message": _git_error(added),
        }

    st = _run_git(wt, "status", "--porcelain", "--", koi_rel)
    if not st.stdout.strip():
        return {
            "ok": True,
            "project_id": mount.project_id,
            "action": "none",
            "message": "После копирования изменений не осталось.",
        }

    commit_msg = message or f"projects({mount.project_id}): sync koi-structure"
    committed = _run_git(wt, "commit", "-m", commit_msg)
    if committed.returncode != 0:
        return {
            "ok": False,
            "project_id": mount.project_id,
            "action": "failed",
            "message": _git_error(committed),
        }

    pushed = _run_git(wt, "push", "origin", branch)
    if pushed.returncode != 0:
        err = _git_error(pushed)
        return {
            "ok": False,
            "project_id": mount.project_id,
            "action": "failed",
            "needs_console": pull_needs_console(err),
            "message": err,
        }

    return {
        "ok": True,
        "project_id": mount.project_id,
        "action": "pushed",
        "message": f"Отправлено в origin/{branch}.",
        "commit": _run_git(wt, "rev-parse", "HEAD").stdout.strip(),
    }


def _aggregate_results(results: list[dict], *, action_key: str = "action") -> dict:
    ok = all(r.get("ok", False) for r in results) if results else False
    actions = [r.get(action_key, "none") for r in results]
    messages = [r.get("message", "") for r in results if r.get("message")]
    discoveries: list[dict] = []
    for r in results:
        discoveries.extend(r.get("rq_discoveries") or [])

    if not results:
        return {"ok": False, "error": "no projects", "results": []}

    primary_action = "none"
    if any(a == "failed" for a in actions):
        primary_action = "failed"
    elif any(a == "blocked" for a in actions):
        primary_action = "blocked"
    elif any(a in {"pulled", "pushed", "created"} for a in actions):
        primary_action = next(a for a in actions if a in {"pulled", "pushed", "created"})
    elif any(a.startswith("would_") for a in actions):
        primary_action = next(a for a in actions if a.startswith("would_"))

    return {
        "ok": ok,
        "action": primary_action,
        "message": "; ".join(messages) if messages else "",
        "results": results,
        "rq_discoveries": discoveries,
    }


def pull_projects(
    *,
    dry_run: bool = False,
    project_id: str | None = None,
    discover_ref_changes: RefChangeDiscovery | None = None,
) -> dict:
    mounts = sync_mounts()
    if project_id:
        mounts = [m for m in mounts if m.project_id == project_id]
        if not mounts:
            touch_pull_check(result=f"project not found: {project_id}")
            return {"ok": False, "error": f"project not found: {project_id}"}

    if not mounts:
        touch_pull_check(result="no git-sync projects")
        return {"ok": False, "error": "no git-sync projects discovered"}

    summary = git_summary(project_id=project_id)
    results = [
        pull_mount(
            mount,
            dry_run=dry_run,
            discover_ref_changes=discover_ref_changes,
        )
        for mount in mounts
    ]
    agg = _aggregate_results(results)
    agg.update(summary)
    agg["projects"] = summary.get("projects", [])

    if not dry_run:
        if agg["action"] == "pulled":
            touch_pull_check(result=agg.get("message", "pulled"))
        elif agg["action"] == "none":
            touch_pull_check(result="already up to date")
        elif agg["action"] == "blocked":
            touch_pull_check(result="blocked: dirty koi-structure")
        elif agg["action"] == "failed":
            touch_pull_check(result=f"pull failed: {agg.get('message', '')[:200]}")

    return agg


def push_projects(
    *,
    dry_run: bool = False,
    project_id: str | None = None,
    message: str | None = None,
) -> dict:
    mounts = sync_mounts()
    if project_id:
        mounts = [m for m in mounts if m.project_id == project_id]
        if not mounts:
            return {"ok": False, "error": f"project not found: {project_id}"}

    if not mounts:
        return {"ok": False, "error": "no git-sync projects discovered"}

    results = [push_mount(m, dry_run=dry_run, message=message) for m in mounts]
    agg = _aggregate_results(results)
    agg.update(git_summary(project_id=project_id))
    return agg


def init_sync_branches(
    *,
    dry_run: bool = False,
    project_id: str | None = None,
    push: bool = True,
) -> dict:
    mounts = sync_mounts()
    if project_id:
        mount = get_mount(project_id)
        if mount is None or not mount.git_repo or not mount.git_sync_branch:
            return {"ok": False, "error": f"project not git-sync enabled: {project_id}"}
        if not _is_git_repo(mount.repo_root):
            return {"ok": False, "error": f"project repo has no .git: {project_id}"}
        mounts = [mount]

    if not mounts:
        return {"ok": False, "error": "no git-sync projects discovered"}

    results = [ensure_sync_branch(m, dry_run=dry_run, push=push) for m in mounts]
    return _aggregate_results(results)
