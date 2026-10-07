# Research Chat

<p class="lead">Панель «Спросить агента» в локальном ResearcherOS: вопрос уходит в очередь, ответ строится сначала из <code>research.json</code>, отчёты читаются только если не хватает деталей. Доставка ответа — через Inbox Cursor, hooks IDE или фоновый API.</p>

<div class="media-slot" data-media="chat-hero" data-accept="png,jpg,webp,mp4,webm">
  <strong>Слот для картинки или видео</strong>
  Положите файл в <code>media/chat-hero.png</code> (или <code>.jpg</code> / <code>.webp</code> / <code>.mp4</code> / <code>.webm</code>).
</div>

## Как работает

Вопрос не отправляется в «весь репозиторий». Политика ответа:

1. Сопоставить вопрос с записями в <code>research.json</code> (вопрос / рассказ для человека / краткий технический ответ, уверенность, важность, карточка-источник).
2. Собрать связный ответ из подходящих записей.
3. Открыть отчёт эксперимента **только** если нужны цифры или метод, которых нет в записи.
4. Если в базе пусто — сказать об этом и предложить закрыть эксперимент (колонка «готово» → сценарий вывода) или уточнить вопрос.

Если вопрос хорошо совпадает с базой, API может ответить сразу (автоответ), без агента.

Три режима доставки (Настройки → «Агент в чате»):

| Режим | Поведение |
|-------|-----------|
| Inbox-чат (<code>cursor_inbox</code>, рекомендуется) | Watcher пишет wake-строку в лог; чат Cursor слушает <code>AGENT_CHAT_WAKE</code> (~1–3 с) |
| Hooks (<code>cursor_ide</code>) | Очередь подхватывается при старте/остановке чата агента в IDE |
| Фоновый API (<code>api</code>) | Воркер + ключ Cursor API |

Очередь: <code>.run/agent-chat-queue.json</code>. Скилл агента: <code>koi-agent-chat</code> (claim → context → ответ → complete).

Рядом по тому же Inbox-паттерну живут чаты литературы и статьи — отдельные страницы каталога; эта страница только про панель вопросов по проекту.

## Как человек работает в интерфейсе

1. Откройте проект. Кнопка открытия панели чата (на главной рабочей области).
2. При первом запуске Inbox: в панели — шаги «Скопировать сообщение» → вставить в чат **ResearchOS Chat Inbox** в Cursor → «Inbox готов». Статус watcher видно в подсказке.
3. Введите вопрос в поле (плейсхолдер вроде «помогает ли …»). Отправьте форму.
4. В ленте: ваш вопрос, статусы «в очереди» / «прочитано» / «Агент пишет…», затем ответ. Область видимости может учитывать текущий метод или узел (scope).
5. В Настройках переключите режим агента в чате, если нужен hooks или API вместо Inbox.

Без настроенного Inbox (в режиме inbox) панель покажет инструкцию bootstrap; без ключа API — соответствующее уведомление в режиме api.

## Какие сценарии для агента подключаются

| Сценарий (skill) | Роль |
|------------------|------|
| <code>koi-agent-chat</code> | Основной: claim / context / ответ по политике «сначала research.json». |
| <code>koi-done-research</code> | Наполняет базу, из которой чат отвечает; без done-выводов чат часто пустой. |
| <code>koi-knowledge-curator</code> | Курируемые заметки — дополнительный контекст, не замена <code>research.json</code> как первого источника. |
| Hooks скилла | <code>agents/skills/koi-agent-chat/hooks/</code> — session/stop для режима IDE. |

Команды локально:

```bash
python -m koi.agent_chat.cli pending
python -m koi.agent_chat.cli claim <queue_id>
python -m koi.agent_chat.cli context <queue_id>
python -m koi.agent_chat.inbox_cli bootstrap
python -m koi.agent_chat.inbox_cli watch
```

Подробности Inbox: <code>docs/agent-chat-inbox.md</code>.

## Как устроено технически

### Поток данных

UI → HTTP постановка вопроса в очередь → (опционально автоответ по совпадению с <code>research.json</code>) → watcher/hook/worker будит агента → агент claim + context (в JSON: вопрос, project, scope, весь <code>research_database</code>, политика) → ответ пишется обратно в очередь/API → панель показывает сообщение.

Пакет: <code>koi/agent_chat/</code> (cli, inbox_cli, очередь под <code>.run/</code>). Клиент: <code>#agent-chat-panel</code> в <code>web/index.html</code>, логика в <code>web/app.js</code> (режимы <code>agent_chat_mode</code>, bootstrap, watcher status).

### Контекст scope

Если пользователь смотрел метод или узел, в context попадают <code>scope_method</code> / <code>scope_node</code> — ответ можно сузить, не теряя доступ ко всей базе проекта.

### Ограничения

- Чат не заменяет онбординг и не пишет дерево сам по себе.
- Качество ответа упирается в заполненность <code>research.json</code> и отчётов.
- Inbox на macOS без inotify поллит очередь (~2 с); нужен запущенный <code>koi-serve</code> / watcher.

## Связанные страницы

- <a href="knowledge.html">База знаний</a>
- <a href="kanban.html">Канбан экспериментов</a>
- <a href="index.html">Обзор архитектуры</a>
- <a href="related-work.html">Related Work</a>
- <a href="paper.html">PaperDraft</a>

<p class="callout">Текст: <code>content/chat.md</code>. Медиа: <code>media/chat-hero.*</code>.</p>
