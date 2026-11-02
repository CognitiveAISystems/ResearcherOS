"""Detect new research-question answers (git sync + local research.json)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

from koi.core.md_io import parse_project_md
from koi.adapters.workspace import get_workspace

_ws = get_workspace()
GIT_ROOT = _ws.git_root()

PROJECTS_PREFIX = "projects/"
KOI_STRUCTURE_PREFIX = "koi-structure/"
KANBAN_COLUMNS = ("backlog", "running", "done", "successful")
CARD_ID_IN_CELL_RE = re.compile(r"<!--\s*id:(\S+)")


def _repo_git_roots() -> list[Path]:
    from koi.adapters.project_sync import _repo_git_roots as roots

    return roots()


def _run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def current_head(repo: Optional[Path] = None) -> Optional[str]:
    root = repo or GIT_ROOT
    r = _run_git(root, "rev-parse", "HEAD")
    if r.returncode != 0:
        return None
    return r.stdout.strip() or None


def current_heads() -> dict[str, str]:
    heads: dict[str, str] = {}
    for root in _repo_git_roots():
        head = current_head(root)
        if head:
            heads[str(root.resolve())] = head
    return heads


def _git_show_file(cwd: Path, ref: str, path: str) -> Optional[str]:
    r = _run_git(cwd, "show", f"{ref}:{path}")
    if r.returncode != 0:
        return None
    return r.stdout


def _answer_signature(item: Optional[dict[str, Any]]) -> str:
    if not item:
        return ""
    narrative = str(item.get("narrative") or "").strip()
    answer = str(item.get("answer") or "").strip()
    body = narrative or answer
    if not body:
        return ""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def _display_answer(item: dict[str, Any]) -> str:
    narrative = str(item.get("narrative") or "").strip()
    if narrative:
        return narrative
    return str(item.get("answer") or "").strip()


def _questions_from_json(text: Optional[str]) -> dict[str, dict[str, Any]]:
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    raw = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("id") or "").strip()
        if not qid:
            continue
        out[qid] = item
    return out


def _project_id_for_repo_path(repo_root: Path, git_path: str) -> Optional[str]:
    from koi.adapters.project_mount import list_mounts

    path = Path(git_path)
    if path.parts[:1] == ("projects",) and len(path.parts) >= 3:
        return path.parts[1]
    if git_path.endswith(f"{KOI_STRUCTURE_PREFIX}research.json"):
        resolved = repo_root.resolve()
        for mount in list_mounts():
            if mount.repo_root.resolve() == resolved:
                return mount.project_id
    return None


def _project_md_git_candidates(project_id: str) -> list[tuple[Path, str]]:
    from koi.adapters.project_mount import get_mount_or_raise
    from koi.adapters.project_sync import _koi_git_cwd, _koi_rel

    candidates: list[tuple[Path, str]] = []
    try:
        mount = get_mount_or_raise(project_id)
        candidates.append((_koi_git_cwd(mount), f"{_koi_rel(mount)}/project.md"))
    except KeyError:
        pass
    legacy = f"{PROJECTS_PREFIX}{project_id}/project.md"
    pair = (GIT_ROOT, legacy)
    if pair not in candidates:
        candidates.append(pair)
    return candidates


def _project_md_git_path(project_id: str) -> tuple[Optional[Path], str]:
    candidates = _project_md_git_candidates(project_id)
    return candidates[0]


def _research_paths_between(cwd: Path, old_ref: str, new_ref: str) -> list[str]:
    paths: set[str] = set()
    for prefix in (KOI_STRUCTURE_PREFIX, PROJECTS_PREFIX):
        r = _run_git(
            cwd,
            "diff",
            "--name-only",
            f"{old_ref}..{new_ref}",
            "--",
            prefix,
        )
        if r.returncode != 0:
            continue
        for line in r.stdout.splitlines():
            p = line.strip()
            if p.endswith("/research.json") or p.endswith("research.json"):
                paths.add(p)
        tree = _run_git(cwd, "ls-tree", "-r", "--name-only", new_ref, "--", prefix)
        if tree.returncode == 0:
            for line in tree.stdout.splitlines():
                p = line.strip()
                if not p.endswith("/research.json") and p != "koi-structure/research.json":
                    continue
                old_text = _git_show_file(cwd, old_ref, p)
                new_text = _git_show_file(cwd, new_ref, p)
                if old_text != new_text:
                    paths.add(p)
    return sorted(paths)


def _card_column_in_row(line: str, card_id: str) -> Optional[str]:
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    cells = [c.strip() for c in stripped.strip("|").split("|")]
    for idx, cell in enumerate(cells[: len(KANBAN_COLUMNS)]):
        m = CARD_ID_IN_CELL_RE.search(cell)
        if m and m.group(1) == card_id:
            return KANBAN_COLUMNS[idx]
    return None


def _patch_moves_card_to_column(patch: str, card_id: str, column_id: str) -> bool:
    removed_col: Optional[str] = None
    added_col: Optional[str] = None
    for line in patch.splitlines():
        if not line or line.startswith(("diff --git", "index ", "---", "+++", "@@")):
            continue
        if line.startswith("-") and not line.startswith("---"):
            col = _card_column_in_row(line[1:], card_id)
            if col is not None:
                removed_col = col
        elif line.startswith("+") and not line.startswith("+++"):
            col = _card_column_in_row(line[1:], card_id)
            if col is not None:
                added_col = col
    return added_col == column_id and removed_col != column_id


def _patch_moves_card_to_done(patch: str, card_id: str) -> bool:
    return _patch_moves_card_to_column(patch, card_id, "done")


def _card_column_at_ref(
    cwd: Path, project_md_path: str, project_id: str, card_id: str, ref: str
) -> Optional[str]:
    if not card_id:
        return None
    text = _git_show_file(cwd, ref, project_md_path)
    if not text:
        return None
    project = parse_project_md(text, project_id=project_id)
    for board in project.boards:
        for card in board.cards:
            if card.id == card_id:
                return card.column_id
    return None


def _iter_commit_patches(
    cwd: Path,
    path: str,
    old_ref: Optional[str],
    new_ref: str,
    *,
    limit: int = 80,
) -> list[tuple[str, str]]:
    rev = f"{old_ref}..{new_ref}" if old_ref else new_ref
    r = _run_git(
        cwd,
        "log",
        rev,
        f"-{limit}",
        "--format=COMMIT %an",
        "-p",
        "--",
        path,
    )
    if r.returncode != 0 or not r.stdout.strip():
        return []

    commits: list[tuple[str, str]] = []
    author: Optional[str] = None
    patch_lines: list[str] = []
    for line in r.stdout.splitlines():
        if line.startswith("COMMIT "):
            if author is not None:
                commits.append((author, "\n".join(patch_lines)))
            author = line[len("COMMIT ") :].strip()
            patch_lines = []
        else:
            patch_lines.append(line)
    if author is not None:
        commits.append((author, "\n".join(patch_lines)))
    return commits


def author_for_card_column(
    project_id: str,
    card_id: str,
    column_id: str,
    *,
    old_ref: Optional[str] = None,
    new_ref: str = "HEAD",
) -> Optional[str]:
    """Git author who moved the experiment card to column_id (project.md kanban)."""
    if not card_id or column_id not in KANBAN_COLUMNS:
        return None

    for cwd, project_md_path in _project_md_git_candidates(project_id):
        if _card_column_at_ref(cwd, project_md_path, project_id, card_id, new_ref) != column_id:
            continue
        if old_ref:
            for author, patch in _iter_commit_patches(cwd, project_md_path, old_ref, new_ref):
                if _patch_moves_card_to_column(patch, card_id, column_id):
                    return author
        for author, patch in _iter_commit_patches(cwd, project_md_path, None, new_ref):
            if _patch_moves_card_to_column(patch, card_id, column_id):
                return author
    return None


def _author_for_card_done(
    project_id: str,
    card_id: str,
    old_ref: str,
    new_ref: str,
) -> Optional[str]:
    """Git author who moved the experiment card to done (project.md kanban)."""
    return author_for_card_column(
        project_id, card_id, "done", old_ref=old_ref, new_ref=new_ref
    )


def _open_subtask(card) -> str:
    for line in str(card.description or "").split("\n"):
        m = re.match(r"^\s*-\s*\[ \]\s*(.+)", line)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return str(card.title or "").strip()


def author_for_card_touch(project_id: str, card_id: str) -> Optional[str]:
    """Last git author who edited this card row in project.md."""
    if not card_id:
        return None
    needle = f"<!-- id:{card_id}"
    for cwd, project_md_path in _project_md_git_candidates(project_id):
        r = _run_git(cwd, "log", "-1", "--format=%an", f"-S{needle}", "--", project_md_path)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
        r = _run_git(cwd, "log", "-1", "--format=%an", "--", project_md_path)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    return None


def _git_contributors(cwd: Path, path: str, *, card_id: str = "") -> list[str]:
    """People who edited a report or this exact card row, newest first."""
    args = ["log", "--format=%x1e%aN%x1f%aE"]
    if card_id:
        args.extend(["-p", f"-G<!--[[:space:]]*id:{re.escape(card_id)}([[:space:]]|-->)"])
    else:
        args.append("--follow")
    result = _run_git(cwd, *args, "--", path)
    if result.returncode:
        return []
    authors = []
    for entry in result.stdout.split("\x1e"):
        identity, _, patch = entry.partition("\n")
        name, separator, email = identity.partition("\x1f")
        if not separator:
            continue
        if card_id and not any(
            line.startswith(("+", "-")) and line[1:].lstrip().startswith("|")
            and re.search(rf"<!--\s*id:{re.escape(card_id)}(?:\s|-->)", line)
            for line in patch.splitlines()
        ):
            continue
        # GitHub noreply email identifies a login; ordinary git names do not.
        match = re.fullmatch(r"(?:\d+\+)?([^@]+)@users\.noreply\.github\.com", email.strip())
        author = match[1] if match else name.strip()
        if author and not author.endswith("[bot]"):
            authors.append(author)
    return authors


def running_kanban_activity(project_id: str) -> list[dict[str, Any]]:
    """Running cards and contributors from their reports and card-specific commits."""
    from koi.adapters import card_reports

    cwd, project_md_path = _project_md_git_path(project_id)
    if cwd is None:
        return []
    path = cwd / project_md_path
    text = (
        path.read_text(encoding="utf-8")
        if path.is_file()
        else _git_show_file(cwd, "HEAD", project_md_path)
    )
    if not text:
        return []
    project = parse_project_md(text, project_id=project_id)
    report_index = card_reports.load_index(project_id)
    items: list[dict[str, Any]] = []
    for board in project.boards:
        for card in board.cards:
            if card.column_id != "running":
                continue
            contributors = []
            report = card_reports.resolve_card_report_path(
                project_id, project, board, card, report_index
            )
            if report:
                for report_path in (report, report.with_suffix(".run.md")):
                    try:
                        relative = report_path.resolve().relative_to(cwd.resolve()).as_posix()
                    except ValueError:
                        continue
                    contributors.extend(_git_contributors(cwd, relative))
            contributors.extend(_git_contributors(cwd, project_md_path, card_id=card.id))
            by_name = {}
            for name in contributors:
                by_name.setdefault(name.casefold(), name)
            authors = list(by_name.values())
            items.append(
                {
                    "card_id": card.id,
                    "board_id": board.id,
                    "author": ", ".join(authors),
                    "authors": authors,
                    "title": card.title,
                    "task": _open_subtask(card),
                }
            )
    return items


def _author_for_question(
    cwd: Path, path: str, question_id: str, old_ref: str, new_ref: str
) -> str:
    needle = f'"id": "{question_id}"'
    r = _run_git(
        cwd,
        "log",
        f"{old_ref}..{new_ref}",
        "-1",
        "--format=%an",
        f"-S{needle}",
        "--",
        path,
    )
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    r = _run_git(
        cwd,
        "log",
        f"{old_ref}..{new_ref}",
        "-1",
        "--format=%an",
        "--",
        path,
    )
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    return "коллега"


def discovery_key(project_id: str, question_id: str, signature: str) -> str:
    return f"{project_id}:{question_id}:{signature}"


def _discovery_from_question(
    project_id: str,
    qid: str,
    nq: dict[str, Any],
    *,
    author: str,
    old_ref: Optional[str] = None,
    new_ref: str = "HEAD",
    git_path: Optional[str] = None,
    git_cwd: Optional[Path] = None,
) -> Optional[dict[str, Any]]:
    new_sig = _answer_signature(nq)
    if not new_sig:
        return None
    question = str(nq.get("question") or "").strip()
    answer = _display_answer(nq)
    if not question or not answer:
        return None
    card_id = str(nq.get("card_id") or "").strip()
    resolved_author = author
    if card_id and old_ref and git_cwd and git_path:
        done_author = _author_for_card_done(project_id, card_id, old_ref, new_ref)
        if done_author:
            resolved_author = done_author
    if resolved_author == author and old_ref and git_cwd and git_path:
        q_author = _author_for_question(git_cwd, git_path, qid, old_ref, new_ref)
        if q_author:
            resolved_author = q_author
    return {
        "project_id": project_id,
        "question_id": qid,
        "card_id": card_id or None,
        "question": question,
        "answer": answer,
        "author": resolved_author,
        "signature": new_sig,
        "key": discovery_key(project_id, qid, new_sig),
    }


def detect_rq_discoveries(
    old_ref: str,
    new_ref: str = "HEAD",
    *,
    repo_root: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """Return RQs whose answer/narrative appeared or changed between two refs."""
    if not old_ref or not new_ref or old_ref == new_ref:
        return []
    cwd = repo_root or GIT_ROOT
    if _run_git(cwd, "cat-file", "-e", f"{old_ref}^{{commit}}").returncode != 0:
        return []
    if _run_git(cwd, "cat-file", "-e", f"{new_ref}^{{commit}}").returncode != 0:
        return []

    discoveries: list[dict[str, Any]] = []
    for path in _research_paths_between(cwd, old_ref, new_ref):
        project_id = _project_id_for_repo_path(cwd, path)
        if not project_id:
            continue
        old_text = _git_show_file(cwd, old_ref, path)
        new_text = _git_show_file(cwd, new_ref, path)
        if not new_text:
            continue
        old_qs = _questions_from_json(old_text)
        new_qs = _questions_from_json(new_text)
        for qid, nq in new_qs.items():
            old_sig = _answer_signature(old_qs.get(qid))
            new_sig = _answer_signature(nq)
            if not new_sig or new_sig == old_sig:
                continue
            item = _discovery_from_question(
                project_id,
                qid,
                nq,
                author="коллега",
                old_ref=old_ref,
                new_ref=new_ref,
                git_path=path,
                git_cwd=cwd,
            )
            if item:
                discoveries.append(item)
    return discoveries


def _filesystem_signature_snapshot() -> dict[str, str]:
    from koi.adapters.paths import research_json
    from koi.adapters.project_mount import list_mounts

    out: dict[str, str] = {}
    for mount in list_mounts():
        path = research_json(mount.project_id)
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for qid, nq in _questions_from_json(text).items():
            sig = _answer_signature(nq)
            if sig:
                out[f"{mount.project_id}:{qid}"] = sig
    return out


def detect_filesystem_rq_discoveries(
    last_sigs: dict[str, str],
    *,
    initialized: bool,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Detect new/changed answers on disk (works without git)."""
    from koi.adapters.paths import research_json
    from koi.adapters.project_mount import list_mounts

    current = _filesystem_signature_snapshot()
    if not initialized:
        return [], current

    default_author = (
        os.environ.get("KOI_DISCOVERY_AUTHOR", "").strip()
        or os.environ.get("USER", "").strip()
        or "коллега"
    )
    discoveries: list[dict[str, Any]] = []
    for mount in list_mounts():
        path = research_json(mount.project_id)
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for qid, nq in _questions_from_json(text).items():
            sig = _answer_signature(nq)
            if not sig:
                continue
            sig_key = f"{mount.project_id}:{qid}"
            old_sig = last_sigs.get(sig_key, "")
            if sig == old_sig:
                continue
            item = _discovery_from_question(
                mount.project_id,
                qid,
                nq,
                author=default_author,
            )
            if item:
                discoveries.append(item)
    return discoveries, current


def detect_all_rq_discoveries(
    last_heads: dict[str, str],
    last_sigs: dict[str, str],
    *,
    sigs_initialized: bool,
) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, str], bool]:
    """Git + filesystem discoveries; returns items, new heads, new sigs, initialized."""
    discoveries: list[dict[str, Any]] = []
    known_keys: set[str] = set()

    for root in _repo_git_roots():
        key = str(root.resolve())
        head = current_head(root)
        if not head:
            continue
        old_ref = last_heads.get(key)
        if old_ref and old_ref != head:
            for item in detect_rq_discoveries(old_ref, head, repo_root=root):
                if item["key"] not in known_keys:
                    discoveries.append(item)
                    known_keys.add(item["key"])

    fs_items, new_sigs = detect_filesystem_rq_discoveries(
        last_sigs, initialized=sigs_initialized
    )
    for item in fs_items:
        if item["key"] not in known_keys:
            discoveries.append(item)
            known_keys.add(item["key"])

    return discoveries, current_heads(), new_sigs, True


def pending_rq_discoveries(
    last_heads: dict[str, str],
    last_sigs: dict[str, str],
    *,
    sigs_initialized: bool,
) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, str], bool]:
    """Discoveries since last snapshot; returns items, current heads, sigs, initialized."""
    heads = current_heads()
    if not last_heads and not sigs_initialized:
        return [], heads, _filesystem_signature_snapshot(), True
    items, new_heads, new_sigs, initialized = detect_all_rq_discoveries(
        last_heads,
        last_sigs,
        sigs_initialized=sigs_initialized,
    )
    return items, new_heads, new_sigs, initialized
