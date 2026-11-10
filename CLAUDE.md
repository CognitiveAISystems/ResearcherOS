# CLAUDE.md

Claude Code читает этот файл при старте сессии. Все правила репозитория лежат в `AGENTS.md`, поэтому он подключён целиком.

@AGENTS.md

## Claude Code в ResearcherOS

- Содержательные скиллы лежат в `agents/skills/*/SKILL.md`. Claude Code видит их через `.claude/skills/<имя>`, команды подключения есть в `docs/agents.md`, раздел «Claude Code».
- Создать дерево исследования для кода или по описанию проекта можно скиллом `koi-project-onboard`. Он ведёт тот же диалог, что и окно «Новое дерево» в приложении, и после согласия сохраняет дерево в `tree/<repo>/koi-structure/`.
- Чат приложения и онбординг запускают Claude Code в режиме `claude -p`. Настройки задаются переменными `KOI_CLAUDE_BIN`, `KOI_CLAUDE_MODEL`, `KOI_CLAUDE_ARGS` и `KOI_CLAUDE_ALLOWED_TOOLS`.
