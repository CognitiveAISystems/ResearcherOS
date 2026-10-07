from __future__ import annotations

import csv
import io

from fastapi import APIRouter, File, HTTPException, UploadFile

from api.deps import workspace_relative
from api.schemas import (
    LibraryDiscoverBody,
    LiteratureSearchBody,
    ReviewSetBody,
    TranslateToEnglishBody,
    ZoteroCollectionsBody,
    ZoteroConnectBody,
    ZoteroImportBody,
    LiteratureSelectionBody,
    ZoteroLinkBody,
)
from koi.literature import review_sets
from koi.projects.views import project_to_client
from koi.literature import (
    LIBRARY_REQUIRED_FIELDS,
    LIBRARY_UPLOAD_PATH,
    bootstrap_library_from_arxiv,
    discover_library_with_agent,
    library_csv_exists,
    list_library_papers,
    reset_library_cache,
    resolve_library_csv,
    search_arxiv_internet,
    search_library,
    translate_to_english,
)
from koi.literature.zotero import (
    ZoteroApiError,
    ZoteroAuthError,
    fetch_zotero_papers,
    list_zotero_collections,
    verify_zotero_credentials,
)
from koi.literature.selection import read_selection, write_selection
from koi.literature.zotero_link import clear_zotero_link, read_zotero_link, write_zotero_link

router = APIRouter(tags=["library"])


@router.get("/library/status")
def get_library_status() -> dict[str, object]:
    exists = library_csv_exists()
    csv_path = None
    if exists:
        try:
            csv_path = workspace_relative(resolve_library_csv())
        except FileNotFoundError:
            exists = False
    return {
        "exists": exists,
        "csv_path": csv_path,
        "upload_path": workspace_relative(LIBRARY_UPLOAD_PATH),
    }


@router.get("/library/papers")
def get_library_papers(limit: int | None = None) -> dict[str, object]:
    papers = list_library_papers(limit=limit)
    csv_path = None
    if library_csv_exists():
        try:
            csv_path = workspace_relative(resolve_library_csv())
        except FileNotFoundError:
            csv_path = None
    return {
        "count": len(papers),
        "papers": papers,
        "source": {
            "csv_path": csv_path,
            "fields": ["no", "arxiv_url", "title", "authors", "abstract"],
        },
    }


@router.post("/library/search")
def post_library_search(body: LiteratureSearchBody) -> dict[str, object]:
    query = body.query.strip()
    if not query:
        raise HTTPException(400, "Query must not be empty")
    try:
        library_csv = resolve_library_csv()
    except FileNotFoundError as e:
        raise HTTPException(
            503,
            "Library CSV was not found. Upload a CSV or use the separate library refresh button to rebuild the current database.",
        ) from e
    results = search_library(query, limit=body.limit)
    return {
        "query": query,
        "count": len(results),
        "results": results,
        "source": {
            "csv_path": workspace_relative(library_csv),
            "fields": ["no", "arxiv_url", "title", "authors", "abstract"],
            "required_fields": ["arxiv_url", "title"],
            "ranking_fields": ["title", "abstract"],
            "method": "hybrid title+abstract lexical ranking",
        },
    }


@router.post("/library/search-internet")
def post_library_search_internet(body: LiteratureSearchBody) -> dict[str, object]:
    query = body.query.strip()
    if not query:
        raise HTTPException(400, "Query must not be empty")
    results = search_arxiv_internet(query, limit=body.limit)
    return {
        "query": query,
        "count": len(results),
        "results": results,
        "papers": [
            {
                "title": result["title"],
                "arxiv_url": result["arxiv_url"],
                "authors": result.get("authors", ""),
                "abstract": result.get("abstract", ""),
            }
            for result in results
        ],
        "source": {
            "method": "arxiv_api",
            "url": "export.arxiv.org/api/query",
            "ranking_fields": ["title", "abstract"],
        },
    }


@router.post("/library/discover")
def post_library_discover(body: LibraryDiscoverBody) -> dict[str, object]:
    query = body.query.strip()
    if not query:
        raise HTTPException(400, "Query must not be empty")
    try:
        return discover_library_with_agent(query, limit=body.limit)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except RuntimeError:
        try:
            return bootstrap_library_from_arxiv(query, limit=body.limit)
        except (ValueError, RuntimeError) as e:
            raise HTTPException(503, str(e)) from e


@router.post("/agent/translate-to-english")
def post_translate_to_english(body: TranslateToEnglishBody) -> dict[str, object]:
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Text must not be empty")
    translated, backend = translate_to_english(text)
    if not translated:
        raise HTTPException(400, "Text must not be empty")
    return {
        "source_text": text,
        "translated_text": translated,
        "backend": backend,
    }


@router.post("/library/upload")
async def post_library_upload(file: UploadFile = File(...)) -> dict[str, object]:
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise HTTPException(400, "Library CSV must be UTF-8 encoded") from e

    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
    except csv.Error as e:
        raise HTTPException(400, f"Invalid CSV: {e}") from e

    fieldnames = tuple(reader.fieldnames or ())
    missing = [field for field in LIBRARY_REQUIRED_FIELDS if field not in fieldnames]
    if missing:
        raise HTTPException(
            400,
            f"Library CSV is missing required columns: {', '.join(missing)}",
        )

    row_count = 0
    try:
        for row_count, _row in enumerate(reader, start=1):
            pass
    except csv.Error as e:
        raise HTTPException(400, f"Invalid CSV row format: {e}") from e

    if row_count == 0:
        raise HTTPException(400, "Library CSV must contain at least one paper row")

    LIBRARY_UPLOAD_PATH.parent.mkdir(parents=True, exist_ok=True)
    LIBRARY_UPLOAD_PATH.write_bytes(data)
    reset_library_cache()

    return {
        "ok": True,
        "csv_path": workspace_relative(LIBRARY_UPLOAD_PATH),
        "count": row_count,
        "fields": list(fieldnames),
        "required_fields": list(LIBRARY_REQUIRED_FIELDS),
        "filename": file.filename or LIBRARY_UPLOAD_PATH.name,
    }


@router.post("/library/zotero/connect")
def post_library_zotero_connect(body: ZoteroConnectBody) -> dict[str, object]:
    try:
        return verify_zotero_credentials(api_key=body.api_key, user_id=body.user_id)
    except ZoteroAuthError as error:
        raise HTTPException(401, str(error)) from error
    except ZoteroApiError as error:
        raise HTTPException(502, str(error)) from error


@router.post("/library/zotero/collections")
def post_library_zotero_collections(body: ZoteroCollectionsBody) -> dict[str, object]:
    try:
        return list_zotero_collections(api_key=body.api_key, user_id=body.user_id)
    except ZoteroAuthError as error:
        raise HTTPException(401, str(error)) from error
    except ZoteroApiError as error:
        raise HTTPException(502, str(error)) from error


@router.post("/library/zotero/import")
def post_library_zotero_import(body: ZoteroImportBody) -> dict[str, object]:
    try:
        return fetch_zotero_papers(
            api_key=body.api_key,
            user_id=body.user_id,
            limit=body.limit,
            collection_key=body.collection_key,
        )
    except ZoteroAuthError as error:
        raise HTTPException(401, str(error)) from error
    except ZoteroApiError as error:
        raise HTTPException(502, str(error)) from error


def _zotero_link_payload(link: dict[str, str] | None) -> dict[str, object]:
    if link is None:
        return {"linked": False}
    return {"linked": True, **link}


@router.get("/projects/{project_id}/zotero")
def get_project_zotero(project_id: str) -> dict[str, object]:
    try:
        return _zotero_link_payload(read_zotero_link(project_id))
    except KeyError as error:
        raise HTTPException(404, str(error)) from error


@router.put("/projects/{project_id}/zotero")
def put_project_zotero(project_id: str, body: ZoteroLinkBody) -> dict[str, object]:
    try:
        link = write_zotero_link(
            project_id,
            api_key=body.api_key,
            user_id=body.user_id,
            username=body.username,
            collection_key=body.collection_key,
            collection_name=body.collection_name,
        )
    except KeyError as error:
        raise HTTPException(404, str(error)) from error
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return _zotero_link_payload(link)


@router.delete("/projects/{project_id}/zotero")
def delete_project_zotero(project_id: str) -> dict[str, object]:
    try:
        clear_zotero_link(project_id)
    except KeyError as error:
        raise HTTPException(404, str(error)) from error
    return {"linked": False}


@router.get("/projects/{project_id}/literature/selection")
def get_literature_selection(project_id: str) -> dict[str, object]:
    try:
        return {"papers": read_selection(project_id)}
    except KeyError as error:
        raise HTTPException(404, str(error)) from error


@router.put("/projects/{project_id}/literature/selection")
def put_literature_selection(project_id: str, body: LiteratureSelectionBody) -> dict[str, object]:
    try:
        papers = write_selection(project_id, [paper.model_dump() for paper in body.papers])
    except KeyError as error:
        raise HTTPException(404, str(error)) from error
    return {"papers": papers}


@router.post("/library/review-set")
def post_library_review_set(body: ReviewSetBody) -> dict[str, object]:
    try:
        result = review_sets.create_review_set(
            review_sets.CreateReviewSetCommand(
                query=body.query,
                limit=body.limit,
                papers=body.papers,
            )
        )
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except RuntimeError as error:
        raise HTTPException(500, str(error)) from error

    return {
        "project": project_to_client(result.project),
        "query": result.query,
        "count": result.count,
    }
