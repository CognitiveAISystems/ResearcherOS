---
name: koi-done-research
description: >-
  When a KOI/ResearchOS kanban card moves to done, generate a method research
  question and answer with certainty (точный/неточный) and importance (1–5).
  Use when the user moves experiments to done, mentions done cards, or when
  the done-research queue has pending items.
---

# KOI: done → исследовательский вывод

## Когда запускать

1. Пользователь перенёс карточку эксперимента в колонку **done** (в UI или через API).
2. В очереди есть необработанные карточки (см. ниже).
3. Пользователь просит сформулировать вывод по завершённому эксперименту.

При старте сессии с KOI/ResearchOS **сначала проверь очередь**:

```bash
KOI/.venv/bin/python -m koi.projects.done_research_cli pending
```

Если список не пуст — обработай каждую запись по workflow ниже.

## Workflow (на одну карточку)

### 1. Собрать контекст

```bash
KOI/.venv/bin/python -m koi.projects.done_research_cli context \
  <project_id> <board_id> <card_id>
```

В JSON: метод, родительская гипотеза, карточка, отчёт (`report_markdown`), уже существующие `research_questions` (макс. 3 на метод).

### 2. Сформулировать вывод

На основе отчёта, описания карточки и контекста метода:

| Поле | Куда | Правила |
|------|------|---------|
| `question` | исследовательский вопрос | Один чёткий вопрос; **понятен человеку без контекста проекта** — без SFT/RL/PPO/diversity/SR и названий метрик; вместо них — «обучение на примерах», «симулятор», «доля успешных попыток», «разнообразие действий» |
| `narrative` | ответ человеческим языком | Показывается в модалке «Выводы»; 2–4 предложения; тот же принцип — внешний читатель должен понять суть без глоссария |
| `answer` | техническая заметка | Сырые метрики, шаги, аббревиатуры — **только здесь**, не в question/narrative |
| `certainty` | `definite` или `tentative` | **Точный ответ** → `definite`; **неточный / предварительный** → `tentative` |
| `importance` | целое 1–5 | Относительная важность для метода: 1 — побочный факт, 3 — умеренный вклад, 5 — ключевой ответ |
| `card_id` | id карточки канбана | **Обязательно** при выводе из done-карточки — `card_id` из контекста (`context` JSON) |

**Оценка certainty**

- `definite`: в отчёте есть критерий done, воспроизводимый результат, явный ответ да/нет или количественное сравнение.
- `tentative`: мало данных, противоречия, только промежуточные метрики, гипотеза не проверена до конца.

**Оценка importance (1–5)**

- **5** — напрямую отвечает на главный вопрос метода или меняет решение «идём дальше / нет».
- **4** — сильный аргумент за/против гипотезы.
- **3** — полезное уточнение (по умолчанию).
- **2** — слабый сигнал, уточняющая деталь.
- **1** — почти не влияет на вывод по методу.

Если подходящий вопрос уже есть — **обнови** его (тот же `id`), не создавай дубликат. Если слотов нет (уже 3 вопроса) — обнови наименее важный (`importance` минимален) или сообщи пользователю.

### 3. Сохранить в ResearchOS

API (dev-сервер на 8010):

```bash
curl -s -X PATCH "http://127.0.0.1:8010/projects/<project_id>/nodes/<method_id>" \
  -H "Content-Type: application/json" \
  -d '{"research_questions": [ ...все вопросы метода, включая новый/обновлённый... ]}'
```

Сохраняй **полный** список `research_questions` узла-метода, не только новую запись. На диске вопросы попадают в `projects/<project_id>/research.json` (не в `project.md`).

### 4. Закрыть очередь

```bash
KOI/.venv/bin/python -m koi.projects.done_research_cli complete \
  <project_id> <board_id> <card_id>
```

Если вывод сформулировать нельзя (пустой отчёт, карточка не в done) — `complete` всё равно, кратко объясни пользователю почему.

## Пример тела research question

```json
{
  "id": "rq-new-001",
  "question": "Становится ли агент разнообразнее в выборе действий после обучения на примерах траекторий?",
  "narrative": "Да. Раньше в одной ситуации модель перебирала примерно полтора варианта действия, после обучения — около двух.",
  "answer": "mean diversity 2.02 vs 1.46 base (step 77)",
  "certainty": "definite",
  "importance": 5,
  "card_id": "kb-sft"
}
```

**Проверка формулировки:** перед PATCH прогони `question` и `narrative` через скилл **koi-prose-style** (subagent-ревью до PASS). Запасной тест: прочитай вслух — если без знания канбана и отчёта неясно, о чём речь, перепиши.

## Очередь

Перенос карточки в `done` пополняет `.run/done-research-queue.json`:

| Способ | Как попадает в очередь |
|--------|------------------------|
| UI drag-and-drop / API `PATCH column_id=done` | `save_project` → `sync_done_research_on_save` |
| Правка `project.md` на диске | `load_project` → `reconcile_done_research_queue` (при следующем чтении проекта) |
| `report_ingest` с §5.2 | **не** в очередь — RQ уже записан из отчёта |

Пропуск: если у метода уже есть `research_questions` с `card_id` этой карточки.

### Cursor hooks

Скрипты: `agents/skills/koi-done-research/hooks/`. В IDE: `.cursor/hooks.json`
из шаблона `agents/cursor-hooks.json`.

| Hook | Скрипт | Поведение |
|------|--------|-----------|
| `sessionStart` | `koi-done-research-session.sh` | Если очередь не пуста — `additional_context` со списком карточек |
| `stop` | `koi-done-research-stop.sh` | Если очередь ещё не пуста — `followup_message` обработать следующую (до 10 итераций) |

Проверка: **Hooks** output channel в Cursor после нового Agent-чата.

## Связанные скиллы

- Выполнение карточки (TODO + канбан): **koi-execute-card**
- Стиль question/narrative: **koi-prose-style**
- Отчёты: **koi-report-review**
- Dev-сервер: `koi-dev-server` (8010 + 8080)
- Визуальная проверка выводов: `koi-visual-qa`
- После сохранения вывода: **koi-project-sync** — предложить синхронизацию; коммит и отправка только по поручению человека
