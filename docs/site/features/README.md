# Features docs (`docs/site/features`)

Архитектура и каталог локальных фич ResearcherOS. Публикуется вместе с docs/site.

## Локально

```bash
python3 -m pip install -r requirements-dev.txt
cd docs/site
python3 scripts/build_features.py
python3 -m http.server 8765
# http://127.0.0.1:8765/features/
```
