"""Parse a single widget package directory under ``koi-structure/widgets/``."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

_WIDGET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_VALID_SURFACES = frozenset({"web", "desktop"})
_VALID_VISIBILITY = frozenset({"public", "private"})


@dataclass
class WidgetManifest:
    id: str
    title: str
    summary: str
    visibility: str
    surfaces: list[str]
    default_enabled: bool
    entry_web: str | None
    entry_desktop: str | None
    root: Path
    source: str  # "koi-structure"
    project_id: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def key(self) -> str:
        """Stable enable/URL key: ``project_id/id``."""
        if not self.project_id:
            return self.id
        return f"{self.project_id}/{self.id}"

    def _web_url(self, prefix: str) -> str | None:
        if not self.entry_web or "web" not in self.surfaces or not self.project_id:
            return None
        url = f"{prefix}/{self.entry_web}"
        path = self.root / self.entry_web
        if path.is_file():
            url += f"?v={int(path.stat().st_mtime)}"
        return url

    def to_public_dict(self, *, enabled: bool) -> dict[str, Any]:
        prefix = f"/widgets/{self.project_id}/{self.id}" if self.project_id else f"/widgets/{self.id}"
        return {
            "id": self.id,
            "key": self.key,
            "project_id": self.project_id,
            "title": self.title,
            "summary": self.summary,
            "visibility": self.visibility,
            "surfaces": list(self.surfaces),
            "default_enabled": self.default_enabled,
            "enabled": enabled,
            "source": self.source,
            "entry": {
                "web": self.entry_web,
                "desktop": self.entry_desktop,
            },
            "web_url": self._web_url(prefix),
        }


def _load_yaml(path: Path) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, f"invalid YAML: {exc}"
    if not isinstance(raw, dict):
        return None, "manifest must be a mapping"
    return raw, None


def parse_widget_dir(
    widget_dir: Path,
    *,
    source: str,
    project_id: str | None = None,
) -> WidgetManifest:
    """Parse ``koi-structure/widgets/<id>/``."""
    folder_id = widget_dir.name
    errors: list[str] = []

    manifest_path = widget_dir / "manifest.yaml"
    if not manifest_path.is_file():
        alt = widget_dir / "manifest.yml"
        if alt.is_file():
            manifest_path = alt
        else:
            errors.append("missing manifest.yaml")

    data: dict[str, Any] = {}
    if "missing manifest.yaml" not in errors:
        loaded, err = _load_yaml(manifest_path)
        if err:
            errors.append(err)
        else:
            assert loaded is not None
            data = loaded

    widget_id = str(data.get("id") or folder_id).strip()
    if widget_id != folder_id:
        errors.append(f"manifest id {widget_id!r} must match folder name {folder_id!r}")
    if not _WIDGET_ID_RE.match(widget_id):
        errors.append(
            "id must match ^[a-z0-9][a-z0-9._-]{0,63}$ "
            f"(got {widget_id!r})"
        )

    visibility = str(data.get("visibility") or "private").strip().lower()
    if visibility not in _VALID_VISIBILITY:
        errors.append("visibility must be public or private")

    raw_surfaces = data.get("surfaces") or ["web"]
    if isinstance(raw_surfaces, str):
        surfaces = [raw_surfaces.strip().lower()]
    elif isinstance(raw_surfaces, list):
        surfaces = [str(s).strip().lower() for s in raw_surfaces]
    else:
        surfaces = []
        errors.append("surfaces must be a list or string")
    bad = [s for s in surfaces if s not in _VALID_SURFACES]
    if bad:
        errors.append(f"unknown surfaces: {bad}")
    if not surfaces and "surfaces must be a list or string" not in errors:
        errors.append("surfaces must not be empty")

    entry = data.get("entry") if isinstance(data.get("entry"), dict) else {}
    entry_web = str(entry.get("web") or "").strip() or None
    entry_desktop = str(entry.get("desktop") or "").strip() or None

    if "web" in surfaces:
        if not entry_web:
            errors.append("entry.web required when surfaces includes web")
        elif not (widget_dir / entry_web).is_file():
            errors.append(f"entry.web file missing: {entry_web}")

    title = str(data.get("title") or widget_id).strip() or widget_id
    summary = str(data.get("summary") or "").strip()
    default_enabled = bool(data.get("default_enabled", False))

    return WidgetManifest(
        id=widget_id,
        title=title,
        summary=summary,
        visibility=visibility,
        surfaces=surfaces,
        default_enabled=default_enabled,
        entry_web=entry_web,
        entry_desktop=entry_desktop,
        root=widget_dir.resolve(),
        source=source,
        project_id=project_id,
        errors=errors,
    )
