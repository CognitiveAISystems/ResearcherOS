"""Pull-based live view for running kanban cards (log tail, metrics images)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from koi.adapters.paths import repo_root

if TYPE_CHECKING:
    from koi.core.models import Project

LIVE_LOG_RE = re.compile(r"^live_log:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
METRICS_DIR_RE = re.compile(r"^metrics_dir:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
LIVE_NOTE_RE = re.compile(r"^live_note:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
EVO_RUN_RE = re.compile(r"^evo_run:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
SUBTASK_RE = re.compile(
    r"-\s*\[([ xX])\]\s*([^\n]*?)(?=\s*-\s*\[|$)",
    re.MULTILINE,
)

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"})
MAX_TAIL_BYTES = 256 * 1024
DEFAULT_TAIL_LINES = 100
MAX_TAIL_LINES = 500
MAX_IMAGES = 24
LIVE_ACTIVITY_MAX_AGE_SEC = 30 * 60
# Prefer gather/host dashboards at the top of the KOI metrics pane.
# Dual-host A-1 10k order: jobs main → ns2 main → ns2 sysmon.
METRICS_IMAGE_PRIORITY = (
    "dashboard.png",
    "dashboard_sr_slices.png",
    "dashboard_scores.png",
    "dashboard_speed.png",
    "dashboard_losses.png",
    "dashboard_sr_return.png",
    "loss_curve.png",
    "action_acc.png",
    "gpu_sysmon.png",
    "agent_sample_tail.png",
    "agent_sample_ask.png",
    "agent_sample.png",
    "agent_sample_full.png",
    "jobs_gather_dashboard.png",
    "ns2_gather_dashboard.png",
    "ns2_host_sysmon.png",
    "gather_dashboard.png",
    "aggregate_metrics.png",
    "host_sysmon.png",
    "gpu_util.png",
    "gpu_mem.png",
    "disk_free.png",
    "progress_over_time.png",
    "traj_per_hour.png",
    "aw_ow_growth.png",
    "trajectories.png",
    "sr.png",
    "recent_vocab_additions.png",
)


def parse_live_hints(text: str) -> dict[str, str]:
    """Extract live_log, metrics_dir, live_note from card description or report."""
    body = str(text or "")
    out: dict[str, str] = {}
    for key, pattern in (
        ("live_log", LIVE_LOG_RE),
        ("metrics_dir", METRICS_DIR_RE),
        ("live_note", LIVE_NOTE_RE),
        ("evo_run", EVO_RUN_RE),
    ):
        m = pattern.search(body)
        if m:
            out[key] = m.group(1).strip()
    return out


def has_live_hints(hints: dict[str, str] | None) -> bool:
    hints = hints or {}
    return any(str(hints.get(key) or "").strip() for key in ("live_log", "metrics_dir", "live_note", "evo_run"))


def _mtime_ts(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def is_live_active(
    snapshot: dict[str, Any],
    *,
    column_id: str | None = None,
    now: datetime | None = None,
    max_age_sec: int = LIVE_ACTIVITY_MAX_AGE_SEC,
) -> bool:
    """True when live artifacts were updated recently or agent reports via live_note only."""
    now_ts = (now or datetime.now(timezone.utc)).timestamp()
    cutoff = now_ts - max_age_sec

    live_log = snapshot.get("live_log") or {}
    metrics = snapshot.get("metrics_dir") or {}
    live_note = str(snapshot.get("live_note") or "").strip()
    log_cfg = bool(live_log.get("configured"))
    metrics_cfg = bool(metrics.get("configured"))

    if live_log.get("exists"):
        ts = _mtime_ts(live_log.get("mtime"))
        if ts is not None and ts >= cutoff:
            return True

    for img in metrics.get("images") or []:
        ts = _mtime_ts(img.get("mtime"))
        if ts is not None and ts >= cutoff:
            return True

    # Running cards with live hints stay visible between sync ticks (watch may be 20m).
    if column_id == "running":
        if log_cfg or metrics_cfg or live_note:
            return True

    if live_note and not log_cfg and not metrics_cfg:
        return True

    return False


def parse_subtasks(description: str) -> dict[str, list[str]]:
    open_items: list[str] = []
    done_items: list[str] = []
    body = str(description or "").replace("\\n", "\n")
    for m in SUBTASK_RE.finditer(body):
        text = m.group(2).strip()
        if not text:
            continue
        if m.group(1).lower() == "x":
            done_items.append(text)
        else:
            open_items.append(text)
    return {"open": open_items, "done": done_items}


def _allowed_roots(project_id: str) -> list[Path]:
    repo = repo_root(project_id).resolve()
    return [repo, repo.parent.resolve()]


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_project_path(project_id: str, rel: str) -> Path:
    """Resolve a project-relative path; allow repo and its parent (sibling repos)."""
    raw = str(rel or "").strip()
    if not raw:
        raise ValueError("Empty path")
    roots = _allowed_roots(project_id)
    if raw.startswith("/"):
        candidates = [Path(raw).resolve()]
    else:
        # ``_path_for_api`` drops the ``../`` from sibling-repo hints, so a
        # relative path may belong to the repo or to the workspace around it.
        candidates = [(root / raw).resolve() for root in roots]
    allowed = [c for c in candidates if any(_is_under(c, root) for root in roots)]
    if not allowed:
        raise ValueError("Path outside project workspace")
    for candidate in allowed:
        if candidate.exists():
            return candidate
    return allowed[0]


def tail_file(path: Path, *, lines: int = DEFAULT_TAIL_LINES) -> str:
    if lines < 1:
        lines = 1
    if lines > MAX_TAIL_LINES:
        lines = MAX_TAIL_LINES
    if not path.is_file():
        raise FileNotFoundError(str(path))
    size = path.stat().st_size
    read_size = min(size, MAX_TAIL_BYTES)
    with path.open("rb") as fh:
        if read_size < size:
            fh.seek(-read_size, 2)
        data = fh.read(read_size)
    text = data.decode("utf-8", errors="replace")
    chunk = text.splitlines()
    if len(chunk) > lines:
        chunk = chunk[-lines:]
    if read_size < size:
        chunk.insert(0, f"… ({size - read_size} bytes omitted) …")
    return "\n".join(chunk)


def list_metric_images(path: Path, *, limit: int = MAX_IMAGES) -> list[dict[str, Any]]:
    if not path.is_dir():
        raise NotADirectoryError(str(path))
    limit = max(1, min(limit, MAX_IMAGES))
    priority = {name: idx for idx, name in enumerate(METRICS_IMAGE_PRIORITY)}
    entries: list[tuple[int, float, Path]] = []
    for child in path.iterdir():
        if not child.is_file():
            continue
        if child.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        try:
            mtime = child.stat().st_mtime
        except OSError:
            continue
        rank = priority.get(child.name, len(METRICS_IMAGE_PRIORITY) + 1)
        # Keep sample dialogs after dashboards but before random leftovers.
        if child.name.startswith("sample_dialog_"):
            rank = len(METRICS_IMAGE_PRIORITY)
        entries.append((rank, -mtime, child))
    entries.sort(key=lambda item: (item[0], item[1]))
    out: list[dict[str, Any]] = []
    for _rank, neg_mtime, child in entries[:limit]:
        out.append(
            {
                "name": child.name,
                "mtime": datetime.fromtimestamp(-neg_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return out


def _path_for_api(project_id: str, resolved: Path) -> str:
    """Project-relative path for live/file URLs (no ``..``)."""
    repo = repo_root(project_id).resolve()
    try:
        return resolved.resolve().relative_to(repo).as_posix()
    except ValueError:
        for root in _allowed_roots(project_id):
            try:
                return resolved.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                continue
    return str(resolved)


def _evo_images(project_id: str, evo_root: Path, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Find benchmark graphs in Evo worktrees and expose safe project paths."""
    found: list[Path] = []
    for node in nodes:
        worktree = Path(str(node.get("worktree") or ""))
        for base in (worktree / "runs", worktree / "datasets", worktree / "artifacts"):
            if base.is_dir():
                found.extend(p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)
    for base in (evo_root / "runs", evo_root.parent.parent / "runs"):
        if base.is_dir():
            found.extend(p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)
    unique = {str(path.resolve()): path for path in found}
    out = []
    for path in sorted(unique.values(), key=lambda item: item.stat().st_mtime, reverse=True)[:MAX_IMAGES]:
        out.append({"name": path.name, "path": _path_for_api(project_id, path), "mtime": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()})
    return out


def _evo_checks(evo_root: Path, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for node in nodes:
        root = evo_root / "experiments" / str(node.get("id") or "") / "checks"
        if not root.is_dir():
            continue
        for folder in sorted(root.iterdir()):
            for name in ("check.json", "gate_check.json"):
                path = folder / name
                if not path.is_file():
                    continue
                try:
                    item = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if isinstance(item, dict):
                    checks.append(item)
    return checks


def normalize_hint_path(project_id: str, rel: str) -> str:
    """Strip legacy ``../<repo>/`` prefixes so paths resolve inside the project repo."""
    raw = str(rel or "").strip()
    if not raw or raw.startswith("/"):
        return raw
    repo_name = repo_root(project_id).name
    for prefix in (f"../{repo_name}/", f"{repo_name}/"):
        if raw.startswith(prefix):
            return raw[len(prefix) :]
    return raw


def live_snapshot(
    project_id: str,
    *,
    hints: dict[str, str],
    description: str,
    tail_lines: int = DEFAULT_TAIL_LINES,
    column_id: str | None = None,
) -> dict[str, Any]:
    """Build pull snapshot for UI polling."""
    subtasks = parse_subtasks(description)
    live_log_path = normalize_hint_path(project_id, hints.get("live_log", ""))
    metrics_path = normalize_hint_path(project_id, hints.get("metrics_dir", ""))
    evo_run_path = normalize_hint_path(project_id, hints.get("evo_run", ""))

    log_block: dict[str, Any] = {"configured": bool(live_log_path), "path": live_log_path}
    metrics_block: dict[str, Any] = {
        "configured": bool(metrics_path),
        "path": metrics_path,
        "images": [],
    }
    evo_block: dict[str, Any] = {"configured": bool(evo_run_path), "path": evo_run_path}
    if evo_run_path:
        try:
            evo_root = resolve_project_path(project_id, evo_run_path)
            state_path = evo_root / "state.json" if evo_root.is_dir() else evo_root
            graph_path = evo_root / "graph.json" if evo_root.is_dir() else evo_root.parent / "graph.json"
            evo_block["exists"] = state_path.is_file() or graph_path.is_file()
            if state_path.is_file():
                payload = json.loads(state_path.read_text(encoding="utf-8"))
                evo_block.update({k: payload.get(k) for k in ("run_id", "status", "pid", "returncode", "started_at", "finished_at", "summary")})
                evo_block["state_path"] = _path_for_api(project_id, state_path)
                experiments = state_path.parent / "experiments.json"
                if experiments.is_file():
                    evo_block["experiments"] = json.loads(experiments.read_text(encoding="utf-8"))
            if graph_path.is_file():
                graph = json.loads(graph_path.read_text(encoding="utf-8"))
                nodes = [node for node in (graph.get("nodes") or {}).values() if node.get("id") != "root"]
                scores = [node.get("score") for node in nodes if isinstance(node.get("score"), (int, float))]
                evo_block.setdefault("run_id", evo_root.name)
                evo_block.setdefault("status", "initialized" if not nodes else "running")
                evo_block.setdefault("summary", {})
                evo_block["summary"] = {**(evo_block.get("summary") or {}), "experiments": len(nodes), "best_score": max(scores) if scores else None}
                evo_block["experiments"] = nodes
                evo_block["state_path"] = _path_for_api(project_id, graph_path)
                live_report = repo_root(project_id) / "koi-structure" / "reports"
                if live_report.is_dir():
                    matches = list(live_report.rglob("evo-live.md"))
                    if matches:
                        evo_block["live_report"] = _path_for_api(project_id, matches[0])
                evo_block["artifacts"] = _evo_images(project_id, evo_root, nodes)
                checks = _evo_checks(evo_root, nodes)
                passed = sum(1 for check in checks if check.get("status") == "passed")
                scored_checks = [check for check in checks if isinstance(check.get("score"), (int, float))]
                score = max((check.get("score") for check in scored_checks), default=None)
                score_by_exp: dict[str, float] = {}
                for check in scored_checks:
                    exp_id = str(check.get("experiment_id") or "")
                    score_by_exp[exp_id] = max(score_by_exp.get(exp_id, float("-inf")), float(check["score"]))
                latest = sorted(nodes, key=lambda node: str(node.get("updated_at") or ""))[-1] if nodes else {}
                best_node = max(
                    nodes,
                    key=lambda node: (
                        score_by_exp.get(str(node.get("id") or ""), float("-inf")),
                        node.get("status") != "pending",
                    ),
                    default=latest,
                )
                evo_block["idea"] = latest.get("hypothesis") if latest else "Ожидание первой candidate-ветки."
                best_id = best_node.get("id") if best_node else "—"
                evo_block["solution"] = f"Лучший кандидат {best_id}; score {score if score is not None else '—'}; проверок passed: {passed}" if best_node else "Решение ещё не предложено."
                evo_block["checks"] = checks[-24:]
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            evo_block["error"] = str(exc)

    if live_log_path:
        try:
            resolved = resolve_project_path(project_id, live_log_path)
            log_block["exists"] = resolved.is_file()
            log_block["resolved_path"] = _path_for_api(project_id, resolved)
            if resolved.is_file():
                st = resolved.stat()
                log_block["tail"] = tail_file(resolved, lines=tail_lines)
                log_block["size"] = st.st_size
                log_block["mtime"] = datetime.fromtimestamp(
                    st.st_mtime, tz=timezone.utc
                ).isoformat()
        except (ValueError, OSError) as exc:
            log_block["error"] = str(exc)

    if metrics_path:
        try:
            resolved = resolve_project_path(project_id, metrics_path)
            metrics_block["exists"] = resolved.is_dir()
            metrics_block["resolved_path"] = _path_for_api(project_id, resolved)
            if resolved.is_dir():
                metrics_block["images"] = list_metric_images(resolved)
        except (ValueError, OSError) as exc:
            metrics_block["error"] = str(exc)

    snapshot = {
        "live_note": hints.get("live_note", ""),
        "subtasks": subtasks,
        "live_log": log_block,
        "metrics_dir": metrics_block,
        "evo": evo_block,
    }
    snapshot["has_live_hints"] = has_live_hints(hints)
    snapshot["active"] = is_live_active(snapshot, column_id=column_id)
    return snapshot


def merge_live_hints(
    project: Project,
    board_id: str,
    card_id: str,
    card_title: str,
    description: str,
) -> dict[str, str]:
    """Live hints from card description plus report body (report wins on overlap)."""
    from koi.adapters.card_reports import read_report

    hints = parse_live_hints(description)
    try:
        report = read_report(project, board_id, card_id, card_title)
        hints = {**hints, **parse_live_hints(report.get("content", ""))}
    except (OSError, KeyError, ValueError):
        pass
    return hints


def live_monitor_cards(project_id: str, project: Project) -> list[dict[str, Any]]:
    """Running cards with live hints and recent activity (for monitor tabs)."""
    items: list[dict[str, Any]] = []
    for board in project.boards:
        for card in board.cards:
            if card.column_id != "running":
                continue
            hints = merge_live_hints(project, board.id, card.id, card.title, card.description)
            if not has_live_hints(hints):
                continue
            items.append(
                {
                    "board_id": board.id,
                    "card_id": card.id,
                    "title": card.title,
                }
            )
    return items
