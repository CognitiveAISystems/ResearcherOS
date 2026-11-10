# Агенты в ResearchOS

ResearchOS рассчитан на выполнение исследовательских задач агентами разных
сред: Cursor, Codex, Claude и другими. Общие инструкции репозитория находятся в
[`AGENTS.md`](../AGENTS.md), а содержательные skills — в [`agents/skills/`](../agents/skills/).

## Layout проектов

```text
workspace/
├── ReseachOS/                         # engine
├── tree/<repo>/koi-structure/         # исследование (ветка koi/research)
└── <repo>/                            # код (любая ветка)
```

Установка / миграция: `python -m koi.projects.install_cli install <repo>`.
Discovery входит в папку `tree` и ищет `*/koi-structure/project.md`.

## Где находится источник правды

| Сущность | Расположение |
|---|---|
| Дерево исследования и канбан | `tree/<repo>/koi-structure/project.md` (legacy: `<repo>/koi-structure/`) |
| Исследовательские выводы | `…/koi-structure/research.json` |
| Публичные и рабочие отчёты | `…/koi-structure/reports/` |
| Курируемые знания | `…/koi-structure/knowledge/*.md` |
| Генерируемый индекс знаний | `KNOWLEDGE.md`, обновляет `koi/knowledge` |
| Содержательные agent skills | `agents/skills/` |

## Skills

- `koi-project-onboard` — подключить code-репо: диалог + prose + дерево в
  `tree/<repo>/koi-structure/`; затем `install_cli` (orphan `koi/research`);
- `koi-grill-experiment` — спроектировать карточку эксперимента до прогона;
- `koi-execute-card` — выполнить карточку эксперимента;
- `koi-card-autoresearch` — длинный прогон с ролями Руководитель / Исследователь / Дебаггер;
- `koi-report-review` — подготовить и проверить отчёт;
- `koi-done-research` — сформулировать вывод завершённого эксперимента;
- `koi-agent-chat` — ответить на вопрос из UI;
- `koi-knowledge-curator` — синтезировать накопленные знания;
- `koi-paper` и `koi-related-work` — подготовить материалы статьи;
- `koi-project-sync` — синхронизировать `tree/<repo>/koi-structure` с веткой sync;
- `koi-prose-style` — проверить человекочитаемый текст.

Шаблоны и правила хранятся рядом с тем skill, который их применяет. Отдельного
глобального каталога стандартов нет.

## Claude Code

Claude Code работает с репозиторием двумя способами.

**Как агент приложения.** Чат, онбординг (интервью, из которого строится дерево) и исполнение карточек запускают `claude -p`. В окне «Новое дерево» агента выбирают рядом с Cursor и Codex. Интервью идёт в режиме чтения, файлы проекта в нём не меняются. Настройки через переменные окружения.

| Переменная | Что задаёт |
|---|---|
| `KOI_CLAUDE_BIN` | путь к `claude`, если его нет в PATH |
| `KOI_CLAUDE_MODEL` | модель, например `sonnet` |
| `KOI_CLAUDE_ARGS` | дополнительные флаги |
| `KOI_CLAUDE_ALLOWED_TOOLS` | инструменты для задач с правкой файлов, по умолчанию `Read,Glob,Grep,Bash,Write,Edit` |

Перед первым запуском выполните `claude login` или задайте `ANTHROPIC_API_KEY`. Проверить, виден ли агент приложению, можно запросом `GET /agent/backends`.

**Как агент в IDE.** Claude Code читает `CLAUDE.md`, который подключает `AGENTS.md`. Скиллы подключаются ссылками на `agents/skills/`, копировать их не нужно. Папка `.claude/` лежит только у вас, в git она не попадает.

```bash
mkdir -p .claude/skills
for d in agents/skills/*/; do ln -sfn "../../$d" ".claude/skills/$(basename "$d")"; done
cp agents/claude-settings.json .claude/settings.json
```

В PowerShell на Windows ссылки создаются так (нужен режим разработчика или права администратора).

```powershell
New-Item -ItemType Directory -Force .claude\skills | Out-Null
Get-ChildItem agents\skills -Directory | ForEach-Object { New-Item -ItemType SymbolicLink -Force -Path ".claude\skills\$($_.Name)" -Target $_.FullName | Out-Null }
Copy-Item agents\claude-settings.json .claude\settings.json
```

Шаблон `agents/claude-settings.json` подключает один hook, `SessionStart` запускает API ResearcherOS, если он ещё не работает. Остальные hooks из `agents/cursor-hooks.json` написаны под формат Cursor и в Claude Code пока не подключены, очереди чата и done-research проверяются по `AGENTS.md` в начале сессии.

Дерево для нового проекта строится скиллом `koi-project-onboard`, в Claude Code он вызывается командой `/koi-project-onboard`.

## Cursor

Локальный `.cursor/` (gitignored) только подключает IDE:

- `.cursor/hooks.json` — скопируй из [`agents/cursor-hooks.json`](../agents/cursor-hooks.json);
- `.cursor/skills/<name>` — symlink на `agents/skills/<name>` (без копирования).

Сами hooks лежат рядом со скиллами:

| Скилл / место | Hooks |
|---|---|
| `agents/hooks/` | `koi-session-start.sh` (старт API) |
| `agents/skills/koi-agent-chat/hooks/` | session / stop → очередь UI-чата |
| `agents/skills/koi-done-research/hooks/` | session / stop → очередь done-research |
| `agents/skills/koi-project-sync/hooks/` | session / stop → pull / push reminders |

Developer-скиллы продукта (например channel news) остаются только в локальном
`.cursor/skills/` и в `agents/skills/` не кладутся — см. [`AGENTS.md`](../AGENTS.md).

Содержательные skills — в [`agents/skills/`](../agents/skills/).

Подробнее: [исследовательский workflow](research-workflow.md),
[доменная модель](domain-model.md), [Inbox](agent-chat-inbox.md),
[ADR-001 discovery](adr-001-project-discovery.md).
