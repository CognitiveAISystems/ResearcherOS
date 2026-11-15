"""Zotero Web API helpers for Literature page connect + import."""

from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import certifi

from koi.literature.library import _normalize_spaces, infer_year_from_arxiv_url

ZOTERO_API_BASE = "https://api.zotero.org"
ARXIV_ID_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf|html)/|arxiv[:\s]+)(\d{2}\d{2}\.\d{4,5})",
    re.IGNORECASE,
)
YEAR_RE = re.compile(r"(19|20)\d{2}")


class ZoteroAuthError(ValueError):
    """Invalid credentials or insufficient library access."""


class ZoteroApiError(RuntimeError):
    """Upstream Zotero API failure."""


def _request_json(
    path: str,
    *,
    api_key: str,
    params: dict[str, str] | None = None,
) -> tuple[Any, dict[str, str]]:
    query = urllib.parse.urlencode(params or {})
    url = f"{ZOTERO_API_BASE}{path}"
    if query:
        url = f"{url}?{query}"
    request = urllib.request.Request(
        url,
        headers={
            "Zotero-API-Key": api_key,
            "Accept": "application/json",
            "User-Agent": "ResearchOS/1.0 (literature-zotero)",
        },
        method="GET",
    )
    try:
        context = ssl.create_default_context()
        context.load_verify_locations(cafile=certifi.where())
        with urllib.request.urlopen(request, timeout=30, context=context) as response:
            body = response.read().decode("utf-8")
            headers = {k.lower(): v for k, v in response.headers.items()}
            return json.loads(body) if body else None, headers
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        if error.code in {401, 403}:
            raise ZoteroAuthError(
                "Zotero отклонил ключ. Проверьте API Key и доступ к библиотеке (library access)."
            ) from error
        if error.code == 404:
            raise ZoteroAuthError(
                "Zotero не нашёл библиотеку. Проверьте User ID или создайте новый API Key."
            ) from error
        raise ZoteroApiError(f"Zotero API error {error.code}: {detail[:240]}") from error
    except urllib.error.URLError as error:
        raise ZoteroApiError(f"Не удалось связаться с Zotero API: {error}") from error


def verify_zotero_credentials(
    *,
    api_key: str,
    user_id: str | None = None,
) -> dict[str, object]:
    key = _normalize_spaces(api_key)
    if not key:
        raise ZoteroAuthError("Укажите Zotero API Key.")

    payload, _headers = _request_json(f"/keys/{urllib.parse.quote(key)}", api_key=key)
    if not isinstance(payload, dict):
        raise ZoteroApiError("Неожиданный ответ Zotero при проверке ключа.")

    resolved_user_id = str(payload.get("userID") or payload.get("userId") or "").strip()
    if user_id:
        provided = str(user_id).strip()
        if resolved_user_id and provided and provided != resolved_user_id:
            raise ZoteroAuthError(
                f"User ID не совпадает с ключом (ожидался {resolved_user_id})."
            )
        if not resolved_user_id:
            resolved_user_id = provided
    if not resolved_user_id:
        raise ZoteroAuthError(
            "Не удалось определить User ID. Укажите его вручную со страницы zotero.org/settings/keys."
        )

    access = payload.get("access") if isinstance(payload.get("access"), dict) else {}
    user_access = access.get("user") if isinstance(access.get("user"), dict) else {}
    library_ok = bool(user_access.get("library"))
    if not library_ok:
        # Still allow connect if /users/{id}/items works; some key payloads omit flags.
        try:
            _request_json(
                f"/users/{urllib.parse.quote(resolved_user_id)}/items/top",
                api_key=key,
                params={"limit": "1"},
            )
            library_ok = True
        except ZoteroAuthError:
            raise ZoteroAuthError(
                "У ключа нет доступа к личной библиотеке. Создайте ключ с «Allow library access»."
            ) from None

    username = str(payload.get("username") or "").strip()
    return {
        "ok": True,
        "user_id": resolved_user_id,
        "username": username,
        "library_access": library_ok,
        "key_name": str(payload.get("name") or "").strip(),
    }


def _format_authors(creators: object) -> str:
    if not isinstance(creators, list):
        return ""
    names: list[str] = []
    for creator in creators:
        if not isinstance(creator, dict):
            continue
        first = _normalize_spaces(str(creator.get("firstName") or ""))
        last = _normalize_spaces(str(creator.get("lastName") or ""))
        name = _normalize_spaces(str(creator.get("name") or ""))
        if first or last:
            names.append(" ".join(part for part in (first, last) if part))
        elif name:
            names.append(name)
    return ", ".join(names)


def _year_from_date(value: object) -> int | None:
    text = _normalize_spaces(str(value or ""))
    if not text:
        return None
    match = YEAR_RE.search(text)
    if not match:
        return None
    year = int(match.group(0))
    if 1900 <= year <= 2100:
        return year
    return None


def _arxiv_url_from_text(*parts: str) -> str | None:
    blob = " ".join(part for part in parts if part)
    match = ARXIV_ID_RE.search(blob)
    if not match:
        return None
    return f"https://arxiv.org/abs/{match.group(1)}"


def _paper_url(data: dict[str, Any], *, item_key: str, user_id: str) -> str:
    title = _normalize_spaces(str(data.get("title") or ""))
    url = _normalize_spaces(str(data.get("url") or ""))
    extra = _normalize_spaces(str(data.get("extra") or ""))
    doi = _normalize_spaces(str(data.get("DOI") or data.get("doi") or ""))
    arxiv = _arxiv_url_from_text(url, extra, title)
    if arxiv:
        return arxiv
    if url and "arxiv.org" in url.lower():
        return url
    if doi:
        doi_path = doi.removeprefix("https://doi.org/").removeprefix("http://doi.org/")
        return f"https://doi.org/{doi_path}"
    if url:
        return url
    return f"https://www.zotero.org/users/{user_id}/items/{item_key}"


def _item_to_paper(item: dict[str, Any], *, user_id: str) -> dict[str, object] | None:
    data = item.get("data") if isinstance(item.get("data"), dict) else item
    if not isinstance(data, dict):
        return None
    item_type = str(data.get("itemType") or "")
    if item_type in {"attachment", "note", "annotation"}:
        return None
    title = _normalize_spaces(str(data.get("title") or ""))
    if not title:
        return None
    item_key = str(item.get("key") or data.get("key") or "").strip()
    authors = _format_authors(data.get("creators"))
    abstract = _normalize_spaces(str(data.get("abstractNote") or ""))
    paper_url = _paper_url(data, item_key=item_key or "item", user_id=user_id)
    year = _year_from_date(data.get("date")) or infer_year_from_arxiv_url(paper_url)
    preview = abstract
    if len(preview) > 280:
        preview = preview[:279].rstrip() + "…"
    return {
        "title": title,
        "arxiv_url": paper_url,
        "authors": authors,
        "year": year,
        "abstract": abstract,
        "abstract_preview": preview,
        "source": "zotero",
        "zotero_key": item_key,
    }


def _collection_name(data: dict[str, Any]) -> str:
    return _normalize_spaces(str(data.get("name") or "")) or "(без названия)"


def _flatten_collections(raw: list[dict[str, Any]]) -> list[dict[str, object]]:
    """Build a depth-indented list of collections (parents before children)."""
    by_key: dict[str, dict[str, Any]] = {}

    for item in raw:
        if not isinstance(item, dict):
            continue
        data = item.get("data") if isinstance(item.get("data"), dict) else item
        if not isinstance(data, dict):
            continue
        key = str(item.get("key") or data.get("key") or "").strip()
        if not key:
            continue
        parent_raw = data.get("parentCollection")
        if parent_raw is False or parent_raw is None:
            parent = ""
        else:
            parent = _normalize_spaces(str(parent_raw or ""))
            if parent in {"false", "0", "None"}:
                parent = ""
        by_key[key] = {
            "key": key,
            "name": _collection_name(data),
            "parent": parent,
        }

    children: dict[str, list[str]] = {key: [] for key in by_key}
    roots: list[str] = []
    for key, meta in by_key.items():
        parent = str(meta["parent"] or "")
        if parent and parent in by_key:
            children[parent].append(key)
        else:
            roots.append(key)

    for parent_key in children:
        children[parent_key].sort(key=lambda k: str(by_key[k]["name"]).lower())
    roots.sort(key=lambda k: str(by_key[k]["name"]).lower())

    flat: list[dict[str, object]] = []

    def walk(key: str, depth: int) -> None:
        meta = by_key.get(key)
        if not meta:
            return
        flat.append(
            {
                "key": key,
                "name": meta["name"],
                "parent_key": meta["parent"] or None,
                "depth": depth,
                "label": f"{' ' * depth}{meta['name']}",
            }
        )
        for child in children.get(key, []):
            walk(child, depth + 1)

    for root in roots:
        walk(root, 0)
    return flat


def list_zotero_collections(
    *,
    api_key: str,
    user_id: str | None = None,
) -> dict[str, object]:
    verified = verify_zotero_credentials(api_key=api_key, user_id=user_id)
    resolved_user_id = str(verified["user_id"])
    key = _normalize_spaces(api_key)

    raw: list[dict[str, Any]] = []
    start = 0
    page_size = 100
    while True:
        payload, headers = _request_json(
            f"/users/{urllib.parse.quote(resolved_user_id)}/collections",
            api_key=key,
            params={
                "limit": str(page_size),
                "start": str(start),
                "sort": "title",
                "direction": "asc",
            },
        )
        if not isinstance(payload, list):
            raise ZoteroApiError("Неожиданный ответ Zotero при загрузке папок.")
        for item in payload:
            if isinstance(item, dict):
                raw.append(item)
        if len(payload) < page_size:
            break
        total_header = headers.get("total-results")
        start += page_size
        if total_header and total_header.isdigit() and start >= int(total_header):
            break
        if start > 2000:
            break

    collections = _flatten_collections(raw)
    return {
        "ok": True,
        "user_id": resolved_user_id,
        "username": verified.get("username") or "",
        "count": len(collections),
        "collections": collections,
    }


def fetch_zotero_papers(
    *,
    api_key: str,
    user_id: str | None = None,
    limit: int = 50,
    collection_key: str | None = None,
) -> dict[str, object]:
    verified = verify_zotero_credentials(api_key=api_key, user_id=user_id)
    resolved_user_id = str(verified["user_id"])
    key = _normalize_spaces(api_key)
    capped = max(1, min(int(limit or 50), 100))
    collection = _normalize_spaces(str(collection_key or ""))
    if collection:
        items_path = (
            f"/users/{urllib.parse.quote(resolved_user_id)}"
            f"/collections/{urllib.parse.quote(collection)}/items/top"
        )
    else:
        items_path = f"/users/{urllib.parse.quote(resolved_user_id)}/items/top"

    payload, headers = _request_json(
        items_path,
        api_key=key,
        params={
            "limit": str(capped),
            "sort": "dateModified",
            "direction": "desc",
            "include": "data",
        },
    )
    if not isinstance(payload, list):
        raise ZoteroApiError("Неожиданный ответ Zotero при загрузке статей.")

    papers: list[dict[str, object]] = []
    seen_urls: set[str] = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        paper = _item_to_paper(item, user_id=resolved_user_id)
        if not paper:
            continue
        url = str(paper["arxiv_url"])
        if url in seen_urls:
            continue
        seen_urls.add(url)
        papers.append(paper)

    total_header = headers.get("total-results")
    total = int(total_header) if total_header and total_header.isdigit() else len(papers)
    return {
        "ok": True,
        "user_id": resolved_user_id,
        "username": verified.get("username") or "",
        "collection_key": collection or None,
        "count": len(papers),
        "total_available": total,
        "papers": papers,
    }
