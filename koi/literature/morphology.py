"""Article morphology: stage one paper for graph-of-transitions analysis.

Mirrors the literature-cluster staging flow (``cluster_orch.stage_literature_cluster``)
but keys runs on a single paper instead of a research question. The agent side of the
contract lives in ``.cursor/skills/article-morphology/SKILL.md``.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from koi.adapters.paths import paper_morphology_dir
from koi.adapters.workspace import get_workspace
from koi.literature.morphology_math import add_rendered_mathml
from koi.literature.naming import normalize_spaces

SKILL_PATH = ".cursor/skills/article-morphology/SKILL.md"

#: Files the agent writes; presence of ``morphology.json`` flips a run to ``ready``.
MORPHOLOGY_FILENAME = "morphology.json"
MATH_ANALYSIS_FILENAME = "math_analysis.json"
CLAIMS_FILENAME = "claims.json"
REPORT_FILENAME = "report.md"
REQUIRED_ARTIFACTS = (MORPHOLOGY_FILENAME, MATH_ANALYSIS_FILENAME)

#: Preferred article sources for the in-page viewer (first hit wins).
_ARTICLE_HTML_NAMES = ("article.html", "source.html")
_ARTICLE_TEXT_NAMES = (
    "source_normalized.txt",
    "source.txt",
    "source_openreview.txt",
)


def morphology_dir(project_id: str) -> Path:
    return paper_morphology_dir(project_id)


def paper_key(url: str = "", title: str = "") -> str:
    """Stable per-paper fingerprint: normalized URL, else casefolded title."""
    normalized_url = re.sub(r"^https?://", "", normalize_spaces(url).casefold()).rstrip("/")
    basis = normalized_url or normalize_spaces(title).casefold()
    if not basis:
        raise ValueError("Paper must have a URL or a title.")
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_run_id(key: str, *, when: datetime | None = None) -> str:
    stamp = (when or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S")
    return f"{key}_{stamp}"


def allocate_run_id(project_id: str, key: str) -> str:
    """Allocate a free paper_morphology/<run_id>/ directory name."""
    root = morphology_dir(project_id)
    base = make_run_id(key)
    if not (root / base).exists():
        return base
    for index in range(2, 100):
        candidate = f"{base}_{index}"
        if not (root / candidate).exists():
            return candidate
    return f"{base}_{hashlib.sha1(base.encode('utf-8')).hexdigest()[:6]}"


def paper_key_from_run_id(run_id: str) -> str:
    token = (run_id or "").strip()
    return token.split("_", 1)[0] if "_" in token else token


def _display_path(path: Path) -> str:
    try:
        return get_workspace().relative_to_engine(path)
    except ValueError:
        return str(path)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _load_index(project_id: str) -> list[dict[str, object]]:
    data = _read_json(morphology_dir(project_id) / "index.json")
    return data if isinstance(data, list) else []


def _save_index(project_id: str, rows: list[dict[str, object]]) -> None:
    root = morphology_dir(project_id)
    root.mkdir(parents=True, exist_ok=True)
    _write_json(root / "index.json", rows)


def _history_run_id(row: dict[str, object]) -> str:
    return str(row.get("run_id") or "").strip()


def _upsert_history_row(project_id: str, row: dict[str, object]) -> None:
    """Replace only the matching run_id — re-analysing a paper keeps older runs."""
    run_id = _history_run_id(row)
    history = [
        existing
        for existing in _load_index(project_id)
        if isinstance(existing, dict) and _history_run_id(existing) != run_id
    ]
    history.append(row)
    _save_index(project_id, history)


def _paper_input_row(raw: dict[str, object]) -> dict[str, object]:
    title = normalize_spaces(str(raw.get("title") or ""))
    url = normalize_spaces(
        str(raw.get("url") or raw.get("arxiv_url") or raw.get("link") or "")
    )
    if not title and not url:
        raise ValueError("Paper must have a title or a URL.")
    year_raw = raw.get("year")
    try:
        year = int(year_raw) if year_raw not in (None, "") else None
    except (TypeError, ValueError):
        year = None
    return {
        "title": title,
        "url": url,
        "authors": normalize_spaces(str(raw.get("authors") or "")),
        "year": year,
        "abstract": normalize_spaces(str(raw.get("abstract") or raw.get("summary") or "")),
    }


def compose_morphology_chat_prompt(
    *,
    paper: dict[str, object],
    run_id: str,
    key: str,
    run_dir: Path,
) -> str:
    """Bootstrap prompt for Cursor chat — no LLM API keys required."""
    input_rel = _display_path(run_dir / "input.json")
    out_rel = _display_path(run_dir)
    title = paper.get("title") or "(untitled)"
    url = paper.get("url") or "(no url)"
    year = paper.get("year") or "—"
    authors = paper.get("authors") or "—"
    return f"""Use the skill `article-morphology` ({SKILL_PATH}).

Build the morphology of ONE paper: extract atomic claims with verbatim quotes (Pass A),
then link them into a typed graph of logical transitions (Pass B), then match the shape
against the templates in `.cursor/skills/article-morphology/references/templates.json`.

## Paper
{title}
{year} · {authors}
{url}

## Staged inputs
- Paper JSON: `{input_rel}`
- Output directory: `{out_rel}`
- run_id: `{run_id}`
- paper_key: `{key}`

## Write
- `claims.json` — Pass A, atomic claims with quotes and section anchors, no template in mind
- `{MATH_ANALYSIS_FILENAME}` — every MathML occurrence grouped into bilingual lessons
  (validate against `.cursor/skills/article-morphology/references/math-analysis.schema.json`)
- `{MORPHOLOGY_FILENAME}` — Pass B, nodes + edges + template_fit + style
  (validate against `.cursor/skills/article-morphology/references/morphology.schema.json`)
- `report.md` — human render for the morphology page
- `critique.json` — grounding audit when full text was available
- `source_normalized.txt` (or `article.html` for arXiv HTML) — the exact text you quoted from,
  so the morphology page can highlight graph blocks in the article view
- Upsert this run into `../index.json` keyed by **`run_id` only**

## Rules that decide whether this run is usable
- Fetch the paper text (arXiv HTML or PDF) when reachable; set `source_coverage` to what
  you actually read. An abstract-only run must not emit section anchors or `quoted` grounding.
- Persist that source as `source_normalized.txt` or `article.html` — without it the UI cannot
  mark quotes in the article pane.
- Every node with `grounding: "quoted"` needs a quote that is a literal substring of the source.
- An unmatched template slot goes to `missing_slots`. Never mint a node to fill a slot.
- `cue` holds the authors' verbatim connective for a transition, or `null` when implicit.
- Report every template with a score, not only the best-fitting one.
- Do not write a slide deck here. Presentation is a later run that reads this graph.
- For saved HTML, enumerate every `<math id=... alttext=...>` occurrence. Group repeated
  expressions by normalized TeX, but preserve every DOM id in `occurrences`.
- Give isolated symbols a glossary lesson. Give every compound inline or display expression
  a full RU/EN lesson: all symbols, expression parts, and a worked example.
- Optional plots contain precomputed finite x/y arrays only. Add one only when the formula
  and paper text justify the relationship; otherwise keep `plots` empty.
- Run `koi.literature.morphology_math.validate_math_analysis` against the saved HTML and
  graph. Fix every error. Write `{MORPHOLOGY_FILENAME}` last so the page never sees a
  partially completed required artifact set.

When finished, leave `{MORPHOLOGY_FILENAME}` ready for the morphology page to poll.
""".strip()


def stage_paper_morphology(project_id: str, paper: dict[str, object]) -> dict[str, object]:
    """Stage one paper and return a chat prompt (no agent / API backend)."""
    row = _paper_input_row(paper if isinstance(paper, dict) else {})
    key = paper_key(str(row["url"]), str(row["title"]))
    run_id = allocate_run_id(project_id, key)
    run_dir = morphology_dir(project_id) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    created_at = _now_iso()
    _write_json(
        run_dir / "input.json",
        {
            "run_id": run_id,
            "paper_key": key,
            "created_at": created_at,
            "status": "staged",
            "required_artifacts": list(REQUIRED_ARTIFACTS),
            "paper": row,
        },
    )

    prompt = compose_morphology_chat_prompt(
        paper=row, run_id=run_id, key=key, run_dir=run_dir
    )
    (run_dir / "PROMPT.md").write_text(prompt + "\n", encoding="utf-8")

    history_row = {
        "run_id": run_id,
        "paper_key": key,
        "paper_title": row["title"],
        "paper_url": row["url"],
        "created_at": created_at,
        "status": "staged",
        "backend": "cursor_chat",
        "path": f"paper_morphology/{run_id}",
    }
    _upsert_history_row(project_id, history_row)

    return {
        **history_row,
        "paper": row,
        "input_path": _display_path(run_dir / "input.json"),
        "output_dir": _display_path(run_dir),
        "prompt": prompt,
        "cursor_message": prompt,
    }


def _required_artifacts(run_dir: Path) -> tuple[str, ...]:
    staged = _read_json(run_dir / "input.json")
    raw = staged.get("required_artifacts") if isinstance(staged, dict) else None
    if not isinstance(raw, list):
        return (MORPHOLOGY_FILENAME,)
    names = tuple(
        str(name)
        for name in raw
        if isinstance(name, str) and name and Path(name).name == name
    )
    return names or (MORPHOLOGY_FILENAME,)


def _run_status(run_dir: Path) -> str:
    required = _required_artifacts(run_dir)
    return "ready" if all((run_dir / name).is_file() for name in required) else "staged"


def list_morphology_runs(
    project_id: str, *, paper_key_filter: str = ""
) -> list[dict[str, object]]:
    root = morphology_dir(project_id)
    wanted = (paper_key_filter or "").strip()
    rows: list[dict[str, object]] = []
    for row in _load_index(project_id):
        if not isinstance(row, dict):
            continue
        run_id = _history_run_id(row)
        if not run_id:
            continue
        normalized = dict(row)
        normalized["run_id"] = run_id
        normalized.setdefault("paper_key", paper_key_from_run_id(run_id))
        # History keeps status=staged even after the agent writes morphology.json.
        normalized["status"] = _run_status(root / run_id)
        if wanted and str(normalized.get("paper_key")) != wanted:
            continue
        rows.append(normalized)
    return sorted(rows, key=lambda row: str(row.get("created_at") or ""), reverse=True)


def load_morphology_run(project_id: str, run_id: str) -> dict[str, object] | None:
    run_id = (run_id or "").strip()
    if not run_id:
        return None
    run_dir = morphology_dir(project_id) / run_id
    staged = _read_json(run_dir / "input.json")
    graph = _read_json(run_dir / MORPHOLOGY_FILENAME)
    if not isinstance(staged, dict) and not isinstance(graph, dict):
        return None

    staged = staged if isinstance(staged, dict) else {}
    paper = staged.get("paper") if isinstance(staged.get("paper"), dict) else {}
    payload: dict[str, object] = {
        "run_id": run_id,
        "paper_key": str(staged.get("paper_key") or paper_key_from_run_id(run_id)),
        "created_at": str(staged.get("created_at") or ""),
        "path": f"paper_morphology/{run_id}",
        "paper": paper,
        "status": _run_status(run_dir),
    }

    if isinstance(graph, dict):
        payload["morphology"] = graph
        if not paper:
            payload["paper"] = {
                "title": graph.get("paper_title") or "",
                "url": graph.get("paper_url") or "",
            }

    claims = _read_json(run_dir / CLAIMS_FILENAME)
    if isinstance(claims, dict):
        payload["claims"] = claims

    report_path = run_dir / REPORT_FILENAME
    if report_path.exists():
        payload["report_markdown"] = report_path.read_text(encoding="utf-8")

    critique = _read_json(run_dir / "critique.json")
    if isinstance(critique, dict):
        payload["critique"] = critique

    math_analysis = _read_json(run_dir / MATH_ANALYSIS_FILENAME)
    if isinstance(math_analysis, dict):
        payload["math_analysis"] = add_rendered_mathml(math_analysis)

    prompt_path = run_dir / "PROMPT.md"
    if prompt_path.exists():
        prompt = prompt_path.read_text(encoding="utf-8")
        payload["prompt"] = prompt
        payload["cursor_message"] = prompt

    chat = _read_json(run_dir / "chat.json")
    if isinstance(chat, dict):
        payload["conversation_id"] = chat.get("conversation_id")

    payload["has_article"] = resolve_article_source(run_dir) is not None
    return payload


def resolve_article_source(run_dir: Path) -> dict[str, object] | None:
    """Pick the best readable source file in a morphology run directory."""
    if not run_dir.is_dir():
        return None
    for name in _ARTICLE_HTML_NAMES:
        path = run_dir / name
        if path.is_file() and path.stat().st_size > 0:
            return {"kind": "html", "path": path, "name": name}
    for name in _ARTICLE_TEXT_NAMES:
        path = run_dir / name
        if path.is_file() and path.stat().st_size > 0:
            return {"kind": "text", "path": path, "name": name}
    # Any leftover source_*.txt / *.html the agent may have dropped.
    texts = sorted(
        (
            path
            for path in run_dir.glob("source_*.txt")
            if path.is_file() and path.stat().st_size > 0
        ),
        key=lambda path: path.stat().st_size,
        reverse=True,
    )
    if texts:
        return {"kind": "text", "path": texts[0], "name": texts[0].name}
    htmls = sorted(
        (
            path
            for path in run_dir.glob("*.html")
            if path.is_file() and path.stat().st_size > 0 and path.name != "index.html"
        ),
        key=lambda path: path.name,
    )
    if htmls:
        return {"kind": "html", "path": htmls[0], "name": htmls[0].name}
    return None


def _collect_evidence_marks(graph: dict[str, object]) -> list[dict[str, object]]:
    marks: list[dict[str, object]] = []
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            continue
        role = str(node.get("role") or "")
        statement = str(node.get("statement") or "")
        for index, evidence in enumerate(node.get("evidence") or []):
            if not isinstance(evidence, dict):
                continue
            quote = str(evidence.get("quote") or "").strip()
            if not quote:
                continue
            marks.append(
                {
                    "mark_id": f"{node_id}-e{index}",
                    "node_id": node_id,
                    "role": role,
                    "statement": statement,
                    "section": evidence.get("section"),
                    "locator": evidence.get("locator"),
                    "quote": quote,
                }
            )
    return marks


def _find_non_overlapping(text: str, quotes: list[str]) -> list[tuple[int, int, int]]:
    """Return (quote_index, start, end) spans, longest quotes first, no overlaps."""
    occupied: list[tuple[int, int]] = []
    placed: list[tuple[int, int, int]] = []
    ranked = sorted(range(len(quotes)), key=lambda i: len(quotes[i]), reverse=True)
    for index in ranked:
        quote = quotes[index]
        if not quote:
            continue
        start = 0
        while True:
            found = text.find(quote, start)
            if found < 0:
                break
            end = found + len(quote)
            if any(not (end <= left or found >= right) for left, right in occupied):
                start = found + 1
                continue
            occupied.append((found, end))
            placed.append((index, found, end))
            break
    placed.sort(key=lambda item: item[1])
    return placed


def _escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _insert_section_breaks(text: str, section_titles: list[str]) -> str:
    """Insert newlines before known section headings so a flat dump becomes readable."""
    titles = sorted(
        {str(title).strip() for title in section_titles if str(title).strip()},
        key=len,
        reverse=True,
    )
    if not titles:
        return text
    hits: list[tuple[int, str]] = []
    occupied: list[tuple[int, int]] = []
    for title in titles:
        start = 0
        while True:
            found = text.find(title, start)
            if found < 0:
                break
            end = found + len(title)
            # Prefer heading-like hits: start of string or preceded by space/newline.
            if found > 0 and text[found - 1] not in " \n\t":
                start = found + 1
                continue
            if any(not (end <= left or found >= right) for left, right in occupied):
                start = found + 1
                continue
            occupied.append((found, end))
            hits.append((found, title))
            break
    if not hits:
        return text
    hits.sort(key=lambda item: item[0])
    parts: list[str] = []
    cursor = 0
    for found, title in hits:
        parts.append(text[cursor:found].rstrip())
        parts.append(f"\n\n{title}\n")
        cursor = found + len(title)
    parts.append(text[cursor:].lstrip())
    return "".join(parts)


def _wrap_text_with_marks(text: str, marks: list[dict[str, object]]) -> tuple[str, list[dict[str, object]]]:
    quotes = [str(mark["quote"]) for mark in marks]
    placed = _find_non_overlapping(text, quotes)
    found_marks: list[dict[str, object]] = []
    parts: list[str] = []
    cursor = 0
    for index, start, end in placed:
        mark = marks[index]
        parts.append(_escape_html(text[cursor:start]))
        role = _escape_html(str(mark.get("role") or ""))
        node_id = _escape_html(str(mark.get("node_id") or ""))
        mark_id = _escape_html(str(mark.get("mark_id") or ""))
        section = _escape_html(str(mark.get("section") or ""))
        parts.append(
            f'<mark class="morph-art-mark role-{role}" id="mark-{mark_id}" '
            f'data-node-id="{node_id}" data-mark-id="{mark_id}" '
            f'data-section="{section}" tabindex="0" role="button">'
            f"{_escape_html(text[start:end])}</mark>"
        )
        found = dict(mark)
        found["start"] = start
        found["end"] = end
        found_marks.append(found)
        cursor = end
    parts.append(_escape_html(text[cursor:]))
    return "".join(parts), found_marks


def _structure_marked_text(escaped_with_marks: str) -> str:
    """Split marked text into readable blocks around section titles."""
    chunks = re.split(
        r"(?=(?:^|\n)("
        r"Abstract|References|Appendix|"
        r"(?:[0-9]+(?:\.[0-9]+)*|[A-Z](?:\.[0-9]+)*)\s+[^\n<]{2,120}"
        r")\n)",
        escaped_with_marks,
    )
    if len(chunks) <= 1:
        body = escaped_with_marks.strip()
        return f'<p class="morph-art-p">{body}</p>' if body else ""

    pieces: list[str] = []
    head = chunks[0].strip()
    if head:
        pieces.append(f'<p class="morph-art-p">{head}</p>')
    index = 1
    while index < len(chunks):
        heading = chunks[index].strip()
        body = chunks[index + 1].strip() if index + 1 < len(chunks) else ""
        index += 2
        if not heading:
            continue
        slug = re.sub(r"[^0-9A-Za-z]+", "-", heading)[:48].strip("-").lower() or "sec"
        pieces.append(
            f'<h2 class="morph-art-h" id="sec-{_escape_html(slug)}">{heading}</h2>'
        )
        if body:
            pieces.append(f'<p class="morph-art-p">{body}</p>')
    return "\n".join(pieces)


def _strip_html_scripts(html: str) -> str:
    cleaned = re.sub(r"(?is)<script\b[^>]*>.*?</script>", "", html)
    cleaned = re.sub(r"(?is)<iframe\b[^>]*>.*?</iframe>", "", cleaned)
    return cleaned


def _extract_article_document(html: str) -> str:
    """Drop source-site chrome and keep the LaTeXML paper document."""
    article = re.search(
        r"(?is)<article\b(?=[^>]*\bltx_document\b)[^>]*>.*?</article>",
        html,
    )
    if article:
        return article.group(0)
    body = re.search(r"(?is)<body\b[^>]*>(.*?)</body>", html)
    return body.group(1) if body else html


def _article_asset_base(raw: str, paper_url: str) -> str:
    og_url = re.search(
        r"""(?is)<meta\b[^>]*property=["']og:url["'][^>]*content=["']([^"']+)["']""",
        raw,
    )
    if og_url:
        return og_url.group(1)
    if "arxiv-html-papers" in raw:
        return "https://arxiv.org/html/"
    parsed = urlsplit(paper_url)
    if parsed.netloc.lower().endswith("arxiv.org"):
        return "https://arxiv.org/html/"
    return paper_url


def _resolve_article_images(html: str, base_url: str) -> str:
    if not base_url:
        return html

    def replace(match: re.Match[str]) -> str:
        prefix, quote, value = match.groups()
        if value.startswith(("data:", "blob:", "#")):
            return match.group(0)
        return f"{prefix}{quote}{urljoin(base_url, value)}{quote}"

    return re.sub(
        r"""(?i)(\bsrc\s*=\s*)(["'])([^"']+)\2""",
        replace,
        html,
    )


def build_morphology_article(project_id: str, run_id: str) -> dict[str, object] | None:
    """Build a highlightable article view for a morphology run.

    Prefers ``article.html`` when present; otherwise wraps quotes from
    ``source_normalized.txt`` (or any ``source_*.txt``) as ``<mark>`` spans.
    """
    run_id = (run_id or "").strip()
    if not run_id:
        return None
    run_dir = morphology_dir(project_id) / run_id
    source = resolve_article_source(run_dir)
    if source is None:
        return {
            "available": False,
            "run_id": run_id,
            "reason": "no_source",
        }

    graph = _read_json(run_dir / MORPHOLOGY_FILENAME)
    marks = _collect_evidence_marks(graph) if isinstance(graph, dict) else []
    path = source["path"]
    assert isinstance(path, Path)
    raw = path.read_text(encoding="utf-8", errors="replace")
    kind = str(source["kind"])

    if kind == "html":
        staged = _read_json(run_dir / "input.json")
        staged_paper = staged.get("paper") if isinstance(staged, dict) else {}
        paper_url = (
            str(staged_paper.get("url") or "")
            if isinstance(staged_paper, dict)
            else ""
        )
        html_body = _extract_article_document(_strip_html_scripts(raw))
        html_body = _resolve_article_images(
            html_body,
            _article_asset_base(raw, paper_url),
        )
        # Client injects marks into HTML; server still reports which quotes exist.
        matched = []
        plain = re.sub(r"(?is)<[^>]+>", " ", html_body)
        plain = re.sub(r"\s+", " ", plain)
        for mark in marks:
            quote = str(mark["quote"])
            matched.append({**mark, "found": quote in raw or quote in plain})
        return {
            "available": True,
            "run_id": run_id,
            "kind": "html",
            "source_name": source["name"],
            "html": html_body,
            "marks": matched,
            "marked_count": sum(1 for item in matched if item.get("found")),
            "mark_total": len(marks),
        }

    body, found = _wrap_text_with_marks(
        _insert_section_breaks(
            raw,
            [str(mark.get("section") or "") for mark in marks],
        ),
        marks,
    )
    structured = _structure_marked_text(body)
    sections = sorted(
        {
            str(mark.get("section") or "").strip()
            for mark in found
            if str(mark.get("section") or "").strip()
        },
        key=lambda value: value,
    )
    html = (
        '<article class="morph-art-doc" data-kind="text">\n'
        f"{structured}\n"
        "</article>"
    )
    return {
        "available": True,
        "run_id": run_id,
        "kind": "text",
        "source_name": source["name"],
        "html": html,
        "marks": found,
        "sections": sections,
        "marked_count": len(found),
        "mark_total": len(marks),
    }


def delete_morphology_run(project_id: str, run_id: str) -> dict[str, object]:
    """Remove a morphology run and its history row.

    Missing runs raise LookupError; an empty run_id raises ValueError.
    """
    run_id = (run_id or "").strip()
    if not run_id:
        raise ValueError("run_id must not be empty")

    run_dir = morphology_dir(project_id) / run_id
    history = _load_index(project_id)
    known = any(
        isinstance(row, dict) and _history_run_id(row) == run_id for row in history
    )
    if not run_dir.is_dir():
        if not known:
            raise LookupError(f"Morphology run '{run_id}' was not found.")
        _save_index(
            project_id,
            [
                row
                for row in history
                if not isinstance(row, dict) or _history_run_id(row) != run_id
            ],
        )
        return {"ok": True, "run_id": run_id, "removed": "index_only"}

    shutil.rmtree(run_dir)
    _save_index(
        project_id,
        [row for row in history if not isinstance(row, dict) or _history_run_id(row) != run_id],
    )
    return {"ok": True, "run_id": run_id, "removed": "run_dir"}


__all__ = [
    "build_morphology_article",
    "compose_morphology_chat_prompt",
    "delete_morphology_run",
    "list_morphology_runs",
    "load_morphology_run",
    "morphology_dir",
    "paper_key",
    "resolve_article_source",
    "stage_paper_morphology",
]
