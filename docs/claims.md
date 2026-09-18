# Claims: sign in, claim your tool, add a key

Vendors verify ownership of a listing and hand over an API key without a person in the loop.
The runs then execute on the vendor's account and the listing gets the *vendor verified* mark.
Claiming changes who pays for the run, not the rank.

Backend: one Supabase project (Auth, Postgres with RLS, Vault, two Edge Functions). Front end:
`/claim/` on the static site. Consumer: the benchmark workflow, which pulls active keys with the
service role right before it runs the adapters.

```
browser (anon key + user JWT)                     GitHub Actions (service role)
  │  magic link ─────────▶ Supabase Auth             │
  │  claim_tool() ───────▶ Postgres (RLS)            │  fetch-vendor-keys.mjs
  │  submit_api_key() ───▶   └─▶ Vault (secret)  ◀───┘  reads active_keys_for_runner
  │  functions.invoke ───▶ Edge: validate-key ── one probe ──▶ vendor API
  │                        Edge: verify-dns ──── DoH TXT ────▶ 1.1.1.1 / 8.8.8.8
```

## Ownership rules

1. **Email domain (instant).** The claimant signs in with a magic link. `claim_tool(slug)` reads
   their email from `auth.users` and compares its domain with the tool's website domain from the
   catalog (`tools.domain`, seeded from `data/catalog/*/tools.json`). A match is exact, a parent
   (`google.com` verifies `cloud.google.com`) or a subdomain (`mail.elevenlabs.io` verifies
   `elevenlabs.io`). Match → claim `verified` / `email_domain`.
2. **DNS TXT (minutes).** No match → claim `pending` / `dns_txt` with a random token. The page
   shows the record to publish: `TXT <tool domain> toolwars-verify=<token>` (also accepted on
   `_toolwars.<tool domain>`). "Check DNS" calls the `verify-dns` function, which resolves the
   name over DNS-over-HTTPS (Cloudflare, then Google) and flips the claim to `verified` on a match.
3. **Manual (days).** No DNS access, or the tool lives on a shared host (github.com,
   huggingface.co: `tools.domain` is null there, nobody auto-verifies those). The vendor emails
   the contact address; a human sets `status = 'verified', verification = 'manual'` in the table
   editor. This is the only human step and it is rare.

Open-weight tools (`open:*` / `open-llm:*` adapters, or `open_weights: true`) are `claimable = false`:
they run on our CPU, there is no account to move them to.

## What a vendor sees

`/claim/`, five numbered steps on one page: sign in (email, magic link), pick the tool (grouped by
category, chips for benchmark status, "Claimed", "Vendor key active", "Open weights", "Yours"),
claim it (instant or the DNS record), add the key (adapter shown, password field, one submit), and
status (last four characters, `pending validation` / `active` / `invalid` with the vendor's reason,
re-check and revoke). Resubmitting replaces the previous key. `?tool=<slug>` preselects; the
"Claim X" buttons on category, pair and tool pages link there when the backend is configured and
stay `mailto:` when it is not.

## What the agent does

- `claim_tool` and `submit_api_key` are `SECURITY DEFINER` functions owned by `postgres`. The
  second one hashes the key (`key_fingerprint`), keeps the last four characters, writes the secret
  with `vault.create_secret`, revokes any previous live key for the same tool and account (and
  deletes its Vault row), inserts the metadata row as `pending_validation` and returns the row id.
- `validate-key` (Edge Function, called by the page with the user's JWT right after submit, or by
  CI with the service role) checks the caller can see the key row (RLS), reads the secret through
  `read_key_secret()` (service role only), and runs one probe: Inworld `POST /tts/v1/voice` with a
  five-word text, OpenAI `POST /v1/audio/speech` with "Key check.", ElevenLabs `GET /v1/user`,
  Cartesia `GET /voices` with the version header, `openai_chat` / `anthropic` / `gemini` a one-token
  completion. 2xx → `active` + `validated_at`; 401/403/402/4xx → `invalid` + `last_error`;
  5xx/429/timeout → stays `pending_validation` with the error, re-checkable. Every probe is a row in
  `key_validation_log`. Errors are scrubbed of the key before they are stored.
- `verify-dns` (Edge Function) as above; only a signed-in claimant can call it for their own claim.
- The benchmark workflow runs `scripts/fetch-vendor-keys.mjs`, which reads
  `active_keys_for_runner` and writes `export INWORLD_API_KEY=…` lines (plus `TOOLWARS_KEY_<SLUG>`)
  to a 0600 file the job sources; each value is registered with `::add-mask::` first.
- `scripts/seed-supabase-tools.mjs` upserts the `tools` table from the catalog whenever it changes
  (`--sql` prints the same as statements for the SQL editor; `--dry-run` prints the rows).

## What never happens

- The key never comes back from the database: no user-readable table, view or function returns it.
  `vendor_api_keys` holds `key_last4` and a sha256 fingerprint, nothing else.
- The key is never in the browser after the RPC returns: the input is cleared before the request is
  sent, nothing is written to `localStorage` (only the Supabase session token lives there).
- The key is never in a log: Edge Functions log ids and status codes; the CI script writes secrets
  only into the sourced file and mask commands.
- The key is never in git: `.vendor-keys.env` is generated in the job and not committed.
- Nobody pays for placement and no claim changes a score. This is on the page.

## The 5-minute human setup

`.github/workflows/setup-supabase.yml` automates this from one `SUPABASE_ACCESS_TOKEN` secret
(creates the project, applies `supabase/migrations/*.sql` through the Management API SQL endpoint,
deploys the functions, seeds `tools`, commits `data/supabase.public.json`). By hand it is:

1. **Create a project** at supabase.com (free tier is fine). Note the project ref, the URL
   `https://<ref>.supabase.co`, the anon key and the service-role key (Settings → API).
2. **Apply the migration.** Either `npx supabase link --project-ref <ref>` then
   `npx supabase db push`, or paste `supabase/migrations/0001_claims.sql` into the SQL editor and
   run it (it is one idempotent script; running it twice is fine).
3. **Seed the tools:** `SUPABASE_URL=https://<ref>.supabase.co SUPABASE_SERVICE_ROLE_KEY=…
   node scripts/seed-supabase-tools.mjs` (or paste the output of `--sql` into the SQL editor).
4. **Deploy the functions:** `npx supabase functions deploy validate-key --project-ref <ref>` and
   the same for `verify-dns`. They use the `SUPABASE_URL` / `SUPABASE_ANON_KEY` /
   `SUPABASE_SERVICE_ROLE_KEY` secrets Supabase injects; nothing to set.
5. **Auth:** Authentication → Providers → Email: enabled, "Confirm email" off is fine for magic
   links. Authentication → URL configuration: Site URL
   `https://hestuppfodarn.github.io/AI-Tool-Wars/claim/`, and add the same URL to the redirect
   allowlist (plus `http://localhost:4321/claim/` for local dev).
6. **GitHub:** secrets `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` (or just
   `SUPABASE_ACCESS_TOKEN` + `SUPABASE_PROJECT_REF`; the scripts resolve the service-role key from
   the Management API); variables `PUBLIC_SUPABASE_URL` and `PUBLIC_SUPABASE_ANON_KEY` for the site
   build, unless the workflow commits `data/supabase.public.json`, which the build prefers.
7. Push. The site build picks up the config, `/claim/` goes live, the CTA buttons switch from
   `mailto:` to the page.

Local check without Supabase (PostgreSQL 16):

```sh
psql -v ON_ERROR_STOP=1 -f scripts/tests/supabase-stubs.sql     # auth.uid()/vault stand-ins, test only
psql -v ON_ERROR_STOP=1 -f supabase/migrations/0001_claims.sql
psql -v ON_ERROR_STOP=1 -f scripts/tests/claims-smoke.sql       # prints "claims smoke test passed"
```

The stubs store Vault secrets in plaintext and use `NOLOGIN` roles; they exist only so the
migration and the RLS/RPC behaviour can be exercised off Supabase.

## Threat model

| Who | Can | Cannot |
|---|---|---|
| Anonymous | read `tools`, `adapters`, `tool_claim_status` (claimed / key active per tool) | see any claim, key row, or secret |
| Signed-in user | `claim_tool`, `submit_api_key`, `revoke_api_key`; read own `vendor_accounts`, `tool_claims`, `vendor_api_keys` metadata, `key_validation_log`; update own `monthly_budget_micros` | insert or edit claims or key rows directly, change key status, read anyone else's rows, read Vault, call `read_key_secret`, select `active_keys_for_runner` |
| Edge Functions | as the caller for the ownership check, then service role for `read_key_secret` and status writes | return or log a secret |
| CI (service role) | select `active_keys_for_runner` at run time | anything the runner does not need; the role is fetched per run from the Management API when `SUPABASE_ACCESS_TOKEN` is used, so no long-lived key sits in the repository |
| Postgres owner | everything, including Vault | (this is Supabase's own `postgres`; the dashboard SQL editor runs as it) |

Mechanics: RLS on every table; `SECURITY DEFINER` functions with an empty `search_path` and
schema-qualified names; `REVOKE`s so the runner view and the secret reader are service-role only;
Vault encrypts at rest with a key the database cannot read back without `vault.decrypted_secrets`,
which only the owner-context view and function touch. The RPC argument `p_api_key` travels in the
request body over TLS to PostgREST; Supabase does not log statement parameters. The supabase-js
session token is in `localStorage` on the claim page only, scoped to the site origin; that is the
standard magic-link model and it can do nothing RLS does not allow.

Residual risks, stated: a compromised claimant mailbox can claim (same as any email-verified
flow); a vendor whose key has broad scope is trusting us with that scope, so the page asks for a
scoped, revocable key with a monthly cap; the probe costs the vendor one tiny request.

## Workflow snippet for `benchmark.yml`

Insert before "Run tools" and source the file in that step. Both env forms work; the step is a
no-op (exit 2 → treated as no keys) when the backend is not configured.

```yaml
      - name: Fetch vendor keys
        id: vendor
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}
          SUPABASE_ACCESS_TOKEN: ${{ secrets.SUPABASE_ACCESS_TOKEN }}
          SUPABASE_PROJECT_REF: ${{ vars.SUPABASE_PROJECT_REF }}
        run: |
          node scripts/fetch-vendor-keys.mjs --out .vendor-keys.env || [ $? -eq 2 ]
```

and in "Run tools", first line of the script:

```yaml
        run: |
          set -u
          [ -f .vendor-keys.env ] && source .vendor-keys.env
          # vendor keys override the repository secrets for the same adapter; tools without either are skipped
```

`steps.vendor.outputs.vendor_tools` carries the comma-separated slugs with an active vendor key,
for a later step that marks those runs `vendor_verified` in the snapshot. `.vendor-keys.env` must
stay out of `git add` (the commit step only adds `data/runs`).
