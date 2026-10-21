# ResearchOS Hub

Public read-only catalog of `koi/research` branches.

## Local dev

```bash
cd ReseachOS
pip install -r requirements.txt -r hub/requirements.txt
cp hub/.env.example hub/.env   # fill GitHub OAuth + HUB_SESSION_SECRET
./hub/scripts/run-local.sh
# http://127.0.0.1:8020
```

GitHub OAuth callback for local dev: `http://127.0.0.1:8020/auth/callback`

## Deploy (Yandex Cloud)

```bash
# hub/.env: GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, HUB_SESSION_SECRET
# optional: HUB_S3_ACCESS_KEY, HUB_S3_SECRET_KEY after first run
chmod +x deploy/hub/deploy.sh
./deploy/hub/deploy.sh
```

After deploy, set `HUB_PUBLIC_URL` to the API Gateway URL and update GitHub OAuth callback.

## Architecture

- `hub/app/` — FastAPI backend (OAuth, catalog, GitHub fetch, snapshots)
- `hub/web/` — read-only UI
- `koi/` — shared parser (reuse from engine)
- Data: Object Storage (prod) or `hub/.data/` (local)

Visibility: `public` | `network` | `unlisted`

### Shared skills (v1 sketch)

Layout in the research branch:

```text
koi-structure/skills/<skill-id>/
  manifest.yaml   # required: id, title, summary, visibility
  README.md       # required: page body on Hub
  SKILL.md        # optional: agent playbook
```

On sync of an **enabled public** Hub project, every skill with
`visibility: public` is published into the global pool (`/skills`).
Non-public projects never publish skills (even if the manifest says public).

API:

- `GET /api/catalog/skills`
- `GET /api/skills/{project_slug}/{skill_id}`

