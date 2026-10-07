# База знаний

<p class="lead">Накопленный опыт проекта: вердикты гипотез, инсайты из done-карточек и курируемые заметки. Часть файлов собирается правилами из <code>project.md</code> и <code>research.json</code>; глубокие обзоры пишет человек или агент в <code>knowledge/</code>.</p>

<div class="media-slot" data-media="knowledge-hero" data-accept="png,jpg,webp,mp4,webm">
  <strong>Слот для картинки или видео</strong>
  Положите файл в <code>media/knowledge-hero.png</code> (или <code>.jpg</code> / <code>.webp</code> / <code>.mp4</code> / <code>.webm</code>).
</div>

## Как работает

Цель — не открывать заново то, что уже проверили: новый человек или агент видит, какие гипотезы закрыты, какие выводы сняты с отчётов, какие темы разобраны вручную.

Два слоя:

| Слой | Где | Кто пишет |
|------|-----|-----------|
| Автоген | <code>KNOWLEDGE.md</code>, <code>knowledge/hypotheses.md</code>, <code>KNOWLEDGE_LOG.md</code> | модуль <code>koi/knowledge/</code> при сохранении проекта |
| Курируемый | <code>knowledge/&lt;тема&gt;.md</code> (кроме <code>hypotheses.md</code>) | человек или сценарий куратора |

Источник правды для автогена: дерево и вердикты в <code>project.md</code>, инсайты в <code>research.json</code> (обычно ≤3 на метод: вопрос, краткий ответ, рассказ для интерфейса, уверенность, важность 1–5, ссылка на карточку). Отчёты — в <code>reports/</code>.

Канонические пути: <code>tree/&lt;repo&gt;/koi-structure/</code> (ветка <code>koi/research</code>). В старых текстах встречается <code>projects/&lt;id&gt;/</code> — тот же смысл mount’а.

Автоген **не правят руками** — перезапишется. Новый <code>.md</code> в <code>knowledge/</code> попадает в оглавление при следующем сохранении или запросе БЗ.

Инсайт появляется, когда карточку разобрали после колонки «готово» (сценарий done-research или ingest отчёта). Вердикт причины может обновиться из §5 рабочего отчёта при автовливании.

## Как человек работает в интерфейсе

1. На панели инструментов рабочей области — кнопка **Knowledge** («База знаний»).
2. Модальное окно: вкладка **База** — дашборд (счётчики подтверждено / опровергнуто / открыто, число инсайтов, документов, отчётов; полоса по вердиктам; карточки гипотез с инсайтами и ссылкой на отчёт; плитки документов; хвост журнала).
3. Клик по документу или отчёту открывает Markdown в том же окне (хлебные крошки назад к дашборду).
4. Вкладка **Журнал пополнений** — полный <code>KNOWLEDGE_LOG.md</code> (что и когда записалось).
5. Файлами: начать с <code>KNOWLEDGE.md</code> и идти по ссылкам; курируемые темы править только в своих <code>knowledge/*.md</code>.

Research Chat опирается на ту же иерархию знаний (отдельная страница каталога) — не на «весь репозиторий подряд».

## Какие сценарии для агента подключаются

| Сценарий (skill) | Роль относительно БЗ |
|------------------|----------------------|
| <code>koi-done-research</code> | После «готово»: формулирует инсайт в <code>research.json</code> (question / answer / narrative, certainty, importance). Триггер автогена при сохранении. |
| <code>koi-knowledge-curator</code> | Кросс-разбор нескольких экспериментов → курируемый <code>knowledge/&lt;тема&gt;.md</code> (связки, противоречия, пределы, открытые вопросы). Автоген не трогает. |
| <code>koi-report-review</code> / ingest | Рабочий отчёт <code>.run.md</code> с §5 может влиться в вердикт + инсайты + колонку done (<code>report_ingest</code>). |
| <code>koi-prose-style</code> | <code>question</code> и <code>narrative</code>, тексты курируемых заметок — для человека, без AI-штампов. |
| <code>koi-agent-chat</code> | Чат по проекту читает накопленные выводы, а не сырой проход по всем файлам подряд. |

## Как устроено технически

### Файлы

```text
koi-structure/
  project.md
  research.json
  reports/… (+ index.json)
  KNOWLEDGE.md          ← оглавление [генерируется]
  KNOWLEDGE_LOG.md      ← журнал [генерируется]
  knowledge/
    hypotheses.md       ← [генерируется]
    .state.json         ← снимок для diff журнала
    NN-тема.md          ← курируемые
```

Пересборка: хук при <code>save_project</code> / запросе знаний. Diff журнала против <code>knowledge/.state.json</code> — пустые пересборки записей не плодят.

### API и UI

- <code>GET /projects/{id}/knowledge</code> — оглавление Markdown (может пересобрать);
- <code>GET /projects/{id}/knowledge/summary</code> — JSON для дашборда;
- <code>GET /projects/{id}/knowledge/log</code> — журнал;
- <code>GET /projects/{id}/knowledge/file?path=…</code> — файл;
- ассеты картинок из knowledge — отдельный URL в клиенте.

Клиент: кнопка <code>#btn-knowledge</code>, модалка и дашборд в <code>web/app.js</code> (<code>knowledgeState</code>, summary → чипы и карточки гипотез). Модуль ядра: пакет <code>koi/knowledge/</code>.

### Связь с остальным

- Канбан даёт done-карточки и отчёты; БЗ не хранит колонки.
- Дерево даёт вердикты причин; инсайты висят на методе через <code>method_id</code>.
- Hub показывает снимок тех же файлов только для чтения.

## Связанные страницы

- <a href="kanban.html">Канбан экспериментов</a>
- <a href="monitor.html">Монитор прогона</a>
- <a href="research-tree.html">Исследовательское дерево</a>
- <a href="index.html">Обзор архитектуры</a>
- <a href="chat.html">Research Chat</a>

<p class="callout">Текст: <code>content/knowledge.md</code>. Медиа: <code>media/knowledge-hero.*</code>. Подробный пользовательский гайд также в <code>docs/human/knowledge-base.md</code>.</p>
