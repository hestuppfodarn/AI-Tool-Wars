# API proxy: side-by-side execution and caching

The proxy is the only process that can call a vendor endpoint. Browsers talk to it over
our own routes; it decrypts keys, enforces budgets, runs both sides of a battle, streams
results back, persists them, and decides what goes into the cache.

```
Browser ──► /api/arena/*  (arena_app role, no key access)
                 │
                 ▼
          Battle service ──► Redis (Tier-1 hot cache, rate limits, locks)
                 │
                 ▼
          Execution proxy (arena_proxy role, KMS access)
                 │            ▲
                 ▼            │ jury jobs
          Vendor APIs      Jury worker (5 judge models)
```

## Routes

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/arena/battles` | Create a battle. Resolves prompt, picks tools, decides cache vs live per side. |
| `GET` | `/api/arena/battles/:id/stream` | SSE stream of both outputs, timers, and status transitions. |
| `GET` | `/api/arena/battles/:id` | Snapshot (for reload / non-SSE clients). Blind mode: no tool identity until revealed. |
| `POST` | `/api/arena/battles/:id/vote` | Record the human vote. Elo is applied by the DB trigger. |
| `POST` | `/api/arena/battles/:id/reveal` | Unlock identities, return Elo deltas and the jury scorecard. Auto-called after vote. |
| `GET` | `/api/leaderboard?category=&rating=human|jury` | Reads the `leaderboard` view. |
| `GET` | `/api/categories/:slug/prompts` | Golden prompt presets for the dropdown. |
| `POST` | `/api/vendor/tools/:id/keys` | Vendor submits a key. Validated by a live probe before `status = active`. |
| `POST` | `/internal/execute` | **Not internet-reachable.** Battle service → execution proxy. mTLS or private network only. |

Everything under `/api/arena/*` runs as `arena_app`. Only the execution proxy runs as
`arena_proxy` and only it holds the KMS decrypt permission.

## `POST /api/arena/battles`

Request:

```jsonc
{
  "mode": "blind_random" | "head_to_head",
  "category": "copywriting",
  "prompt": { "golden_id": "…" } | { "text": "…", "params": {} },
  "tool_a": "copy-a",   // head_to_head only
  "tool_b": "copy-b"    // head_to_head only
}
```

Flow:

1. **Resolve prompt.** Golden id → row. Custom text → normalise, `prompt_content_hash()`,
   upsert into `prompts(category_id, content_hash)`; identical text from different users
   collapses onto one row. Optional: embed and call `match_golden_prompt()` (migration 0002)
   to snap near-paraphrases onto a golden prompt.
2. **Pick tools.** `head_to_head` uses the request. `blind_random` runs the matchmaker:
   sample two tools in the category with `status IN ('seeded','vendor_verified')`, weighted
   toward pairs with similar Elo and fewer battles (uncertainty sampling), excluding pairs
   this session has seen recently. Then **shuffle slot order** so tool identity can't be
   inferred from position.
3. **Decide the source per side** (see cache logic below). Insert the `battles` row with
   `status = 'pending'` and `served_from` set once both sides are decided.
4. **Return `{ battle_id, stream_url, tier: { a: 'cache'|'live', b: … } }`.** The client
   opens the SSE stream immediately.

## Cache logic

Key scheme, shared between Redis and `executions.cache_key`:

```
exec:{tool_id}:{prompt.content_hash}:{tool.adapter_version}
```

`adapter_version` is part of the key so a vendor shipping a new model or a changed request
template invalidates their whole cache with one column bump, and old rows stay for audit.

```
resolveSide(tool, prompt):
  key = cacheKey(tool, prompt)

  # Tier 1a — Redis hot cache
  hit = redis.get(key)
  if hit: return { source: 'cache', execution: hit }

  # Tier 1b — durable cache in Postgres (Redis was cold/evicted)
  row = executions.findCanonical(tool.id, prompt.id, tool.adapter_version, status='success')
  if row:
    redis.set(key, row, ttl = prompt.kind == 'golden' ? ∞ : 7d)
    return { source: 'cache', execution: row }

  # Tier 2 — live
  # Single-flight: if another request is already executing this exact key,
  # subscribe to its stream instead of paying twice.
  lock = redis.set(`lock:${key}`, requestId, NX, EX 90)
  if not lock: return { source: 'live', follow: `stream:${key}` }

  return { source: 'live', execute: true }
```

Golden prompts are pre-executed by a **seeding job** (`for each active golden prompt × each
listed tool → execute if no canonical row`) so users almost never trigger Tier-2 on them.
The seeding job also queues jury evaluations, so the scorecard is ready at reveal time.

Custom prompts go live once, then the resulting execution becomes canonical for that
(tool, prompt) and is cached with a 7-day Redis TTL. The Postgres row is permanent, so a
second user typing the same text months later is still a cache hit.

What is **never** cached: executions with `status <> 'success'`, outputs over
`tools.max_output_bytes`, and anything that failed the response scrubber (below).

## Live execution: `/internal/execute`

Called once per live side. Runs as `arena_proxy`.

```
execute(battle_id, side, tool, prompt, request_id):
  key = selectKey(tool)                     # vendor key preferred over platform key
    ├─ status = 'active', not expired
    ├─ spent_micros_month + estimate <= monthly_budget_micros   (else mark 'exhausted', fail side)
    └─ redis token bucket  rl:{key.id}  ≤ rate_limit_rpm         (else 'rate_limited')

  secret = kms.decrypt(key.kms_key_id, key.key_ciphertext, key.key_nonce)   # in-memory only, zeroed after
  adapter = adapters[tool.adapter_kind]
  req = adapter.build(tool, prompt, secret)   # secret goes into the header/query per key.auth_scheme
  guardEndpoint(tool.endpoint_url)            # https only, resolve DNS, reject private/link-local, no redirects

  exec = executions.insert({ tool_id, prompt_id, api_key_id: key.id, adapter_version, cache_key, source:'live', status:'running', started_at: now() })

  t0 = now()
  stream = adapter.call(req, timeout = tool.timeout_ms ?? category.default_timeout_ms)
  for chunk in stream:
    if first: ttft_ms = now() - t0; emit(side, 'ttft', ttft_ms)
    buffer += chunk; if len(buffer) > max_output_bytes: abort('output_too_large')
    emit(side, 'delta', chunk)                # SSE to the client, also redis pub/sub stream:{key} for single-flight followers
  latency_ms = now() - t0

  out = scrub(adapter.extract(buffer))        # strip vendor request ids, echoed headers, anything that looks like a key
  executions.update(exec.id, { status:'success', output_text: out, ttft_ms, latency_ms, tokens_in, tokens_out, cost_micros, finished_at })
  vendor_api_keys.update(key.id, { last_used_at, spent_micros_month += cost_micros, consecutive_errors: 0 })

  # Promote to canonical + cache. ON CONFLICT on the partial unique index means a
  # concurrent racer loses gracefully.
  executions.markCanonical(exec.id)           # UPDATE … SET is_canonical = true WHERE NOT EXISTS (another canonical)
  redis.set(key, exec, ttl)
  redis.del(`lock:${key}`)

  jury.enqueue(exec.id)
  emit(side, 'done', { latency_ms, ttft_ms })
```

Error path: `status ∈ {error, timeout, rate_limited}`, `consecutive_errors += 1`, and after 5
consecutive errors the key flips to `invalid` and the tool to `suspended` with a vendor
notification. The battle goes to `failed` if either side fails; it is never scored.

## SSE stream: `GET /api/arena/battles/:id/stream`

One connection carries both sides. Event shapes:

```
event: status     data: {"side":"a","source":"cache"}          // or "live"
event: ttft       data: {"side":"b","ms":312}
event: delta      data: {"side":"b","text":"Get paid "}
event: done       data: {"side":"b","latency_ms":2104,"ttft_ms":312}
event: ready      data: {"battle_id":"…"}                      // both sides done → status='ready', vote enabled
event: error      data: {"side":"a","code":"timeout"}
```

Cache-served sides are replayed as one `delta` after a short artificial delay (200–400 ms)
so the UI doesn't reveal which side was cached; the real `ttft_ms`/`latency_ms` from the
canonical execution are what the timer shows and what the jury's Execution Velocity uses.

Nothing on this stream identifies the tool in blind mode. Slot labels are "A" and "B";
model names, vendor request ids and headers are stripped by the scrubber.

## Vote and reveal

`POST /vote` inserts into `votes` with `session_id`, `time_to_vote_ms` (from `ready` to
click) and hashed IP. The DB trigger validates the battle is `ready` and unrevealed, applies
Elo, snapshots before/after onto the vote row, and sets `battles.status = 'voted'`.

Integrity checks that set `is_counted = false` before insert: vote < 1.5 s after `ready`, same
IP hash voting > N times/min on the same pair, session belongs to a vendor account that owns
one of the tools.

`POST /reveal` (auto-called after vote; also allowed without a vote in `head_to_head` mode,
which simply makes the battle unscorable): sets `revealed_at`, returns

```jsonc
{
  "a": { "tool": {slug,name,logo}, "elo_before": 1500, "elo_after": 1516, "jury": { … } },
  "b": { … },
  "prompt": { … },
  "jury": {
    "judges": ["gpt-4o","claude-3-7-sonnet","gemini-2.0-flash","llama-3.3-70b","deepseek-v3"],
    "metrics": ["constraint_adherence","factuality_integrity","conciseness_utility","execution_velocity"],
    "status": "complete" | "partial"        // partial → client polls /battles/:id until complete
  }
}
```

## Jury worker

- Consumes `exec.id` jobs. For each of the 5 judge models, one call with the category's
  `jury_rubric`, the prompt's `constraints` and `reference`, and the output. Judges return
  three 1–10 scores + rationale as JSON; the worker validates the shape and writes
  `jury_evaluations` (idempotent on `(execution_id, judge_model, judge_version)`).
- **Execution Velocity** is not asked of the LLM. The worker computes it from the execution's
  `ttft_ms` and `latency_ms` against the category's rolling latency percentiles (p10 → 10,
  p90 → 1, linear in between) and writes the same value under every judge row so the
  composite stays a simple mean.
- Judges see the output **without** the tool name, and outputs are judged one at a time,
  not pairwise, so a golden output's score is stable across battles.
- Bumping `judge_version` (rubric change) re-judges lazily: the reveal endpoint reports
  `partial` and enqueues the missing rows.
- After each batch: `REFRESH MATERIALIZED VIEW CONCURRENTLY leaderboard_jury_scores`.

## Security checklist

- Keys: envelope-encrypted at rest; decrypted only inside the execution proxy, only for the
  duration of one request; never logged, never in Redis, never in SSE. `arena_app` cannot
  SELECT the ciphertext columns (enforced by column grants, tested in the smoke test).
- Vendor key validation: on submission the proxy runs one golden prompt through it. Success
  → `status = active`, `tools.verified_at`, `tools.verified_by_key_id`, `tools.status =
  vendor_verified`. Failure → `invalid` with the vendor-facing error, no retry storm.
- SSRF: `endpoint_url` is HTTPS by CHECK; the proxy resolves DNS and rejects RFC1918,
  loopback, link-local, and cloud metadata ranges; follows no redirects; pins a
  per-request egress timeout.
- Budgets: enforced before the call using the adapter's cost estimate; reconciled after with
  the actual usage. Platform keys have `monthly_budget_micros = NULL` but still get a global
  cap in config.
- Rate limits: per key (`rl:{key_id}`), per session (`rl:session:{id}` for live battles,
  e.g. 10/hour anonymous), and per IP.
- Output scrubbing: regex pass for `sk-`, `Bearer `, JWT-shaped tokens, and the vendor's own
  key fingerprint before anything is persisted or streamed.
- Blind mode: tool ids never appear in any response until `revealed_at`; the `battles` row
  is read through a view that nulls `tool_a_id/tool_b_id` when `revealed_at IS NULL`.

## Skeleton (TypeScript, framework-agnostic)

```ts
// POST /api/arena/battles
export async function createBattle(req: CreateBattleRequest, ctx: Ctx) {
  const category = await db.categories.bySlug(req.category);
  const prompt   = await resolvePrompt(category.id, req.prompt);
  const [toolA, toolB] = req.mode === 'head_to_head'
    ? await db.tools.bySlugs([req.tool_a, req.tool_b])
    : await matchmaker.pair(category.id, ctx.sessionId);

  const [sideA, sideB] = await Promise.all([resolveSide(toolA, prompt), resolveSide(toolB, prompt)]);

  const battle = await db.battles.insert({
    mode: req.mode, category_id: category.id, prompt_id: prompt.id,
    tool_a_id: toolA.id, tool_b_id: toolB.id,
    execution_a_id: sideA.execution?.id ?? null,
    execution_b_id: sideB.execution?.id ?? null,
    status: 'pending', served_from: servedFrom(sideA, sideB),
    session_id: ctx.sessionId, user_id: ctx.userId ?? null,
    client_ip_hash: ctx.ipHash, user_agent_hash: ctx.uaHash,
  });

  for (const [side, r, tool] of [['a', sideA, toolA], ['b', sideB, toolB]] as const) {
    if (r.execute) void internalExecute({ battleId: battle.id, side, toolId: tool.id, promptId: prompt.id });
  }
  return { battle_id: battle.id, stream_url: `/api/arena/battles/${battle.id}/stream`,
           tier: { a: sideA.source, b: sideB.source } };
}

// GET /api/arena/battles/:id/stream
export async function streamBattle(battleId: string, ctx: Ctx, sse: SseSink) {
  const battle = await db.battles.forSession(battleId, ctx.sessionId);   // 404 if not theirs
  for (const side of ['a', 'b'] as const) {
    const execId = battle[`execution_${side}_id`];
    if (execId) { void replayCached(side, execId, sse); continue; }      // cache side
    redis.subscribe(`battle:${battleId}:${side}`, (ev) => sse.send(ev));   // live side
  }
  redis.subscribe(`battle:${battleId}:ready`, () => sse.send({ event: 'ready', data: { battle_id: battleId } }));
}
```

`internalExecute` is the pseudocode in "Live execution" above, running in the proxy process
with the `arena_proxy` connection and the KMS client. The battle service never imports it
directly; it calls it over the private network.
