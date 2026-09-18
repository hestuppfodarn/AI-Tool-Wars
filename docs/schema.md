# Database schema

Source of truth: [`db/migrations/0001_initial_schema.sql`](../db/migrations/0001_initial_schema.sql).
Optional semantic cache lookup: [`db/migrations/0002_prompt_embeddings.sql`](../db/migrations/0002_prompt_embeddings.sql) (needs pgvector).
Smoke test: [`db/tests/0001_smoke.sql`](../db/tests/0001_smoke.sql).

## Entity map

```
vendor_accounts ─┬─< users
                 ├─< tools ──< tool_categories >── categories
                 └─< vendor_api_keys >── tools          │
                                                        │
prompts >── categories                                  │
   │                                                    │
   └─< executions >── tools ── vendor_api_keys          │
          │                                             │
          ├─< jury_evaluations                          │
          │                                             │
          └─< battles (execution_a, execution_b) >── tools ×2, prompts, categories
                 │
                 └── votes (1:1) ──< rating_history >── tool_ratings (tool, category)
```

## Tables

| Table | One row is… | Notes |
|---|---|---|
| `categories` | a leaderboard bucket (AI voice, copywriting, coding…) | Carries category defaults: timeout, output modality, jury rubric, golden-prompt target. |
| `tools` | a listed product | Holds the execution adapter config (endpoint, model id, request template, response path). `adapter_version` bumps invalidate that tool's whole cache. `status` walks `draft → seeded → vendor_verified`. |
| `tool_categories` | a tool's entry in a category | A tool may compete in several categories. One `is_primary`. |
| `vendor_api_keys` | one encrypted secret for one tool | Ciphertext only. Budget and rate-limit columns are enforced by the proxy before each live call. Partial unique index: one `active` key per tool per funding source. |
| `prompts` | a prompt in a category | `kind = golden` is Tier-1 cache eligible; `custom` is user-typed. `content_hash` dedupes identical custom prompts so repeats hit cache. |
| `executions` | one tool's output for one prompt | The durable Tier-1 cache. Exactly one `is_canonical` row per (tool, prompt, adapter_version) is what the cache serves. Stores TTFT, latency, tokens, cost. |
| `battles` | one side-by-side comparison shown to one session | Slot A/B is display order. In `blind_random` mode the matchmaker shuffles which tool is in which slot. `revealed_at` gates identity. |
| `votes` | the human verdict on a battle | 1:1 with battle. Inserting a counted vote fires the Elo trigger. Elo before/after snapshots are written onto the row for the reveal panel. |
| `jury_evaluations` | one judge model's 1–10 scorecard for one execution | Keyed by execution, not battle, so a golden output is judged once and reused. `composite` is a stored generated column. |
| `tool_ratings` | the leaderboard row per (tool, category) | Human Elo plus W/L/T counters. |
| `rating_history` | every Elo movement | Feeds sparklines and the post-vote delta. |
| `vendor_accounts`, `users` | identity | Deliberately minimal. Replace with your auth provider's tables; only the FKs matter. |

## Views

- `leaderboard_jury_scores` (materialized): per (tool, category) averages of the four jury metrics, computed over **canonical golden executions only**, so custom prompts can't be used to farm a jury score. Refresh from a cron or after each jury batch: `REFRESH MATERIALIZED VIEW CONCURRENTLY leaderboard_jury_scores;`
- `leaderboard`: joins ratings + jury scores + tool metadata and computes `human_rank` and `jury_rank` per category. This is what `GET /api/leaderboard` reads. The dual-rating toggle in the UI is just which rank column you sort by.

## Elo

Applied inside the database by `apply_vote_elo()` (BEFORE INSERT on `votes`) so there is exactly one place the maths lives and a vote can never be recorded without its rating update.

- Start at 1500. K = 32 until a tool has 30 counted battles in the category, then 16.
- `a` / `b` score 1 / 0. `tie` and `both_bad` score 0.5 each (LMSYS convention); `both_bad` is still counted separately.
- Both `tool_ratings` rows are locked with `FOR UPDATE` in `tool_id` order to avoid deadlocks under concurrent votes.
- The trigger refuses a vote unless the battle is `ready` and not yet revealed, and refuses a second vote per battle.
- `is_counted = false` keeps a vote for audit (fast votes, IP bursts, vendor self-votes) without touching ratings. Flipping `is_counted` later does **not** replay Elo; that's a job for an admin recompute script that walks `votes` in order.
- `votes.choice` and `votes.battle_id` are immutable (trigger).

## Security boundaries in the schema

- `vendor_api_keys.key_ciphertext` / `key_nonce` are AES-GCM envelope-encrypted by the proxy using a KMS-wrapped data key (`kms_key_id`). The database never sees plaintext.
- Two roles: `arena_app` (web/API) gets column-level SELECT on `vendor_api_keys` that **excludes** the secret columns; `arena_proxy` gets full access. The smoke test asserts `arena_app` cannot read `key_ciphertext`.
- `key_fingerprint` (sha256 of plaintext) lets the vendor dashboard dedupe and audit keys without ever storing or returning the key.
- `tools.endpoint_url` must be `https://` (CHECK). SSRF protection (private IP ranges, redirects) is the proxy's job, see `docs/api-proxy.md`.

## Deliberate omissions / next migrations

- **Users/auth**: minimal on purpose. Swap for Supabase/Clerk/NextAuth tables; keep the UUID FKs.
- **Audio/image outputs**: `executions.output_asset_url` points at object storage. There is no `assets` table yet.
- **Abuse signals**: only `is_counted` + hashed IP/UA. A `vote_signals` table (fingerprint, velocity, vendor-IP overlap) is the next step once there's traffic.
- **Vendor billing**: `spent_micros_month` on the key is enough for budget enforcement; invoices/ledger are out of scope for this migration.
- **Partitioning**: `executions`, `battles`, `votes` will want monthly range partitions once they pass ~50M rows. Not needed to start.
