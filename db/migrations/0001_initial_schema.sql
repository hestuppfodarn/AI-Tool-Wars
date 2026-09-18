-- =============================================================================
-- AI Software Arena — foundational PostgreSQL schema
-- Migration 0001: core tables for tools, categories, prompts, battles, votes,
-- jury evaluations, vendor API keys, and the rating/leaderboard machinery.
--
-- Requires PostgreSQL 14+ (gen_random_uuid() is built in). pgcrypto is only
-- used for digest() when computing prompt content hashes in SQL.
--
-- Design notes are in docs/schema.md. Short version:
--   * Ratings are per (tool, category), not per tool — a tool that competes in
--     "copywriting" and "coding" holds two independent Elo ratings.
--   * An `execution` is one tool's output for one prompt. A battle references
--     two executions. Golden-prompt executions are reusable across many
--     battles; this is what makes the Tier-1 cache free to serve.
--   * Jury evaluations hang off executions (not battles) so a golden output is
--     judged once and the scorecard is reused every time it is served.
--   * Vendor API keys are stored as ciphertext only. The web/app role never
--     gets SELECT on that table; only the proxy service role does.
-- =============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

-- -----------------------------------------------------------------------------
-- Enumerations
-- -----------------------------------------------------------------------------

CREATE TYPE tool_status AS ENUM (
  'draft',            -- created, not yet visible in the arena
  'seeded',           -- Phase 1: listed on platform-owned key
  'vendor_verified',  -- Phase 2: vendor supplied a working key, ownership proven
  'suspended',        -- temporarily hidden (key exhausted, repeated errors, abuse)
  'delisted'          -- permanently removed from matchmaking
);

CREATE TYPE adapter_kind AS ENUM (
  'openai_chat',      -- OpenAI-compatible /v1/chat/completions
  'anthropic_messages',
  'http_json',        -- generic: request_template + response_path
  'custom'            -- handled by a named adapter module in the proxy
);

CREATE TYPE key_funding_source AS ENUM ('platform', 'vendor');

CREATE TYPE api_key_status AS ENUM (
  'pending_validation',
  'active',
  'invalid',          -- vendor endpoint rejected the key
  'exhausted',        -- budget or vendor quota hit
  'revoked'
);

CREATE TYPE prompt_kind AS ENUM (
  'golden',           -- curated benchmark prompt, Tier-1 cache eligible
  'custom'            -- user-typed prompt, Tier-2 live sandbox
);

CREATE TYPE execution_source AS ENUM ('cache', 'live');

CREATE TYPE execution_status AS ENUM (
  'queued', 'running', 'success', 'error', 'timeout', 'rate_limited', 'cancelled'
);

CREATE TYPE battle_mode AS ENUM (
  'blind_random',     -- category chosen, tools paired by matchmaker
  'head_to_head'      -- user picked Tool A and Tool B explicitly
);

CREATE TYPE battle_status AS ENUM (
  'pending',          -- created, executions not yet started
  'running',          -- at least one execution in flight
  'ready',            -- both outputs available, awaiting vote
  'voted',            -- vote recorded, reveal unlocked
  'failed',           -- one or both executions failed; not scorable
  'expired'           -- never voted within the TTL
);

CREATE TYPE vote_choice AS ENUM ('a', 'b', 'tie', 'both_bad');

CREATE TYPE user_role AS ENUM ('user', 'vendor', 'admin');

-- -----------------------------------------------------------------------------
-- Utility: updated_at trigger
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

-- -----------------------------------------------------------------------------
-- Identity (kept minimal; swap for your auth provider's user table as needed)
-- -----------------------------------------------------------------------------

CREATE TABLE vendor_accounts (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name           text NOT NULL,
  website_url    text,
  contact_email  citext NOT NULL,
  verified_at    timestamptz,                 -- set when first vendor key validates
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE users (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email              citext UNIQUE,
  display_name       text,
  role               user_role NOT NULL DEFAULT 'user',
  vendor_account_id  uuid REFERENCES vendor_accounts(id) ON DELETE SET NULL,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX users_vendor_account_idx ON users (vendor_account_id) WHERE vendor_account_id IS NOT NULL;

-- -----------------------------------------------------------------------------
-- categories
-- -----------------------------------------------------------------------------

CREATE TABLE categories (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug                  citext NOT NULL UNIQUE,          -- 'ai-voice', 'copywriting', 'coding'
  name                  text NOT NULL,
  description           text,
  parent_id             uuid REFERENCES categories(id) ON DELETE SET NULL,
  golden_prompt_target  smallint NOT NULL DEFAULT 75    -- how many golden prompts to maintain
                        CHECK (golden_prompt_target BETWEEN 0 AND 1000),
  -- Category-level defaults used by the proxy and the jury.
  default_timeout_ms    integer NOT NULL DEFAULT 60000 CHECK (default_timeout_ms > 0),
  output_modality       text NOT NULL DEFAULT 'text'    -- 'text' | 'audio' | 'image' | 'code' | 'json'
                        CHECK (output_modality IN ('text','audio','image','code','json')),
  jury_rubric           jsonb NOT NULL DEFAULT '{}'::jsonb,  -- category-specific judge instructions
  sort_order            integer NOT NULL DEFAULT 0,
  is_active             boolean NOT NULL DEFAULT true,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX categories_parent_idx ON categories (parent_id);
CREATE INDEX categories_active_sort_idx ON categories (is_active, sort_order);

-- -----------------------------------------------------------------------------
-- tools
-- -----------------------------------------------------------------------------

CREATE TABLE tools (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug                citext NOT NULL UNIQUE,
  name                text NOT NULL,
  vendor_account_id   uuid REFERENCES vendor_accounts(id) ON DELETE SET NULL,
  vendor_name         text,                              -- display only, denormalised
  website_url         text,
  logo_url            text,
  tagline             text,
  description         text,
  status              tool_status NOT NULL DEFAULT 'draft',

  -- Execution adapter. Everything the proxy needs to call this tool lives
  -- here EXCEPT the secret, which lives in vendor_api_keys.
  adapter_kind        adapter_kind NOT NULL DEFAULT 'openai_chat',
  adapter_version     smallint NOT NULL DEFAULT 1,       -- bump to invalidate the whole cache for this tool
  endpoint_url        text,                              -- validated against SSRF allowlist in the proxy
  model_identifier    text,                              -- e.g. 'gpt-4o', 'eleven_multilingual_v2'
  request_template    jsonb NOT NULL DEFAULT '{}'::jsonb, -- for http_json: body template with {{prompt}} slots
  response_path       text,                              -- JSONPath/JMESPath to the output in the vendor response
  default_params      jsonb NOT NULL DEFAULT '{}'::jsonb, -- temperature, voice_id, etc.
  supports_streaming  boolean NOT NULL DEFAULT false,
  timeout_ms          integer,                           -- NULL → category default
  max_output_bytes    integer NOT NULL DEFAULT 262144,

  -- Ownership / verification
  verified_at         timestamptz,                       -- set when the vendor's own key first succeeds
  verified_by_key_id  uuid,                              -- FK added after vendor_api_keys exists

  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT tools_timeout_positive CHECK (timeout_ms IS NULL OR timeout_ms > 0),
  CONSTRAINT tools_endpoint_https CHECK (endpoint_url IS NULL OR endpoint_url ~* '^https://')
);

CREATE INDEX tools_status_idx ON tools (status);
CREATE INDEX tools_vendor_account_idx ON tools (vendor_account_id);

-- A tool can compete in several categories.
CREATE TABLE tool_categories (
  tool_id      uuid NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
  category_id  uuid NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  is_primary   boolean NOT NULL DEFAULT false,
  created_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tool_id, category_id)
);

CREATE INDEX tool_categories_category_idx ON tool_categories (category_id);
CREATE UNIQUE INDEX tool_categories_one_primary_idx ON tool_categories (tool_id) WHERE is_primary;

-- -----------------------------------------------------------------------------
-- vendor_api_keys
-- Secrets are envelope-encrypted by the proxy (KMS data key). This table never
-- holds plaintext. See docs/api-proxy.md §Security.
-- -----------------------------------------------------------------------------

CREATE TABLE vendor_api_keys (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tool_id             uuid NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
  vendor_account_id   uuid REFERENCES vendor_accounts(id) ON DELETE SET NULL,
  funding_source      key_funding_source NOT NULL DEFAULT 'vendor',
  label               text,                               -- 'prod key Sept 2026'

  -- Ciphertext + envelope metadata. Never log, never return over HTTP.
  key_ciphertext      bytea NOT NULL,
  key_nonce           bytea NOT NULL,
  kms_key_id          text NOT NULL,                       -- which KMS key/version wrapped the DEK
  key_fingerprint     text NOT NULL,                       -- sha256(plaintext) hex; dedupe + audit without plaintext
  key_last4           text,                                -- for the vendor dashboard only

  -- How the secret is presented to the vendor endpoint.
  auth_scheme         text NOT NULL DEFAULT 'bearer'      -- 'bearer' | 'header' | 'query' | 'basic'
                      CHECK (auth_scheme IN ('bearer','header','query','basic')),
  auth_param_name     text NOT NULL DEFAULT 'Authorization',

  status              api_key_status NOT NULL DEFAULT 'pending_validation',
  validated_at        timestamptz,
  last_used_at        timestamptz,
  last_error          text,
  consecutive_errors  integer NOT NULL DEFAULT 0,

  -- Spend controls enforced by the proxy before every live call.
  monthly_budget_micros  bigint,                          -- NULL = unlimited (platform keys) ; micro-dollars
  spent_micros_month     bigint NOT NULL DEFAULT 0,
  spend_month            date NOT NULL DEFAULT date_trunc('month', now())::date,
  rate_limit_rpm         integer,                         -- NULL = adapter default

  rotated_from_id     uuid REFERENCES vendor_api_keys(id) ON DELETE SET NULL,
  expires_at          timestamptz,
  revoked_at          timestamptz,
  created_by          uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT vendor_api_keys_budget_nonneg CHECK (monthly_budget_micros IS NULL OR monthly_budget_micros >= 0),
  CONSTRAINT vendor_api_keys_spent_nonneg  CHECK (spent_micros_month >= 0)
);

-- At most one ACTIVE key per tool per funding source (a tool may carry a
-- platform seed key and a vendor key simultaneously during the Phase 1→2 hand-off;
-- the proxy prefers the vendor key).
CREATE UNIQUE INDEX vendor_api_keys_one_active_idx
  ON vendor_api_keys (tool_id, funding_source) WHERE status = 'active';
CREATE INDEX vendor_api_keys_tool_status_idx ON vendor_api_keys (tool_id, status);
CREATE UNIQUE INDEX vendor_api_keys_fingerprint_idx ON vendor_api_keys (tool_id, key_fingerprint);

ALTER TABLE tools
  ADD CONSTRAINT tools_verified_by_key_fk
  FOREIGN KEY (verified_by_key_id) REFERENCES vendor_api_keys(id) ON DELETE SET NULL;

COMMENT ON TABLE  vendor_api_keys IS 'Encrypted vendor/platform API keys. Only the arena_proxy role may SELECT key_ciphertext/key_nonce.';
COMMENT ON COLUMN vendor_api_keys.key_ciphertext IS 'AES-256-GCM ciphertext of the vendor secret, wrapped by kms_key_id. Never expose.';

-- -----------------------------------------------------------------------------
-- prompts
-- -----------------------------------------------------------------------------

CREATE TABLE prompts (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  category_id    uuid NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
  kind           prompt_kind NOT NULL DEFAULT 'custom',
  title          text,                                   -- short label shown in preset dropdown (golden only)
  body           text NOT NULL,                          -- the prompt text sent to tools
  params         jsonb NOT NULL DEFAULT '{}'::jsonb,     -- per-prompt overrides (voice, language, max_len…)
  constraints    jsonb NOT NULL DEFAULT '[]'::jsonb,     -- machine-checkable rubric items for Constraint Adherence
  reference      jsonb,                                  -- optional ground truth for Factuality (facts, expected outputs)
  -- sha256(normalised body || canonical params). Identical custom prompts collapse
  -- onto one row so their executions become cache hits too.
  content_hash   text NOT NULL,
  golden_rank    integer,                                -- ordering inside the preset list; NULL for custom
  created_by     uuid REFERENCES users(id) ON DELETE SET NULL,
  is_active      boolean NOT NULL DEFAULT true,
  usage_count    integer NOT NULL DEFAULT 0,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT prompts_body_nonempty CHECK (length(btrim(body)) > 0),
  CONSTRAINT prompts_body_size     CHECK (length(body) <= 20000),
  CONSTRAINT prompts_golden_has_rank CHECK (kind <> 'golden' OR golden_rank IS NOT NULL)
);

CREATE UNIQUE INDEX prompts_category_hash_idx ON prompts (category_id, content_hash);
CREATE INDEX prompts_golden_idx ON prompts (category_id, golden_rank) WHERE kind = 'golden' AND is_active;
CREATE INDEX prompts_created_by_idx ON prompts (created_by) WHERE created_by IS NOT NULL;

-- Helper so the app and the SQL seed scripts hash prompts identically.
CREATE OR REPLACE FUNCTION prompt_content_hash(p_body text, p_params jsonb DEFAULT '{}'::jsonb)
RETURNS text LANGUAGE sql IMMUTABLE STRICT AS $$
  SELECT encode(digest(
    lower(regexp_replace(btrim(p_body), '\s+', ' ', 'g')) || E'\n' || COALESCE(p_params::text, '{}'),
    'sha256'), 'hex');
$$;

-- -----------------------------------------------------------------------------
-- executions — one tool's output for one prompt. The durable form of the
-- Tier-1 cache. Redis holds a hot copy keyed by cache_key.
-- -----------------------------------------------------------------------------

CREATE TABLE executions (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tool_id          uuid NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
  prompt_id        uuid NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,
  api_key_id       uuid REFERENCES vendor_api_keys(id) ON DELETE SET NULL, -- NULL when served from cache
  adapter_version  smallint NOT NULL,
  -- 'exec:{tool_id}:{prompt.content_hash}:{adapter_version}' — same string used in Redis.
  cache_key        text NOT NULL,
  source           execution_source NOT NULL,
  status           execution_status NOT NULL DEFAULT 'queued',

  -- The canonical execution for a (tool, prompt) is the one served from the
  -- Tier-1 cache. Exactly one per (tool, prompt, adapter_version).
  is_canonical     boolean NOT NULL DEFAULT false,

  output_text      text,                                 -- text/code/json modalities
  output_json      jsonb,                                -- structured output or metadata (e.g. audio URL, duration)
  output_asset_url text,                                 -- object storage URL for audio/image outputs
  output_bytes     integer,
  error_code       text,
  error_message    text,

  -- Execution Velocity inputs
  ttft_ms          integer,                              -- time to first token/byte
  latency_ms       integer,                              -- end-to-end
  tokens_in        integer,
  tokens_out       integer,
  cost_micros      bigint,                               -- estimated vendor cost, micro-dollars

  vendor_request_id text,                                -- vendor's own trace id, for support
  model_snapshot    text,                                -- model_identifier at run time
  started_at        timestamptz,
  finished_at       timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT executions_latency_nonneg CHECK (latency_ms IS NULL OR latency_ms >= 0),
  CONSTRAINT executions_ttft_nonneg    CHECK (ttft_ms IS NULL OR ttft_ms >= 0),
  CONSTRAINT executions_ttft_le_latency CHECK (ttft_ms IS NULL OR latency_ms IS NULL OR ttft_ms <= latency_ms)
);

CREATE UNIQUE INDEX executions_canonical_idx
  ON executions (tool_id, prompt_id, adapter_version) WHERE is_canonical;
CREATE INDEX executions_cache_key_idx ON executions (cache_key) WHERE status = 'success';
CREATE INDEX executions_tool_prompt_idx ON executions (tool_id, prompt_id, created_at DESC);
CREATE INDEX executions_api_key_idx ON executions (api_key_id, created_at DESC) WHERE api_key_id IS NOT NULL;

-- -----------------------------------------------------------------------------
-- battles
-- -----------------------------------------------------------------------------

CREATE TABLE battles (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  mode             battle_mode NOT NULL,
  category_id      uuid NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
  prompt_id        uuid NOT NULL REFERENCES prompts(id) ON DELETE RESTRICT,

  -- Slot A/B is what the user SEES. In blind mode the matchmaker randomises
  -- which tool lands in which slot; identity is withheld until revealed_at.
  tool_a_id        uuid NOT NULL REFERENCES tools(id) ON DELETE RESTRICT,
  tool_b_id        uuid NOT NULL REFERENCES tools(id) ON DELETE RESTRICT,
  execution_a_id   uuid REFERENCES executions(id) ON DELETE SET NULL,
  execution_b_id   uuid REFERENCES executions(id) ON DELETE SET NULL,

  status           battle_status NOT NULL DEFAULT 'pending',
  -- 'cache' if both outputs came from Tier-1, 'live' if both were Tier-2,
  -- 'mixed' otherwise. Useful for cost reporting and for weighting votes.
  served_from      text CHECK (served_from IN ('cache','live','mixed')),

  -- Who is playing. Anonymous sessions are the common case.
  user_id          uuid REFERENCES users(id) ON DELETE SET NULL,
  session_id       uuid NOT NULL,                        -- signed cookie / anon id
  client_ip_hash   text,
  user_agent_hash  text,

  revealed_at      timestamptz,
  expires_at       timestamptz NOT NULL DEFAULT now() + interval '1 hour',
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT battles_distinct_tools CHECK (tool_a_id <> tool_b_id),
  CONSTRAINT battles_distinct_execs CHECK (execution_a_id IS NULL OR execution_a_id <> execution_b_id)
);

CREATE INDEX battles_session_idx   ON battles (session_id, created_at DESC);
CREATE INDEX battles_user_idx      ON battles (user_id, created_at DESC) WHERE user_id IS NOT NULL;
CREATE INDEX battles_category_idx  ON battles (category_id, created_at DESC);
CREATE INDEX battles_tool_a_idx    ON battles (tool_a_id);
CREATE INDEX battles_tool_b_idx    ON battles (tool_b_id);
CREATE INDEX battles_pending_idx   ON battles (expires_at) WHERE status IN ('pending','running','ready');

-- -----------------------------------------------------------------------------
-- tool_ratings — the leaderboard row. One per (tool, category).
-- -----------------------------------------------------------------------------

CREATE TABLE tool_ratings (
  tool_id            uuid NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
  category_id        uuid NOT NULL REFERENCES categories(id) ON DELETE CASCADE,

  -- Human Elo
  human_elo          numeric(8,2) NOT NULL DEFAULT 1500.00,
  human_battles      integer NOT NULL DEFAULT 0,
  human_wins         integer NOT NULL DEFAULT 0,
  human_losses       integer NOT NULL DEFAULT 0,
  human_ties         integer NOT NULL DEFAULT 0,
  human_both_bad     integer NOT NULL DEFAULT 0,
  last_battle_at     timestamptz,

  updated_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tool_id, category_id),
  FOREIGN KEY (tool_id, category_id) REFERENCES tool_categories(tool_id, category_id) ON DELETE CASCADE
);

CREATE INDEX tool_ratings_leaderboard_idx ON tool_ratings (category_id, human_elo DESC);

-- Every Elo movement, for sparklines and the post-vote "Elo delta" panel.
CREATE TABLE rating_history (
  id           bigserial PRIMARY KEY,
  tool_id      uuid NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
  category_id  uuid NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
  vote_id      uuid NOT NULL,                            -- FK added after votes exists
  elo_before   numeric(8,2) NOT NULL,
  elo_after    numeric(8,2) NOT NULL,
  delta        numeric(8,2) GENERATED ALWAYS AS (elo_after - elo_before) STORED,
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX rating_history_tool_cat_idx ON rating_history (tool_id, category_id, created_at DESC);

-- -----------------------------------------------------------------------------
-- votes — exactly one per battle. Inserting a vote drives the Elo update.
-- -----------------------------------------------------------------------------

CREATE TABLE votes (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  battle_id        uuid NOT NULL UNIQUE REFERENCES battles(id) ON DELETE CASCADE,
  user_id          uuid REFERENCES users(id) ON DELETE SET NULL,
  session_id       uuid NOT NULL,
  choice           vote_choice NOT NULL,

  -- Integrity. is_counted=false keeps the row for audit but excludes it from
  -- Elo (e.g. vote arrived after reveal, duplicate IP burst, vendor self-vote).
  is_counted       boolean NOT NULL DEFAULT true,
  exclusion_reason text,
  time_to_vote_ms  integer,                              -- from status='ready' to vote; <2s is suspicious
  client_ip_hash   text,

  -- Snapshot of the Elo maths so the reveal panel can be rendered without
  -- recomputation and the history is auditable.
  k_factor         numeric(5,2),
  elo_a_before     numeric(8,2),
  elo_b_before     numeric(8,2),
  elo_a_after      numeric(8,2),
  elo_b_after      numeric(8,2),

  created_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX votes_session_idx ON votes (session_id, created_at DESC);
CREATE INDEX votes_user_idx    ON votes (user_id, created_at DESC) WHERE user_id IS NOT NULL;
CREATE INDEX votes_uncounted_idx ON votes (created_at DESC) WHERE NOT is_counted;

-- Deferred: apply_vote_elo() writes history from a BEFORE INSERT trigger on
-- votes, i.e. before the vote row itself is visible. Checked at commit.
ALTER TABLE rating_history
  ADD CONSTRAINT rating_history_vote_fk FOREIGN KEY (vote_id) REFERENCES votes(id) ON DELETE CASCADE
  DEFERRABLE INITIALLY DEFERRED;

-- -----------------------------------------------------------------------------
-- jury_evaluations — one row per (execution, judge model). Attached to the
-- execution rather than the battle so a cached golden output is judged once.
-- Scores are 1–10. execution_velocity is computed by the proxy from
-- ttft/latency against the category's latency distribution, not by the LLM.
-- -----------------------------------------------------------------------------

CREATE TABLE jury_evaluations (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  execution_id          uuid NOT NULL REFERENCES executions(id) ON DELETE CASCADE,
  judge_model           text NOT NULL,                    -- 'gpt-4o', 'claude-3-7-sonnet', 'gemini-2.0-flash', 'llama-3.3-70b', 'deepseek-v3'
  judge_version         text NOT NULL DEFAULT 'v1',       -- judge prompt/rubric version; bump to re-judge
  constraint_adherence  smallint NOT NULL CHECK (constraint_adherence BETWEEN 1 AND 10),
  factuality_integrity  smallint NOT NULL CHECK (factuality_integrity BETWEEN 1 AND 10),
  conciseness_utility   smallint NOT NULL CHECK (conciseness_utility BETWEEN 1 AND 10),
  execution_velocity    smallint NOT NULL CHECK (execution_velocity BETWEEN 1 AND 10),
  composite             numeric(4,2) GENERATED ALWAYS AS (
                          (constraint_adherence + factuality_integrity + conciseness_utility + execution_velocity) / 4.0
                        ) STORED,
  rationale             text,
  raw_response          jsonb,
  judge_latency_ms      integer,
  judge_cost_micros     bigint,
  created_at            timestamptz NOT NULL DEFAULT now(),

  UNIQUE (execution_id, judge_model, judge_version)
);

CREATE INDEX jury_evaluations_execution_idx ON jury_evaluations (execution_id);

-- -----------------------------------------------------------------------------
-- Elo: applied by trigger on votes insert.
-- K = 32 until a tool has 30 counted battles in the category, then 16.
-- tie / both_bad score 0.5 each (LMSYS convention); both_bad is still recorded.
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION elo_k_factor(p_battles integer) RETURNS numeric
LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN p_battles < 30 THEN 32.0 ELSE 16.0 END;
$$;

CREATE OR REPLACE FUNCTION apply_vote_elo() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  b            battles%ROWTYPE;
  ra           tool_ratings%ROWTYPE;
  rb           tool_ratings%ROWTYPE;
  score_a      numeric;   -- 1, 0.5, 0
  expected_a   numeric;
  expected_b   numeric;
  k_a          numeric;
  k_b          numeric;
  new_a        numeric;
  new_b        numeric;
BEGIN
  IF NOT NEW.is_counted THEN
    RETURN NEW;
  END IF;

  SELECT * INTO b FROM battles WHERE id = NEW.battle_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'vote % references missing battle %', NEW.id, NEW.battle_id;
  END IF;
  IF b.status <> 'ready' THEN
    RAISE EXCEPTION 'battle % is not ready for voting (status=%)', b.id, b.status
      USING ERRCODE = 'check_violation';
  END IF;
  IF b.revealed_at IS NOT NULL THEN
    RAISE EXCEPTION 'battle % was revealed before the vote', b.id
      USING ERRCODE = 'check_violation';
  END IF;

  -- Ensure rating rows exist, then lock both in a stable order to avoid deadlocks.
  INSERT INTO tool_ratings (tool_id, category_id)
  VALUES (b.tool_a_id, b.category_id), (b.tool_b_id, b.category_id)
  ON CONFLICT DO NOTHING;

  IF b.tool_a_id < b.tool_b_id THEN
    SELECT * INTO ra FROM tool_ratings WHERE tool_id = b.tool_a_id AND category_id = b.category_id FOR UPDATE;
    SELECT * INTO rb FROM tool_ratings WHERE tool_id = b.tool_b_id AND category_id = b.category_id FOR UPDATE;
  ELSE
    SELECT * INTO rb FROM tool_ratings WHERE tool_id = b.tool_b_id AND category_id = b.category_id FOR UPDATE;
    SELECT * INTO ra FROM tool_ratings WHERE tool_id = b.tool_a_id AND category_id = b.category_id FOR UPDATE;
  END IF;

  score_a := CASE NEW.choice WHEN 'a' THEN 1.0 WHEN 'b' THEN 0.0 ELSE 0.5 END;
  expected_a := 1.0 / (1.0 + power(10.0, (rb.human_elo - ra.human_elo) / 400.0));
  expected_b := 1.0 - expected_a;
  k_a := elo_k_factor(ra.human_battles);
  k_b := elo_k_factor(rb.human_battles);

  new_a := round(ra.human_elo + k_a * (score_a - expected_a), 2);
  new_b := round(rb.human_elo + k_b * ((1.0 - score_a) - expected_b), 2);

  UPDATE tool_ratings SET
    human_elo      = new_a,
    human_battles  = human_battles + 1,
    human_wins     = human_wins     + (NEW.choice = 'a')::int,
    human_losses   = human_losses   + (NEW.choice = 'b')::int,
    human_ties     = human_ties     + (NEW.choice = 'tie')::int,
    human_both_bad = human_both_bad + (NEW.choice = 'both_bad')::int,
    last_battle_at = now(),
    updated_at     = now()
  WHERE tool_id = b.tool_a_id AND category_id = b.category_id;

  UPDATE tool_ratings SET
    human_elo      = new_b,
    human_battles  = human_battles + 1,
    human_wins     = human_wins     + (NEW.choice = 'b')::int,
    human_losses   = human_losses   + (NEW.choice = 'a')::int,
    human_ties     = human_ties     + (NEW.choice = 'tie')::int,
    human_both_bad = human_both_bad + (NEW.choice = 'both_bad')::int,
    last_battle_at = now(),
    updated_at     = now()
  WHERE tool_id = b.tool_b_id AND category_id = b.category_id;

  INSERT INTO rating_history (tool_id, category_id, vote_id, elo_before, elo_after) VALUES
    (b.tool_a_id, b.category_id, NEW.id, ra.human_elo, new_a),
    (b.tool_b_id, b.category_id, NEW.id, rb.human_elo, new_b);

  UPDATE battles SET status = 'voted', updated_at = now() WHERE id = b.id;

  -- Snapshot onto the vote row for the reveal panel.
  NEW.k_factor     := k_a;
  NEW.elo_a_before := ra.human_elo;
  NEW.elo_b_before := rb.human_elo;
  NEW.elo_a_after  := new_a;
  NEW.elo_b_after  := new_b;
  RETURN NEW;
END;
$$;

CREATE TRIGGER votes_apply_elo
  BEFORE INSERT ON votes
  FOR EACH ROW EXECUTE FUNCTION apply_vote_elo();

-- Votes are immutable once counted; corrections happen via is_counted flips
-- performed by an admin job that recomputes ratings.
CREATE OR REPLACE FUNCTION forbid_vote_choice_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.choice <> OLD.choice OR NEW.battle_id <> OLD.battle_id THEN
    RAISE EXCEPTION 'votes.choice and votes.battle_id are immutable';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER votes_immutable
  BEFORE UPDATE ON votes
  FOR EACH ROW EXECUTE FUNCTION forbid_vote_choice_update();

-- -----------------------------------------------------------------------------
-- Leaderboard views
-- -----------------------------------------------------------------------------

-- Jury scorecard aggregated per (tool, category), across canonical golden
-- executions only, so a tool cannot pump its jury score with custom prompts.
CREATE MATERIALIZED VIEW leaderboard_jury_scores AS
SELECT
  e.tool_id,
  p.category_id,
  count(DISTINCT e.id)                         AS executions_judged,
  count(j.id)                                  AS evaluations,
  round(avg(j.constraint_adherence), 2)        AS constraint_adherence,
  round(avg(j.factuality_integrity), 2)        AS factuality_integrity,
  round(avg(j.conciseness_utility), 2)         AS conciseness_utility,
  round(avg(j.execution_velocity), 2)          AS execution_velocity,
  round(avg(j.composite), 2)                   AS jury_composite,
  percentile_cont(0.5) WITHIN GROUP (ORDER BY e.latency_ms) AS median_latency_ms,
  percentile_cont(0.5) WITHIN GROUP (ORDER BY e.ttft_ms)    AS median_ttft_ms
FROM executions e
JOIN prompts p          ON p.id = e.prompt_id AND p.kind = 'golden'
JOIN jury_evaluations j ON j.execution_id = e.id
WHERE e.is_canonical AND e.status = 'success'
GROUP BY e.tool_id, p.category_id
WITH NO DATA;

CREATE UNIQUE INDEX leaderboard_jury_scores_pk ON leaderboard_jury_scores (tool_id, category_id);

CREATE VIEW leaderboard AS
SELECT
  t.id            AS tool_id,
  t.slug,
  t.name,
  t.logo_url,
  t.status,
  c.id            AS category_id,
  c.slug          AS category_slug,
  r.human_elo,
  r.human_battles,
  r.human_wins,
  r.human_losses,
  r.human_ties,
  rank() OVER (PARTITION BY c.id ORDER BY r.human_elo DESC)            AS human_rank,
  j.jury_composite,
  j.constraint_adherence,
  j.factuality_integrity,
  j.conciseness_utility,
  j.execution_velocity,
  j.median_latency_ms,
  j.median_ttft_ms,
  rank() OVER (PARTITION BY c.id ORDER BY j.jury_composite DESC NULLS LAST) AS jury_rank
FROM tool_ratings r
JOIN tools t      ON t.id = r.tool_id
JOIN categories c ON c.id = r.category_id
LEFT JOIN leaderboard_jury_scores j ON j.tool_id = r.tool_id AND j.category_id = r.category_id
WHERE t.status IN ('seeded', 'vendor_verified') AND c.is_active;

-- -----------------------------------------------------------------------------
-- updated_at triggers
-- -----------------------------------------------------------------------------

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['vendor_accounts','users','categories','tools','vendor_api_keys','prompts','battles','tool_ratings']
  LOOP
    EXECUTE format('CREATE TRIGGER %I_set_updated_at BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION set_updated_at()', t, t);
  END LOOP;
END $$;

-- -----------------------------------------------------------------------------
-- Roles. The web/app role can never read key material; the proxy role can.
-- Adjust names to your deployment; passwords are set out-of-band.
-- -----------------------------------------------------------------------------

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'arena_app')   THEN CREATE ROLE arena_app   NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'arena_proxy') THEN CREATE ROLE arena_proxy NOLOGIN; END IF;
END $$;

GRANT SELECT, INSERT, UPDATE ON
  vendor_accounts, users, categories, tools, tool_categories, prompts,
  battles, votes, tool_ratings, rating_history, executions, jury_evaluations
  TO arena_app;
GRANT SELECT ON leaderboard, leaderboard_jury_scores TO arena_app;
GRANT USAGE, SELECT ON SEQUENCE rating_history_id_seq TO arena_app;

-- arena_app may manage key METADATA (status, budget, label) but never the secret columns.
GRANT SELECT (id, tool_id, vendor_account_id, funding_source, label, key_last4, auth_scheme,
              status, validated_at, last_used_at, last_error, consecutive_errors,
              monthly_budget_micros, spent_micros_month, spend_month, rate_limit_rpm,
              rotated_from_id, expires_at, revoked_at, created_by, created_at, updated_at)
  ON vendor_api_keys TO arena_app;
GRANT UPDATE (label, status, monthly_budget_micros, rate_limit_rpm, revoked_at) ON vendor_api_keys TO arena_app;

GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO arena_proxy;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO arena_proxy;

COMMIT;
