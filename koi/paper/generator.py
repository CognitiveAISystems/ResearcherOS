"""Генерация научной статьи (NeurIPS preprint, LaTeX → PDF) по графу исследования.

Источник данных — всё накопленное в проекте: дерево гипотез (project.md),
выводы по экспериментам (research.json), отчёты карточек (reports/**.md и
**.run.md), графики из reports/**/assets/*.png|jpg, курируемые документы
knowledge/*.md.

Сценарий в режиме **cursor_inbox**: кнопка в UI → очередь `.run/paper-queue.json` →
`PAPER_WAKE` → агент в чате **ResearchOS Paper Inbox** → `answer` → сборка PDF.

Сценарий в других режимах: кнопка → POST /projects/{id}/paper → фоновая задача:
  1. собрать контекст проекта;
  2. попросить LLM-агента (koi.adapters.agent_backends.run_agent) написать тело статьи
     на английском в LaTeX;
  3. собрать main.tex (фиксированная преамбула + тело), скомпилировать PDF
     (tectonic из .tools/ или системный tectonic/pdflatex);
  4. при сбое агента или компиляции — детерминированный fallback, который
     верстает статью напрямую из структурированных данных.

Результат: ``paper/`` (legacy slug ``default``) или ``paper/<slug>/`` с
``{main.tex, paper.pdf, figures/, status.json, paper.json}``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from koi.adapters.agent_backends import run_agent
from koi.adapters.card_reports import load_index, reports_dir
from koi.core.models import NodeType, Project, Verdict
from koi.adapters.repository import load_project
from koi.adapters.paths import knowledge_dir, paper_dir
from koi.adapters.workspace import get_workspace
from koi.paper.catalog import (
    DEFAULT_PAPER_SLUG,
    list_project_papers,
    prepare_paper_slot_dir,
    read_paper_meta,
    read_paper_status,
)

_ws = get_workspace()
STY_NAME = "neurips_2025.sty"
STY_SOURCE = Path(__file__).with_name("templates") / STY_NAME
PAPER_DIRNAME = "paper"
STATUS_NAME = "status.json"
TEX_NAME = "main.tex"
PDF_NAME = "paper.pdf"
FIGURES_DIRNAME = "figures"

AGENT_TIMEOUT_S = int(os.environ.get("KOI_PAPER_AGENT_TIMEOUT", "1800"))
COMPILE_TIMEOUT_S = 600
RUNNING_STALE_S = 45 * 60
MAX_REPORT_CHARS = 7000
MAX_TOTAL_REPORT_CHARS = 80_000
MAX_KNOWLEDGE_CHARS = 6000
FIGURE_EXTS = (".png", ".jpg", ".jpeg")

LATEX_MARKER = "===LATEX==="

PREAMBLE = r"""\documentclass{article}
% numbers — иначе natbib (автор-год) несовместим с plain thebibliography
\PassOptionsToPackage{numbers}{natbib}
\usepackage[preprint]{neurips_2025}
\usepackage{iftex}
\ifPDFTeX
  \usepackage[utf8]{inputenc}
  \usepackage[T1]{fontenc}
  \usepackage{times}
\else
  \usepackage{fontspec}
  % Latin Modern ships with tectonic; Liberation is not in the bundle.
  \setmainfont{lmroman10-regular.otf}
  \setmonofont{lmmono10-regular.otf}
\fi
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{amsmath,amssymb}
\usepackage{url}
"""


# ---------------------------------------------------------------------------
# Пути и статус


def _status_path(project_id: str, paper_slug: str = DEFAULT_PAPER_SLUG) -> Path:
    return prepare_paper_slot_dir(project_id, paper_slug) / STATUS_NAME


def _read_status_file(project_id: str, paper_slug: str = DEFAULT_PAPER_SLUG) -> dict:
    return read_paper_status(prepare_paper_slot_dir(project_id, paper_slug))


def _write_status(project_id: str, *, paper_slug: str = DEFAULT_PAPER_SLUG, **fields) -> dict:
    slot_dir = prepare_paper_slot_dir(project_id, paper_slug)
    status = read_paper_status(slot_dir)
    status.update(fields)
    (slot_dir / STATUS_NAME).write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return status


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_running(status: dict) -> bool:
    if status.get("state") != "running":
        return False
    started = status.get("started_at", "")
    try:
        dt = datetime.fromisoformat(started)
    except (TypeError, ValueError):
        return False
    return (datetime.now(timezone.utc) - dt).total_seconds() < RUNNING_STALE_S


def paper_status(project_id: str, paper_slug: str = DEFAULT_PAPER_SLUG) -> dict:
    """Состояние статьи: status.json + наличие артефактов."""
    papers = list_project_papers(project_id)
    match = next((item for item in papers if item["slug"] == paper_slug), None)
    if match is not None:
        out = dict(match)
    else:
        status = _read_status_file(project_id, paper_slug)
        slot_dir = prepare_paper_slot_dir(project_id, paper_slug)
        pdf = slot_dir / PDF_NAME
        tex = slot_dir / TEX_NAME
        out = {
            "slug": paper_slug,
            "title": paper_slug,
            "state": status.get("state", "none"),
            "started_at": status.get("started_at"),
            "finished_at": status.get("finished_at"),
            "backend": status.get("backend"),
            "engine": status.get("engine"),
            "mode": status.get("mode"),
            "error": status.get("error"),
            "log_tail": status.get("log_tail"),
            "pdf_exists": pdf.is_file(),
            "tex_exists": tex.is_file(),
        }
        if pdf.is_file():
            out["pdf_mtime"] = datetime.fromtimestamp(
                pdf.stat().st_mtime, tz=timezone.utc
            ).isoformat(timespec="seconds")

    status = _read_status_file(project_id, paper_slug)
    if not _is_running(status) and out.get("state") == "running":
        out["state"] = "error"
        out["error"] = out.get("error") or "Генерация прервана (устаревший running-статус)."
    return out


def start_paper_generation(project_id: str, paper_slug: str = DEFAULT_PAPER_SLUG) -> bool:
    """Пометить генерацию запущенной. False — уже идёт другая генерация."""
    if _is_running(_read_status_file(project_id, paper_slug)):
        return False
    _write_status(
        project_id,
        paper_slug=paper_slug,
        state="running",
        started_at=_now_iso(),
        finished_at=None,
        error=None,
        log_tail=None,
        backend=None,
        engine=None,
        mode=None,
    )
    return True


# ---------------------------------------------------------------------------
# Сбор контекста проекта


def _slug(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return (s[:max_len].rstrip("_") or "item").lower()


def _children(project: Project, parent_id: Optional[str]):
    return [n for n in project.nodes if n.parent_id == parent_id]


def _outline(project: Project) -> str:
    """Текстовое дерево гипотез с типами, вердиктами и описаниями."""
    lines: list[str] = []

    def walk(parent_id: Optional[str], depth: int) -> None:
        for node in _children(project, parent_id):
            if node.node_type == NodeType.EXPERIMENT:
                continue
            pad = "  " * depth
            verdict = f" [verdict: {node.verdict.value}]" if node.verdict != Verdict.OPEN else ""
            lines.append(f"{pad}- ({node.node_type.value}) {node.title}{verdict} <id:{node.id}>")
            desc = (node.description or "").strip()
            if desc:
                lines.append(f"{pad}  {desc}")
            walk(node.id, depth + 1)

    walk(None, 0)
    return "\n".join(lines)


def _research_questions_text(project: Project) -> str:
    blocks: list[str] = []
    for node in project.nodes:
        if node.node_type != NodeType.METHOD or not node.research_questions:
            continue
        blocks.append(f"Method: {node.title} <id:{node.id}>")
        for q in node.research_questions:
            blocks.append(
                f"  Q (importance {q.importance}/5, {q.certainty.value}): {q.question}\n"
                f"  A (metrics): {q.answer}\n"
                f"  A (narrative): {q.narrative}"
            )
        blocks.append("")
    return "\n".join(blocks).strip()


def _cards_text(project: Project) -> str:
    lines: list[str] = []
    by_id = {n.id: n for n in project.nodes}
    for board in project.boards:
        owner = by_id.get(board.owner_node_id)
        owner_title = owner.title if owner else board.owner_node_id
        for card in board.cards:
            lines.append(
                f"- [{card.column_id}] {card.title} (method: {owner_title}, card: {card.id})"
            )
            desc = (card.description or "").strip()
            if desc:
                lines.append(f"  {desc}")
    return "\n".join(lines)


def _report_text_for_card(project_id: str, relative: str) -> str:
    """Содержимое отчёта карточки: сохранённый .md, иначе рабочий .run.md."""
    path = reports_dir(project_id) / relative
    texts: list[str] = []
    if path.is_file():
        try:
            saved = path.read_text(encoding="utf-8").strip()
        except OSError:
            saved = ""
        if saved:
            texts.append(saved)
    run_path = path.with_name(path.stem + ".run.md")
    if run_path.is_file():
        try:
            run = run_path.read_text(encoding="utf-8").strip()
        except OSError:
            run = ""
        if run and run not in texts:
            texts.append(run)
    return "\n\n".join(texts)


def _collect_reports(project: Project) -> list[dict]:
    index = load_index(project.id)
    titles = {c.id: c.title for b in project.boards for c in b.cards}
    out: list[dict] = []
    total = 0
    for card_id, relative in index.items():
        text = _report_text_for_card(project.id, relative)
        if not text:
            continue
        if len(text) > MAX_REPORT_CHARS:
            text = text[:MAX_REPORT_CHARS] + "\n…[truncated]"
        if total + len(text) > MAX_TOTAL_REPORT_CHARS:
            break
        total += len(text)
        out.append(
            {
                "card_id": card_id,
                "card_title": titles.get(card_id, card_id),
                "relative": relative,
                "text": text,
            }
        )
    return out


def _collect_knowledge(project_id: str) -> list[dict]:
    kdir = knowledge_dir(project_id)
    docs: list[dict] = []
    if not kdir.is_dir():
        return docs
    for path in sorted(kdir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not text:
            continue
        if len(text) > MAX_KNOWLEDGE_CHARS:
            text = text[:MAX_KNOWLEDGE_CHARS] + "\n…[truncated]"
        docs.append({"name": path.name, "text": text})
    return docs


def _collect_figures(project: Project, dest: Path) -> list[dict]:
    """Скопировать png/jpg из reports/**/assets в paper/figures, вернуть список."""
    rdir = reports_dir(project.id)
    dest.mkdir(parents=True, exist_ok=True)
    for old in dest.iterdir():
        if old.is_file():
            old.unlink()
    figures: list[dict] = []
    seen: set[str] = set()
    for assets in sorted(rdir.glob("*/assets")):
        hypothesis = assets.parent.name
        for asset in sorted(assets.iterdir()):
            if asset.suffix.lower() not in FIGURE_EXTS:
                continue
            base = f"{_slug(hypothesis, 40)}__{_slug(asset.stem, 40)}{asset.suffix.lower()}"
            name = base
            n = 2
            while name in seen:
                name = f"{n}_{base}"
                n += 1
            seen.add(name)
            shutil.copyfile(asset, dest / name)
            figures.append(
                {
                    "file": name,
                    "hypothesis_dir": hypothesis,
                    "asset": asset.name,
                }
            )
    return figures


def collect_paper_context(
    project: Project,
    *,
    paper_slug: str = DEFAULT_PAPER_SLUG,
) -> dict:
    slot_dir = prepare_paper_slot_dir(project.id, paper_slug)
    figures = _collect_figures(project, slot_dir / FIGURES_DIRNAME)
    return {
        "title": project.title,
        "description": project.description or "",
        "outline": _outline(project),
        "research_questions": _research_questions_text(project),
        "cards": _cards_text(project),
        "reports": _collect_reports(project),
        "knowledge": _collect_knowledge(project.id),
        "figures": figures,
    }


# ---------------------------------------------------------------------------
# LaTeX-сборка


_LATEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def latex_escape(text: str) -> str:
    return "".join(_LATEX_ESCAPES.get(ch, ch) for ch in text)


def _assemble_tex(title: str, body: str) -> str:
    return (
        PREAMBLE
        + "\n\\title{" + latex_escape(title) + "}\n\n"
        + "\\author{%\n  KOI Research Agent\\\\\n"
        + "  ResearchOS\\\\\n}\n\n"
        + "\\begin{document}\n\n\\maketitle\n\n"
        + body.strip()
        + "\n\n\\end{document}\n"
    )


def _figures_fallback_latex(figures: list[dict], limit: int = 8) -> str:
    parts: list[str] = []
    for fig in figures[:limit]:
        caption = latex_escape(
            f"{fig['asset']} ({fig['hypothesis_dir'].replace('_', ' ')})"
        )
        parts.append(
            "\\begin{figure}[ht]\n  \\centering\n"
            f"  \\includegraphics[width=0.85\\linewidth]{{{FIGURES_DIRNAME}/{fig['file']}}}\n"
            f"  \\caption{{{caption}}}\n"
            "\\end{figure}\n"
        )
    return "\n".join(parts)


def build_fallback_body(context: dict) -> str:
    """Детерминированная статья напрямую из данных графа (без LLM)."""
    esc = latex_escape
    parts: list[str] = []

    abstract = context["description"] or context["title"]
    parts.append(
        "\\begin{abstract}\n"
        + esc(abstract)
        + " This report is automatically assembled from the project research graph: "
        "hypothesis tree, experiment kanban, run reports, and accumulated research answers.\n"
        "\\end{abstract}\n"
    )

    parts.append("\\section{Problem}\n" + esc(context["title"]) + "\n")
    if context["outline"]:
        parts.append(
            "\\section{Hypothesis tree}\n"
            "\\begin{verbatim}\n" + context["outline"] + "\n\\end{verbatim}\n"
        )

    rq = context["research_questions"]
    if rq:
        parts.append("\\section{Research questions and findings}\n")
        for block in rq.split("\n\n"):
            parts.append(esc(block) + "\n")

    if context["cards"]:
        parts.append(
            "\\section{Experiments}\n"
            "\\begin{verbatim}\n" + context["cards"] + "\n\\end{verbatim}\n"
        )

    figs = _figures_fallback_latex(context["figures"])
    if figs:
        parts.append("\\section{Figures}\n" + figs)

    if context["knowledge"]:
        parts.append("\\section{Curated knowledge}\n")
        for doc in context["knowledge"]:
            parts.append("\\subsection{" + esc(doc["name"]) + "}\n")
            parts.append("\\begin{verbatim}\n" + doc["text"][:3000] + "\n\\end{verbatim}\n")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Агентная генерация


def _figures_prompt_block(figures: list[dict]) -> str:
    if not figures:
        return "(no figures available)"
    lines = []
    for fig in figures:
        lines.append(
            f"- {FIGURES_DIRNAME}/{fig['file']}  (plot `{fig['asset']}` from experiment "
            f"series `{fig['hypothesis_dir']}`)"
        )
    return "\n".join(lines)


def _build_agent_prompt(context: dict) -> str:
    reports = "\n\n".join(
        f"### Report for experiment card «{r['card_title']}» ({r['relative']})\n{r['text']}"
        for r in context["reports"]
    )
    knowledge = "\n\n".join(
        f"### Curated document {d['name']}\n{d['text']}" for d in context["knowledge"]
    )
    return f"""You are a research scientist writing a full research paper in NeurIPS preprint format.

Write the paper in ENGLISH (translate any Russian source material). Base it strictly on the
research data below — do not invent experiments, numbers, or results that are not present.

## Output format (MANDATORY)

Return EXACTLY this structure, with no markdown fences and no commentary before or after:

TITLE: <concise scientific paper title in English>
{LATEX_MARKER}
<LaTeX body of the paper>

## LaTeX body rules

- The body is everything that goes between \\maketitle and \\end{{document}}.
  Do NOT output \\documentclass, \\usepackage, \\begin{{document}}, \\end{{document}}, \\title, \\author or \\maketitle.
- Start with \\begin{{abstract}}...\\end{{abstract}}.
- Use the standard structure: Introduction, Related work (only if justified by the data),
  Method, Experiments, Results, Discussion / Limitations, Conclusion.
- Available packages: graphicx, booktabs, amsmath, amssymb, url (plus the NeurIPS style). Do not require others.
- Use tables (booktabs) for quantitative comparisons of metrics found in the reports.
- Mathematical notation in math mode; never use raw Unicode math symbols (γ → $\\gamma$).
- Escape special LaTeX characters in plain text (%, &, _, #).
- Include the most informative figures using
  \\begin{{figure}}[ht] \\centering \\includegraphics[width=0.8\\linewidth]{{<path>}} \\caption{{...}} \\end{{figure}}
  ONLY with the exact paths from the figure list below. Give every figure a meaningful caption.
- If you cite external work mentioned in the data (e.g. the OAT tokenizer), use a plain
  \\begin{{thebibliography}}{{9}} ... \\end{{thebibliography}} block at the end with \\bibitem entries; cite with \\cite{{...}}.
- The paper should be self-contained, honest about negative results and open questions,
  and roughly 4–8 pages of content.

## Project

Title: {context['title']}
Description: {context['description']}

## Hypothesis tree (research graph)

{context['outline']}

## Research questions and validated answers (research.json)

{context['research_questions'] or '(none)'}

## Experiment kanban cards

{context['cards'] or '(none)'}

## Available figures (use these exact paths)

{_figures_prompt_block(context['figures'])}

## Experiment run reports

{reports or '(none)'}

## Curated knowledge documents

{knowledge or '(none)'}
"""


def _parse_agent_response(text: str) -> Optional[tuple[str, str]]:
    """Достать (title, latex_body) из ответа агента; None — формат не распознан."""
    if LATEX_MARKER not in text:
        return None
    head, _, body = text.partition(LATEX_MARKER)
    title = ""
    for line in head.splitlines():
        line = line.strip()
        if line.upper().startswith("TITLE:"):
            title = line[len("TITLE:"):].strip()
    body = body.strip()
    body = re.sub(r"^```(?:latex|tex)?\s*", "", body)
    body = re.sub(r"\s*```$", "", body)
    # Подстраховка: вырезать всё вне document, если агент прислал целый файл
    if "\\begin{document}" in body:
        body = body.split("\\begin{document}", 1)[1]
    if "\\end{document}" in body:
        body = body.split("\\end{document}", 1)[0]
    body = body.replace("\\maketitle", "").strip()
    if not body:
        return None
    return title or "Untitled research report", body


# ---------------------------------------------------------------------------
# Компиляция


def _compile_log_tail(log_parts: list[str]) -> str:
    log = "\n".join(log_parts)
    interesting = [
        ln
        for ln in log.splitlines()
        if ln.startswith(("!", "error", "Error", "warning"))
        or ".tex:" in ln
        or "I couldn't open file name" in ln
    ]
    return "\n".join(interesting[-20:]) or log[-2000:]


def _slot_prefers_pdflatex(slot_dir: Path) -> bool:
    """External / conference papers usually need pdflatex+bibtex, not tectonic."""
    meta = read_paper_meta(slot_dir)
    engine = str(meta.get("compile_engine") or "").strip().lower()
    if engine == "pdflatex":
        return True
    if engine == "tectonic":
        return False
    if meta.get("source") == "external":
        return True
    fmt = str(meta.get("format") or "").strip().lower()
    if fmt and "neurips" not in fmt:
        return True
    if any(slot_dir.glob("*.bib")):
        return True
    tex_path = slot_dir / TEX_NAME
    if tex_path.is_file():
        head = tex_path.read_text(encoding="utf-8", errors="replace")[:12000]
        if re.search(r"\\usepackage\{EMNLP", head, re.I):
            return True
        if "\\bibliography{" in head or "\\bibliographystyle{" in head:
            return True
    for sty in slot_dir.glob("*.sty"):
        if "neurips" not in sty.name.lower():
            return True
    return False


def _finalize_pdf(tex_dir: Path, engine: str, log_parts: list[str]) -> tuple[bool, str, str]:
    produced = tex_dir / TEX_NAME.replace(".tex", ".pdf")
    target = tex_dir / PDF_NAME
    if produced.is_file():
        if produced != target:
            shutil.copy2(produced, target)
        return True, engine, "\n".join(log_parts)[-1500:]
    return False, engine, "Компиляция завершилась без PDF.\n" + "\n".join(log_parts)[-2000:]


def _system_path_files() -> list[Path]:
    """macOS path_helper sources. A Finder-launched app never loads them."""
    files = [Path("/etc/paths")]
    folder = Path("/etc/paths.d")
    if folder.is_dir():
        files.extend(sorted(p for p in folder.iterdir() if p.is_file()))
    return files


def _system_path_dirs() -> list[str]:
    dirs: list[str] = []
    for path in _system_path_files():
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#") and line not in dirs:
                dirs.append(line)
    return dirs


def _which_tool(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for directory in _system_path_dirs():
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _compile_pdflatex_bibtex(tex_dir: Path) -> tuple[bool, str, str]:
    pdflatex = _which_tool("pdflatex")
    bibtex = _which_tool("bibtex")
    if not pdflatex:
        return False, "", "Не найден pdflatex в PATH."

    base = Path(TEX_NAME).stem
    logs: list[str] = []

    def run_pdflatex() -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            [pdflatex, "-interaction=nonstopmode", "-halt-on-error", TEX_NAME],
            cwd=str(tex_dir),
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT_S,
        )
        logs.append((proc.stdout or "") + "\n" + (proc.stderr or ""))
        return proc

    def run_bibtex() -> subprocess.CompletedProcess[str] | None:
        if not bibtex:
            return None
        proc = subprocess.run(
            [bibtex, base],
            cwd=str(tex_dir),
            capture_output=True,
            text=True,
            timeout=COMPILE_TIMEOUT_S,
        )
        logs.append((proc.stdout or "") + "\n" + (proc.stderr or ""))
        return proc

    proc = run_pdflatex()
    if proc.returncode != 0:
        return False, "pdflatex+bibtex", _compile_log_tail(logs)

    aux_path = tex_dir / f"{base}.aux"
    if bibtex and aux_path.is_file():
        aux_text = aux_path.read_text(encoding="utf-8", errors="replace")
        if "\\citation" in aux_text or "\\bibdata" in aux_text:
            bproc = run_bibtex()
            if bproc is not None and bproc.returncode != 0:
                return False, "pdflatex+bibtex", _compile_log_tail(logs)

    for _ in range(2):
        proc = run_pdflatex()
        if proc.returncode != 0:
            return False, "pdflatex+bibtex", _compile_log_tail(logs)

    return _finalize_pdf(tex_dir, "pdflatex+bibtex", logs)


def _find_engine() -> Optional[tuple[str, str]]:
    """(name, binary). tectonic из .tools предпочтителен, затем PATH, затем pdflatex."""
    env_bin = os.environ.get("KOI_TECTONIC_BIN", "").strip()
    if env_bin and Path(env_bin).is_file():
        return "tectonic", env_bin
    local = _ws.tools_dir / "tectonic"
    if local.is_file():
        return "tectonic", str(local)
    which = _which_tool("tectonic")
    if which:
        return "tectonic", which
    pdflatex = _which_tool("pdflatex")
    if pdflatex:
        return "pdflatex", pdflatex
    return None


def _compile_tex(tex_dir: Path) -> tuple[bool, str, str]:
    """Скомпилировать main.tex → paper.pdf. Возвращает (ok, engine, log_tail)."""
    engine = _find_engine()
    if engine is None:
        return False, "", (
            "Не найден LaTeX-движок: положите tectonic в .tools/tectonic, "
            "задайте KOI_TECTONIC_BIN или установите pdflatex."
        )
    name, bin_path = engine
    if name == "tectonic":
        cmd = [bin_path, "-X", "compile", TEX_NAME]
        runs = 1
    else:
        cmd = [bin_path, "-interaction=nonstopmode", "-halt-on-error", TEX_NAME]
        runs = 2
    log = ""
    for _ in range(runs):
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(tex_dir),
                capture_output=True,
                text=True,
                timeout=COMPILE_TIMEOUT_S,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, name, f"Компиляция не запустилась/прервана: {e}"
        log = (proc.stdout or "") + "\n" + (proc.stderr or "")
        if proc.returncode != 0:
            return False, name, _compile_log_tail([log])
    return _finalize_pdf(tex_dir, name, [log])


def compile_paper_slot(slot_dir: Path) -> tuple[bool, str, str]:
    """Compile main.tex in an existing paper slot directory."""
    if _slot_prefers_pdflatex(slot_dir):
        return _compile_pdflatex_bibtex(slot_dir)
    ok, engine, log = _compile_tex(slot_dir)
    if ok or not _which_tool("pdflatex"):
        return ok, engine, log
    return _compile_pdflatex_bibtex(slot_dir)


# ---------------------------------------------------------------------------
# Оркестратор


def _prepare_paper_dir(
    project_id: str,
    paper_slug: str = DEFAULT_PAPER_SLUG,
) -> Path:
    d = prepare_paper_slot_dir(project_id, paper_slug)
    shutil.copyfile(STY_SOURCE, d / STY_NAME)
    return d


def build_paper_from_agent_text(
    project_id: str,
    agent_text: str,
    *,
    backend: str | None = None,
    paper_slug: str = DEFAULT_PAPER_SLUG,
) -> dict:
    """Собрать main.tex и PDF из ответа агента (Paper Inbox или headless)."""
    project = load_project(project_id, sync_reports=False)
    if project is None:
        raise KeyError(f"Project not found: {project_id}")

    d = _prepare_paper_dir(project_id, paper_slug)
    context = collect_paper_context(project, paper_slug=paper_slug)
    parsed = _parse_agent_response(agent_text) if agent_text else None

    attempts: list[tuple[str, str, str, Optional[str]]] = []
    if parsed is not None:
        attempts.append(("agent", parsed[0], parsed[1], backend))
    attempts.append(("fallback", project.title, build_fallback_body(context), None))

    last_log = ""
    agent_compile_log: Optional[str] = None
    for mode, title, body, used_backend in attempts:
        (d / TEX_NAME).write_text(_assemble_tex(title, body), encoding="utf-8")
        ok, engine, log_tail = _compile_tex(d)
        last_log = log_tail
        if ok:
            return _write_status(
                project_id,
                paper_slug=paper_slug,
                state="done",
                finished_at=_now_iso(),
                backend=used_backend,
                engine=engine,
                mode=mode,
                error=None,
                log_tail=None,
                agent_compile_log=agent_compile_log,
            )
        if mode == "agent":
            agent_compile_log = log_tail[-1500:]

    error = "Не удалось скомпилировать статью."
    if parsed is None:
        error += " Ответ агента не распознан (нужны TITLE: и ===LATEX===)."
    _write_status(
        project_id,
        paper_slug=paper_slug,
        state="error",
        finished_at=_now_iso(),
        backend=backend,
        mode="fallback",
        error=error,
        log_tail=last_log[-2000:],
    )
    raise RuntimeError(error)


def generate_paper(project_id: str, paper_slug: str = DEFAULT_PAPER_SLUG) -> dict:
    """Полный цикл генерации. Вызывается из фоновой задачи API."""
    try:
        return _generate_paper_inner(project_id, paper_slug=paper_slug)
    except Exception as e:  # noqa: BLE001 — фоновую задачу нельзя ронять молча
        return _write_status(
            project_id,
            paper_slug=paper_slug,
            state="error",
            finished_at=_now_iso(),
            error=f"Внутренняя ошибка генерации: {e}",
        )


def _generate_paper_inner(
    project_id: str,
    *,
    paper_slug: str = DEFAULT_PAPER_SLUG,
) -> dict:
    project = load_project(project_id, sync_reports=False)
    if project is None:
        return _write_status(
            project_id,
            paper_slug=paper_slug,
            state="error",
            finished_at=_now_iso(),
            error="Проект не найден",
        )

    d = _prepare_paper_dir(project_id, paper_slug)
    context = collect_paper_context(project, paper_slug=paper_slug)

    agent_text, backend = run_agent(
        _build_agent_prompt(context), cwd=_ws.agent_cwd(), timeout=AGENT_TIMEOUT_S
    )
    if not agent_text:
        project = load_project(project_id, sync_reports=False)
        assert project is not None
        body = build_fallback_body(context)
        (d / TEX_NAME).write_text(_assemble_tex(project.title, body), encoding="utf-8")
        ok, engine, log_tail = _compile_tex(d)
        if ok:
            return _write_status(
                project_id,
                paper_slug=paper_slug,
                state="done",
                finished_at=_now_iso(),
                backend=None,
                engine=engine,
                mode="fallback",
                error=None,
                log_tail=None,
            )
        return _write_status(
            project_id,
            paper_slug=paper_slug,
            state="error",
            finished_at=_now_iso(),
            backend=None,
            mode="fallback",
            error="Агент-бэкенд недоступен, fallback-вёрстка не собралась.",
            log_tail=log_tail[-2000:],
        )

    try:
        return build_paper_from_agent_text(
            project_id,
            agent_text,
            backend=backend,
            paper_slug=paper_slug,
        )
    except RuntimeError:
        return paper_status(project_id, paper_slug)
