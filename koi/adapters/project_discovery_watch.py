"""Background scan for ``tree/*/koi-structure/project.md`` (and legacy) mounts."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

from koi.adapters.project_mount import PROJECT_MD, discover_projects, rescan_projects

log = logging.getLogger(__name__)

POLL_INTERVAL_S = 2.0
DEBOUNCE_S = 0.5

_lock = threading.Lock()
_revision = 0
_running = False
_last_fingerprint: dict[str, float] = {}
_pending_changes: dict[str, list[dict[str, Any]]] = {
    "added": [],
    "removed": [],
    "changed": [],
}
_watch_thread: threading.Thread | None = None
_stop_event = threading.Event()


@dataclass(frozen=True)
class DiscoveryScanResult:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[str, ...]


def _fingerprint() -> dict[str, float]:
    out: dict[str, float] = {}
    for mount in discover_projects():
        md_path = mount.koi_root / PROJECT_MD
        try:
            out[mount.project_id] = md_path.stat().st_mtime
        except OSError:
            continue
    return out


def _project_titles(ids: set[str]) -> dict[str, str]:
    titles: dict[str, str] = {}
    if not ids:
        return titles
    for mount in discover_projects():
        if mount.project_id not in ids:
            continue
        md_path = mount.koi_root / PROJECT_MD
        title = mount.project_id
        try:
            import yaml

            text = md_path.read_text(encoding="utf-8")
            if text.startswith("---"):
                parts = text.split("---", 2)
                if len(parts) >= 3:
                    meta = yaml.safe_load(parts[1]) or {}
                    title = str(meta.get("title") or mount.project_id)
        except Exception:
            pass
        titles[mount.project_id] = title
    return titles


def _diff_fingerprints(
    previous: dict[str, float], current: dict[str, float]
) -> DiscoveryScanResult:
    prev_ids = set(previous)
    cur_ids = set(current)
    added = tuple(sorted(cur_ids - prev_ids))
    removed = tuple(sorted(prev_ids - cur_ids))
    changed = tuple(
        sorted(pid for pid in prev_ids & cur_ids if previous[pid] != current[pid])
    )
    return DiscoveryScanResult(added=added, removed=removed, changed=changed)


def _apply_scan_result(result: DiscoveryScanResult, *, initial: bool) -> None:
    global _revision, _last_fingerprint, _pending_changes

    if not result.added and not result.removed and not result.changed:
        return

    rescan_projects()
    titles = _project_titles(set(result.added) | set(result.changed))

    with _lock:
        _last_fingerprint = _fingerprint()
        if initial:
            return
        _revision += 1
        # Keep the latest event per project so each browser can poll independently.
        affected = set(result.added) | set(result.removed) | set(result.changed)
        for events in _pending_changes.values():
            events[:] = [event for event in events if event["id"] not in affected]
        for pid in result.added:
            _pending_changes["added"].append(
                {"id": pid, "title": titles.get(pid, pid), "revision": _revision}
            )
        for pid in result.removed:
            _pending_changes["removed"].append({"id": pid, "revision": _revision})
        for pid in result.changed:
            _pending_changes["changed"].append(
                {"id": pid, "title": titles.get(pid, pid), "revision": _revision}
            )
        log.info(
            "Project discovery revision %s: +%s -%s ~%s",
            _revision,
            result.added,
            result.removed,
            result.changed,
        )


def scan_once(*, initial: bool = False) -> DiscoveryScanResult:
    """Compare filesystem mounts to the last snapshot; refresh cache on change."""
    current = _fingerprint()
    with _lock:
        previous = dict(_last_fingerprint)
    result = _diff_fingerprints(previous, current)
    if initial or result.added or result.removed or result.changed:
        _apply_scan_result(result, initial=initial)
    return result


def discovery_status(*, since_revision: int = 0) -> dict[str, Any]:
    with _lock:
        revision = _revision
        running = _running
        project_ids = sorted(_last_fingerprint)
        if since_revision >= revision:
            return {
                "ok": True,
                "running": running,
                "revision": revision,
                "projects": project_ids,
                "changes": {"added": [], "removed": [], "changed": []},
            }
        changes = {
            kind: [
                {key: value for key, value in event.items() if key != "revision"}
                for event in events if event["revision"] > since_revision
            ]
            for kind, events in _pending_changes.items()
        }
        return {
            "ok": True,
            "running": running,
            "revision": revision,
            "projects": project_ids,
            "changes": changes,
        }


def _watch_loop() -> None:
    global _running
    _running = True
    scan_once(initial=True)
    last_scan_at = 0.0
    try:
        while not _stop_event.is_set():
            now = time.time()
            if now - last_scan_at >= POLL_INTERVAL_S:
                scan_once()
                last_scan_at = now
            _stop_event.wait(0.25)
    finally:
        _running = False


def start_project_discovery_watch() -> None:
    """Start background polling for new ``koi-structure/`` project mounts."""
    global _watch_thread
    if _watch_thread and _watch_thread.is_alive():
        return
    _stop_event.clear()
    _watch_thread = threading.Thread(
        target=_watch_loop,
        name="koi-project-discovery-watch",
        daemon=True,
    )
    _watch_thread.start()
    log.info("Project discovery watcher started (poll every %ss)", POLL_INTERVAL_S)


def stop_project_discovery_watch() -> None:
    _stop_event.set()
    thread = _watch_thread
    if thread and thread.is_alive():
        thread.join(timeout=POLL_INTERVAL_S + 1.0)
