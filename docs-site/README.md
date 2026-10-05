# ResearcherOS docs-site

Публичный сайт (RU) для GitHub Pages: о проекте, три пути старта, каталог скиллов, уроки.

## Локально

```bash
cd docs-site
python3 scripts/generate_skills.py   # обновить skills/*.html из skills.json
python3 -m http.server 8765
# http://127.0.0.1:8765/
```

## Деплой

Workflow [`.github/workflows/pages.yml`](../.github/workflows/pages.yml) публикует папку `docs-site/` на GitHub Pages при пуше в `main`.

В настройках репозитория: **Settings → Pages → Source: GitHub Actions**.

URL проекта: `https://cognitiveaisystems.github.io/ResearcherOS/` (имя репо `ResearcherOS`).

## Обновить скилл

1. Правьте `skills.json` (описание, mermaid, example).
2. `python3 scripts/generate_skills.py`
3. Закоммитьте `skills.json` и сгенерированные `skills/*.html`.
