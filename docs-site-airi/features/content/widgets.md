# Виджеты

<p class="lead">Проектные панели поверх локального ResearcherOS: пакет лежит в <code>koi-structure/widgets/</code>, ядро только обнаруживает манифест и монтирует <code>mount()</code> в <code>#koi-widgets-root</code>. Ядро приложения ради виджета не меняют.</p>

<div class="media-slot" data-media="widgets-hero" data-accept="png,jpg,webp,mp4,webm">
  <strong>Слот для картинки или видео</strong>
  Положите файл в <code>media/widgets-hero.png</code> (или <code>.jpg</code> / <code>.webp</code> / <code>.mp4</code> / <code>.webm</code>).
</div>

## Как работает

Виджет — папка в исследовании:

```text
tree/<repo>/koi-structure/widgets/<widget-id>/
  manifest.yaml
  README.md
  web/
    widget.js    # export async function mount(host, ctx)
    widget.css
  backend/       # опционально: fetch.py → dict
```

Манифест задаёт id (как имя папки), title, summary, visibility, surfaces (<code>web</code> / <code>desktop</code>), <code>default_enabled</code>, точку входа.

При загрузке главной страницы клиент запрашивает каталог <code>GET /api/widgets</code>, для каждого включённого с <code>web_url</code> динамически импортирует JS и вызывает <code>mount(host, ctx)</code>. Контекст: <code>api</code>, id/key виджета, <code>assetBase</code>, манифест.

Включение/выключение хранится в <code>.run/widgets.json</code> (ключ <code>project_id/widget_id</code>), не в Git проекта — локальный выбор на машине.

Общие хелперы UI (например плавающее окно): <code>/widgets/_base/floating.js</code> из <code>widgets/base/web/</code> в репозитории ResearcherOS. Ассеты пакета: <code>/widgets/&lt;project_id&gt;/&lt;id&gt;/…</code>.

Опционально бэкенд: если есть <code>backend/fetch.py</code> с <code>fetch() -> dict</code>, UI зовёт <code>GET /api/widgets/&lt;project&gt;/&lt;id&gt;/data</code> (квоты, метрики кластера и т.п.).

Пример из манифеста: «Cursor usage» — кольцо остатка квоты Cursor; другие проекты кладут свои панели (ресурсы, кастомный мониторинг).

## Как человек работает в интерфейсе

1. Виджеты появляются сами на главном workspace, если пакет есть и включён (часто плавающий элемент поверх карты).
2. Включение через CLI (или API), не через отдельную большую «витрину» в UI:

```bash
python -m widgets.base.cli list
python -m widgets.base.cli enable  <project_id>/<widget-id>
python -m widgets.base.cli disable <project_id>/<widget-id>
```

3. Чтобы добавить виджет в проект: положить папку по контракту выше в <code>koi-structure/widgets/</code>, закоммитить в ветку исследования, перезагрузить страницу.
4. Hub задуман как место публикации переиспользуемых виджетов (как скиллы); живая правка пакета — локально в своём проекте.

Отдельного скилла «виджет» нет: это расширение UI, не сценарий агента. Агент может помочь написать <code>widget.js</code>, но монтирование — ответственность runtime.

## Какие сценарии для агента подключаются

| Что | Роль |
|-----|------|
| Нет обязательного skill | Виджет не в очереди Inbox |
| Ручная разработка | Агент в IDE правит файлы в <code>widgets/&lt;id&gt;/</code> по контракту README |
| Hub (каталог) | Позже — browse/download чужих пакетов; сейчас акцент на project-local |

## Как устроено технически

### Engine vs project

| Где | Что |
|-----|-----|
| <code>ReseachOS/widgets/base/</code> | манифест, registry, CLI, <code>floating.js</code> |
| <code>tree/…/koi-structure/widgets/</code> | пакеты исследователя |
| <code>web/widgets-loader.js</code> | загрузка и <code>mount</code> |
| <code>#koi-widgets-root</code> в <code>index.html</code> | контейнер |
| <code>api/routers/widgets.py</code> + <code>api/web_proxy.py</code> | каталог, data, раздача статики |

Legacy: <code>cursor-usage-widget.js</code> — shim на тот же <code>initWidgets</code>.

### Контракт mount

```js
export async function mount(host, ctx) {
  // ctx.api, ctx.widgetId, ctx.widgetKey, ctx.assetBase, ctx.manifest
  return () => { /* unmount */ };
}
```

### Ограничения

- Без валидного манифеста и <code>entry.web</code> пакет не попадёт в каталог с URL.
- Состояние enable локальное (<code>.run/widgets.json</code>) — у коллеги виджет нужно включить отдельно (или сменить <code>default_enabled</code> в манифесте).
- Desktop surface в манифесте зарезервирован; текущий loader — web.

## Связанные страницы

- <a href="paper.html">PaperDraft</a>
- <a href="monitor.html">Монитор прогона</a>
- <a href="index.html">Обзор архитектуры</a>

<p class="callout">Текст: <code>content/widgets.md</code>. Медиа: <code>media/widgets-hero.*</code>. Контракт пакета: <code>widgets/README.md</code>.</p>
