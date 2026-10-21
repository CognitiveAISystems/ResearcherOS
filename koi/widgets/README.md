# ResearchOS Widgets

ResearchOS ships **only** the runtime: base helpers + discovery API.
Widget packages live in research projects:

```text
tree/<repo>/koi-structure/widgets/<widget-id>/
  manifest.yaml
  README.md
  web/
    widget.js      # export async function mount(host, ctx)
    widget.css
```

## Engine layout (ResearchOS)

```text
koi/widgets/
└── base/          # contracts, registry, CLI, shared JS
```

## Manifest

```yaml
id: cursor-usage                 # must match folder name
title: Cursor usage
summary: Floating ring with remaining Cursor quota
visibility: private
surfaces: [web]                  # web | desktop
default_enabled: true
entry:
  web: web/widget.js
```

## Enable / disable

```bash
python -m koi.widgets.base.cli list
python -m koi.widgets.base.cli enable  verl-agent-craftext/cursor-usage
python -m koi.widgets.base.cli disable verl-agent-craftext/cursor-usage
```

State: `.run/widgets.json`. Keys are `project_id/widget_id`.

## Web contract

```js
export async function mount(host, ctx) {
  // ctx.api, ctx.widgetId, ctx.widgetKey, ctx.assetBase, ctx.manifest
  return () => { /* unmount */ };
}
```

Shared drag helpers: `/widgets/_base/floating.js`.

Assets: `/widgets/<project_id>/<id>/…`.

## Optional backend data

If a widget has `backend/fetch.py` with `fetch() -> dict`, the UI can call:

```http
GET /api/widgets/<project_id>/<widget_id>/data
```
