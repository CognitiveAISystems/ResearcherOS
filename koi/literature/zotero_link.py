"""One Zotero login for every project. The key stays in the runtime dir, not in git."""

from __future__ import annotations

import json
from pathlib import Path

from koi.adapters.paths import koi_root

LINK_FILENAME = "zotero.local.json"


def link_path(project_id: str) -> Path:
    return koi_root(project_id) / LINK_FILENAME


def account_path() -> Path:
    from koi.adapters.workspace import get_workspace

    return get_workspace().run_dir / LINK_FILENAME


def _clean(value: object, limit: int = 300) -> str:
    return str(value or "").strip()[:limit]


def _read_link_file(path: Path) -> dict[str, str] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    api_key = _clean(data.get("api_key"))
    if not api_key:
        return None
    return {
        "user_id": _clean(data.get("user_id")),
        "api_key": api_key,
        "username": _clean(data.get("username")),
        "collection_key": _clean(data.get("collection_key"), 64),
        "collection_name": _clean(data.get("collection_name")),
    }


def _write_link_file(path: Path, link: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(link, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _legacy_links():
    from koi.adapters.project_mount import list_mounts

    for mount in list_mounts():
        path = mount.koi_root / LINK_FILENAME
        link = _read_link_file(path)
        if link:
            yield path, link


def read_zotero_link(project_id: str) -> dict[str, str] | None:
    koi_root(project_id)
    account = _read_link_file(account_path())
    if account:
        return account
    legacy = _read_link_file(link_path(project_id))
    if legacy:
        _write_link_file(account_path(), legacy)
        return legacy
    for _path, link in _legacy_links():
        _write_link_file(account_path(), link)
        return link
    return None


def write_zotero_link(
    project_id: str,
    *,
    api_key: str,
    user_id: str = "",
    username: str = "",
    collection_key: str = "",
    collection_name: str = "",
) -> dict[str, str]:
    koi_root(project_id)
    key = _clean(api_key)
    if not key:
        raise ValueError("Укажите Zotero API Key.")
    link = {
        "user_id": _clean(user_id),
        "api_key": key,
        "username": _clean(username),
        "collection_key": _clean(collection_key, 64),
        "collection_name": _clean(collection_name),
    }
    _write_link_file(account_path(), link)
    return link


def clear_zotero_link(project_id: str) -> None:
    koi_root(project_id)
    account = account_path()
    if account.is_file():
        account.unlink()
    legacy = link_path(project_id)
    if legacy.is_file():
        legacy.unlink()
    for path, _link in _legacy_links():
        if path.is_file():
            path.unlink()
