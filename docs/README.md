# Документация ReseachOS

Два входа — по аудитории:

| Аудитория | Каталог | С чего начать |
|-----------|---------|---------------|
| **Человек** | [human/](human/) | [getting-started.md](human/getting-started.md) |
| **Агент IDE** | [agents.md](agents.md) | [AGENTS.md](../AGENTS.md) |

Страницы фич платформы: [docs-site/features/](../docs-site/features/) (ссылка **Docs** в хедере сайта).
Спецификация новой реализации: [spec/](spec/) · витрина [docs-site/todo/](../docs-site/todo/).

## Человек (`docs/human/`)

Путеводители, форматы данных, как устроена база знаний.

## Агенты

- **`AGENTS.md`** — роль агента, очереди, рабочие циклы, форматные ворота.
- **`agents/skills/`** — содержательные исследовательские skills и их шаблоны.
- **`docs/agents.md`** — устройство агентной работы.
- **`docs/research-workflow.md`** — процесс отчётов и накопления знаний.

Cursor получает доступ к общим skills через ссылки в `.cursor/skills/`.

## Совместимость

Старые пути в корне `docs/` — symlink: `GETTING_STARTED.md`, `PROJECT_FORMAT.md`, `domain-model.md` и т.д.
