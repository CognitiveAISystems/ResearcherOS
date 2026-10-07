"""Persistent, machine-local workspace selection for the desktop application.

The selected directory is deliberately kept out of the engine checkout and every
research repository.  It is an application preference, not research data.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Final


APP_NAME: Final = "ResearcherOS"
CONFIG_FILE: Final = "desktop-workspace.json"


def application_support_dir() -> Path:
    """Return the per-user application-data directory.

    macOS is the first shipping target.  The other branches make the persisted
    setting portable when the desktop shell is packaged for them later.
    ``KOI_DESKTOP_CONFIG_DIR`` is an integration-test override.
    """
    override = os.environ.get("KOI_DESKTOP_CONFIG_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME


def config_path() -> Path:
    return application_support_dir() / CONFIG_FILE


def _read_payload() -> dict[str, object]:
    try:
        raw = config_path().read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _usable_directory(path: Path) -> bool:
    return path.is_dir() and os.access(path, os.R_OK | os.X_OK)


def selected_workspace_root() -> Path | None:
    """Return the stored root only while it remains a readable directory."""
    raw = _read_payload().get("workspace_root")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        root = Path(raw).expanduser().resolve(strict=True)
    except OSError:
        return None
    return root if _usable_directory(root) else None


def set_workspace_root(root: str | Path) -> Path:
    """Validate and atomically persist a user-selected workspace directory."""
    try:
        resolved = Path(root).expanduser().resolve(strict=True)
    except OSError as exc:
        raise ValueError("Workspace folder does not exist") from exc
    if not _usable_directory(resolved):
        raise ValueError("Workspace folder is not readable")

    destination = config_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        destination.parent.chmod(0o700)
    except OSError:
        pass
    temporary = destination.with_suffix(".tmp")
    payload = json.dumps({"workspace_root": str(resolved)}, ensure_ascii=False) + "\n"
    try:
        temporary.write_text(payload, encoding="utf-8")
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)
    return resolved
