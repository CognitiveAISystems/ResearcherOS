"""Discover widgets from project ``koi-structure/widgets/``."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from koi.adapters.project_mount import list_mounts
from koi.adapters.workspace import RUN_DIR
from widgets.base.manifest import WidgetManifest, parse_widget_dir

STATE_PATH = RUN_DIR / "widgets.json"
WIDGETS_DIRNAME = "widgets"


@dataclass(frozen=True)
class WidgetRecord:
    manifest: WidgetManifest
    enabled: bool

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def key(self) -> str:
        return self.manifest.key

    def to_public_dict(self) -> dict[str, Any]:
        return self.manifest.to_public_dict(enabled=self.enabled)


def _iter_package_dirs() -> list[tuple[Path, str, str | None]]:
    """Yield ``(path, source, project_id)`` from mounted ``koi-structure/widgets/``."""
    found: dict[str, tuple[Path, str, str | None]] = {}

    for mount in list_mounts():
        root = mount.koi_root / WIDGETS_DIRNAME
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if child.is_dir() and not child.name.startswith("."):
                key = f"{mount.project_id}/{child.name}"
                found[key] = (child, "koi-structure", mount.project_id)

    return list(found.values())


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.is_file():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(data: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _enabled_map(manifests: list[WidgetManifest]) -> dict[str, bool]:
    state = _load_state()
    raw = state.get("enabled")
    overrides: dict[str, bool] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(key, str):
                overrides[key] = bool(value)
    elif isinstance(raw, list):
        listed = {str(x) for x in raw if isinstance(x, str)}
        for m in manifests:
            overrides[m.key] = m.key in listed or m.id in listed

    result: dict[str, bool] = {}
    for m in manifests:
        if m.key in overrides:
            result[m.key] = overrides[m.key]
        elif m.id in overrides:
            result[m.key] = overrides[m.id]
        else:
            result[m.key] = bool(m.default_enabled)
    return result


def list_widgets(*, ok_only: bool = True) -> list[WidgetRecord]:
    manifests: list[WidgetManifest] = []
    for path, source, project_id in _iter_package_dirs():
        manifests.append(parse_widget_dir(path, source=source, project_id=project_id))
    if ok_only:
        manifests = [m for m in manifests if m.ok]
    enabled = _enabled_map(manifests)
    return [
        WidgetRecord(manifest=m, enabled=enabled.get(m.key, bool(m.default_enabled)))
        for m in sorted(manifests, key=lambda m: m.key)
    ]


def enabled_widget_ids() -> list[str]:
    """Return widget folder ids that are enabled (may collide across projects)."""
    return [w.id for w in list_widgets(ok_only=True) if w.enabled]


def enabled_widget_keys() -> list[str]:
    return [w.key for w in list_widgets(ok_only=True) if w.enabled]


def resolve_widget_dir(widget_key_or_id: str) -> Path | None:
    """Resolve by full key (``project/id``) or bare id (first match)."""
    rows = list_widgets(ok_only=False)
    for rec in rows:
        if rec.key == widget_key_or_id or rec.id == widget_key_or_id:
            return rec.manifest.root
    return None


def resolve_widget_asset(project_id: str, widget_id: str, rel: str) -> Path | None:
    """Map URL segments to a file under a widget package (path-traversal safe)."""
    if not widget_id or widget_id.startswith(".") or ".." in widget_id.split("/"):
        return None
    if rel and ".." in Path(rel).parts:
        return None
    if project_id.startswith("_") or not project_id:
        return None

    mounts = {m.project_id: m for m in list_mounts()}
    mount = mounts.get(project_id)
    if mount is None:
        return None
    root = (mount.koi_root / WIDGETS_DIRNAME / widget_id).resolve()
    if not root.is_dir():
        return None

    candidate = (root / rel).resolve() if rel else root
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def set_widget_enabled(widget_key_or_id: str, enabled: bool) -> WidgetRecord:
    records = list_widgets(ok_only=False)
    by_key = {r.key: r for r in records}
    by_id: dict[str, WidgetRecord] = {}
    for r in records:
        by_id.setdefault(r.id, r)

    rec = by_key.get(widget_key_or_id) or by_id.get(widget_key_or_id)
    if rec is None:
        raise KeyError(f"unknown widget: {widget_key_or_id}")
    if not rec.manifest.ok:
        raise ValueError(f"widget {rec.key} has manifest errors: {rec.manifest.errors}")

    state = _load_state()
    raw = state.get("enabled")
    if not isinstance(raw, dict):
        current = _enabled_map([r.manifest for r in records if r.manifest.ok])
        raw = dict(current)
    raw[rec.key] = bool(enabled)
    raw.pop(rec.id, None)
    state["enabled"] = raw
    _save_state(state)
    return WidgetRecord(manifest=rec.manifest, enabled=bool(enabled))
