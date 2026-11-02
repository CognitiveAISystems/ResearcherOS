"""Multi-agent literature clustering: workers → exchange → orchestrator."""

from __future__ import annotations

import hashlib
import json
import random
import re
import shutil
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from koi.adapters.agent_backends import any_agent_available, run_agent
from koi.adapters.paths import koi_root
from koi.adapters.settings_store import load_env_file
from koi.adapters.workspace import get_workspace
from koi.literature.naming import normalize_spaces, safe_filename, slugify
from koi.review.arxiv import (
    extract_arxiv_html_text,
    extract_arxiv_id,
    extract_pdf_text,
    fetch_arxiv_html,
    fetch_arxiv_pdf,
)
from koi.review.papers import build_review_papers_from_results
from koi.review.parsing import _extract_json_object, _meaningful_tokens
from koi.review.util import _normalize_text

ProgressFn = Optional[Callable[[str], None]]


def literature_dir(project_id: str) -> Path:
    return koi_root(project_id) / "literature"


def query_hash(question: str) -> str:
    normalized = re.sub(r"\s+", " ", (question or "").strip()).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_run_id(qhash: str, *, when: datetime | None = None) -> str:
    """Unique per staging/run: question hash + UTC timestamp."""
    stamp = (when or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S")
    return f"{qhash}_{stamp}"


def allocate_run_id(project_id: str, qhash: str) -> str:
    """Allocate a free literature/<run_id>/ directory name."""
    root = literature_dir(project_id)
    base = make_run_id(qhash)
    if not (root / base).exists():
        return base
    for index in range(2, 100):
        candidate = f"{base}_{index}"
        if not (root / candidate).exists():
            return candidate
    suffix = hashlib.sha1(base.encode("utf-8")).hexdigest()[:6]
    return f"{base}_{suffix}"


def query_hash_from_run_id(run_id: str) -> str:
    """Recover content hash from run_id (supports legacy hash-only dirs)."""
    token = (run_id or "").strip()
    if "_" not in token:
        return token
    return token.split("_", 1)[0]


def _history_run_id(row: dict[str, object]) -> str:
    return str(row.get("run_id") or row.get("query_hash") or "").strip()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_index(project_id: str) -> list[dict[str, object]]:
    path = literature_dir(project_id) / "index.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _save_index(project_id: str, rows: list[dict[str, object]]) -> None:
    root = literature_dir(project_id)
    root.mkdir(parents=True, exist_ok=True)
    _write_json(root / "index.json", rows)


def _upsert_history_row(project_id: str, row: dict[str, object]) -> None:
    """Replace only the matching run_id (never collapse by question hash)."""
    run_id = _history_run_id(row)
    history = [existing for existing in _load_index(project_id) if _history_run_id(existing) != run_id]
    history.append(row)
    _save_index(project_id, history)


def list_literature_runs(project_id: str) -> list[dict[str, object]]:
    rows = []
    root = literature_dir(project_id)
    for row in _load_index(project_id):
        if not isinstance(row, dict):
            continue
        normalized = dict(row)
        run_id = _history_run_id(normalized)
        if run_id:
            normalized.setdefault("run_id", run_id)
            normalized.setdefault("query_hash", query_hash_from_run_id(run_id))
            # History often keeps status=staged even after the agent writes report.md.
            normalized["status"] = "ready" if (root / run_id / "report.md").exists() else "staged"
        chat_path = root / run_id / "chat.json"
        if chat_path.exists() and normalized.get("status") != "ready":
            from koi.agent_chat import conversations
            try:
                chat = json.loads(chat_path.read_text(encoding="utf-8"))
                items = conversations.messages(chat["conversation_id"])
                last = items[0] if items else None
                if last:
                    if last["status"] != "answered":
                        normalized["status"] = last["status"]
                    else:
                        normalized["status"] = "cancelled" if "Остановлено пользователем" in str(last.get("answer")) else "failed"
                        normalized["error"] = last.get("answer") or "Агент не сохранил обзор."
            except (OSError, ValueError, KeyError):
                pass
        rows.append(normalized)
    return sorted(rows, key=lambda row: str(row.get("created_at") or ""), reverse=True)


def load_literature_run(project_id: str, run_id: str) -> dict[str, object] | None:
    run_id = (run_id or "").strip()
    if not run_id:
        return None
    run_dir = literature_dir(project_id) / run_id
    manifest_path = run_dir / "index.json"
    input_path = run_dir / "input.json"
    if not manifest_path.exists() and not input_path.exists():
        return None

    payload: dict[str, object] = {}
    if manifest_path.exists():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, dict):
            payload = loaded
    elif input_path.exists():
        try:
            loaded = json.loads(input_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, dict):
            qhash = str(loaded.get("query_hash") or query_hash_from_run_id(run_id))
            payload = {
                "run_id": run_id,
                "query_hash": qhash,
                "question": loaded.get("question") or "",
                "created_at": loaded.get("created_at") or "",
                "count": loaded.get("count") or len(loaded.get("papers") or []),
                "status": loaded.get("status") or "staged",
                "cluster_backend": "cursor_chat",
                "papers": loaded.get("papers") or [],
            }

    if not payload:
        return None

    chat_path = run_dir / "chat.json"
    if chat_path.exists():
        payload.update(json.loads(chat_path.read_text(encoding="utf-8")))
    report_path = run_dir / "report.md"
    related_path = run_dir / "related_work.md"
    prompt_path = run_dir / "PROMPT.md"
    qhash = str(payload.get("query_hash") or query_hash_from_run_id(run_id))
    payload.setdefault("path", f"literature/{run_id}")
    payload["run_id"] = run_id
    payload["query_hash"] = qhash
    if report_path.exists():
        payload["report_markdown"] = report_path.read_text(encoding="utf-8")
        payload["status"] = "ready"
    else:
        payload["status"] = "staged"
    if related_path.exists():
        payload["related_work_markdown"] = related_path.read_text(encoding="utf-8")
    if prompt_path.exists() and "prompt" not in payload:
        payload["prompt"] = prompt_path.read_text(encoding="utf-8")
        payload["cursor_message"] = payload["prompt"]
    return _normalize_literature_payload_for_ui(payload)


def delete_literature_run(project_id: str, run_id: str, *, delete_report: bool = False) -> dict[str, object]:
    """Remove a literature run, requiring explicit opt-in to delete a report.

    Ready runs with a report cannot be cancelled this way — raise ValueError.
    Missing runs raise LookupError.
    """
    run_id = (run_id or "").strip()
    if not run_id:
        raise ValueError("run_id must not be empty")

    run_dir = literature_dir(project_id) / run_id
    if not run_dir.is_dir():
        history = _load_index(project_id)
        if any(_history_run_id(row) == run_id for row in history if isinstance(row, dict)):
            _save_index(
                project_id,
                [row for row in history if not isinstance(row, dict) or _history_run_id(row) != run_id],
            )
            return {"ok": True, "run_id": run_id, "removed": "index_only"}
        raise LookupError(f"Literature run '{run_id}' was not found.")

    report_path = run_dir / "report.md"
    if report_path.exists() and not delete_report:
        raise ValueError("Cannot cancel a literature run that already has a report.")

    shutil.rmtree(run_dir)
    history = _load_index(project_id)
    _save_index(
        project_id,
        [row for row in history if not isinstance(row, dict) or _history_run_id(row) != run_id],
    )
    return {"ok": True, "run_id": run_id, "removed": "run"}


def _normalize_literature_payload_for_ui(payload: dict[str, object]) -> dict[str, object]:
    """Alias cluster_key / nest cluster.papers so the Literature UI can bind members."""
    clusters_raw = payload.get("clusters")
    clusters: list[dict[str, object]] = (
        [c for c in clusters_raw if isinstance(c, dict)] if isinstance(clusters_raw, list) else []
    )
    papers_raw = payload.get("papers")
    top_papers: list[dict[str, object]] = (
        [p for p in papers_raw if isinstance(p, dict)] if isinstance(papers_raw, list) else []
    )

    def _normalize_paper(paper: dict[str, object], cluster_key: str = "") -> dict[str, object]:
        out = dict(paper)
        primary = str(
            out.get("cluster_key") or out.get("primary_cluster_key") or cluster_key or ""
        ).strip()
        if primary:
            out["cluster_key"] = primary
            out.setdefault("primary_cluster_key", primary)
        if "arxiv_url" not in out and out.get("url"):
            out["arxiv_url"] = out.get("url")
        if not out.get("tldr"):
            out["tldr"] = out.get("comprehensive_answer") or out.get("solution_summary") or ""
        if not out.get("query_answer"):
            out["query_answer"] = out.get("short_answer") or out.get("answer") or ""
        if not out.get("short_answer") and out.get("query_answer"):
            out["short_answer"] = out["query_answer"]
        quotes = out.get("quotes")
        if not isinstance(quotes, list):
            evidence = out.get("evidence") if isinstance(out.get("evidence"), list) else []
            quotes = [{"text": str(t), "why": ""} for t in evidence if str(t).strip()]
            out["quotes"] = quotes
        if not out.get("evidence") and isinstance(quotes, list):
            out["evidence"] = [
                str(q.get("text") if isinstance(q, dict) else q).strip()
                for q in quotes
                if (q.get("text") if isinstance(q, dict) else q)
            ]
        return out

    by_title: dict[str, dict[str, object]] = {}
    for paper in top_papers:
        normalized = _normalize_paper(paper)
        title = str(normalized.get("title") or "").strip()
        if title:
            by_title[title] = normalized

    clusters_out: list[dict[str, object]] = []
    for cluster in clusters:
        key = str(cluster.get("key") or "").strip()
        nested_raw = cluster.get("papers")
        nested: list[dict[str, object]] = []
        if isinstance(nested_raw, list):
            for paper in nested_raw:
                if isinstance(paper, dict):
                    nested.append(_normalize_paper(paper, key))
        if not nested:
            titles = cluster.get("paper_titles") if isinstance(cluster.get("paper_titles"), list) else []
            for title in titles:
                t = str(title).strip()
                if t in by_title:
                    nested.append(_normalize_paper({**by_title[t], "cluster_key": key}, key))
            if not nested:
                for paper in by_title.values():
                    paper_key = str(paper.get("cluster_key") or paper.get("primary_cluster_key") or "")
                    keys = paper.get("cluster_keys") if isinstance(paper.get("cluster_keys"), list) else []
                    if paper_key == key or key in [str(k) for k in keys]:
                        nested.append(_normalize_paper({**paper, "cluster_key": key}, key))
        for paper in nested:
            title = str(paper.get("title") or "").strip()
            if not title:
                continue
            prev = by_title.get(title) or {}
            merged = {**prev, **paper}
            if not merged.get("quotes") and prev.get("quotes"):
                merged["quotes"] = prev["quotes"]
            by_title[title] = merged
        cluster_out = dict(cluster)
        cluster_out["answer"] = cluster.get("answer") or cluster.get("description") or ""
        cluster_out["rationale"] = cluster.get("rationale") or cluster.get("similarity_basis") or ""
        cluster_out["papers"] = nested
        if not cluster_out.get("paper_titles"):
            cluster_out["paper_titles"] = [str(p.get("title") or "") for p in nested if p.get("title")]
        clusters_out.append(cluster_out)

    payload = dict(payload)
    payload["clusters"] = clusters_out
    payload["papers"] = list(by_title.values())
    return payload


@dataclass
class PaperDoc:
    title: str
    url: str
    authors: str = ""
    year: int | None = None
    abstract: str = ""
    full_text: str = ""

    @property
    def source_text(self) -> str:
        return self.full_text or self.abstract or self.title


@dataclass
class Finding:
    paper_title: str
    paper_url: str
    answer: str
    solution_summary: str
    quotes: list[dict[str, str]] = field(default_factory=list)
    worker_id: str = ""


@dataclass
class Judgment:
    their_paper_title: str
    my_paper_title: str | None
    similar: bool
    confidence: float
    rationale: str
    worker_id: str = ""


def _choose_worker_count(n_papers: int) -> int:
    if n_papers <= 0:
        return 0
    if n_papers < 3:
        return n_papers
    return min(4, n_papers)


def _partition_papers(papers: list[PaperDoc], n_workers: int, seed: int) -> list[list[PaperDoc]]:
    buckets: list[list[PaperDoc]] = [[] for _ in range(n_workers)]
    order = list(papers)
    random.Random(seed).shuffle(order)
    for index, paper in enumerate(order):
        buckets[index % n_workers].append(paper)
    return [bucket for bucket in buckets if bucket]


def _token_jaccard(left: str, right: str) -> float:
    a = _meaningful_tokens(left)
    b = _meaningful_tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _prepare_paper_docs(
    question: str,
    selected_results: list[dict[str, object]],
    *,
    run_dir: Path,
    download_pdfs: bool,
    force_refresh: bool,
    progress: ProgressFn,
) -> list[PaperDoc]:
    review_papers = build_review_papers_from_results(question, selected_results)
    html_dir = run_dir / "htmls"
    pdf_dir = run_dir / "pdfs"
    text_dir = run_dir / "texts"
    docs: list[PaperDoc] = []

    for rank, paper in enumerate(review_papers, start=1):
        if progress:
            progress(f"[{rank}/{len(review_papers)}] Preparing text for '{paper.title}'")
        arxiv_id = ""
        try:
            arxiv_id = extract_arxiv_id(paper.arxiv_url)
        except Exception:
            arxiv_id = ""
        full_text = ""
        if arxiv_id:
            html_path = html_dir / f"{arxiv_id}.html"
            pdf_path = pdf_dir / f"{arxiv_id}.pdf"
            text_path = text_dir / f"{arxiv_id}.txt"
            available_html = None
            available_pdf = None
            if download_pdfs:
                available_html = fetch_arxiv_html(arxiv_id, html_path, force_refresh=force_refresh)
                available_pdf = fetch_arxiv_pdf(arxiv_id, pdf_path, force_refresh=force_refresh)
            elif html_path.exists():
                available_html = html_path
                if pdf_path.exists():
                    available_pdf = pdf_path
            elif pdf_path.exists():
                available_pdf = pdf_path
            if text_path.exists() and not force_refresh:
                full_text = text_path.read_text(encoding="utf-8")
            elif available_html is not None:
                full_text = extract_arxiv_html_text(available_html) or (
                    extract_pdf_text(available_pdf) if available_pdf else ""
                )
                if full_text:
                    text_path.parent.mkdir(parents=True, exist_ok=True)
                    text_path.write_text(full_text, encoding="utf-8")
            elif available_pdf is not None:
                full_text = extract_pdf_text(available_pdf)
                if full_text:
                    text_path.parent.mkdir(parents=True, exist_ok=True)
                    text_path.write_text(full_text, encoding="utf-8")

        year = None
        raw_year = selected_results[rank - 1].get("year") if rank - 1 < len(selected_results) else None
        if isinstance(raw_year, int):
            year = raw_year
        authors = ""
        raw_authors = selected_results[rank - 1].get("authors") if rank - 1 < len(selected_results) else None
        if isinstance(raw_authors, str):
            authors = raw_authors
        docs.append(
            PaperDoc(
                title=paper.title,
                url=paper.arxiv_url,
                authors=authors,
                year=year,
                abstract=paper.abstract or "",
                full_text=full_text,
            )
        )
    return docs


def _finding_prompt(question: str, worker_id: str, papers: list[PaperDoc]) -> str:
    blocks = []
    for paper in papers:
        text = paper.source_text
        if len(text) > 12000:
            text = text[:12000] + "\n…[truncated]"
        blocks.append(
            f"### {paper.title}\nURL: {paper.url}\nAuthors: {paper.authors}\n\n{text}"
        )
    return (
        "You are a literature worker agent. Read ONLY the papers below.\n"
        "Answer the research question for each paper with verbatim quotes that support the answer.\n"
        "Do not use outside knowledge. Return valid JSON only.\n\n"
        f'Research question: {question}\n'
        f"Worker id: {worker_id}\n\n"
        "Schema:\n"
        "{\n"
        '  "worker_id": string,\n'
        '  "findings": [\n'
        "    {\n"
        '      "paper_title": string,\n'
        '      "paper_url": string,\n'
        '      "answer": string,\n'
        '      "solution_summary": string,\n'
        '      "quotes": [{"text": string, "why": string}]\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Papers:\n\n" + "\n\n".join(blocks)
    )


def _judgment_prompt(
    question: str,
    worker_id: str,
    own_papers: list[PaperDoc],
    foreign_findings: list[Finding],
) -> str:
    own = "\n".join(
        f"- {paper.title}: {(paper.abstract or paper.title)[:500]}" for paper in own_papers
    )
    foreign_blocks = []
    for finding in foreign_findings:
        quotes = "; ".join(q.get("text", "")[:160] for q in finding.quotes[:2])
        foreign_blocks.append(
            f"### {finding.paper_title}\n"
            f"Answer: {finding.answer}\n"
            f"Solution: {finding.solution_summary}\n"
            f"Quotes: {quotes}"
        )
    return (
        "You previously read a subset of papers. Other workers extracted answers from DIFFERENT papers.\n"
        "For each foreign finding, decide whether their solution is similar to a paper YOU read.\n"
        "Return valid JSON only.\n\n"
        f"Research question: {question}\n"
        f"Worker id: {worker_id}\n\n"
        "Your papers:\n"
        f"{own}\n\n"
        "Foreign findings:\n"
        + "\n\n".join(foreign_blocks)
        + "\n\nSchema:\n"
        "{\n"
        '  "worker_id": string,\n'
        '  "judgments": [\n'
        "    {\n"
        '      "their_paper_title": string,\n'
        '      "my_paper_title": string or null,\n'
        '      "similar": boolean,\n'
        '      "confidence": number,\n'
        '      "rationale": string\n'
        "    }\n"
        "  ]\n"
        "}\n"
    )


def _orchestrator_prompt(
    question: str,
    findings: list[Finding],
    edges: list[dict[str, object]],
) -> str:
    findings_text = "\n\n".join(
        f"### {f.paper_title}\nAnswer: {f.answer}\nSolution: {f.solution_summary}\nWorker: {f.worker_id}"
        for f in findings
    )
    edges_text = "\n".join(
        f"- {e['a']} ↔ {e['b']}: similar_votes={e['similar_votes']}, "
        f"mean_confidence={e['mean_confidence']}"
        for e in edges
    )
    titles = sorted({f.paper_title for f in findings})
    return (
        "You are the literature cluster orchestrator.\n"
        "Using worker findings and the similarity table, form clusters of similar SOLUTIONS "
        "(not merely similar topics), assign every paper a primary cluster, and write Related Work.\n"
        "Use only the paper titles listed. Return valid JSON only.\n\n"
        "Related Work style (mandatory for related_work_markdown):\n"
        "- Write continuous survey prose that answers the research question.\n"
        "- NEVER one paragraph/heading per cluster; NEVER bullet dumps of papers.\n"
        "- Generalize each affinity group; cite as [1, 2, 3] then contrast with [4, 5].\n"
        "- Example cadence: 'In works [1, 2, 3] they propose … . In contrast, [4, 5] … .'\n"
        "- Number papers stably; optional short reference list at the end (title + url).\n"
        "- Match the language of the research question. Keep clusters as invisible scaffolding.\n\n"
        f"Research question: {question}\n\n"
        f"Paper titles: {json.dumps(titles, ensure_ascii=False)}\n\n"
        f"Similarity edges:\n{edges_text or '(none)'}\n\n"
        f"Findings:\n{findings_text}\n\n"
        "Schema:\n"
        "{\n"
        '  "clusters": [\n'
        "    {\n"
        '      "key": string,\n'
        '      "label": string,\n'
        '      "description": string,\n'
        '      "similarity_basis": string,\n'
        '      "paper_titles": [string]\n'
        "    }\n"
        "  ],\n"
        '  "paper_assignments": [\n'
        "    {\n"
        '      "paper_title": string,\n'
        '      "primary_cluster_key": string,\n'
        '      "cluster_keys": [string],\n'
        '      "membership_scores": {string: number},\n'
        '      "rationale": string\n'
        "    }\n"
        "  ],\n"
        '  "related_work_markdown": string\n'
        "}\n"
    )


def _rw_critic_prompt(
    question: str,
    related_work: str,
    clusters: list[dict[str, object]],
) -> str:
    cluster_hint = "\n".join(
        f"- {c.get('label')}: {c.get('similarity_basis') or c.get('description') or ''}"
        for c in clusters
    )
    return (
        "You are the Related Work critic for a literature clustering run.\n"
        "Judge ONLY how well the Related Work answers the research question.\n"
        "Do NOT demand one paragraph per cluster. Continuous contrasting prose is correct.\n"
        "Return valid JSON only.\n\n"
        f"Research question:\n{question}\n\n"
        f"Cluster context (scaffolding only):\n{cluster_hint or '(none)'}\n\n"
        f"Draft Related Work:\n{related_work}\n\n"
        "Schema:\n"
        "{\n"
        '  "answers_question": boolean,\n'
        '  "score": number,  // 0-100\n'
        '  "summary": string,\n'
        '  "gaps": [string],\n'
        '  "comments": [\n'
        "    {\n"
        '      "severity": string,\n'
        '      "issue": string,\n'
        '      "fix": string\n'
        "    }\n"
        "  ],\n"
        '  "pass": boolean  // true only if score>=80 and answers_question and gaps empty\n'
        "}\n"
    )


def _rw_reviser_prompt(
    question: str,
    related_work: str,
    critique: dict[str, object],
) -> str:
    return (
        "You are the Related Work reviser.\n"
        "Rewrite the Related Work so it answers the research question and addresses EVERY critic comment and gap.\n"
        "Keep continuous survey prose with [n] citations and contrasts between groups — never one heading/paragraph per cluster.\n"
        "Do not invent papers. Return valid JSON only.\n\n"
        f"Research question:\n{question}\n\n"
        f"Critic summary: {critique.get('summary') or ''}\n"
        f"Gaps: {json.dumps(critique.get('gaps') or [], ensure_ascii=False)}\n"
        f"Comments: {json.dumps(critique.get('comments') or [], ensure_ascii=False)}\n\n"
        f"Current Related Work:\n{related_work}\n\n"
        "Schema:\n"
        "{\n"
        '  "related_work_markdown": string,\n'
        '  "addressed": [string]  // each comment/gap → how fixed\n'
        "}\n"
    )


def _heuristic_rw_critique(question: str, related_work: str) -> dict[str, object]:
    q_tokens = _meaningful_tokens(question)
    rw_tokens = _meaningful_tokens(related_work)
    overlap = len(q_tokens & rw_tokens) / max(1, len(q_tokens))
    score = int(round(min(95, max(25, overlap * 100))))
    answers = overlap >= 0.35 and len(related_work.strip()) > 80
    gaps: list[str] = []
    comments: list[dict[str, str]] = []
    if not answers:
        gaps.append("Related Work does not clearly restate or answer the research question.")
        comments.append(
            {
                "severity": related_work[:180],
                "issue": "Low lexical overlap with the question; reads like a paper dump.",
                "fix": "Open with how the cited groups answer the question, then contrast solutions.",
            }
        )
    passed = score >= 80 and answers and not gaps
    return {
        "answers_question": answers,
        "score": score,
        "summary": (
            "Heuristic critic: token overlap with the question looks sufficient."
            if answers
            else "Heuristic critic: Related Work is weakly aligned with the question."
        ),
        "gaps": gaps,
        "comments": comments,
        "pass": passed,
        "backend": "heuristic_fallback",
    }


def _normalize_rw_critique(payload: dict[str, object] | None, question: str, related_work: str) -> dict[str, object]:
    if not payload:
        return _heuristic_rw_critique(question, related_work)
    try:
        score = int(payload.get("score") or 0)
    except (TypeError, ValueError):
        score = 0
    score = max(0, min(100, score))
    gaps = [str(g).strip() for g in (payload.get("gaps") or []) if str(g).strip()]
    comments: list[dict[str, str]] = []
    raw_comments = payload.get("comments")
    if isinstance(raw_comments, list):
        for item in raw_comments:
            if not isinstance(item, dict):
                continue
            comments.append(
                {
                    "severity": str(item.get("severity") or "").strip(),
                    "issue": str(item.get("issue") or "").strip(),
                    "fix": str(item.get("fix") or "").strip(),
                }
            )
    answers = bool(payload.get("answers_question"))
    passed = bool(payload.get("pass"))
    if score < 80 or gaps or not answers:
        passed = False
    if score >= 80 and answers and not gaps:
        passed = True
    return {
        "answers_question": answers,
        "score": score,
        "summary": str(payload.get("summary") or "").strip(),
        "gaps": gaps,
        "comments": comments,
        "pass": passed,
        "backend": str(payload.get("backend") or "agent"),
    }


def critique_and_revise_related_work(
    *,
    question: str,
    related_work: str,
    clusters: list[dict[str, object]],
    agent_ready: bool,
    max_rounds: int = 2,
    progress: ProgressFn = None,
) -> tuple[str, dict[str, object]]:
    """RW Critic → Reviser loop. Returns final Related Work + critique log."""
    current = related_work.strip()
    rounds: list[dict[str, object]] = []
    final_critique: dict[str, object] = {}

    for round_idx in range(1, max_rounds + 1):
        if progress:
            progress(f"RW Critic: round {round_idx}")
        critique_payload = None
        backend = "heuristic_fallback"
        if agent_ready:
            critique_payload, backend_name = _run_json_agent(
                _rw_critic_prompt(question, current, clusters)
            )
            backend = backend_name or backend
        critique = _normalize_rw_critique(critique_payload, question, current)
        critique["backend"] = backend
        critique["round"] = round_idx
        final_critique = critique

        round_row: dict[str, object] = {
            "round": round_idx,
            "critique": critique,
            "draft_related_work": current,
        }

        if critique.get("pass"):
            rounds.append(round_row)
            break

        if progress:
            progress(f"RW Reviser: addressing critic comments (round {round_idx})")
        revised = current
        addressed: list[str] = []
        if agent_ready:
            rev_payload, rev_backend = _run_json_agent(
                _rw_reviser_prompt(question, current, critique)
            )
            round_row["reviser_backend"] = rev_backend or "agent"
            if isinstance(rev_payload, dict):
                candidate = str(rev_payload.get("related_work_markdown") or "").strip()
                if candidate:
                    revised = candidate
                raw_addr = rev_payload.get("addressed")
                if isinstance(raw_addr, list):
                    addressed = [str(a).strip() for a in raw_addr if str(a).strip()]
        else:
            # Heuristic revise: prepend question-answering frame.
            frame = (
                f"Отвечая на вопрос «{question}»: "
                if any(ord(ch) > 127 for ch in question)
                else f"Answering «{question}»: "
            )
            if not current.lower().startswith(frame.lower()[:20]):
                revised = frame + current
            addressed = ["Prepended explicit question-answering frame (heuristic)."]
            round_row["reviser_backend"] = "heuristic_fallback"

        round_row["addressed"] = addressed
        round_row["revised_related_work"] = revised
        rounds.append(round_row)
        current = revised

    log = {
        "question": question,
        "max_rounds": max_rounds,
        "final_pass": bool(final_critique.get("pass")),
        "final_score": final_critique.get("score"),
        "rounds": rounds,
    }
    return current, log


def _parse_findings(payload: dict[str, object] | None, worker_id: str, papers: list[PaperDoc]) -> list[Finding]:
    if not payload or not isinstance(payload.get("findings"), list):
        return _heuristic_findings(worker_id, papers)
    by_title = {p.title: p for p in papers}
    out: list[Finding] = []
    for item in payload["findings"]:
        if not isinstance(item, dict):
            continue
        title = _normalize_text(str(item.get("paper_title") or ""))
        paper = by_title.get(title)
        if paper is None:
            # fuzzy: casefold match
            folded = {t.casefold(): p for t, p in by_title.items()}
            paper = folded.get(title.casefold())
        if paper is None:
            continue
        quotes_raw = item.get("quotes") if isinstance(item.get("quotes"), list) else []
        quotes: list[dict[str, str]] = []
        for quote in quotes_raw:
            if isinstance(quote, dict) and quote.get("text"):
                quotes.append(
                    {
                        "text": str(quote.get("text") or "").strip(),
                        "why": str(quote.get("why") or "").strip(),
                    }
                )
        out.append(
            Finding(
                paper_title=paper.title,
                paper_url=paper.url,
                answer=str(item.get("answer") or "").strip() or paper.abstract[:280],
                solution_summary=str(item.get("solution_summary") or "").strip() or paper.title,
                quotes=quotes,
                worker_id=worker_id,
            )
        )
    missing = [p for p in papers if p.title not in {f.paper_title for f in out}]
    if missing:
        out.extend(_heuristic_findings(worker_id, missing))
    return out


def _heuristic_findings(worker_id: str, papers: list[PaperDoc]) -> list[Finding]:
    findings: list[Finding] = []
    for paper in papers:
        snippet = normalize_spaces(paper.abstract or paper.title)
        quote = snippet[:220] if snippet else paper.title
        findings.append(
            Finding(
                paper_title=paper.title,
                paper_url=paper.url,
                answer=f"Based on the abstract/title, this paper addresses: {snippet[:320]}",
                solution_summary=snippet[:180] or paper.title,
                quotes=[{"text": quote, "why": "Supporting excerpt from available text."}],
                worker_id=worker_id,
            )
        )
    return findings


def _parse_judgments(
    payload: dict[str, object] | None,
    worker_id: str,
    own_papers: list[PaperDoc],
    foreign_findings: list[Finding],
) -> list[Judgment]:
    if not payload or not isinstance(payload.get("judgments"), list):
        return _heuristic_judgments(worker_id, own_papers, foreign_findings)
    own_titles = {p.title for p in own_papers}
    out: list[Judgment] = []
    for item in payload["judgments"]:
        if not isinstance(item, dict):
            continue
        their = _normalize_text(str(item.get("their_paper_title") or ""))
        mine_raw = item.get("my_paper_title")
        mine = _normalize_text(str(mine_raw)) if mine_raw else None
        if mine and mine not in own_titles:
            folded = {t.casefold(): t for t in own_titles}
            mine = folded.get(mine.casefold())
        out.append(
            Judgment(
                their_paper_title=their,
                my_paper_title=mine,
                similar=bool(item.get("similar")),
                confidence=float(item.get("confidence") or 0.0),
                rationale=str(item.get("rationale") or "").strip(),
                worker_id=worker_id,
            )
        )
    if not out:
        return _heuristic_judgments(worker_id, own_papers, foreign_findings)
    return out


def _heuristic_judgments(
    worker_id: str,
    own_papers: list[PaperDoc],
    foreign_findings: list[Finding],
) -> list[Judgment]:
    own_findings = {
        p.title: (p.abstract or p.title) for p in own_papers
    }
    judgments: list[Judgment] = []
    for foreign in foreign_findings:
        best_title = None
        best_score = 0.0
        for title, text in own_findings.items():
            score = _token_jaccard(foreign.solution_summary + " " + foreign.answer, text)
            if score > best_score:
                best_score = score
                best_title = title
        similar = best_score >= 0.22
        judgments.append(
            Judgment(
                their_paper_title=foreign.paper_title,
                my_paper_title=best_title if similar else None,
                similar=similar,
                confidence=round(best_score, 3),
                rationale=(
                    f"Heuristic token overlap {best_score:.2f} with '{best_title}'."
                    if similar
                    else f"Heuristic overlap too low ({best_score:.2f})."
                ),
                worker_id=worker_id,
            )
        )
    return judgments


def _aggregate_similarity(judgments: list[Judgment]) -> list[dict[str, object]]:
    bucket: dict[tuple[str, str], dict[str, object]] = {}
    for judgment in judgments:
        if not judgment.their_paper_title:
            continue
        left = judgment.my_paper_title or ""
        right = judgment.their_paper_title
        if not left:
            # still record dissimilar-only against anonymous; skip undirected edge without pair
            continue
        key = tuple(sorted((left, right)))
        row = bucket.setdefault(
            key,
            {
                "a": key[0],
                "b": key[1],
                "similar_votes": 0,
                "dissimilar_votes": 0,
                "confidence_sum": 0.0,
                "vote_count": 0,
                "rationales": [],
            },
        )
        if judgment.similar:
            row["similar_votes"] = int(row["similar_votes"]) + 1
        else:
            row["dissimilar_votes"] = int(row["dissimilar_votes"]) + 1
        row["confidence_sum"] = float(row["confidence_sum"]) + float(judgment.confidence)
        row["vote_count"] = int(row["vote_count"]) + 1
        if judgment.rationale:
            rationales = list(row["rationales"])
            rationales.append(judgment.rationale)
            row["rationales"] = rationales[:6]
    edges: list[dict[str, object]] = []
    for row in bucket.values():
        votes = max(int(row["vote_count"]), 1)
        edges.append(
            {
                "a": row["a"],
                "b": row["b"],
                "similar_votes": row["similar_votes"],
                "dissimilar_votes": row["dissimilar_votes"],
                "mean_confidence": round(float(row["confidence_sum"]) / votes, 3),
                "rationales": row["rationales"],
            }
        )
    edges.sort(key=lambda e: (-int(e["similar_votes"]), -float(e["mean_confidence"])))
    return edges


def _connected_components(titles: list[str], edges: list[dict[str, object]]) -> list[list[str]]:
    graph: dict[str, set[str]] = {t: set() for t in titles}
    for edge in edges:
        if int(edge.get("similar_votes") or 0) < 1:
            continue
        if float(edge.get("mean_confidence") or 0) < 0.45:
            continue
        a = str(edge["a"])
        b = str(edge["b"])
        if a in graph and b in graph:
            graph[a].add(b)
            graph[b].add(a)
    seen: set[str] = set()
    components: list[list[str]] = []
    for title in titles:
        if title in seen:
            continue
        stack = [title]
        comp: list[str] = []
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            comp.append(node)
            stack.extend(graph[node] - seen)
        components.append(sorted(comp))
    components.sort(key=lambda c: (-len(c), c[0] if c else ""))
    return components


def _heuristic_orchestrator(
    question: str,
    findings: list[Finding],
    edges: list[dict[str, object]],
) -> dict[str, object]:
    by_title = {f.paper_title: f for f in findings}
    components = _connected_components(list(by_title), edges)
    clusters = []
    assignments = []
    for index, titles in enumerate(components, start=1):
        texts = " ".join(by_title[t].solution_summary for t in titles if t in by_title)
        terms = sorted(_meaningful_tokens(texts), key=lambda t: (-len(t), t))[:4]
        label = " · ".join(term.replace("-", " ") for term in terms[:3]).title() or f"Cluster {index}"
        key = slugify(label, fallback=f"cluster-{index:02d}")
        description = (
            f"Papers grouped by overlapping solution language for: {question}"
        )
        basis = ", ".join(terms) if terms else "shared topical tokens"
        clusters.append(
            {
                "key": key,
                "label": label,
                "description": description,
                "similarity_basis": basis,
                "paper_titles": titles,
            }
        )
        for title in titles:
            assignments.append(
                {
                    "paper_title": title,
                    "primary_cluster_key": key,
                    "cluster_keys": [key],
                    "membership_scores": {key: 1.0},
                    "rationale": f"Connected via similarity votes to component '{label}'.",
                }
            )
    # Continuous prose with [n] cites — never one heading/paragraph per cluster.
    refs: list[str] = []
    n = 1
    title_to_nums: dict[str, int] = {}
    for cluster in clusters:
        for title in cluster["paper_titles"]:
            if title in title_to_nums:
                continue
            title_to_nums[title] = n
            refs.append(f"[{n}] {title}")
            n += 1
    prose_chunks: list[str] = []
    for index, cluster in enumerate(clusters):
        nums = [str(title_to_nums[t]) for t in cluster["paper_titles"] if t in title_to_nums]
        cite = ", ".join(nums) if nums else "?"
        basis = _normalize_text(str(cluster.get("similarity_basis") or cluster.get("description") or ""))
        if index == 0:
            prose_chunks.append(f"В работах [{cite}] предлагают {basis}.")
        else:
            prose_chunks.append(f"В отличие от этого в работах [{cite}] делают иначе: {basis}.")
    related_md = (
        f"# Related Work\n\n"
        f"{' '.join(prose_chunks)}\n\n"
        f"## References\n\n" + "\n".join(refs) + "\n"
    )
    return {
        "clusters": clusters,
        "paper_assignments": assignments,
        "related_work_markdown": related_md,
    }


def _normalize_orchestrator(
    payload: dict[str, object] | None,
    findings: list[Finding],
    edges: list[dict[str, object]],
    question: str,
) -> dict[str, object]:
    titles = {f.paper_title for f in findings}
    if not payload or not isinstance(payload.get("clusters"), list):
        return _heuristic_orchestrator(question, findings, edges)
    clusters_out = []
    assigned: set[str] = set()
    for index, cluster in enumerate(payload["clusters"], start=1):
        if not isinstance(cluster, dict):
            continue
        label = _normalize_text(str(cluster.get("label") or f"Cluster {index}"))
        key = slugify(str(cluster.get("key") or label), fallback=f"cluster-{index:02d}")
        paper_titles = []
        raw_titles = cluster.get("paper_titles")
        if isinstance(raw_titles, list):
            for title in raw_titles:
                t = _normalize_text(str(title))
                if t in titles:
                    paper_titles.append(t)
                    assigned.add(t)
        if not paper_titles:
            continue
        clusters_out.append(
            {
                "key": key,
                "label": label,
                "description": str(cluster.get("description") or "").strip(),
                "similarity_basis": str(cluster.get("similarity_basis") or "").strip(),
                "paper_titles": paper_titles,
            }
        )
    assignments_out = []
    raw_assignments = payload.get("paper_assignments")
    if isinstance(raw_assignments, list):
        for item in raw_assignments:
            if not isinstance(item, dict):
                continue
            title = _normalize_text(str(item.get("paper_title") or ""))
            if title not in titles:
                continue
            primary = slugify(str(item.get("primary_cluster_key") or ""), fallback="")
            cluster_keys = []
            if isinstance(item.get("cluster_keys"), list):
                cluster_keys = [
                    slugify(str(k), fallback="") for k in item["cluster_keys"] if str(k).strip()
                ]
            cluster_keys = [k for k in cluster_keys if k]
            if not primary and cluster_keys:
                primary = cluster_keys[0]
            if not primary:
                continue
            scores = item.get("membership_scores") if isinstance(item.get("membership_scores"), dict) else {}
            assignments_out.append(
                {
                    "paper_title": title,
                    "primary_cluster_key": primary,
                    "cluster_keys": cluster_keys or [primary],
                    "membership_scores": scores,
                    "rationale": str(item.get("rationale") or "").strip(),
                }
            )
            assigned.add(title)
    missing = titles - assigned
    if missing or not clusters_out:
        fallback = _heuristic_orchestrator(question, findings, edges)
        if not clusters_out:
            return fallback
        # append missing papers as singleton clusters from fallback
        for assignment in fallback["paper_assignments"]:
            if assignment["paper_title"] in missing:
                assignments_out.append(assignment)
        for cluster in fallback["clusters"]:
            if any(t in missing for t in cluster["paper_titles"]):
                clusters_out.append(cluster)
    related = str(payload.get("related_work_markdown") or "").strip()
    if not related:
        related = str(_heuristic_orchestrator(question, findings, edges)["related_work_markdown"])
    return {
        "clusters": clusters_out,
        "paper_assignments": assignments_out,
        "related_work_markdown": related,
    }


def _run_json_agent(prompt: str) -> tuple[dict[str, object] | None, str | None]:
    load_env_file()
    text, backend = run_agent(prompt, cwd=get_workspace().agent_cwd())
    if not text:
        return None, backend
    return _extract_json_object(text), backend


def build_report_markdown(
    *,
    question: str,
    query_hash_value: str,
    created_at: str,
    n_workers: int,
    papers: list[PaperDoc],
    clusters: list[dict[str, object]],
    assignments: list[dict[str, object]],
    edges: list[dict[str, object]],
    related_work: str,
    backend: str,
    rw_critique: dict[str, object] | None = None,
    findings: list[Finding] | None = None,
    run_id: str | None = None,
) -> str:
    findings_by_title = {f.paper_title: f for f in (findings or [])}
    paper_by_title = {p.title: p for p in papers}
    lines = [
        f"# {question}",
        "",
        f"- Run id: `{run_id or query_hash_value}`",
        f"- Query hash: `{query_hash_value}`",
        f"- Created: {created_at}",
        f"- Workers: {n_workers}",
        f"- Papers: {len(papers)}",
        f"- Backend: {backend}",
    ]
    if rw_critique:
        lines.append(f"- RW critic score: `{rw_critique.get('final_score', 'n/a')}`")
        lines.append(f"- RW critic pass: `{rw_critique.get('final_pass', False)}`")
    lines.extend(
        [
            "",
            "## Clusters",
            "",
        ]
    )
    for cluster in clusters:
        lines.append(f"### {cluster['label']}")
        lines.append("")
        desc = str(cluster.get("description") or "").strip()
        basis = str(cluster.get("similarity_basis") or "").strip()
        lines.append(desc or "_No description._")
        if basis and basis != desc:
            lines.append("")
            lines.append(f"**Почему вместе.** {basis}")
        lines.append("")
        for title in cluster.get("paper_titles") or []:
            finding = findings_by_title.get(title)
            paper = paper_by_title.get(title)
            lines.append(f"#### {title}")
            lines.append("")
            meta_bits = []
            if paper and paper.year:
                meta_bits.append(str(paper.year))
            if paper and paper.authors:
                meta_bits.append(paper.authors)
            if paper and paper.url:
                meta_bits.append(paper.url)
            if meta_bits:
                lines.append(" · ".join(meta_bits))
                lines.append("")
            tldr = (finding.solution_summary if finding else "") or ""
            answer = (finding.answer if finding else "") or ""
            lines.append(f"**TLDR.** {tldr or '—'}")
            lines.append("")
            lines.append(f"**Ответ на вопрос.** {answer or '—'}")
            lines.append("")
            quotes = finding.quotes if finding else []
            if quotes:
                lines.append("**Цитаты.**")
                lines.append("")
                for quote in quotes:
                    text = str(quote.get("text") or "").strip()
                    why = str(quote.get("why") or "").strip()
                    if not text:
                        continue
                    lines.append(f"> {text}")
                    if why:
                        lines.append(f">")
                        lines.append(f"> — {why}")
                    lines.append("")
            else:
                lines.append("**Цитаты.** _нет_")
                lines.append("")
        lines.append("")
    lines.extend(["## Paper assignments", ""])
    lines.append("| Paper | Primary cluster | Also | Rationale |")
    lines.append("| --- | --- | --- | --- |")
    label_by_key = {c["key"]: c["label"] for c in clusters}
    for assignment in assignments:
        primary = label_by_key.get(assignment["primary_cluster_key"], assignment["primary_cluster_key"])
        also = ", ".join(
            label_by_key.get(k, k)
            for k in assignment.get("cluster_keys") or []
            if k != assignment["primary_cluster_key"]
        ) or "—"
        rationale = str(assignment.get("rationale") or "").replace("|", "/")
        lines.append(
            f"| {assignment['paper_title']} | {primary} | {also} | {rationale or '—'} |"
        )
    lines.extend(["", "## Related Work", ""])
    related = related_work.strip()
    if related.lower().startswith("# related work"):
        related = "\n".join(related.splitlines()[1:]).lstrip()
    lines.append(related or "_No Related Work generated._")
    if rw_critique:
        lines.extend(["", "## RW critique", ""])
        lines.append(
            f"Score **{rw_critique.get('final_score', 'n/a')}** "
            f"(pass={rw_critique.get('final_pass', False)})."
        )
        rounds = rw_critique.get("rounds") if isinstance(rw_critique.get("rounds"), list) else []
        if rounds:
            last = rounds[-1] if isinstance(rounds[-1], dict) else {}
            critique = last.get("critique") if isinstance(last.get("critique"), dict) else {}
            if critique.get("summary"):
                lines.append("")
                lines.append(str(critique["summary"]))
            comments = critique.get("comments") if isinstance(critique.get("comments"), list) else []
            if comments:
                lines.append("")
                lines.append("Final comments:")
                for comment in comments[:8]:
                    if not isinstance(comment, dict):
                        continue
                    issue = comment.get("issue") or ""
                    fix = comment.get("fix") or ""
                    lines.append(f"- {issue}" + (f" → {fix}" if fix else ""))
    lines.extend(["", "## Similarity evidence", ""])
    strong = [e for e in edges if int(e.get("similar_votes") or 0) >= 1]
    if not strong:
        lines.append("_No similar edges were agreed by workers._")
    else:
        for edge in strong[:40]:
            lines.append(
                f"- **{edge['a']}** ↔ **{edge['b']}** "
                f"(votes={edge['similar_votes']}, confidence={edge['mean_confidence']})"
            )
            for rationale in (edge.get("rationales") or [])[:2]:
                lines.append(f"  - {rationale}")
    lines.append("")
    return "\n".join(lines)


def run_literature_cluster(
    project_id: str,
    *,
    question: str,
    selected_results: list[dict[str, object]],
    force_refresh: bool = False,
    download_pdfs: bool = True,
    progress: ProgressFn = None,
) -> dict[str, object]:
    normalized_question = normalize_spaces(question)
    if not normalized_question:
        raise ValueError("Question must not be empty.")
    if not selected_results:
        raise ValueError("Select at least one paper before clustering.")

    qhash = query_hash(normalized_question)
    run_id = allocate_run_id(project_id, qhash)
    run_dir = literature_dir(project_id) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "workers").mkdir(parents=True, exist_ok=True)
    if progress:
        progress(f"Starting literature run {run_id}")

    agent_ready = any_agent_available()
    if not agent_ready:
        download_pdfs = False
        if progress:
            progress("No LLM backend; using heuristic multi-agent fallback.")

    papers = _prepare_paper_docs(
        normalized_question,
        selected_results,
        run_dir=run_dir,
        download_pdfs=download_pdfs,
        force_refresh=force_refresh,
        progress=progress,
    )
    if not papers:
        raise ValueError("No papers available for clustering.")

    n_workers = _choose_worker_count(len(papers))
    seed = int(qhash[:8], 16)
    buckets = _partition_papers(papers, n_workers, seed)
    if progress:
        progress(f"Partitioned {len(papers)} papers into {len(buckets)} workers")

    findings: list[Finding] = []
    backends: list[str] = []
    for index, bucket in enumerate(buckets, start=1):
        worker_id = f"w{index:02d}"
        if progress:
            progress(f"Worker {worker_id}: extracting answers for {len(bucket)} paper(s)")
        payload = None
        backend = "heuristic_fallback"
        if agent_ready:
            payload, backend_name = _run_json_agent(
                _finding_prompt(normalized_question, worker_id, bucket)
            )
            backend = backend_name or backend
        worker_findings = _parse_findings(payload, worker_id, bucket)
        findings.extend(worker_findings)
        backends.append(backend)
        _write_json(
            run_dir / "workers" / f"{worker_id}_findings.json",
            {
                "worker_id": worker_id,
                "backend": backend,
                "findings": [asdict(f) for f in worker_findings],
            },
        )

    _write_json(run_dir / "findings.json", {"findings": [asdict(f) for f in findings]})

    findings_by_worker: dict[str, list[Finding]] = defaultdict(list)
    for finding in findings:
        findings_by_worker[finding.worker_id].append(finding)

    all_judgments: list[Judgment] = []
    for index, bucket in enumerate(buckets, start=1):
        worker_id = f"w{index:02d}"
        foreign = [f for f in findings if f.worker_id != worker_id]
        if not foreign:
            continue
        if progress:
            progress(f"Worker {worker_id}: judging {len(foreign)} foreign finding(s)")
        payload = None
        backend = "heuristic_fallback"
        if agent_ready:
            payload, backend_name = _run_json_agent(
                _judgment_prompt(normalized_question, worker_id, bucket, foreign)
            )
            backend = backend_name or backend
        judgments = _parse_judgments(payload, worker_id, bucket, foreign)
        all_judgments.extend(judgments)
        _write_json(
            run_dir / "workers" / f"{worker_id}_judgments.json",
            {
                "worker_id": worker_id,
                "backend": backend,
                "judgments": [asdict(j) for j in judgments],
            },
        )

    edges = _aggregate_similarity(all_judgments)
    similarity_payload = {"edges": edges, "judgments": [asdict(j) for j in all_judgments]}
    _write_json(run_dir / "similarity.json", similarity_payload)

    if progress:
        progress("Orchestrator: building clusters and Related Work")
    orch_payload = None
    orch_backend = "heuristic_fallback"
    if agent_ready:
        orch_payload, orch_backend_name = _run_json_agent(
            _orchestrator_prompt(normalized_question, findings, edges)
        )
        orch_backend = orch_backend_name or orch_backend
    orchestrated = _normalize_orchestrator(
        orch_payload, findings, edges, normalized_question
    )

    draft_rw = str(orchestrated["related_work_markdown"]).strip()
    (run_dir / "related_work.draft.md").write_text(draft_rw + "\n", encoding="utf-8")
    final_rw, rw_critique = critique_and_revise_related_work(
        question=normalized_question,
        related_work=draft_rw,
        clusters=orchestrated["clusters"],
        agent_ready=agent_ready,
        max_rounds=2,
        progress=progress,
    )
    orchestrated["related_work_markdown"] = final_rw
    _write_json(run_dir / "rw_critique.json", rw_critique)

    created_at = _now_iso()
    backend_label = (
        f"multi_agent:{orch_backend}"
        if agent_ready
        else "heuristic_fallback"
    )
    report_md = build_report_markdown(
        question=normalized_question,
        query_hash_value=qhash,
        created_at=created_at,
        n_workers=len(buckets),
        papers=papers,
        clusters=orchestrated["clusters"],
        assignments=orchestrated["paper_assignments"],
        edges=edges,
        related_work=final_rw,
        backend=backend_label,
        rw_critique=rw_critique,
        findings=findings,
        run_id=run_id,
    )
    (run_dir / "report.md").write_text(report_md, encoding="utf-8")
    (run_dir / "related_work.md").write_text(
        final_rw + "\n",
        encoding="utf-8",
    )

    # Shape clusters for UI compatibility with prior literature.js
    ui_clusters = []
    for cluster in orchestrated["clusters"]:
        ui_clusters.append(
            {
                "key": cluster["key"],
                "label": cluster["label"],
                "answer": cluster.get("description") or "",
                "rationale": cluster.get("similarity_basis") or "",
                "distinguishing_features": cluster.get("similarity_basis") or "",
                "signature_terms": [],
                "paper_titles": cluster.get("paper_titles") or [],
            }
        )
    assignment_by_title = {
        a["paper_title"]: a for a in orchestrated["paper_assignments"]
    }
    ui_papers = []
    for paper in papers:
        assignment = assignment_by_title.get(paper.title) or {}
        finding = next((f for f in findings if f.paper_title == paper.title), None)
        primary = assignment.get("primary_cluster_key") or ""
        label = next((c["label"] for c in ui_clusters if c["key"] == primary), "")
        ui_papers.append(
            {
                "title": paper.title,
                "arxiv_url": paper.url,
                "authors": paper.authors,
                "year": paper.year,
                "cluster_key": primary,
                "cluster_label": label,
                "cluster_rationale": assignment.get("rationale") or "",
                "tldr": finding.solution_summary if finding else "",
                "query_answer": finding.answer if finding else "",
                "short_answer": finding.answer if finding else "",
                "comprehensive_answer": finding.solution_summary if finding else "",
                "quotes": [
                    {"text": q.get("text", ""), "why": q.get("why", "")}
                    for q in (finding.quotes if finding else [])
                    if q.get("text")
                ],
                "evidence": [q.get("text", "") for q in (finding.quotes if finding else [])],
                "membership_scores": assignment.get("membership_scores") or {},
                "cluster_keys": assignment.get("cluster_keys") or ([primary] if primary else []),
            }
        )

    manifest: dict[str, object] = {
        "question": normalized_question,
        "run_id": run_id,
        "query_hash": qhash,
        "project_id": project_id,
        "created_at": created_at,
        "count": len(papers),
        "n_workers": len(buckets),
        "cluster_backend": backend_label,
        "path": f"literature/{run_id}",
        "report_markdown_path": "report.md",
        "related_work_path": "related_work.md",
        "rw_critique_path": "rw_critique.json",
        "similarity_path": "similarity.json",
        "findings_path": "findings.json",
        "clusters": ui_clusters,
        "papers": ui_papers,
        "paper_assignments": orchestrated["paper_assignments"],
        "similarity_edges": edges,
        "related_work_markdown": orchestrated["related_work_markdown"],
        "rw_critique": {
            "final_score": rw_critique.get("final_score"),
            "final_pass": rw_critique.get("final_pass"),
        },
        "report_markdown": report_md,
    }
    _write_json(run_dir / "index.json", {k: v for k, v in manifest.items() if k != "report_markdown"})

    _upsert_history_row(
        project_id,
        {
            "run_id": run_id,
            "query_hash": qhash,
            "question": normalized_question,
            "created_at": created_at,
            "count": len(papers),
            "n_workers": len(buckets),
            "cluster_backend": backend_label,
            "path": f"literature/{run_id}",
            "report_markdown": f"literature/{run_id}/report.md",
        },
    )
    return manifest


def _display_path(path: Path) -> str:
    try:
        return get_workspace().relative_to_engine(path)
    except ValueError:
        return str(path)


def _paper_input_rows(selected_results: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for raw in selected_results:
        if not isinstance(raw, dict):
            continue
        title = normalize_spaces(str(raw.get("title") or ""))
        url = normalize_spaces(
            str(raw.get("url") or raw.get("arxiv_url") or raw.get("link") or "")
        )
        if not title and not url:
            continue
        year_raw = raw.get("year")
        year: int | None
        try:
            year = int(year_raw) if year_raw not in (None, "") else None
        except (TypeError, ValueError):
            year = None
        abstract = normalize_spaces(str(raw.get("abstract") or raw.get("summary") or ""))
        authors = normalize_spaces(str(raw.get("authors") or ""))
        rows.append(
            {
                "title": title,
                "url": url,
                "authors": authors,
                "year": year,
                "abstract": abstract,
            }
        )
    return rows


def compose_literature_cluster_chat_prompt(
    *,
    question: str,
    run_id: str,
    query_hash_value: str,
    run_dir: Path,
    papers: list[dict[str, object]],
) -> str:
    """Bootstrap prompt for Cursor chat — no LLM API keys required."""
    input_rel = _display_path(run_dir / "input.json")
    out_rel = _display_path(run_dir)
    skill_hint = ".cursor/skills/literature-cluster-orchestrator/SKILL.md"
    paper_lines: list[str] = []
    for index, paper in enumerate(papers, start=1):
        year = paper.get("year") or "—"
        authors = paper.get("authors") or "—"
        paper_lines.append(
            f"{index}. {paper.get('title') or '(untitled)'}\n"
            f"   {year} · {authors}\n"
            f"   {paper.get('url') or '(no url)'}"
        )
    paper_block = "\n".join(paper_lines) if paper_lines else "(see input.json)"
    return f"""Use the skill `literature-cluster-orchestrator` ({skill_hint}).

Run the full multi-agent protocol (partition → worker findings → cross-judgments → orchestrator clusters + Related Work) for this staged literature job.

## Research question
{question}

## Staged inputs (already selected by the user)
- Papers JSON: `{input_rel}`
- Output directory: `{out_rel}/`
- run_id: `{run_id}`
- query_hash: `{query_hash_value}` (question fingerprint only — not the directory name)

## Selected papers ({len(papers)})
{paper_block}

## Required outputs (write under the output directory)
Follow the skill storage contract exactly:
- `input.json` is already written — read papers + abstracts from it (fetch PDF/HTML text when useful)
- `workers/wXX_findings.json`, `workers/wXX_judgments.json`
- `findings.json`, `similarity.json`
- `related_work.draft.md`, then critic→revise → `related_work.md`, `rw_critique.json`, `report.md`
- In `report.md` / cluster UI: each paper under a cluster must show **TLDR**, **answer to the question**, and **quotes** (from findings)
- `index.json` (machine-readable manifest for the UI; include both `run_id` and `query_hash`)
- Upsert this run into `../index.json` keyed by **`run_id` only** (never replace other history rows that share the same question / query_hash)

Do not invent paper titles. Every selected paper must land in a primary cluster.
Related Work must be continuous survey prose with contrast across groups
(`[1, 2, 3]` vs `[4, 5]`), never one paragraph/heading per cluster.
After the draft Related Work, run the RW Critic (does it answer the research question?)
and revise from the comments (up to 2 rounds) before finalizing `report.md`.
When finished, leave `report.md` ready for the Literature page to poll and render.
""".strip()


def stage_literature_cluster(
    project_id: str,
    *,
    question: str,
    selected_results: list[dict[str, object]],
) -> dict[str, object]:
    """Stage papers + question and return a chat prompt (no agent / API backend)."""
    normalized_question = normalize_spaces(question)
    if not normalized_question:
        raise ValueError("Question must not be empty.")
    papers = _paper_input_rows(selected_results)
    if not papers:
        raise ValueError("Select at least one paper before clustering.")

    qhash = query_hash(normalized_question)
    run_id = allocate_run_id(project_id, qhash)
    run_dir = literature_dir(project_id) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "workers").mkdir(parents=True, exist_ok=True)

    created_at = _now_iso()
    input_payload = {
        "run_id": run_id,
        "query_hash": qhash,
        "question": normalized_question,
        "created_at": created_at,
        "status": "staged",
        "count": len(papers),
        "papers": papers,
    }
    _write_json(run_dir / "input.json", input_payload)

    prompt = compose_literature_cluster_chat_prompt(
        question=normalized_question,
        run_id=run_id,
        query_hash_value=qhash,
        run_dir=run_dir,
        papers=papers,
    )
    (run_dir / "PROMPT.md").write_text(prompt + "\n", encoding="utf-8")

    _upsert_history_row(
        project_id,
        {
            "run_id": run_id,
            "query_hash": qhash,
            "question": normalized_question,
            "created_at": created_at,
            "count": len(papers),
            "status": "staged",
            "cluster_backend": "cursor_chat",
            "path": f"literature/{run_id}",
            "report_markdown": f"literature/{run_id}/report.md",
        },
    )

    return {
        "run_id": run_id,
        "query_hash": qhash,
        "question": normalized_question,
        "created_at": created_at,
        "count": len(papers),
        "status": "staged",
        "cluster_backend": "cursor_chat",
        "path": f"literature/{run_id}",
        "input_path": _display_path(run_dir / "input.json"),
        "output_dir": _display_path(run_dir),
        "prompt": prompt,
        "cursor_message": prompt,
        "papers": papers,
    }
