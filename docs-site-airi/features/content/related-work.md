# Related Work

<p class="lead">Отдельная страница литературы: коллекция статей (поиск, Zotero, CSV), вопрос исследователя, кластеризация ответов и черновик Related Works. Результаты лежат в <code>koi-structure/literature/</code>; агент будится через Literature Inbox.</p>

<div class="media-slot" data-media="related-work-hero" data-accept="png,jpg,webp,mp4,webm">
  <strong>Слот для картинки или видео</strong>
  Положите файл в <code>media/related-work-hero.png</code> (или <code>.jpg</code> / <code>.webp</code> / <code>.mp4</code> / <code>.webm</code>).
</div>

## Как работает

Вход с главной рабочей области — пункт **RelatedWork** (открывает <code>literature.html</code>, можно с <code>?project=…</code>).

Три источника коллекции:

| Источник | Что делает |
|----------|------------|
| Найти | поиск (в т.ч. arXiv / настройки режима поиска) по ключевым словам |
| Zotero | подключение user id + API key, выбор коллекции |
| CSV | загрузка локальной таблицы статей |

Дальше типичный цикл:

1. Собрать и отметить статьи слева.
2. Задать **исследовательский вопрос** в центре.
3. Запустить анализ (промпт / кластеризация) — агенты читают выбранные тексты относительно вопроса.
4. Смотреть кластеры, findings, черновик Related Works справа / в панелях.
5. История прогонов — в <code>literature/index.json</code> и по ссылке «Прошлые вопросы».

Мультиагентная кластеризация (скилл orchestrator): 3–4 агента-работника без пересечения статей → обмен суждениями о похожести → оркестратор собирает кластеры и черновик Related Work → критик и правщик → <code>report.md</code> и <code>related_work.md</code> в каталоге прогона.

Короткая очередь UI → Markdown Related Works: кнопка Related Work ставит задачу в <code>.run/related-work-queue.json</code>; скилл <code>koi-related-work</code> делает claim → пишет 2–5 абзацев только по фактам из промпта → <code>answer</code> возвращает текст на страницу.

Разбор **одной** статьи как графа утверждений (морфология) — соседний инструмент (<code>morphology.html</code>), часто из карточки статьи; к Related Work по коллекции не подменяет.

## Как человек работает в интерфейсе

1. С workspace: клик **RelatedWork** в доке (или прямой URL). Выберите проект в селекте, если нужно.
2. Пустая коллекция: три кнопки Найти / Zotero / CSV. После загрузки — список, «Все» / «Сброс», «+» для добавления ещё.
3. Введите вопрос → «Промпт» (или связанный запуск кластеризации — по текущему UI сценарию). Настройте Inbox литературы один раз: скопировать bootstrap → чат **ResearchOS Literature Inbox** → «Inbox готов».
4. Пока агент работает — статус «Агент работает» / таймер. Появление отчёта и Related Works — в колонке insights / панелях просмотра.
5. Навигация по кластерам слева; настройки поиска (шестерёнка) — режим internet/library, ключи Zotero.
6. «←» к проекту возвращает в <code>index.html</code>.

## Какие сценарии для агента подключаются

| Сценарий (skill) | Роль |
|------------------|------|
| <code>literature-cluster-orchestrator</code> | Полный прогон: работники → таблица похожести → кластеры → Related Work + критик → файлы в <code>literature/&lt;run_id&gt;/</code>. |
| <code>koi-related-work</code> | Очередь из UI: короткий синтез Related Works в Markdown обратно на страницу. |
| Literature Inbox | <code>koi.related_work.inbox_cli</code>, wake <code>RELATED_WORK_WAKE</code> в <code>.run/logs/related-work-watch.log</code>. |
| Article morphology (внешний скилл / <code>morphology.html</code>) | Граф утверждений одной статьи со ссылками на места в тексте. |

```bash
python -m koi.related_work.cli pending
python -m koi.related_work.cli claim <queue_id>
python -m koi.related_work.cli context <queue_id>
python -m koi.related_work.cli answer <queue_id> -f related-work.md
python -m koi.related_work.inbox_cli watch
```

## Как устроено технически

### Хранение прогонов

```text
koi-structure/literature/
  index.json                 # история run_id
  <run_id>/                  # {query_hash}_{UTC}
    index.json
    report.md                # основной рендер в UI
    findings.json
    similarity.json
    related_work.draft.md
    related_work.md
    rw_critique.json
    workers/…
```

<code>query_hash</code> — отпечаток вопроса; <code>run_id</code> уникален на каждый запуск.

### Клиент и очереди

Страница: <code>web/literature.html</code> + <code>web/literature.js</code>. Связь с проектом с главной: <code>btn-related-work</code> в <code>web/app.js</code>. Очередь Related Work: пакет <code>koi/related_work/</code>. Морфология: <code>web/morphology.html</code> (+ JS рядом).

Настройки RW в <code>localStorage</code> (<code>koi-rw-settings</code>): режим поиска, Zotero.

### Ограничения

- Без выбранных статей и вопроса кластеризация не стартует.
- Related Works из очереди не выдумывает статьи — только материал промпта/кластеров.
- PDF и полные тексты зависят от того, что удалось скачать/приложить к записи библиотеки.

## Связанные страницы

- <a href="chat.html">Research Chat</a> (тот же Inbox-паттерн, другая очередь)
- <a href="knowledge.html">База знаний</a>
- <a href="index.html">Обзор архитектуры</a>
- <a href="paper.html">PaperDraft</a>

<p class="callout">Текст: <code>content/related-work.md</code>. Медиа: <code>media/related-work-hero.*</code>.</p>
