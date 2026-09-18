# AI Software Arena

Execution-driven comparison platform and Elo leaderboard for finished AI software and SaaS
tools. Blind A/B battles (LMSYS-style) applied to the B2B application layer: a user submits a
prompt, sees two anonymous outputs side by side, votes, and then gets the reveal, the Elo
delta and a 5-model LLM jury scorecard.

## What's here

| Path | Contents |
|---|---|
| `db/migrations/0001_initial_schema.sql` | Core PostgreSQL schema: tools, categories, prompts, executions, battles, votes, jury evaluations, encrypted vendor API keys, ratings, leaderboard views, Elo trigger, DB roles. |
| `db/migrations/0002_prompt_embeddings.sql` | Optional pgvector migration for snapping paraphrased custom prompts onto golden prompts. |
| `db/tests/0001_smoke.sql` | Rolled-back smoke test covering the Elo trigger, vote guards, cache uniqueness, role grants and the leaderboard view. |
| `docs/schema.md` | Entity map, table-by-table rationale, Elo rules, security boundaries. |
| `docs/api-proxy.md` | Route list, two-tier cache decision flow, live execution proxy, SSE stream, vote/reveal, jury worker, security checklist. |

## Running the schema locally

```sh
createdb arena
psql -d arena -v ON_ERROR_STOP=1 -f db/migrations/0001_initial_schema.sql
psql -d arena -v ON_ERROR_STOP=1 -f db/tests/0001_smoke.sql     # prints "smoke test passed"
# optional, needs pgvector:
psql -d arena -v ON_ERROR_STOP=1 -f db/migrations/0002_prompt_embeddings.sql
```

Requires PostgreSQL 14+. Tested on 16.
