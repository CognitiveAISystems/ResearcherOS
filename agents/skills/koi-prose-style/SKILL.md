---
name: koi-prose-style
description: >-
  Review and rewrite KOI user-facing prose (kanban cards, project.md nodes,
  research question/narrative, knowledge docs) for natural-language style and
  against Wikipedia Signs of AI writing tells. Launches a readonly style-reviewer
  subagent before saving. Use when adding or editing cards on a board,
  descriptions, hypotheses, method titles, or any text shown in the KOI UI
  without extra documentation.
---

# KOI: стиль пользовательского текста

Перед написанием и ревью прочитай общий `tree/glossary.txt` рабочего
пространства и `glossary.txt` рядом с `project.md` дерева, если они существуют.
Следуй разделу «Словарь терминов» в AGENTS.md: локальные правила приоритетнее
общих, термины применяются по смыслу и с учётом склонений. Передай эти правила
всем авторам и критикам. Критик отмечает нарушения словаря и не отвергает
согласованную терминологию по стилистическим причинам; проверка фактов сохраняется.


Перед записью в файл любого **человекочитаемого** текста проекта — заголовки
узлов, описания, карточки канбана (`title` и `desc`), `question`/`narrative` в
`research.json`, курируемые `knowledge/*.md` — прогони цикл **черновик →
subagent-ревью → переписать → снова ревью**. В файл пиши только после `PASS`.

Технические поля (`id`, `answer`, пути, fenced json в отчётах) этим скиллом не
покрываются — там действуют форматные ворота из `AGENTS.md`.

## Когда запускать

1. Пользователь просит добавить/изменить карточки на канбане.
2. Правка `koi-structure/project.md` (problem, cause, method, remediation).
   Если есть `koi-structure/onboard-brief.md` — перед правкой **заголовков**
   узлов перечитай brief и не отходи от высоких целей онбординга.
3. Формулировка `question` / `narrative` (в т.ч. внутри `koi-done-research`).
4. Курируемые документы в `projects/<id>/knowledge/*.md`.
5. Любой текст, который увидит человек в UI без открытия отчёта или глоссария.
6. **Онбординг проекта (`koi-project-onboard`)** — правила стиля на **каждое**
   сообщение человеку (бриф, сверка с литературой, вопрос, комментарий);
   полный цикл subagent → `PASS` на фиксации слоя и перед записью
   `koi-structure/project.md`. Без `PASS` онбординг в файл не пишет.

Если задача **только** про вывод по done-карточке — сначала `koi-done-research`,
но проверку стиля для `question`/`narrative` всё равно выполни по workflow ниже.

## Правила стиля (обязательные)

### A. Понятный язык (KOI)

Должно быть максимально на естественном языке, постараться не смешивать несколько языков сразу, если к примеру нужно название метрики на английском сказать, то нужно сначала говорить естественным языком что за метрика, к примеру "количество кликов на рекламу" а потом в скобках абривиатуру, любые надписи в проекте должны быть написаны так, чтобы человек мог понять без дополнительной документации о проекте.

### B. Без шаблонного AI-тона (Wikipedia)

Дополнительно лови и убирай признаки из
[Wikipedia:Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing).
Краткий чеклист для коротких UI-текстов:
[anti-ai-writing.md](anti-ai-writing.md).

Обязательно смотреть:

1. **Пустые «важные» слова** — groundbreaking, nuanced, seamless, tapestry,
   delve, underscore, foster; по-русски: *революционный*, *многогранный*,
   *стоит отметить*, *играет ключевую роль*, *открывает новые горизонты*.
2. **Горлочистки** — «Важно понимать, что…», «В контексте…», «It is worth
   noting…»; шаблонные «В целом / Подводя итог» без нового факта.
3. **Риторика** — *не только X, но и Y*; натянутые тройки A, B и C;
   ложные диапазоны «от … до …».
4. **Значимость без факта** — *знаменует сдвиг*, *testament*, хвостовые
   `, выделяя…` / `, underscoring…` без измеримого следствия.
5. **Размытые «эксперты»** — без имени источника.
6. **Оформление** — скопление длинных тире, Title Case в русских ярлыках,
   эмодзи/жирный как украшение, плейсхолдеры в видимом тексте.
7. **Вычурные глаголы** вместо «есть / имеет» (*serves as*, *boasts*,
   *выступает в роли*).

Признаки вероятностные: скопление в одном фрагменте = `FAIL`. Чини конкретным
смыслом, не синонимом другого AI-слова.

### Длина заголовков на карте (жёстко)

**Заголовок узла дерева** (первая строка после `# problem:` / `## cause:` /
`### remediation:` / `### cause_evidence:` / `#### method:`) и **заголовок
карточки канбана** (видимый текст до `<!-- id:… -->`) — **не больше 8 слов**
по умолчанию (слова = токены через пробел).

**Исключение (только `koi-project-onboard` clarity loop):** если холодный
читатель дважды не понял критический узел при ≤8 словах — этот title может
быть **до 12 слов**. Остальные заголовки остаются ≤8. Без пометки clarity loop
> 8 слов = `FAIL`.

Все уточнения, метрики, условия, baselines, пути к скриптам — только в
**описании узла** (абзацы после заголовка) или в **`desc:`** карточки. На карте
человек видит короткий ярлык; подробности — при открытии узла/карточки.

| | Пример |
|---|--------|
| ✅ заголовок узла (6 слов) | Политика не переносится на новые среды |
| ✅ описание (при открытии) | После обучения с подкреплением в одной среде доля успешных эпизодов падает вне обучающего распределения… |
| ❌ заголовок (слишком длинный) | Агент на языковой модели после обучения с подкреплением в одной среде хуже действует вне обучающего распределения |

`FAIL`, если заголовок > 8 слов без исключения clarity loop — Suggested rewrite:
короткий title + перенос остального в описание/`desc`.

### Дополнительные уточнения (не противоречат правилам выше)

| Область | Писатель | Ревьюер |
|---------|----------|---------|
| Язык интерфейса | Русский для учебных/русскоязычных проектов; один язык на фразу | Смешение EN/RU в одной фразе без пояснения — нарушение |
| Аббревиатуры | Сначала смысл, потом `(CTR)`, `(CPC)`, `(SFT)` и т.д. | Голые `CTR analysis` / `проверить SFT` без расшифровки — нарушение |
| Заголовок узла / карточки | ≤ **8 слов** (≤12 только critical после onboard clarity loop) | > лимита или весь протокол в title — нарушение |
| Описание узла / `desc` | Подробности, метрики, условия, baselines | Пустое описание при длинном title — нарушение |
| Карточка канбана | Короткий title; `desc` — выход и детали | Заголовок с жаргоном или id вместо смысла — нарушение |
| `research.json` | `question` + `narrative` — для человека; сырые метрики — в `answer` | Числа и шаги обучения в narrative — нарушение |
| Идентификаторы | `id:fmt-aggregate` в HTML-комментарии — ок; в видимом тексте — нет | Видимый `fmt-aggregate` / `kb-sft` — нарушение |
| Анти-AI (Wikipedia) | Конкретный факт; простой глагол; без горлочисток | Скопление AI-маркеров / пустая значимость — нарушение; см. [anti-ai-writing.md](anti-ai-writing.md) |

Эталонные примеры: [examples.md](examples.md), [anti-ai-writing.md](anti-ai-writing.md)
и `bicycle_problem/koi-structure/project.md`.

## Workflow

### 1. Черновик

Собери **только проверяемые фрагменты** — по одному блоку на карточку или поле.
Не смешивай с diff всего файла. Формат для ревьюера:

```text
## Fragment: <карточка id:… | узел cause:… | research question rq-…>
<title или заголовок узла>
desc: <если есть>
---
<остальной видимый текст>
```

### 2. Subagent-ревьюер

Запусти **ровно один** subagent:

- `subagent_type`: `generalPurpose`
- `readonly`: `true`
- `run_in_background`: `false`
- `description`: `KOI prose style review`

Промпт subagent'у (подставь фрагменты; при необходимости приложи выдержки из
`anti-ai-writing.md` и `examples.md`):

```text
You are a KOI prose style reviewer. Read-only. Do not edit files.

Style rules (mandatory):
1) Natural language for a cold reader. Do not mix languages in one phrase.
   If an English metric name is needed, explain in plain language first, then
   put the abbreviation in parentheses (e.g. доля кликов по показам (CTR)).
2) Anti-AI tells (Wikipedia:Signs of AI writing), adapted for short UI text:
   - empty prestige words (groundbreaking, nuanced, seamless, tapestry, delve,
     underscore, foster; RU: революционный, многогранный, стоит отметить,
     играет ключевую роль, открывает новые горизонты)
   - throat-clearing openers / empty wrap-ups (It is worth noting; Важно понимать;
     в целом / подводя итог without new fact)
   - rhetorical filler (not only X but also Y; forced triples; false ranges)
   - significance puffery without measurable consequence; trailing ", highlighting…"
   - vague "experts/researchers say" without a named source
   - em-dash piles, Title Case on Russian labels, emoji/bold decoration,
     placeholders in visible text
   - ornate verbs instead of plain is/has (serves as, boasts, выступает в роли)
   Clusters of tells = FAIL. Fix with specific claims, not synonym swaps.
3) Node/kanban title: at most 8 words; details only in body/desc.
4) No bare English jargon without Russian explanation first.
5) question/narrative: no raw metrics (those belong in answer).
6) Visible text must not contain internal ids (fmt-aggregate, kb-sft, …).

Fragments to review:
<paste fragments from step 1>

Reference: anti-ai-writing.md and examples.md if needed.

Output format (strict):
Line 1: exactly PASS or FAIL
If FAIL: markdown table with columns Fragment | Problem | Suggested rewrite
If PASS: one short sentence why it passes.
```

### 3. Цикл переписывания

- `PASS` → переходи к шагу 4.
- `FAIL` → перепиши **только** указанные фрагменты по колонке Suggested rewrite;
  снова шаг 2. Максимум **3** итерации ревью.
- После 3-го `FAIL` — покажи пользователю таблицу замечаний и спроси, сохранять
  ли как есть или править вручную. **Не пиши в файл** без явного согласия.

### 4. Сохранение

Только после `PASS` — `Write`/`StrReplace` в целевой файл. В ответе пользователю
кратко: «стиль проверен (koi-prose-style), N итераций» или перечисли что изменил
ревьюер.

## Быстрая самопроверка (если subagent недоступен)

Прочитай каждый фрагмент вслух. Если без знания проекта неясно, о чём речь —
перепиши. Аббревиатуру без пояснения — добавь расшифровку в скобках. Пройдись
по [anti-ai-writing.md](anti-ai-writing.md) (пустые слова, горлочистки,
риторика). Это запасной путь; при доступном Task/subagent предпочитай полный
цикл выше.

## Связанные скиллы

- `koi-project-onboard` — attach репо; prose-gate на frames и на финальный skeleton
- `koi-report-review` — отчёты §1–§N: четыре критика (стиль, постановка, SMART, результаты)
- `koi-done-research` — вывод по done-карточке; narrative/question проверяй здесь
- `koi-knowledge-curator` — курируемые knowledge-документы; перед сохранением — здесь
- `koi-project-sync` — commit после правок `koi-structure/`
- Paper anti-AI A–H (статьи): `.cursor/skills/paper-orchestra-shared/writing_quality_check.md`
