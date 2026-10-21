#!/usr/bin/env python3
"""Generate skills/*.html from skills.json — chrome aligned with landing."""
from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = json.loads((ROOT / "skills.json").read_text(encoding="utf-8"))
OUT = ROOT / "skills"
CSS_V = "13"
JS_V = "12"

THEME_BOOT = """  <script>
    (function () {
      var t = localStorage.getItem("koi-theme");
      if (t !== "light" && t !== "dark") t = "light";
      document.documentElement.setAttribute("data-theme", t);
    })();
  </script>"""

FONT = """  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />"""

THEME_BTN = """        <button type="button" id="btn-theme" class="btn-theme" title="Тёмная тема" aria-label="Тёмная тема">
          <svg class="theme-icon theme-icon-sun" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4" fill="currentColor"/><path fill="currentColor" d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" stroke="currentColor" stroke-width="2"/></svg>
          <svg class="theme-icon theme-icon-moon" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M21 14.5A8.5 8.5 0 0 1 9.5 3 7 7 0 1 0 21 14.5z"/></svg>
        </button>"""

HEADER = f"""  <header class="site-header site-header--detail">
    <div class="site-header__inner">
      <a class="brand" href="../airi.html" aria-label="ResearcherOS — на главную">ResearcherOS</a>
      <nav class="nav" aria-label="Main navigation">
        <a href="../airi.html#about">О проекте</a>
        <a href="../airi.html#versions">Версии</a>
        <a href="../airi.html#start">Как начать</a>
        <a href="../airi.html#skills" aria-current="page">Навыки</a>
        <a href="../airi.html#lessons">Уроки</a>
        <a href="https://github.com/CognitiveAISystems/ResearcherOS">GitHub</a>
      </nav>
    </div>
  </header>"""

FOOTER = f"""  <footer class="site-footer">
    <div class="site-footer__inner">
      <span>ResearcherOS · code / hub</span>
      <a href="https://github.com/CognitiveAISystems/ResearcherOS">CognitiveAISystems/ResearcherOS</a>
    </div>
  </footer>
  <script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
  <script src="../js/site.js?v={JS_V}"></script>"""


def _p(text: str) -> str:
    return f"<p>{html.escape(text)}</p>"


def _ul(items: list[str]) -> str:
    lis = "\n".join(f"      <li>{html.escape(i)}</li>" for i in items)
    return f"    <ul class=\"skill-scenarios\">\n{lis}\n    </ul>"


def skill_page(s: dict) -> str:
    title = html.escape(s["title"])
    sid = html.escape(s["id"])
    summary = html.escape(s["summary"])
    when = html.escape(s["when"])
    what = html.escape(s.get("what") or s.get("detail") or "")
    why = html.escape(s.get("why") or "")
    scenarios = s.get("scenarios") or []
    how = html.escape(s.get("how") or "")
    diagram = html.escape(s.get("diagram") or "")
    mermaid = s["mermaid"].strip()
    example = html.escape(s["example"].strip())
    scenarios_html = _ul(scenarios) if scenarios else ""

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title} · ResearcherOS</title>
  <meta name="description" content="{summary}" />
  <link rel="stylesheet" href="../css/airi-page.css" />
</head>
<body class="page-detail">
{HEADER}
  <main class="article">
    <a class="back-link" href="../airi.html#skills">← Skills</a>
    <h1 class="article__title">{title}</h1>
    <p class="skill-id">{sid}</p>
    <div class="article__meta">
      <span class="chip">{when}</span>
    </div>
    <p class="article__lead">{summary}</p>

    <h2>Что делает</h2>
    <p>{what}</p>

    <h2>Зачем</h2>
    <p>{why}</p>

    <h2>Когда вызывать</h2>
{scenarios_html}

    <h2>Как вызвать</h2>
    <p>{how}</p>
    <div class="example">
      <p>Пример фразы AI-помощнику в редакторе:</p>
      <pre><code>{example}</code></pre>
    </div>

    <h2>Схема работы</h2>
    <p class="diagram-caption">{diagram}</p>
    <div class="graph">
      <pre class="mermaid">
{mermaid}
      </pre>
    </div>

    <div class="article__actions">
      <a class="btn btn-ghost" href="https://github.com/CognitiveAISystems/ResearcherOS/tree/main/agents/skills/{sid}">Исходник на GitHub</a>
      <a class="btn btn-primary" href="../airi.html#skills">К списку Skills</a>
    </div>
  </main>
{FOOTER}
</body>
</html>
"""


def index_page(skills: list[dict]) -> str:
    return """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <meta http-equiv="refresh" content="0;url=../airi.html#skills" />
  <title>Skills · ResearcherOS</title>
  <link rel="canonical" href="../airi.html#skills" />
  <script>location.replace("../airi.html#skills");</script>
</head>
<body>
  <p><a href="../airi.html#skills">→ Skills</a></p>
</body>
</html>
"""


OUT.mkdir(parents=True, exist_ok=True)
required = ("what", "why", "scenarios", "how", "diagram", "mermaid", "example")
for s in SKILLS:
    missing = [k for k in required if k not in s]
    if missing:
        raise SystemExit(f"{s.get('id')}: missing fields {missing}")
    (OUT / f"{s['id']}.html").write_text(skill_page(s), encoding="utf-8")
(OUT / "index.html").write_text(index_page(SKILLS), encoding="utf-8")
print(f"Wrote {len(SKILLS)} skill pages + index redirect → {OUT}")
