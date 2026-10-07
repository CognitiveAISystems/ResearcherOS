# Формат файла проекта KOI (`project.md`)

Проекты хранятся в `projects/<project-id>/project.md`. Формат рассчитан на чтение и правку человеком и AI-агентом.

## Frontmatter (YAML)

```yaml
---
id: demo-aggregation
title: Название проекта
description: Краткое описание (опционально)
updated: 2026-05-20T12:00:00Z
format: koi/1
---
```

## Дерево гипотез

Узлы задаются заголовками Markdown. Уровень `#` = глубина в дереве.

```markdown
# problem: n-problem

Заголовок проблемы (первая непустая строка после заголовка)

Описание проблемы (следующие строки до следующего заголовка или канбана).

## cause: n-cause-misfold

Причина: агрегация из-за неправильного фолдинга

### cause_evidence: n-ev-fold

Доказательство: ThT-флуоресценция
```

Типы узлов: `problem`, `cause`, `cause_evidence`, `remediation`, `method`, `experiment` (legacy).

Опционально сразу после заголовка:

```markdown
verdict: supported
```

Значения: `open`, `supported`, `refuted`.

## Канбан экспериментов

Только у узлов `method`. Таблица Markdown сразу после текста метода:

```markdown
#### method: m-ev-fold

ThT и TEM

Описание метода…
```

```markdown
<!-- koi:kanban board-ev-fold -->
| backlog | running | done | successful |
| --- | --- | --- | --- |
| TEM инклюзий <!-- id:c2 desc:n=3 повторности --> | ThT time-course <!-- id:c1 --> | |
```

- Имя доски в комментарии: `board-<node-id>` или своё.
- Заголовки колонок — id колонок (латиница, lowercase): `backlog`, `running`, `done`, `successful` (опционально — «Успешные», после `done`).
- Ячейки: текст карточки; метаданные в HTML-комментарии `<!-- id:... created:... updated:... desc:... tags:... deps:... -->`.
- `created:` / `updated:` — опционально, ISO-8601 UTC (`2026-08-07T08:18:00Z`); выставляются системой при создании и любой правке карточки.
- `tags:` — опционально, через запятую (латиница, цифры, `-`, `_`); пример: `tags:gpu,sft,ablation`.
- `deps:` — опционально, prerequisite-карточки (id через запятую); пример: `deps:seg-pareto-groups,seg-targeting`.
- Словарь тегов проекта — опциональный frontmatter `card_tags: [gpu, baseline, ...]` для подсказок в UI.

## Исследовательские вопросы по методу

Вопросы и ответы по завершённым экспериментам **не** хранятся в `project.md`. Они лежат в:

```
projects/<project-id>/research.json
```

Формат:

```json
{
  "version": 1,
  "questions": [
    {
      "id": "rq-sft-diversity",
      "method_id": "m-n-rem-pretrain",
      "card_id": "kb-sft",
      "question": "…",
      "answer": "краткая техническая сводка",
      "narrative": "человекочитаемый ответ для UI",
      "certainty": "definite",
      "importance": 5
    }
  ]
}
```

- `method_id` — id узла `method` из дерева.
- `card_id` — id карточки канбана (источник вывода).
- `certainty`: `definite` | `tentative`.
- `importance`: 1–5.
- Не больше **3** вопросов на один метод.

При загрузке проекта API читает `research.json` и подставляет вопросы в узлы-методы. При сохранении (UI или PATCH) — пишет обратно в `research.json`. Старые блоки `<!-- koi:method-questions -->` в `project.md` при первой загрузке мигрируют автоматически.

## Правила дерева

| Родитель | Дети |
|----------|------|
| — | problem |
| problem | cause |
| cause | cause_evidence, remediation |
| cause_evidence, remediation | experiment |

## Пример для агента

1. Прочитать `projects/<id>/project.md`.
2. Добавить узел: новый заголовок нужного уровня под родителем.
3. Для доказательства/устранения — блок `<!-- koi:kanban ... -->` + таблица.
4. Сохранить файл; API при старте подхватит изменения после перезагрузки проекта (или PUT через API).

## Отчёты по карточкам канбана

Подробные отчёты хранятся отдельно от `project.md`:

```
projects/<project-id>/reports/
  index.json                    # card_id → путь относительно reports/
  Название_гипотезы/            # папка = заголовок узла с канбаном (гипотеза или доказательство)
    Название_карточки.md
```

- Имя файла строится из **заголовка карточки**: пробелы → `_` (остальной текст сохраняется; убираются только символы, недопустимые в пути).
- При совпадении имён добавляется суффикс `_2`, `_3`, …
- При переименовании карточки файл переименовывается; при удалении карточки — удаляется.
- При загрузке проекта и добавлении карточки для **каждой** задачи канбана автоматически создаётся пустой `.md`, если его ещё нет.
- API: `GET/PUT /projects/{id}/boards/{board_id}/cards/{card_id}/report` (тело PUT: `{ "content": "..." }`).

### Содержание отчёта

Полные правила оформления входят в skill **[koi-report-review](../../agents/skills/koi-report-review/)**:

| Файл | Тема |
|------|------|
| [report-skeleton.md](../../agents/skills/koi-report-review/report-skeleton.md) | Шаблон §1–§N и HOW-TODO под каждым разделом |
| [report-rules.md](../../agents/skills/koi-report-review/report-rules.md) | Делать / не делать; оформление без «AI-markdown» |

Кратко: шапка → **зачем** (§1) → **метрика** (§2) → **постановка и сбор** (§3) → по прогону в §4+: **результаты** и **выводы** (без дубля постановки из §3).

В шапке после GPU/train-прогона можно (не обязательно) добавить строку стоимости — UI покажет чип на карточке канбана и бейдж в углу отчёта:

```text
compute_cost: wall_h=2.4; gpu_h=4.8; n_gpus=2; until=SMA SR≥0.8; source=measured
```

`source=recovered` — восстановлено из старых логов; analysis/literature без train — строку не писать.

В шапке после GPU/train-прогона можно (не обязательно) добавить строку стоимости — UI покажет чип на карточке канбана и бейдж в углу отчёта:

```text
compute_cost: wall_h=2.4; gpu_h=4.8; n_gpus=2; until=SMA SR≥0.8; source=measured
```

`source=recovered` — восстановлено из старых логов; analysis/literature без train — строку не писать.

Примеры финального теста (см. также стили):

- **SFT:** согласованная метрика diversity на **train** и **test** для чекпоинтов LoRA (база vs адаптер); промежуточный probe на `fork_prompts.json` не является финальным тестом.
- **RL (закрытие гипотезы):** таблица SR для BASE, SFT до RL, BASE+RL, SFT+RL; минимум `SR(SFT+RL) > SR(BASE+RL)`.

Эталонный отчёт в репозитории: `projects/ai-agents-embodied/reports/.../Запустить_обучение_SFT_на_наборе.md`.
