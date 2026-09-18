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
| `scripts/export-snapshot.mjs` | Catalog + recorded runs → snapshot. Copies run audio into the site. Grows a Postgres path later. |
| `scripts/run-voice.mjs` | Runner: executes the prompt bank against one tool, records audio and timings under `data/runs/`. Adapters: `inworld`, `openai`, `elevenlabs`, `cartesia`. |
| `.github/workflows/benchmark.yml` | Runs the bank on a GitHub runner from repository secrets, commits `data/runs/`, redeploys the site. Manual trigger or weekly. |
| `scripts/score-voice.mjs` | Scorer: ASR transcript → word error rate → accuracy; LLM judge → instruction following. Writes scores into `runs.json`. |
| `scripts/verdict.mjs` | Day-60 continue/stop check from click metrics and vendor-key state. |
| `scripts/mock-tts-server.mjs` | Local stand-in for a vendor TTS API and the OpenAI ASR/chat endpoints, to test the pipeline offline. |
| `docs/outreach/` | Vendor outreach email templates. |
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

## Running a tool

```sh
cp .env.example .env            # then fill in the vendor key(s); .env is gitignored
node scripts/run-voice.mjs --tool inworld-tts --limit 3      # smoke
node scripts/run-voice.mjs --tool inworld-tts                # full 30-prompt bank
npm run build                                                # snapshot picks up data/runs/, site shows outputs
```

Runs are idempotent (successful prompts are skipped unless `--force`). Failures are recorded and
published, never hidden. Scoring needs `OPENAI_API_KEY` (Whisper transcripts and the judge):

```sh
node scripts/score-voice.mjs --tool inworld-tts      # writes scores into data/runs/voice/inworld-tts/runs.json
npm run build                                         # ratings, ranks, verdicts and badges update
```

Speed is computed at export time as a rank across tools, so it appears once two tools have runs
on the same prompt. Naturalness has no backend yet and stays blank.

### Running from GitHub Actions (no local machine needed)

1. Add the vendor keys as repository secrets under Settings, Secrets and variables, Actions:
   `INWORLD_API_KEY`, `OPENAI_API_KEY`, `ELEVENLABS_API_KEY`, `CARTESIA_API_KEY`. Tools without a
   secret are skipped.
2. Run the **benchmark** workflow from the Actions tab (or via the API). Inputs: `tools`
   (comma-separated slugs), `limit` (smoke test), `force`.
3. The workflow commits `data/runs/` back to the branch and redeploys the site.

Only the Inworld adapter has been exercised (against a mock). The OpenAI, ElevenLabs and
Cartesia adapters are written from their public API shapes and untested; Cartesia also needs a
real voice id in `data/catalog/voice/tools.json`. Google Cloud TTS and Amazon Polly need
signed auth and have no adapter yet.

To test the pipeline without network access: `node scripts/mock-tts-server.mjs &` then add
`--base-url http://localhost:9999` to the runner.

## Database

```sh
createdb arena
psql -d arena -v ON_ERROR_STOP=1 -f db/migrations/0001_initial_schema.sql
psql -d arena -v ON_ERROR_STOP=1 -f db/tests/0001_smoke.sql     # prints "smoke test passed"
psql -d arena -v ON_ERROR_STOP=1 -f db/migrations/0002_prompt_embeddings.sql   # optional, needs pgvector
```

Requires PostgreSQL 14+. Tested on 16.
