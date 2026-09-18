# AI Tool Wars

AI software compared on what it actually produces. Every tool in a category runs the same
public prompt set; the outputs are published side by side and scored the same way. No paid
placement. Vendors can claim a listing by supplying an API key and get a verified mark and an
embeddable badge.

First category: **AI voice (text to speech)**. See `docs/roadmap.md` for the plan and the
day-60 success test.

## Layout

| Path | Contents |
|---|---|
| `data/catalog/voice/` | The category definition (metrics), five tools, thirty golden prompts. Editing these is how you change what gets benchmarked. |
| `data/snapshot.json` | Generated. The single input the site renders from. Today built from the catalog with no runs, so every tool is "benchmark pending". |
| `data/fixtures/demo-snapshot.json` | Generated. A fictional dataset for previewing the populated layout. Never deployed as real data. |
| `apps/site/` | Astro static site: home, category leaderboard, `X vs Y` pages, tool pages, methodology, sitemap. |
| `scripts/export-snapshot.mjs` | Catalog → snapshot. Grows a Postgres path in the runner phase. |
| `scripts/make-demo-fixtures.py` | Fictional snapshot + tone audio for `SNAPSHOT=demo`. |
| `db/` | PostgreSQL schema, optional pgvector migration, smoke test. |
| `docs/` | `schema.md`, `api-proxy.md`, `roadmap.md`. |
| `.github/workflows/site.yml` | Build + deploy to GitHub Pages. |

## Site

```sh
npm install
npm run build          # regenerates data/snapshot.json from the catalog, builds apps/site/dist
npm run dev            # local dev server, pending state
npm run build:demo     # fictional data, for layout work
npm run dev:demo
npm run check          # astro check (types)
```

Build-time environment: `SITE_URL` (canonical origin), `BASE_PATH` (for GitHub Pages
project sites), `SITE_NAME`, `PUBLIC_CONTACT_EMAIL` (claim CTA address), `SNAPSHOT=demo`.

## Database

```sh
createdb arena
psql -d arena -v ON_ERROR_STOP=1 -f db/migrations/0001_initial_schema.sql
psql -d arena -v ON_ERROR_STOP=1 -f db/tests/0001_smoke.sql     # prints "smoke test passed"
psql -d arena -v ON_ERROR_STOP=1 -f db/migrations/0002_prompt_embeddings.sql   # optional, needs pgvector
```

Requires PostgreSQL 14+. Tested on 16.
