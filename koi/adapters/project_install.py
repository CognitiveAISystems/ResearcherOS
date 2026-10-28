"""Install / migrate projects into the canonical ``tree/`` + code layout.

Target::

    <scan_root>/
      tree/<repo>/koi-structure/   # branch koi/research (git worktree when git)
      <repo>/                      # code, any branch

Cases
-----
1. **new_with_code** — code repo exists, no koi integration yet:
   create orphan ``koi/research``, seed ``koi-structure/``, attach as tree worktree.
2. **integrated** — ``koi/research`` (or configured sync branch) already exists:
   add ``tree/<repo>`` worktree pointing at that branch.
3. **new_empty** — create code folder + ``tree/<repo>/koi-structure/`` (local).
4. **migrate_to_tree** — integration exists but ``koi-structure`` is still under the
   code repo or ``.koi-sync-worktree``; move checkout into ``tree/``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import yaml

from koi.adapters.project_mount import (
    DEFAULT_SYNC_BRANCH,
    KOI_STRUCTURE_DIR,
    PROJECT_MD,
    WORKTREE_DIR,
    is_under_tree,
    primary_scan_root,
    rescan_projects,
    tree_dir_for,
    tree_koi_for,
    tree_worktree_for,
)


class InstallCase(str, Enum):
    NEW_WITH_CODE = "new_with_code"
    INTEGRATED = "integrated"
    NEW_EMPTY = "new_empty"
    MIGRATE_TO_TREE = "migrate_to_tree"
    ALREADY_OK = "already_ok"


@dataclass(frozen=True)
class InstallPlan:
    case: InstallCase
    scan_root: Path
    repo_name: str
    code_root: Path
    tree_worktree: Path
    tree_koi: Path
    sync_branch: str
    detail: str


def _run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _git_err(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or "git failed").strip()


def _is_git_repo(path: Path) -> bool:
    return (path / ".git").exists()


def _branch_exists(repo: Path, branch: str) -> bool:
    if _run_git(repo, "rev-parse", "--verify", branch).returncode == 0:
        return True
    _run_git(repo, "fetch", "--quiet", "origin", branch)
    return _run_git(repo, "rev-parse", "--verify", f"origin/{branch}").returncode == 0


def _worktree_active(path: Path) -> bool:
    return (path / ".git").exists()


def _read_sync_branch(koi_root: Path | None) -> str:
    if koi_root is None or not (koi_root / PROJECT_MD).is_file():
        return DEFAULT_SYNC_BRANCH
    text = (koi_root / PROJECT_MD).read_text(encoding="utf-8")
    if not text.startswith("---"):
        return DEFAULT_SYNC_BRANCH
    parts = text.split("---", 2)
    if len(parts) < 3:
        return DEFAULT_SYNC_BRANCH
    meta = yaml.safe_load(parts[1]) or {}
    raw = meta.get("git_sync_branch")
    if raw is not None and str(raw).strip():
        return str(raw).strip()
    return DEFAULT_SYNC_BRANCH


def _find_legacy_koi(code_root: Path) -> Path | None:
    in_repo = code_root / KOI_STRUCTURE_DIR
    if (in_repo / PROJECT_MD).is_file():
        return in_repo
    wt = code_root / WORKTREE_DIR / KOI_STRUCTURE_DIR
    if (wt / PROJECT_MD).is_file():
        return wt
    return None


def resolve_repo_name(path: Path | str, *, scan_root: Path | None = None) -> tuple[Path, str]:
    """Return (code_root, repo_name) for a path or bare name."""
    scan = (scan_root or primary_scan_root()).resolve()
    raw = Path(path).expanduser()
    if raw.exists():
        code = raw.resolve()
        return code, code.name
    name = str(path).strip().rstrip("/")
    if "/" in name or name in {".", ".."}:
        raise ValueError(f"Unknown path: {path}")
    return scan / name, name


def classify_install(
    path: Path | str,
    *,
    scan_root: Path | None = None,
    sync_branch: str | None = None,
    create_if_missing: bool = False,
    tree_name: str | None = None,
) -> InstallPlan:
    scan = (scan_root or primary_scan_root()).resolve()
    code_root, repo_name = resolve_repo_name(path, scan_root=scan)
    if tree_name is not None and (not tree_name or Path(tree_name).name != tree_name or tree_name in {".", ".."}):
        raise ValueError("Invalid research tree folder name")
    tree_wt = tree_worktree_for(scan, tree_name or repo_name)
    tree_koi = tree_koi_for(scan, tree_name or repo_name)
    legacy = _find_legacy_koi(code_root) if code_root.is_dir() and tree_name is None else None
    branch = sync_branch or _read_sync_branch(
        tree_koi if (tree_koi / PROJECT_MD).is_file() else legacy
    )

    if (tree_koi / PROJECT_MD).is_file() and code_root.is_dir():
        return InstallPlan(
            case=InstallCase.ALREADY_OK,
            scan_root=scan,
            repo_name=repo_name,
            code_root=code_root,
            tree_worktree=tree_wt,
            tree_koi=tree_koi,
            sync_branch=branch,
            detail="tree/ + code already present",
        )

    if code_root.is_dir() and legacy is not None and not (tree_koi / PROJECT_MD).is_file():
        return InstallPlan(
            case=InstallCase.MIGRATE_TO_TREE,
            scan_root=scan,
            repo_name=repo_name,
            code_root=code_root,
            tree_worktree=tree_wt,
            tree_koi=tree_koi,
            sync_branch=branch,
            detail=f"legacy koi at {legacy}; will move into tree/",
        )

    if code_root.is_dir() and _is_git_repo(code_root) and _branch_exists(code_root, branch):
        return InstallPlan(
            case=InstallCase.INTEGRATED,
            scan_root=scan,
            repo_name=repo_name,
            code_root=code_root,
            tree_worktree=tree_wt,
            tree_koi=tree_koi,
            sync_branch=branch,
            detail=f"sync branch {branch} found; will attach tree/ worktree",
        )

    if code_root.is_dir():
        return InstallPlan(
            case=InstallCase.NEW_WITH_CODE,
            scan_root=scan,
            repo_name=repo_name,
            code_root=code_root,
            tree_worktree=tree_wt,
            tree_koi=tree_koi,
            sync_branch=branch,
            detail="code present; will create koi-structure + tree/",
        )

    if create_if_missing or not code_root.exists():
        return InstallPlan(
            case=InstallCase.NEW_EMPTY,
            scan_root=scan,
            repo_name=repo_name,
            code_root=code_root,
            tree_worktree=tree_wt,
            tree_koi=tree_koi,
            sync_branch=branch,
            detail="will create code folder + tree/koi-structure",
        )

    raise ValueError(f"Cannot classify install for {path}")


def _minimal_project_md(project_id: str, title: str, *, git_repo: bool, branch: str) -> str:
    meta: dict[str, Any] = {
        "id": project_id,
        "title": title,
        "format": "koi/1",
    }
    if git_repo:
        meta["git_repo"] = True
        meta["git_sync_branch"] = branch
    body = f"# problem: problem\n\n{title}\n"
    return (
        "---\n"
        + yaml.dump(meta, allow_unicode=True, sort_keys=False).strip()
        + "\n---\n\n"
        + body
    )


def _seed_koi_structure(koi: Path, *, project_id: str, title: str, git_repo: bool, branch: str) -> None:
    koi.mkdir(parents=True, exist_ok=True)
    md = koi / PROJECT_MD
    if not md.is_file():
        md.write_text(
            _minimal_project_md(project_id, title, git_repo=git_repo, branch=branch),
            encoding="utf-8",
        )
    research = koi / "research.json"
    if not research.is_file():
        research.write_text(
            json.dumps({"version": 1, "questions": []}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def _ensure_gitignore(code_root: Path) -> None:
    gi = code_root / ".gitignore"
    lines = [
        "koi-structure/",
        f"{WORKTREE_DIR}/",
        ".koi-sync-bootstrap/",
    ]
    existing = gi.read_text(encoding="utf-8") if gi.is_file() else ""
    missing = [ln for ln in lines if ln not in existing.splitlines()]
    if not missing:
        return
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    gi.write_text(existing + prefix + "\n".join(missing) + "\n", encoding="utf-8")


def _remove_worktree(repo: Path, path: Path) -> None:
    if not path.exists():
        return
    _run_git(repo, "worktree", "remove", "--force", str(path))
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _add_tree_worktree(code_root: Path, tree_wt: Path, branch: str) -> dict[str, Any]:
    tree_wt.parent.mkdir(parents=True, exist_ok=True)
    if _worktree_active(tree_wt):
        return {"ok": True, "action": "exists", "path": str(tree_wt)}

    if tree_wt.exists():
        if any(tree_wt.iterdir()):
            return {
                "ok": False,
                "action": "failed",
                "error": f"path exists and is not a worktree: {tree_wt}",
            }
        tree_wt.rmdir()

    if _run_git(code_root, "rev-parse", "--verify", branch).returncode == 0:
        added = _run_git(code_root, "worktree", "add", str(tree_wt), branch)
    elif _run_git(code_root, "rev-parse", "--verify", f"origin/{branch}").returncode == 0:
        added = _run_git(
            code_root, "worktree", "add", "-b", branch, str(tree_wt), f"origin/{branch}"
        )
    else:
        return {
            "ok": False,
            "action": "failed",
            "error": f"branch {branch} not found locally or on origin",
        }

    if added.returncode != 0:
        return {"ok": False, "action": "failed", "error": _git_err(added)}
    return {"ok": True, "action": "created", "path": str(tree_wt)}


def _bootstrap_orphan_branch(
    code_root: Path,
    *,
    branch: str,
    koi_source: Path,
    push: bool,
) -> dict[str, Any]:
    if _branch_exists(code_root, branch):
        return {"ok": True, "action": "exists", "branch": branch}

    bootstrap = code_root / ".koi-sync-bootstrap"
    _remove_worktree(code_root, bootstrap)
    created = _run_git(code_root, "worktree", "add", "-b", branch, "--orphan", str(bootstrap))
    if created.returncode != 0:
        return {"ok": False, "action": "failed", "error": _git_err(created)}

    target = bootstrap / KOI_STRUCTURE_DIR
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(koi_source, target)
    added = _run_git(bootstrap, "add", KOI_STRUCTURE_DIR)
    if added.returncode != 0:
        _remove_worktree(code_root, bootstrap)
        return {"ok": False, "action": "failed", "error": _git_err(added)}

    committed = _run_git(
        bootstrap, "commit", "-m", f"chore(koi): init sync branch {branch}"
    )
    if committed.returncode != 0:
        _remove_worktree(code_root, bootstrap)
        return {"ok": False, "action": "failed", "error": _git_err(committed)}

    result: dict[str, Any] = {
        "ok": True,
        "action": "created",
        "branch": branch,
        "commit": _run_git(bootstrap, "rev-parse", "HEAD").stdout.strip(),
    }
    if push:
        remotes = _run_git(code_root, "remote")
        if remotes.returncode == 0 and remotes.stdout.strip():
            pushed = _run_git(bootstrap, "push", "-u", "origin", branch)
            if pushed.returncode != 0:
                result["ok"] = False
                result["action"] = "push_failed"
                result["error"] = _git_err(pushed)
    _remove_worktree(code_root, bootstrap)
    return result


def _project_id_for(repo_name: str, koi: Path | None) -> str:
    if koi and (koi / PROJECT_MD).is_file():
        text = (koi / PROJECT_MD).read_text(encoding="utf-8")
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                meta = yaml.safe_load(parts[1]) or {}
                if meta.get("id"):
                    return str(meta["id"])
    return repo_name.replace("_", "-")


def install_project(
    path: Path | str,
    *,
    scan_root: Path | None = None,
    sync_branch: str | None = None,
    title: str | None = None,
    push: bool = True,
    dry_run: bool = False,
    create_if_missing: bool = False,
    tree_name: str | None = None,
) -> dict[str, Any]:
    plan = classify_install(
        path,
        scan_root=scan_root,
        sync_branch=sync_branch,
        create_if_missing=create_if_missing,
        tree_name=tree_name,
    )
    result: dict[str, Any] = {
        "ok": True,
        "case": plan.case.value,
        "repo_name": plan.repo_name,
        "code_root": str(plan.code_root),
        "tree_worktree": str(plan.tree_worktree),
        "tree_koi": str(plan.tree_koi),
        "sync_branch": plan.sync_branch,
        "detail": plan.detail,
        "steps": [],
    }

    if plan.case == InstallCase.ALREADY_OK:
        result["message"] = "Already in canonical tree/ layout."
        return result

    if dry_run:
        result["message"] = f"Would run case {plan.case.value}: {plan.detail}"
        return result

    steps: list[dict[str, Any]] = result["steps"]
    project_title = title or plan.repo_name.replace("_", " ")
    project_id = tree_name or _project_id_for(plan.repo_name, _find_legacy_koi(plan.code_root))

    try:
        if plan.case == InstallCase.NEW_EMPTY:
            plan.code_root.mkdir(parents=True, exist_ok=False)
            (plan.code_root / "projectcode").mkdir()
            (plan.code_root / "projectcode" / "README.md").write_text(
                "# Project code\n\nExperiment scripts and implementation live here.\n",
                encoding="utf-8",
            )
            _seed_koi_structure(
                plan.tree_koi,
                project_id=project_id,
                title=project_title,
                git_repo=False,
                branch=plan.sync_branch,
            )
            steps.append({"action": "created_empty", "code": str(plan.code_root)})
            rescan_projects()
            result["message"] = "Created new local project under tree/ + code."
            return result

        if plan.case == InstallCase.NEW_WITH_CODE:
            if not _is_git_repo(plan.code_root):
                # Local-only: just place koi-structure under tree/
                _seed_koi_structure(
                    plan.tree_koi,
                    project_id=project_id,
                    title=project_title,
                    git_repo=False,
                    branch=plan.sync_branch,
                )
                steps.append({"action": "seeded_tree_local", "path": str(plan.tree_koi)})
                rescan_projects()
                result["message"] = "Seeded tree/koi-structure (no git in code repo)."
                return result

            # A new tree must never seed from another tree in the code checkout.
            with TemporaryDirectory(prefix="koi-install-") as temporary:
                tmp_koi = Path(temporary) / KOI_STRUCTURE_DIR
                _seed_koi_structure(
                    tmp_koi,
                    project_id=project_id,
                    title=project_title,
                    git_repo=True,
                    branch=plan.sync_branch,
                )
                boot = _bootstrap_orphan_branch(
                    plan.code_root,
                    branch=plan.sync_branch,
                    koi_source=tmp_koi,
                    push=push,
                )
            steps.append({"action": "bootstrap_branch", **boot})
            if not boot.get("ok"):
                result["ok"] = False
                result["message"] = boot.get("error", "bootstrap failed")
                return result

            attached = _add_tree_worktree(plan.code_root, plan.tree_worktree, plan.sync_branch)
            steps.append({"action": "attach_tree", **attached})
            if not attached.get("ok"):
                result["ok"] = False
                result["message"] = attached.get("error", "attach failed")
                return result

            _ensure_gitignore(plan.code_root)
            steps.append({"action": "gitignore", "path": str(plan.code_root / ".gitignore")})
            rescan_projects()
            result["message"] = "Created orphan sync branch and tree/ worktree."
            return result

        if plan.case == InstallCase.INTEGRATED:
            attached = _add_tree_worktree(plan.code_root, plan.tree_worktree, plan.sync_branch)
            steps.append({"action": "attach_tree", **attached})
            if not attached.get("ok"):
                result["ok"] = False
                result["message"] = attached.get("error", "attach failed")
                return result
            _ensure_gitignore(plan.code_root)
            rescan_projects()
            result["message"] = f"Attached tree/ worktree on {plan.sync_branch}."
            return result

        if plan.case == InstallCase.MIGRATE_TO_TREE:
            legacy = _find_legacy_koi(plan.code_root)
            if legacy is None:
                result["ok"] = False
                result["message"] = "No legacy koi-structure to migrate"
                return result

            if _is_git_repo(plan.code_root):
                if not _branch_exists(plan.code_root, plan.sync_branch):
                    boot = _bootstrap_orphan_branch(
                        plan.code_root,
                        branch=plan.sync_branch,
                        koi_source=legacy,
                        push=push,
                    )
                    steps.append({"action": "bootstrap_branch", **boot})
                    if not boot.get("ok"):
                        result["ok"] = False
                        result["message"] = boot.get("error", "bootstrap failed")
                        return result

                # Drop legacy in-repo worktree if present
                legacy_wt = plan.code_root / WORKTREE_DIR
                if _worktree_active(legacy_wt):
                    _remove_worktree(plan.code_root, legacy_wt)
                    steps.append({"action": "removed_legacy_worktree", "path": str(legacy_wt)})

                attached = _add_tree_worktree(
                    plan.code_root, plan.tree_worktree, plan.sync_branch
                )
                steps.append({"action": "attach_tree", **attached})
                if not attached.get("ok"):
                    result["ok"] = False
                    result["message"] = attached.get("error", "attach failed")
                    return result

                # If tree koi is empty/missing but legacy had content, copy once
                if not (plan.tree_koi / PROJECT_MD).is_file() and (legacy / PROJECT_MD).is_file():
                    plan.tree_koi.parent.mkdir(parents=True, exist_ok=True)
                    if plan.tree_koi.exists():
                        shutil.rmtree(plan.tree_koi)
                    shutil.copytree(legacy, plan.tree_koi)
                    steps.append({"action": "copied_legacy_into_tree"})

                in_repo = plan.code_root / KOI_STRUCTURE_DIR
                if in_repo.is_dir() and not is_under_tree(in_repo):
                    # Leave files but ensure ignored; optional remove if identical to tree
                    _ensure_gitignore(plan.code_root)
                    steps.append(
                        {
                            "action": "left_in_repo_koi_gitignored",
                            "hint": f"You may delete {in_repo} after verifying tree/",
                        }
                    )
            else:
                # Non-git: physically move into tree/
                plan.tree_worktree.mkdir(parents=True, exist_ok=True)
                if plan.tree_koi.exists():
                    shutil.rmtree(plan.tree_koi)
                shutil.move(str(legacy), str(plan.tree_koi))
                steps.append({"action": "moved_local_koi", "to": str(plan.tree_koi)})

            _ensure_gitignore(plan.code_root)
            rescan_projects()
            result["message"] = "Migrated koi-structure into tree/."
            return result

    except Exception as exc:  # noqa: BLE001 — surface as install error
        result["ok"] = False
        result["message"] = str(exc)
        return result

    result["ok"] = False
    result["message"] = f"Unhandled case: {plan.case}"
    return result


def layout_status(*, scan_root: Path | None = None) -> dict[str, Any]:
    """Summarize code siblings vs tree/ layout for the scan root."""
    scan = (scan_root or primary_scan_root()).resolve()
    tree = tree_dir_for(scan)
    projects: list[dict[str, Any]] = []

    names: set[str] = set()
    if tree.is_dir():
        names.update(p.name for p in tree.iterdir() if p.is_dir() and not p.name.startswith("."))
    for child in scan.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue
        if child.name in {"ReseachOS", "koi-workspace", "tree", "node_modules"}:
            continue
        if child.resolve() == Path(__file__).resolve().parents[2]:
            continue
        names.add(child.name)

    for name in sorted(names):
        code = scan / name
        tree_koi = tree_koi_for(scan, name)
        legacy = _find_legacy_koi(code) if code.is_dir() else None
        plan = None
        try:
            if code.is_dir() or (tree_koi / PROJECT_MD).is_file():
                plan = classify_install(name, scan_root=scan)
        except ValueError:
            plan = None
        projects.append(
            {
                "name": name,
                "code_exists": code.is_dir(),
                "tree_koi": (tree_koi / PROJECT_MD).is_file(),
                "legacy_koi": str(legacy) if legacy else None,
                "case": plan.case.value if plan else None,
                "detail": plan.detail if plan else None,
            }
        )

    return {"scan_root": str(scan), "tree_dir": str(tree), "projects": projects}
