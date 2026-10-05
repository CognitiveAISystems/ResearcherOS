<p align="center">
  <img src="docs/assets/researcher_os_logo.png" alt="ResearcherOS" width="480">
</p>

## About

ResearcherOS is a research organization platform built around knowledge extraction: from a problem and hypothesis tree, through kanban experiments and structured reports, to verdicts and insights that accumulate in a curated knowledge base.

```
Problem → causes (nature hypotheses) → hypotheses (how to prove / fix)
  → verification methods → kanban experiment cards
  → report → verdict + insights → knowledge base
```

All research data lives in Markdown files — no database required. The engine is this repository (`koi/`, `api/`, `web/`, `agents/`). Research materials live under `tree/<repo>/koi-structure/` (usually git branch `koi/research`); experiment code stays in the sibling `<repo>/` folder (any branch).

| Docs | |
|------|---|
| Getting started walkthrough | [docs/human/getting-started.md](docs/human/getting-started.md) |
| Project format | [docs/human/project-format.md](docs/human/project-format.md) |
| Agent instructions | [AGENTS.md](AGENTS.md) |

## News

| Date | What shipped |
|------|----------------|
| 2026-07-24 | **Widgets API** — build your own floating panels on the project workspace (Cursor quota, free GPUs, budget, and similar). Widget files live with the project; ResearcherOS finds the enabled ones and shows them. |
| 2026-07-22 | **Literature review** — on the Literature page, pick papers from a local library, arXiv, or Zotero, ask a research question, and get groups of similar papers from several AI assistants plus a final report with a map of those groups and a draft Related Work (prior-work) section. |
| 2026-07-22 | **Hub Skills catalog** — public projects can publish agent skill packages into a shared Hub pool; after sync, open packages appear on the Skills tab for others to browse and download. |
| 2026-07-22 | **Telegram channel for product news** — public channel [@researcher_os](https://t.me/researcher_os) for ResearcherOS development updates (new features, the web interface, and Hub — a catalog of shared tools); not experiment metrics. |
| 2026-07-17 | **`tree/` layout + install CLI** — research data under `tree/<repo>/koi-structure/` (branch `koi/research`); code in sibling `<repo>/`. One command: `python -m koi.projects.install_cli install <repo>`. |
| 2026-07-16 | **Composite merge by title** — shared ancestors match on `(type, normalized title, parent)`, not only id; remaps child/board links. Fixes duplicate problem/cause branches in ResearcherOS and Hub. ADR: [docs/adr-002-composite-view.md](docs/adr-002-composite-view.md). |
| 2026-07-15 | **DAG layout JSON** — card positions in DAG view persist to `koi-structure/dag-layouts/<board_id>.json` (API `GET/PUT /projects/{id}/boards/{board_id}/dag-layout`); browser `localStorage` is migrated on first open. |
| 2026-07-13 | **Method board DAG view** — optional `depends_on` prerequisite edges between experiment cards; Kanban/DAG tabs in the method modal; interactive editor (link, delete, auto-layout, tag filter, Q/A pills, fit-to-view); card status styling (backlog, running pulse, done checkmark); persisted as `deps:` in `project.md`; API `POST /projects/{id}/boards/{board_id}/dag/suggest`. |
| 2026-07-03 | **Composite view** — projects with the same `composite_id` merge into one hypothesis tree at read time; virtual program entry in the sidebar; writes route to the owning repo via `node.project_id`. API: `GET /composites`, `GET /composites/{id}`. ADR: [docs/adr-002-composite-view.md](docs/adr-002-composite-view.md). |
| 2026-07-02 | Kanban **Successful** column (`successful`) — 4th column after Done for confirmed experiments; `done` stays the agent/report terminal state; auto-migration of `project.md` on load. |
| 2026-07-01 | Open-source release on GitHub (`main` = engine, `test_project` = demo sample). |
| 2026-07-01 | Orphan-branch sync — `koi-structure/` can live on a dedicated git branch (`koi/research` or custom) while your code branch stays clean. CLI: `python -m koi.projects.sync_cli init-sync-branch`. |
| 2026-07-01 | Stable local serve — `koi-serve.sh` works reliably on macOS; web port proxies `/api` so one URL is enough. |
| 2026-07-01 | Live card view — real-time experiment activity on kanban cards; refreshed method-activity UI. |
| 2026-07-01 | Report & knowledge fixes — reliable card report loading; repo `docs/*.md` served via knowledge API. |
| 2026-06-23 | Demo project — `bicycle_problem` sample (search-ad budget efficiency) for onboarding. |

## Installation

Requirements: Python 3.10+, `git`, `curl`. Optional: [tectonic](https://tectonic-typesetting.github.io) or `pdflatex` for NeurIPS PDF export.

### Clone

```bash
git clone git@github.com:CognitiveAISystems/ResearcherOS.git ReseachOS
cd ReseachOS
```

### Option A — conda (recommended)

```bash
conda create -n researchos python=3.11 -y
conda activate researchos
pip install -r requirements.txt
pip install -r requirements-dev.txt   # optional, for tests
```

### Option B — venv

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Start

```bash
./scripts/koi-serve.sh start
./scripts/koi-serve.sh status
```

| Service | URL |
|---------|-----|
| Web UI | http://127.0.0.1:8080 |
| API (Swagger) | http://127.0.0.1:8010/docs |

`koi-serve.sh` creates `.venv` if missing, installs dependencies, and downloads tectonic to `.tools/tectonic` when needed.

```bash
./scripts/koi-serve.sh stop      # stop
./scripts/koi-serve.sh restart  # restart
```

Settings and API keys — Settings button in the UI, or `.env` in the repo root (gitignored; see `.env.example`).

### Try the demo project

The sample project lives on orphan branch `test_project`. Check it out as a sibling worktree:

```bash
cd ..                              # parent of ReseachOS/
git -C ReseachOS worktree add bicycle_problem test_project
./ReseachOS/scripts/koi-serve.sh restart
```

Open http://127.0.0.1:8080 — `bicycle_problem` appears in the sidebar.

## Add a project

ResearcherOS scans the parent of the engine. Prefer the canonical layout:

```
workspace/
├── ReseachOS/                         # engine
├── tree/
│   └── my_experiment/koi-structure/   # research data (branch koi/research)
└── my_experiment/                     # code, any branch
    └── … experiment code …
```

Discovery: folder named `tree` → next level `*/koi-structure/project.md`.  
Legacy `my_experiment/koi-structure/` still works. Extra roots: `KOI_SCAN_ROOTS`.

### One-command install / migrate

```bash
cd ReseachOS
python -m koi.projects.install_cli status
python -m koi.projects.install_cli install my_experiment
# new empty project:
python -m koi.projects.install_cli install my_idea --create
```

| Case | What happens |
|------|----------------|
| Code repo, no ResearcherOS yet | Create orphan `koi/research`, seed `koi-structure/`, attach as `tree/<repo>` worktree |
| Branch `koi/research` already exists | Attach `tree/<repo>` worktree to that branch |
| `--create` | New local `tree/<repo>/koi-structure` + `<repo>/projectcode` |
| Old layout (koi inside code repo) | Migrate checkout into `tree/` |

Then restart: `./scripts/koi-serve.sh restart`.

### Attach with the agent (onboarding interview)

Place the code repo next to `ReseachOS/`, then in Cursor / Claude Code:

```
Подключи ../my_experiment к ResearcherOS.

Следуй agents/skills/koi-project-onboard/SKILL.md.
В конце: python -m koi.projects.install_cli install my_experiment
(материалы → tree/my_experiment/koi-structure на ветке koi/research).
```

Ongoing sync (push/pull research branch):

```bash
python -m koi.projects.sync_cli push --project-id my-project
python -m koi.projects.sync_cli pull --project-id my-project
```

### Start from scratch (no repo yet)

#### Option 1 — Install CLI

```bash
python -m koi.projects.install_cli install my_idea --create --title "My research problem"
./scripts/koi-serve.sh restart
```

#### Option 2 — Agent interview

Paste into your IDE agent:

```
Create a new ResearcherOS project from scratch.

1. Interview me: research problem, domain, what we already know, what experiments are feasible.
2. Propose a hypothesis tree: problem → causes → evidence/remediation hypotheses → methods.
3. Ask for a folder tag (latin slug, e.g. protein_folding).
4. Create tree/<tag>/koi-structure/ and <tag>/projectcode/ (or run install_cli --create).
5. If I want git sync, init git in <tag>/, set git_repo: true, install_cli install <tag>.
6. Restart ./scripts/koi-serve.sh and tell me to open the UI.

Follow koi-prose-style for all user-facing text. Do not commit without my explicit ask.
```

#### Option 3 — Build the tree in the UI

1. Open http://127.0.0.1:8080
2. Expand the project sidebar (`<` / `>` chevron)
3. Click "+ New project"
4. Fill in: Title, Description, Tag (folder name), Program
5. Click Create

The UI creates `tree/<tag>/koi-structure/` and `<tag>/projectcode/`. A Problem node appears on the map.

| Next step | Where |
|-----------|-------|
| Add cause / hypothesis / method | Dashed "+" under a node on the map |
| Edit a node | Click node → Edit |
| Create an experiment | Click method → kanban → + in a column |
| Write a report | Click kanban card → report editor |
| Ask the agent | Node panel or workspace chat button |

Where to write code: `projectcode/` (not inside `koi-structure/`).  
Where research lives: tree + kanban in UI or `koi-structure/project.md`; reports in `koi-structure/reports/`.

## Platform overview

| Area | Highlights |
|------|------------|
| Hypothesis map | Radial tree: problem → cause → evidence / remediation → method |
| Kanban | Per-method backlog / running / done / successful columns |
| Reports | Structured experiment reports with ingest → verdicts + insights |
| Knowledge base | Auto-built from reports; curator skill for deep synthesis |
| Related work | Literature search and review generation |
| Paper export | NeurIPS LaTeX → PDF from the full project graph |
| Agent skills | `agents/skills/koi-*` — card execution, sync, review, chat, paper |

## Links

| | |
|---|---|
| Public site (GitHub Pages) | [docs-site/](docs-site/) → after deploy: `https://cognitiveaisystems.github.io/ResearcherOS/` |
| Documentation | [docs/](docs/) |
| Issues | [github.com/CognitiveAISystems/ResearcherOS/issues](https://github.com/CognitiveAISystems/ResearcherOS/issues) |
