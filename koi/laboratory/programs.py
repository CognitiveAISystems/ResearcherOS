"""Laboratory and research programs — derived from project frontmatter."""

from __future__ import annotations

import re
from typing import Any, Optional

import yaml

from koi.adapters.paths import project_md
from koi.adapters.project_mount import list_mounts
from koi.core.models import NodeType, Verdict
from koi.adapters.repository import list_projects as list_stored_projects
from koi.adapters.repository import load_project


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta = yaml.safe_load(parts[1]) or {}
    body = parts[2].lstrip("\n")
    return meta, body


def _slugify(title: str) -> str:
    s = title.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s, flags=re.UNICODE)
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:48] or "program"


def parse_program_entries(raw: Any) -> list[dict[str, str]]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [{"id": raw, "title": raw, "description": ""}]
    out: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, dict):
            pid = str(item.get("id") or "").strip()
            if not pid:
                continue
            out.append(
                {
                    "id": pid,
                    "title": str(item.get("title") or pid),
                    "description": str(item.get("description") or ""),
                }
            )
        elif item:
            pid = str(item)
            out.append({"id": pid, "title": pid, "description": ""})
    return out


# Back-compat for internal callers
_parse_program_entries = parse_program_entries


def _read_project_programs(project_id: str) -> list[dict[str, str]]:
    path = project_md(project_id)
    if not path.exists():
        return []
    meta, _ = _split_frontmatter(path.read_text(encoding="utf-8"))
    return _parse_program_entries(meta.get("programs"))


def _build_membership() -> dict[str, set[str]]:
    """program_id -> set of project ids (from project frontmatter only)."""
    membership: dict[str, set[str]] = {}
    for mount in list_mounts():
        for entry in _read_project_programs(mount.project_id):
            membership.setdefault(entry["id"], set()).add(mount.project_id)
    return membership


def _program_meta() -> dict[str, dict[str, str]]:
    """Best-effort program title/description from any project declaring them."""
    meta: dict[str, dict[str, str]] = {}
    for mount in list_mounts():
        for entry in _read_project_programs(mount.project_id):
            pid = entry["id"]
            if pid not in meta or (entry["title"] != pid and meta[pid]["title"] == pid):
                meta[pid] = {
                    "title": entry["title"],
                    "description": entry["description"],
                }
    return meta


def load_laboratory() -> dict[str, Any]:
    programs = [p["id"] for p in list_programs()]
    return {
        "id": "discovered",
        "title": "Laboratory",
        "description": "",
        "programs": programs,
    }


def list_programs() -> list[dict[str, Any]]:
    membership = _build_membership()
    program_meta = _program_meta()
    items: list[dict[str, Any]] = []
    for program_id in sorted(membership):
        meta = program_meta.get(program_id, {})
        project_ids = sorted(membership[program_id])
        items.append(
            {
                "id": program_id,
                "title": meta.get("title", program_id),
                "description": meta.get("description", ""),
                "projects": project_ids,
                "body": "",
            }
        )
    return items


def load_program(program_id: str) -> Optional[dict[str, Any]]:
    for item in list_programs():
        if item["id"] == program_id:
            return item
    return None


def create_program(title: str, description: str = "") -> dict[str, Any]:
    """Register a program id (metadata lives on projects that reference it)."""
    program_id = _slugify(title)
    return {
        "id": program_id,
        "title": title,
        "description": description.strip(),
        "projects": [],
        "body": "",
    }


def add_project_to_program(program_id: str, project_id: str, title: str | None = None) -> dict[str, Any]:
    path = project_md(project_id)
    if not path.exists():
        raise ValueError(f"Project not found: {project_id}")
    text = path.read_text(encoding="utf-8")
    meta, body = _split_frontmatter(text)
    entries = _parse_program_entries(meta.get("programs"))
    if not any(e["id"] == program_id for e in entries):
        entries.append({"id": program_id, "title": (title or program_id).strip() or program_id, "description": ""})
    meta["programs"] = entries
    serialized = (
        "---\n"
        + yaml.dump(meta, allow_unicode=True, sort_keys=False).strip()
        + "\n---\n\n"
        + body
    )
    path.write_text(serialized, encoding="utf-8")
    from koi.adapters.project_mount import rescan_projects

    rescan_projects()
    program = load_program(program_id)
    if program is None:
        raise RuntimeError(f"Failed to reload program {program_id}")
    return program


def _methods_under(nodes, cause_id: str) -> list:
    out = []
    for mid in (n for n in nodes if n.parent_id == cause_id):
        out += [m for m in nodes if m.parent_id == mid.id and m.node_type == NodeType.METHOD]
    return out


def _project_stats(project_id: str) -> Optional[dict[str, Any]]:
    project = load_project(project_id, sync_reports=False)
    if project is None:
        return None
    nodes = project.nodes
    causes = [n for n in nodes if n.node_type == NodeType.CAUSE]
    running = 0
    for board in project.boards:
        for card in board.cards:
            if card.column_id == "running":
                running += 1
    return {
        "id": project.id,
        "title": project.title,
        "description": project.description,
        "hypotheses": len(causes),
        "supported": sum(1 for c in causes if c.verdict == Verdict.SUPPORTED),
        "refuted": sum(1 for c in causes if c.verdict == Verdict.REFUTED),
        "insights": sum(
            len(m.research_questions) for c in causes for m in _methods_under(nodes, c.id)
        ),
        "running_experiments": running,
    }


def program_summary(program_id: str) -> Optional[dict[str, Any]]:
    program = load_program(program_id)
    if program is None:
        return None

    project_stats = []
    totals = {
        "projects": 0,
        "hypotheses": 0,
        "supported": 0,
        "refuted": 0,
        "insights": 0,
        "running_experiments": 0,
    }
    for pid in program["projects"]:
        stats = _project_stats(pid)
        if stats is None:
            continue
        project_stats.append(stats)
        totals["projects"] += 1
        totals["hypotheses"] += stats["hypotheses"]
        totals["supported"] += stats["supported"]
        totals["refuted"] += stats["refuted"]
        totals["insights"] += stats["insights"]
        totals["running_experiments"] += stats["running_experiments"]

    return {**program, "totals": totals, "project_stats": project_stats}


def projects_for_program(program_id: str) -> list[str]:
    program = load_program(program_id)
    return list(program["projects"]) if program else []


def programs_for_project(project_id: str) -> list[str]:
    return [e["id"] for e in _read_project_programs(project_id)]


def enrich_projects(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from koi.projects.composites import read_composite_id

    out: list[dict[str, Any]] = []
    for p in projects:
        cid = read_composite_id(p["id"])
        entry = {**p, "programs": programs_for_project(p["id"])}
        if cid:
            entry["composite_id"] = cid
        out.append(entry)
    return out


def list_project_summaries() -> list[dict[str, Any]]:
    """Project summaries enriched with laboratory and composite membership."""
    return enrich_projects(list_stored_projects())


def grouped_projects() -> dict[str, Any]:
    """Projects grouped by program for UI; unassigned projects go to ``ungrouped``."""
    from koi.projects.composites import list_composites_summary

    all_projects = {p["id"]: p for p in list_project_summaries()}
    composites = list_composites_summary()
    composite_member_ids: set[str] = set()
    for comp in composites:
        composite_member_ids.update(comp.get("member_ids") or [])

    lab = load_laboratory()
    groups: list[dict[str, Any]] = []
    assigned: set[str] = set()

    for program in list_programs():
        projects = []
        program_composites = []
        for comp in composites:
            if program["id"] in (comp.get("programs") or []):
                program_composites.append(comp)
        for project_id in program["projects"]:
            if project_id in all_projects:
                projects.append(all_projects[project_id])
                assigned.add(project_id)
        groups.append(
            {
                "id": program["id"],
                "title": program["title"],
                "description": program["description"],
                "composites": program_composites,
                "projects": projects,
            }
        )

    ungrouped = [p for pid, p in sorted(all_projects.items()) if pid not in assigned]
    return {
        "laboratory": {
            "id": lab["id"],
            "title": lab["title"],
            "description": lab.get("description", ""),
        },
        "composites": composites,
        "groups": groups,
        "ungrouped": ungrouped,
    }
