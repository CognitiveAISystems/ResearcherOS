"""ResearchOS Hub FastAPI application."""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from hub.app.auth import (
    OAUTH_REDIRECT_COOKIE,
    OAUTH_STATE_COOKIE,
    clear_session_cookie,
    get_session,
    oauth_callback,
    oauth_callback_url,
    oauth_login_url,
    require_session,
    set_session_cookie,
)
from hub.app.config import HubConfig
from hub.app.github_client import GitHubClient
from hub.app.koi_loader import project_snapshot, read_koi_meta
from koi.laboratory.programs import parse_program_entries
from hub.app.access import can_view_project_with_store, is_project_listed
from hub.app.link_utils import parse_hub_project_url, project_share_url, project_view_href
from hub.app.koi_readonly import router as koi_readonly_router
from hub.app.running_activity import running_activity_for_project
from hub.app.project_identity import (
    dedupe_hub_projects,
    find_canonical_slug,
    find_project_by_source,
    source_key,
)
from hub.app.store import HubProject, HubStore
from hub.app.skills import (
    public_skills_for_publish,
    skill_file_contents_for_download,
    skill_public_payload,
    skill_to_entry,
)

HUB_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = HUB_ROOT.parent
WEB_ROOT = HUB_ROOT / "web"
CORE_WEB_ROOT = REPO_ROOT / "web"

config = HubConfig.from_env()
store = HubStore(config)

app = FastAPI(title="ResearchOS Hub", version="0.1.0")
app.state.hub_config = config
app.state.hub_store = store
app.include_router(koi_readonly_router)


class RegisterProjectBody(BaseModel):
    repo_full_name: str = Field(..., min_length=3)
    branch: str = Field(default="koi/research")
    visibility: str = Field(default="public")
    title: str = ""


class FollowBody(BaseModel):
    github_id: int


class LinkSubscribeBody(BaseModel):
    url: str = Field(..., min_length=3)


class UpdateProjectBody(BaseModel):
    enabled: Optional[bool] = None


async def _sync_project(project: HubProject, access_token: str) -> dict[str, Any]:
    gh = GitHubClient(access_token)
    tmp = Path(tempfile.mkdtemp(prefix="hub-sync-"))
    try:
        commit = await gh.fetch_koi_structure(
            project.repo_full_name,
            project.branch,
            config.koi_path,
            tmp,
        )
        if commit is None:
            raise HTTPException(
                400,
                f"Could not find {config.koi_path}/project.md on {project.branch}",
            )
        snapshot = project_snapshot(tmp)
        if snapshot is None:
            raise HTTPException(400, "Failed to parse project.md")
        if not project.title:
            project.title = str(snapshot.get("title") or project.slug)
        meta = read_koi_meta(tmp)
        project.composite_id = str(meta.get("composite_id") or "").strip()
        project.programs = parse_program_entries(meta.get("programs"))
        # Snapshot first, then mark sync success. Large reports trees can exceed the
        # serverless time limit — if they run before save_snapshot, Hub keeps a
        # stale kanban while last_commit looks fresh (seen on dophamine_agent).
        synced_at = datetime.now(timezone.utc).isoformat()
        owner = store.get_user(project.owner_github_id)
        payload = {
            "meta": {
                "slug": project.slug,
                "repo_full_name": project.repo_full_name,
                "branch": project.branch,
                "visibility": project.visibility,
                "owner_login": project.owner_login,
                "owner_avatar_url": (owner.avatar_url if owner else "")
                or f"https://avatars.githubusercontent.com/{project.owner_login}?s=64&v=4",
                "composite_id": project.composite_id,
                "programs": project.programs,
                "last_sync_at": synced_at,
            },
            "project": snapshot,
            "running_activity": running_activity_for_project(
                snapshot, author=project.owner_login or "коллега"
            ),
        }
        store.save_snapshot(project.slug, payload)
        project.last_sync_at = synced_at
        project.last_commit = commit or ""
        store.save_project(project)
        # Skills pool: only from enabled public projects; else clear.
        if project.enabled and project.visibility == "public":
            skill_entries = [
                skill_to_entry(
                    skill,
                    project_slug=project.slug,
                    project_title=project.title,
                    owner_login=project.owner_login,
                    repo_full_name=project.repo_full_name,
                    branch=project.branch,
                    synced_at=project.last_sync_at,
                )
                for skill in public_skills_for_publish(tmp)
            ]
            published_ids = store.replace_project_skills(project.slug, skill_entries)
            payload["skills"] = {
                "published": published_ids,
                "count": len(published_ids),
            }
        else:
            store.clear_project_skills(project.slug)
            payload["skills"] = {"published": [], "count": 0}
        # Reports are best-effort: thousands of assets can time out the container.
        reports_src = tmp / "reports"
        try:
            reports_count = store.save_reports_tree(project.slug, reports_src)
            payload["reports"] = {"ok": True, "count": reports_count}
        except Exception as exc:  # noqa: BLE001 — surface partial sync to the owner
            payload["reports"] = {"ok": False, "error": str(exc)[:300]}
        # Master HTML pages (map pins) — usually small; still best-effort.
        pages_src = tmp / "pages"
        try:
            pages_count = store.save_pages_tree(project.slug, pages_src)
            payload["pages"] = {"ok": True, "count": pages_count}
        except Exception as exc:  # noqa: BLE001
            payload["pages"] = {"ok": False, "error": str(exc)[:300]}
        return payload
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "researchos-hub"}


@app.get("/auth/github")
def auth_github(request: Request) -> RedirectResponse:
    redirect_uri = oauth_callback_url(request, config)
    url, state = oauth_login_url(config, redirect_uri=redirect_uri)
    redirect = RedirectResponse(url, status_code=302)
    secure = redirect_uri.startswith("https")
    redirect.set_cookie(
        OAUTH_STATE_COOKIE,
        state,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=600,
    )
    redirect.set_cookie(
        OAUTH_REDIRECT_COOKIE,
        redirect_uri,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=600,
    )
    return redirect


@app.get("/auth/callback")
async def auth_callback(
    request: Request,
    code: str = Query(default=""),
    state: str = Query(default=""),
) -> RedirectResponse:
    if not code:
        raise HTTPException(400, "Missing OAuth code")
    redirect_uri = request.cookies.get(OAUTH_REDIRECT_COOKIE) or oauth_callback_url(request, config)
    try:
        session = await oauth_callback(
            config=config,
            store=store,
            code=code,
            state=state,
            expected_state=request.cookies.get(OAUTH_STATE_COOKIE),
            redirect_uri=redirect_uri,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"GitHub auth failed: {exc}") from exc
    redirect = RedirectResponse("/", status_code=302)
    set_session_cookie(redirect, config, session.session_id)
    redirect.delete_cookie(OAUTH_STATE_COOKIE)
    redirect.delete_cookie(OAUTH_REDIRECT_COOKIE)
    return redirect


@app.post("/auth/logout")
def auth_logout(request: Request, response: Response) -> dict[str, bool]:
    session = get_session(request, config, store)
    if session:
        store.delete_session(session.session_id)
    clear_session_cookie(response)
    return {"ok": True}


@app.get("/api/me")
def api_me(request: Request) -> dict[str, Any]:
    session = get_session(request, config, store)
    if session is None:
        return {"authenticated": False}
    user = store.get_user(session.github_id)
    if user is None:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "user": {
            "github_id": user.github_id,
            "login": user.login,
            "avatar_url": user.avatar_url,
            "discoverable": user.discoverable,
        },
    }


@app.get("/api/repos")
async def api_repos(request: Request) -> dict[str, Any]:
    session = require_session(request, config, store)
    gh = GitHubClient(session.access_token)
    repos = await gh.list_repos()
    out = []
    for repo in repos:
        full_name = str(repo.get("full_name") or "")
        if not full_name:
            continue
        out.append(
            {
                "full_name": full_name,
                "private": bool(repo.get("private")),
                "updated_at": repo.get("updated_at"),
                "default_branch": repo.get("default_branch"),
            }
        )
    return {"repos": out}


def _catalog_project_item(
    project: HubProject,
    snap: Optional[dict[str, Any]],
    *,
    viewer_id: Optional[int],
    following: set[int],
    view_href: Optional[str] = None,
    saved_by_link: bool = False,
) -> dict[str, Any]:
    is_self = viewer_id is not None and project.owner_github_id == viewer_id
    is_following = is_self or (
        viewer_id is not None and project.owner_github_id in following
    )
    likes = store.get_likes(project.slug)
    href = view_href or project_view_href(project)
    return {
        "slug": project.slug,
        "title": project.title,
        "owner_login": project.owner_login,
        "owner_github_id": project.owner_github_id,
        "repo_full_name": project.repo_full_name,
        "branch": project.branch,
        "visibility": project.visibility,
        "last_sync_at": project.last_sync_at,
        "is_following": is_following,
        "is_self": is_self,
        "view_href": href,
        "saved_by_link": saved_by_link,
        "like_count": likes["count"],
        "liked_by_me": bool(
            viewer_id is not None and viewer_id in likes["user_ids"]
        ),
        "preview": {
            "node_count": len((snap or {}).get("project", {}).get("nodes", [])),
        },
    }


@app.get("/api/catalog/public")
def catalog_public(request: Request) -> dict[str, Any]:
    session = get_session(request, config, store)
    viewer_id = session.github_id if session else None
    following = store.following_ids(viewer_id) if viewer_id else set()
    items = []
    candidates = [
        p
        for p in store.list_projects()
        if p.visibility == "public" and is_project_listed(p)
    ]
    for project in dedupe_hub_projects(candidates):
        snap = store.get_snapshot(project.slug)
        items.append(_catalog_project_item(project, snap, viewer_id=viewer_id, following=following))
    items.sort(key=lambda x: x.get("last_sync_at") or "", reverse=True)
    return {"projects": items}


@app.get("/api/catalog/network")
def catalog_network(request: Request) -> dict[str, Any]:
    session = require_session(request, config, store)
    following = store.following_ids(session.github_id)
    by_slug: dict[str, HubProject] = {}
    item_meta: dict[str, dict[str, Any]] = {}

    for project in store.list_projects():
        if project.visibility == "unlisted" or not is_project_listed(project):
            continue
        if project.visibility == "public" or (
            project.visibility == "network"
            and (
                project.owner_github_id == session.github_id
                or project.owner_github_id in following
            )
        ):
            by_slug[project.slug] = project

    for bookmark in store.user_bookmarks(session.github_id):
        slug = bookmark["slug"]
        token = bookmark.get("token") or ""
        project = store.get_project(slug)
        if project is None or not project.enabled:
            continue
        if project.visibility == "unlisted":
            if not token or token != project.secret_token:
                continue
            by_slug[slug] = project
            item_meta[slug] = {
                "view_href": project_view_href(project, token),
                "saved_by_link": True,
            }
            continue
        if project.visibility == "network" and (
            project.owner_github_id != session.github_id
            and project.owner_github_id not in following
        ):
            continue
        by_slug[slug] = project
        item_meta[slug] = {
            "view_href": project_view_href(project, token or None),
            "saved_by_link": True,
        }

    items = []
    for project in dedupe_hub_projects(list(by_slug.values())):
        snap = store.get_snapshot(project.slug)
        meta = item_meta.get(project.slug, {})
        items.append(
            _catalog_project_item(
                project,
                snap,
                viewer_id=session.github_id,
                following=following,
                view_href=meta.get("view_href"),
                saved_by_link=bool(meta.get("saved_by_link")),
            )
        )
    items.sort(key=lambda x: x.get("last_sync_at") or "", reverse=True)
    return {"projects": items}


@app.post("/api/subscriptions/by-link")
def subscribe_by_link(request: Request, body: LinkSubscribeBody) -> dict[str, Any]:
    session = require_session(request, config, store)
    try:
        slug, token = parse_hub_project_url(body.url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    project = store.get_project(slug)
    if project is None or not project.enabled:
        raise HTTPException(404, "Project not found")

    if project.owner_github_id == session.github_id:
        store.add_bookmark(session.github_id, slug, token or "")
        return {
            "ok": True,
            "slug": slug,
            "title": project.title,
            "view_href": project_view_href(project, token or None),
            "already_saved": True,
        }

    if project.visibility == "unlisted":
        if not token or token != project.secret_token:
            raise HTTPException(403, "Invalid or missing token for unlisted project")
    elif project.visibility == "network":
        store.add_follow(session.github_id, project.owner_github_id)
    elif project.visibility != "public":
        raise HTTPException(403, "Cannot add this project")

    created = store.add_bookmark(session.github_id, slug, token or "")
    return {
        "ok": True,
        "slug": slug,
        "title": project.title,
        "view_href": project_view_href(project, token or None),
        "already_saved": not created,
    }


@app.get("/api/users/discoverable")
def users_discoverable() -> dict[str, Any]:
    users = [
        {
            "github_id": u.github_id,
            "login": u.login,
            "avatar_url": u.avatar_url,
        }
        for u in store.list_users()
        if u.discoverable
    ]
    return {"users": users}


@app.post("/api/follow")
def api_follow(request: Request, body: FollowBody) -> dict[str, bool]:
    session = require_session(request, config, store)
    if body.github_id == session.github_id:
        raise HTTPException(400, "Cannot follow yourself")
    if store.get_user(body.github_id) is None:
        raise HTTPException(404, "User not found")
    store.add_follow(session.github_id, body.github_id)
    return {"ok": True}


@app.post("/api/projects/{slug}/like")
def api_toggle_like(
    request: Request,
    slug: str,
    token: Optional[str] = Query(default=None),
) -> dict[str, Any]:
    session = require_session(request, config, store)
    project = store.get_project(slug)
    if project is None or not project.enabled:
        raise HTTPException(404, "Project not found")
    if not can_view_project_with_store(project, session.github_id, store, token=token):
        raise HTTPException(403, "Not allowed to like this project")
    result = store.toggle_like(session.github_id, project.slug)
    return {"ok": True, "slug": project.slug, **result}


@app.get("/api/projects/mine")
def projects_mine(request: Request) -> dict[str, Any]:
    session = require_session(request, config, store)
    items = []
    for p in store.list_projects():
        if p.owner_github_id != session.github_id:
            continue
        likes = store.get_likes(p.slug)
        items.append(
            {
                "slug": p.slug,
                "title": p.title,
                "repo_full_name": p.repo_full_name,
                "branch": p.branch,
                "visibility": p.visibility,
                "enabled": p.enabled,
                "is_canonical": find_canonical_slug(store, p) == p.slug,
                "canonical_slug": find_canonical_slug(store, p),
                "secret_token": p.secret_token if p.visibility == "unlisted" else None,
                "share_url": project_share_url(config, p),
                "last_sync_at": p.last_sync_at,
                "view_url": f"/p/{p.slug}",
                "view_href": project_view_href(p),
                "like_count": likes["count"],
                "liked_by_me": session.github_id in likes["user_ids"],
            }
        )
    return {"projects": items}


@app.post("/api/projects")
async def register_project(request: Request, body: RegisterProjectBody) -> dict[str, Any]:
    session = require_session(request, config, store)
    user = store.get_user(session.github_id)
    if user is None:
        raise HTTPException(401, "User missing")

    visibility = body.visibility.lower().strip()
    if visibility not in {"public", "network", "unlisted"}:
        raise HTTPException(400, "visibility must be public, network, or unlisted")

    repo = body.repo_full_name.strip()
    if "/" not in repo:
        raise HTTPException(400, "repo_full_name must be owner/name")

    branch = body.branch.strip() or config.default_branch
    gh = GitHubClient(session.access_token)
    if not await gh.branch_exists(repo, branch):
        raise HTTPException(400, f"Branch {branch} not found in {repo}")

    existing = find_project_by_source(store, user.github_id, repo, branch)
    if existing is not None:
        if not existing.enabled:
            existing.enabled = True
            store.save_project(existing)
        payload = await _sync_project(existing, session.access_token)
        return {
            "ok": True,
            "slug": existing.slug,
            "title": existing.title,
            "visibility": existing.visibility,
            "secret_token": existing.secret_token if existing.visibility == "unlisted" else None,
            "view_url": f"/p/{existing.slug}",
            "reused_existing": True,
        }

    slug = HubStore.new_slug(body.title, repo)
    project = HubProject(
        slug=slug,
        owner_github_id=user.github_id,
        owner_login=user.login,
        repo_full_name=repo,
        branch=branch,
        title=body.title.strip(),
        visibility=visibility,
        secret_token=HubStore.new_secret() if visibility == "unlisted" else "",
    )
    store.save_project(project)
    payload = await _sync_project(project, session.access_token)
    return {
        "ok": True,
        "slug": project.slug,
        "title": project.title,
        "visibility": project.visibility,
        "secret_token": project.secret_token if project.visibility == "unlisted" else None,
        "view_url": f"/p/{project.slug}",
    }


@app.delete("/api/projects/{slug}")
def delete_project(request: Request, slug: str) -> dict[str, bool]:
    session = require_session(request, config, store)
    project = store.get_project(slug)
    if project is None:
        raise HTTPException(404, "Project not found")
    if project.owner_github_id != session.github_id:
        raise HTTPException(403, "Only the owner can delete this project")
    canonical = find_canonical_slug(store, project)
    if canonical == project.slug and project.enabled:
        siblings = [
            p
            for p in store.list_projects()
            if p.owner_github_id == session.github_id
            and source_key(p.repo_full_name, p.branch)
            == source_key(project.repo_full_name, project.branch)
            and p.slug != project.slug
        ]
        if not siblings:
            raise HTTPException(
                400,
                "Нельзя удалить единственную регистрацию — отключите проект вместо удаления",
            )
    store.delete_project(slug)
    return {"ok": True}


@app.patch("/api/projects/{slug}")
def update_project(request: Request, slug: str, body: UpdateProjectBody) -> dict[str, Any]:
    session = require_session(request, config, store)
    project = store.get_project(slug)
    if project is None:
        raise HTTPException(404, "Project not found")
    if project.owner_github_id != session.github_id:
        raise HTTPException(403, "Only the owner can update this project")
    if body.enabled is None:
        raise HTTPException(400, "Nothing to update")
    project.enabled = bool(body.enabled)
    store.save_project(project)
    if not project.enabled or project.visibility != "public":
        store.clear_project_skills(project.slug)
    return {
        "ok": True,
        "slug": project.slug,
        "enabled": project.enabled,
    }


@app.post("/api/projects/{slug}/sync")
async def resync_project(request: Request, slug: str) -> dict[str, Any]:
    session = require_session(request, config, store)
    project = store.get_project(slug)
    if project is None:
        raise HTTPException(404, "Project not found")
    if project.owner_github_id != session.github_id:
        raise HTTPException(403, "Only the owner can sync")
    payload = await _sync_project(project, session.access_token)
    return {"ok": True, "project": payload["project"]}


@app.get("/api/projects/{slug}")
def get_project(
    request: Request,
    slug: str,
    token: Optional[str] = Query(default=None),
) -> dict[str, Any]:
    project = store.get_project(slug)
    if project is None:
        raise HTTPException(404, "Project not found")

    session = get_session(request, config, store)
    viewer_id = session.github_id if session else None

    if not can_view_project_with_store(project, viewer_id, store, token=token):
        # Unlisted: hide existence unless token / owner / bookmark grants access.
        if project.visibility == "unlisted" or (
            not project.enabled and project.owner_github_id != viewer_id
        ):
            raise HTTPException(404, "Project not found")
        raise HTTPException(403, "Not allowed to view this project")

    snap = store.get_snapshot(slug)
    if snap is None:
        raise HTTPException(404, "Snapshot missing — owner should sync")
    # Enrich avatar for UI without requiring a re-sync.
    meta = snap.get("meta") if isinstance(snap.get("meta"), dict) else {}
    if not meta.get("owner_avatar_url"):
        owner = store.get_user(project.owner_github_id)
        avatar = (owner.avatar_url if owner else "") or (
            f"https://avatars.githubusercontent.com/{project.owner_login}?s=64&v=4"
            if project.owner_login
            else ""
        )
        if avatar:
            snap = {
                **snap,
                "meta": {
                    **meta,
                    "owner_login": meta.get("owner_login") or project.owner_login,
                    "owner_avatar_url": avatar,
                },
            }
    return snap


@app.get("/api/catalog/skills")
def catalog_skills() -> dict[str, Any]:
    """Global pool of skills published from public Hub projects."""
    items = store.list_skills_catalog()
    return {"skills": items, "count": len(items)}


@app.get("/api/skills/{project_slug}/{skill_id}")
def get_skill(project_slug: str, skill_id: str) -> dict[str, Any]:
    project = store.get_project(project_slug)
    if project is None or not project.enabled or project.visibility != "public":
        raise HTTPException(404, "Skill not found")
    entry = store.get_skill(project_slug, skill_id)
    if entry is None:
        raise HTTPException(404, "Skill not found")
    return skill_public_payload(entry)


@app.get("/api/skills/{project_slug}/{skill_id}/download")
def download_skill(project_slug: str, skill_id: str) -> Response:
    """Download the skill package as a zip (all text files from sync)."""
    import io
    import zipfile

    project = store.get_project(project_slug)
    if project is None or not project.enabled or project.visibility != "public":
        raise HTTPException(404, "Skill not found")
    entry = store.get_skill(project_slug, skill_id)
    if entry is None:
        raise HTTPException(404, "Skill not found")

    contents = skill_file_contents_for_download(entry)
    if not contents:
        raise HTTPException(404, "Skill package is empty")

    buf = io.BytesIO()
    root = str(entry.get("id") or skill_id)
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel, text in sorted(contents.items()):
            zf.writestr(f"{root}/{rel}", text.encode("utf-8"))
    data = buf.getvalue()
    filename = f"{root}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(data)),
        },
    )


@app.get("/", response_class=HTMLResponse)
def index_page() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")


@app.get("/skills", response_class=HTMLResponse)
def skills_catalog_page() -> FileResponse:
    return FileResponse(WEB_ROOT / "skills.html")


@app.get("/skills/{project_slug}/{skill_id}", response_class=HTMLResponse)
def skill_detail_page(project_slug: str, skill_id: str) -> FileResponse:
    return FileResponse(WEB_ROOT / "skill.html")


@app.get("/connect", response_class=HTMLResponse)
def connect_page() -> FileResponse:
    return FileResponse(WEB_ROOT / "connect.html")


@app.get("/manage")
def manage_page() -> RedirectResponse:
    return RedirectResponse(url="/?tab=mine", status_code=302)


@app.get("/p/{slug}", response_class=HTMLResponse)
def project_page(slug: str) -> FileResponse:
    # Relative asset misses (app.js, styles.css) must not be treated as projects.
    if "." in slug or slug in {"app.js", "styles.css"}:
        raise HTTPException(404, "Not found")
    index = CORE_WEB_ROOT / "index.html"
    if not index.exists():
        raise HTTPException(503, "Core web UI not found")
    return FileResponse(index)


if CORE_WEB_ROOT.exists():
    app.mount("/core", StaticFiles(directory=CORE_WEB_ROOT), name="core")

if WEB_ROOT.exists():
    app.mount("/static", StaticFiles(directory=WEB_ROOT), name="static")
