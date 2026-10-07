# PaperDraft

<p class="lead">Черновик научной статьи в проекте: LaTeX и PDF в <code>paper/&lt;slug&gt;/</code>, генерация из контекста исследования, предложения правок от агента с ревью человека, совместное редактирование по Yjs/WebRTC. Долговременная копия — коммиты Git.</p>

<div class="media-slot" data-media="paper-hero" data-accept="png,jpg,webp,mp4,webm">
  <strong>Слот для картинки или видео</strong>
  Положите файл в <code>media/paper-hero.png</code> (или <code>.jpg</code> / <code>.webp</code> / <code>.mp4</code> / <code>.webm</code>).
</div>

## Как работает

Кнопка **PaperDraft** на панели workspace открывает модальное окно статьи. Внутри:

- список статей проекта (вкладки / slug);
- редактор LaTeX (тело или полный файл — по текущей схеме UI);
- превью / сборка PDF;
- генерация или перегенерация из очереди Paper Inbox;
- статус совместного редактирования;
- предложения правок от агента: агент предлагает правки с подсветкой изменений, человек принимает или отклоняет по фрагментам;
- комментарии;
- выгрузка версии в Git (push чекпоинта).

Генерация: задача в <code>.run/paper-queue.json</code> → агент по <code>koi-paper</code> пишет английский LaTeX из дерева, <code>research.json</code>, отчётов и figures → <code>answer</code> собирает <code>main.tex</code> и PDF. Без выдуманных путей к картинкам — только из списка в промпте.

Совместная работа: документ в браузере — CRDT (Yjs); обмен между инстансами — WebRTC (до ~5 человек); signaling только для SDP/ICE (и relay, если DataChannel не открылся). Пиры с разным Git <code>HEAD</code> не синхронизируют текст. Realtime **не** создаёт коммиты.

Правило продукта: предложения агента по тексту статьи остаются на проверке человека — агент (и ассистент в IDE) не должен сам принимать предложение в основной текст от имени пользователя.

## Как человек работает в интерфейсе

1. Выберите проект → **PaperDraft** в доке.
2. Первый раз для Paper Inbox: скопировать bootstrap → чат **ResearchOS Paper Inbox** → «Inbox готов» (в модалке статьи).
3. **Сгенерировать статью** / перегенерировать — статус «Агент работает», затем появление tex/PDF.
4. Правите LaTeX в поле; **Сохранить** пишет на диск; **Собрать PDF** запускает компиляцию.
5. Если пришло предложение правок — в превью сегменты; принять или отклонить фрагмент. Пока предложение активно, поле tex может быть только для чтения.
6. Комментарии — кнопка добавления в панели статьи.
7. Статус коллаба показывает пиров / ошибки signaling. Для двух машин — одинаковые <code>KOI_COLLAB_*</code> в <code>.env</code>.
8. **Push версии** — зафиксировать рукопись в Git, когда нужна долгая точка сохранения.

## Какие сценарии для агента подключаются

| Сценарий (skill) | Роль |
|------------------|------|
| <code>koi-paper</code> | Очередь UI: claim → context → LaTeX → answer (PDF). |
| Paper Inbox | <code>koi.paper.inbox_cli</code>, wake <code>PAPER_WAKE</code>. |
| Контекст проекта | Дерево, инсайты, отчёты, figures — уже в промпте context; отдельно «читать всё подряд» не нужно. |
| (коллаб) | Клиент <code>paper-collab.js</code> / <code>paper-webrtc.js</code>; сервер signaling в <code>koi/paper/collaboration/</code>. |

```bash
python -m koi.paper.cli pending
python -m koi.paper.cli claim <queue_id>
python -m koi.paper.cli context <queue_id>
python -m koi.paper.cli answer <queue_id> -f paper-body.txt
python -m koi.paper.inbox_cli watch
```

## Как устроено технически

### Файлы

Обычно <code>koi-structure/paper/&lt;slug&gt;/</code> — <code>main.tex</code>, PDF, ассеты, метаданные прогресса (в UI есть блок настроек прогресса). Точный layout slug’ов задаёт backend paper API.

### Очередь и API

Пакет <code>koi/paper/</code> (cli, inbox, сборка). Клиент: <code>#paper-modal</code> в <code>web/index.html</code>, логика в <code>web/app.js</code> (состояние статьи, генерация, предложения правок, статус коллаба).

### Realtime

- Yjs-документ в браузере;
- полная сеть WebRTC между инстансами;
- комната от Git remote + slug + путь файла;
- несовместимый <code>HEAD</code> — без обмена апдейтами;
- переменные: <code>KOI_COLLAB_SIGNALING_URL</code>, <code>KOI_COLLAB_TOKEN_SECRET</code>, STUN/TURN.

Чеклист и деплой signaling: <code>docs/paper-collaboration-spike-b.md</code>. На главной features-странице раздел «Синхронизация» описывает, как это стыкуется с Git.

### Ограничения

- Генерация на английском под шаблон конференции (NeurIPS-ориентированный поток в скилле).
- Без совместимой Git-базы коллаб между машинами не стартует.
- Предложение правок без явного принятия человеком в основной текст не должно попадать.

## Связанные страницы

- <a href="related-work.html">Related Work</a>
- <a href="knowledge.html">База знаний</a>
- <a href="chat.html">Research Chat</a>
- <a href="index.html">Обзор архитектуры</a>
- <a href="widgets.html">Виджеты</a>

<p class="callout">Текст: <code>content/paper.md</code>. Медиа: <code>media/paper-hero.*</code>.</p>
