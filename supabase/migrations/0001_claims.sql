-- =============================================================================
-- AI Tool Wars — vendor claims and API keys on Supabase
-- Migration 0001: tools reference table, vendor accounts, tool claims,
-- vendor API keys (secret in Vault), validation log, RLS, RPCs, runner view.
--
-- Runs as `postgres` via `supabase db push`, the SQL editor, or the Management
-- API (POST /v1/projects/{ref}/database/query, the whole file as one query).
-- Plain SQL only, no psql meta-commands, no explicit transaction control, and
-- idempotent: re-running it is a no-op. Depends on
-- Supabase-provided schemas: auth (auth.users, auth.uid(), auth.role()) and
-- vault (vault.create_secret, vault.secrets, vault.decrypted_secrets).
-- For a plain PostgreSQL 16 check, scripts/tests/supabase-stubs.sql provides
-- minimal stand-ins for those; see docs/claims.md.
--
-- Design (see docs/claims.md for the prose):
--   * The browser talks to PostgREST as an authenticated user. RLS lets a user
--     see and manage only their own claims and key METADATA. No table that a
--     user can read holds a secret.
--   * The secret itself is written by submit_api_key(), a SECURITY DEFINER
--     function owned by postgres, straight into Vault. It returns the key row
--     id and nothing else.
--   * The runner (GitHub Actions, service role) reads active_keys_for_runner,
--     a view that joins key rows to vault.decrypted_secrets. Only service_role
--     may SELECT it. Edge Functions read one pending secret through
--     read_key_secret(), also service_role only.
--   * Ownership: a claim is auto-verified when the claimant's email domain
--     (from auth.users) matches the tool's website domain from the catalog;
--     otherwise it stays pending until a DNS TXT record proves control of the
--     domain (verify-dns Edge Function) or a human flips it (manual).
-- =============================================================================


-- -----------------------------------------------------------------------------
-- Enumerations
-- -----------------------------------------------------------------------------

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'public' AND t.typname = 'claim_verification') THEN
    CREATE TYPE public.claim_verification AS ENUM ('email_domain', 'dns_txt', 'manual');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'public' AND t.typname = 'claim_status') THEN
    CREATE TYPE public.claim_status AS ENUM ('pending', 'verified', 'rejected');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace WHERE n.nspname = 'public' AND t.typname = 'api_key_status') THEN
    CREATE TYPE public.api_key_status AS ENUM ('pending_validation', 'active', 'invalid', 'revoked');
  END IF;
END;
$$;

-- Adapters a submitted key can be validated for. Mirrors scripts/run-voice.mjs
-- (inworld, openai, elevenlabs, cartesia) plus the text adapters the next
-- categories will use. The Edge Function validate-key has one probe per value.
CREATE TABLE IF NOT EXISTS public.adapters (
  adapter      text PRIMARY KEY,
  key_env      text NOT NULL,           -- env var the runner reads, e.g. INWORLD_API_KEY
  auth_scheme  text NOT NULL            -- how the key is presented to the vendor
               CHECK (auth_scheme IN ('bearer', 'basic', 'header:xi-api-key', 'header:X-API-Key',
                                      'header:x-api-key', 'header:x-goog-api-key'))
);

INSERT INTO public.adapters (adapter, key_env, auth_scheme) VALUES
  ('inworld',     'INWORLD_API_KEY',    'basic'),
  ('openai',      'OPENAI_API_KEY',     'bearer'),
  ('elevenlabs',  'ELEVENLABS_API_KEY', 'header:xi-api-key'),
  ('cartesia',    'CARTESIA_API_KEY',   'header:X-API-Key'),
  ('openai_chat', 'OPENAI_API_KEY',     'bearer'),
  ('anthropic',   'ANTHROPIC_API_KEY',  'header:x-api-key'),
  ('gemini',      'GEMINI_API_KEY',     'header:x-goog-api-key')
ON CONFLICT (adapter) DO UPDATE SET key_env = EXCLUDED.key_env, auth_scheme = EXCLUDED.auth_scheme;

-- -----------------------------------------------------------------------------
-- Utility: updated_at trigger
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

-- -----------------------------------------------------------------------------
-- tools — reference copy of data/catalog/*/tools.json, upserted by
-- scripts/seed-supabase-tools.mjs with the service role. Public read.
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.tools (
  slug            text PRIMARY KEY,
  category_slug   text NOT NULL,
  name            text NOT NULL,
  vendor          text NOT NULL,
  website         text NOT NULL,
  -- Registrable host of `website` with a leading "www." removed. NULL for tools
  -- hosted on a shared domain (github.com, huggingface.co): nobody auto-verifies
  -- a claim on those and there is no DNS path either.
  domain          text,
  adapter         text NOT NULL,         -- catalog adapter name; 'open:*' means open weights, runs on our CPU
  claimable       boolean NOT NULL DEFAULT true,
  -- The adapter the claim page will submit keys for, or NULL when we cannot
  -- run a vendor key yet (google-cloud-tts, amazon-polly need signed auth).
  key_adapter     text REFERENCES public.adapters(adapter),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT tools_domain_shape CHECK (domain IS NULL OR domain ~ '^[a-z0-9.-]+\.[a-z]{2,}$')
);

CREATE INDEX IF NOT EXISTS tools_category_idx ON public.tools (category_slug);
DROP TRIGGER IF EXISTS tools_updated_at ON public.tools;
CREATE TRIGGER tools_updated_at BEFORE UPDATE ON public.tools
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- -----------------------------------------------------------------------------
-- vendor_accounts — one per signed-in claimant. Created lazily by claim_tool().
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.vendor_accounts (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name        text NOT NULL,
  domain      text NOT NULL,             -- email domain of the creator, lower-case
  created_by  uuid NOT NULL UNIQUE REFERENCES auth.users(id) ON DELETE CASCADE,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS vendor_accounts_updated_at ON public.vendor_accounts;
CREATE TRIGGER vendor_accounts_updated_at BEFORE UPDATE ON public.vendor_accounts
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- -----------------------------------------------------------------------------
-- tool_claims
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.tool_claims (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tool_slug          text NOT NULL REFERENCES public.tools(slug) ON DELETE CASCADE,
  category_slug      text NOT NULL,
  vendor_account_id  uuid NOT NULL REFERENCES public.vendor_accounts(id) ON DELETE CASCADE,
  claimant           uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  claimant_email     text NOT NULL,
  verification       public.claim_verification NOT NULL,
  status             public.claim_status NOT NULL DEFAULT 'pending',
  -- DNS path: the claimant publishes TXT "toolwars-verify=<dns_token>" on the
  -- tool's domain; verify-dns checks it over DNS-over-HTTPS.
  dns_token          text NOT NULL DEFAULT replace(gen_random_uuid()::text, '-', ''),
  verified_at        timestamptz,
  rejected_reason    text,
  created_at         timestamptz NOT NULL DEFAULT now(),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT tool_claims_one_per_claimant UNIQUE (tool_slug, claimant),
  CONSTRAINT tool_claims_verified_has_time CHECK (status <> 'verified' OR verified_at IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS tool_claims_claimant_idx ON public.tool_claims (claimant);
CREATE INDEX IF NOT EXISTS tool_claims_tool_status_idx ON public.tool_claims (tool_slug, status);
DROP TRIGGER IF EXISTS tool_claims_updated_at ON public.tool_claims;
CREATE TRIGGER tool_claims_updated_at BEFORE UPDATE ON public.tool_claims
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- -----------------------------------------------------------------------------
-- vendor_api_keys — metadata only. The secret is a Vault row.
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.vendor_api_keys (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  tool_slug              text NOT NULL REFERENCES public.tools(slug) ON DELETE CASCADE,
  vendor_account_id      uuid NOT NULL REFERENCES public.vendor_accounts(id) ON DELETE CASCADE,
  vault_secret_id        uuid,                             -- vault.secrets.id (FK added below when permitted)
  key_last4              text NOT NULL,
  key_fingerprint        text NOT NULL,                    -- sha256(plaintext) hex: dedupe and audit without plaintext
  adapter                text NOT NULL REFERENCES public.adapters(adapter),
  auth_scheme            text NOT NULL,
  status                 public.api_key_status NOT NULL DEFAULT 'pending_validation',
  validated_at           timestamptz,
  last_error             text,
  monthly_budget_micros  bigint CHECK (monthly_budget_micros IS NULL OR monthly_budget_micros >= 0),
  revoked_at             timestamptz,
  created_by             uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT vendor_api_keys_last4_shape CHECK (key_last4 ~ '^.{1,4}$'),
  CONSTRAINT vendor_api_keys_fingerprint_shape CHECK (key_fingerprint ~ '^[0-9a-f]{64}$')
);

-- One live key (pending or active) per tool per vendor account; older ones are revoked on resubmit.
CREATE UNIQUE INDEX IF NOT EXISTS vendor_api_keys_one_live_idx
  ON public.vendor_api_keys (tool_slug, vendor_account_id) WHERE status IN ('pending_validation', 'active');
CREATE UNIQUE INDEX IF NOT EXISTS vendor_api_keys_fingerprint_idx
  ON public.vendor_api_keys (tool_slug, key_fingerprint) WHERE status IN ('pending_validation', 'active');
CREATE INDEX IF NOT EXISTS vendor_api_keys_owner_idx ON public.vendor_api_keys (created_by);
CREATE INDEX IF NOT EXISTS vendor_api_keys_status_idx ON public.vendor_api_keys (status);
DROP TRIGGER IF EXISTS vendor_api_keys_updated_at ON public.vendor_api_keys;
CREATE TRIGGER vendor_api_keys_updated_at BEFORE UPDATE ON public.vendor_api_keys
  FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- vault.secrets is owned by supabase_admin; `postgres` may or may not hold
-- REFERENCES on it depending on the platform version. Add the FK when allowed,
-- otherwise keep the plain uuid and say so.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'vendor_api_keys_vault_secret_fk') THEN RETURN; END IF;
  ALTER TABLE public.vendor_api_keys
    ADD CONSTRAINT vendor_api_keys_vault_secret_fk
    FOREIGN KEY (vault_secret_id) REFERENCES vault.secrets(id) ON DELETE SET NULL;
EXCEPTION
  WHEN insufficient_privilege OR undefined_table THEN
    RAISE NOTICE 'vendor_api_keys.vault_secret_id: no FK to vault.secrets (%), kept as a plain uuid', SQLERRM;
END;
$$;

COMMENT ON TABLE public.vendor_api_keys IS
  'Vendor API key metadata. The secret is in Vault (vault_secret_id); nothing here or in any user-readable relation holds it.';

-- -----------------------------------------------------------------------------
-- key_validation_log — one row per probe by validate-key.
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.key_validation_log (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  key_id       uuid NOT NULL REFERENCES public.vendor_api_keys(id) ON DELETE CASCADE,
  probed_at    timestamptz NOT NULL DEFAULT now(),
  adapter      text NOT NULL,
  probe        text NOT NULL,                 -- endpoint name, e.g. 'GET /v1/user'
  ok           boolean NOT NULL,
  http_status  integer,
  latency_ms   integer,
  error        text,                          -- vendor-facing, scrubbed, <= 300 chars
  actor        text NOT NULL DEFAULT 'edge:validate-key'
);

CREATE INDEX IF NOT EXISTS key_validation_log_key_idx ON public.key_validation_log (key_id, probed_at DESC);

-- -----------------------------------------------------------------------------
-- Ownership helpers
-- -----------------------------------------------------------------------------

-- Email of the calling user, from auth.users (not readable by users directly).
CREATE OR REPLACE FUNCTION public.current_user_email() RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT lower(u.email::text) FROM auth.users u WHERE u.id = auth.uid();
$$;
REVOKE ALL ON FUNCTION public.current_user_email() FROM PUBLIC;

-- Does an email domain prove ownership of a tool domain?
--   exact match                       elevenlabs.io      = elevenlabs.io
--   email domain is a parent          google.com         ~ cloud.google.com
--   email domain is a subdomain       mail.elevenlabs.io ~ elevenlabs.io
CREATE OR REPLACE FUNCTION public.domain_matches(p_email_domain text, p_tool_domain text) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT p_email_domain IS NOT NULL AND p_tool_domain IS NOT NULL AND (
       p_email_domain = p_tool_domain
    OR p_tool_domain LIKE '%.' || p_email_domain
    OR p_email_domain LIKE '%.' || p_tool_domain
  );
$$;

-- -----------------------------------------------------------------------------
-- claim_tool(tool_slug) → the claim row. Idempotent per (tool, user).
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.claim_tool(p_tool_slug text)
RETURNS public.tool_claims
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_uid      uuid := auth.uid();
  v_email    text;
  v_domain   text;
  v_tool     public.tools;
  v_account  public.vendor_accounts;
  v_claim    public.tool_claims;
BEGIN
  IF v_uid IS NULL THEN RAISE EXCEPTION 'not signed in' USING ERRCODE = '42501'; END IF;

  v_email := public.current_user_email();
  IF v_email IS NULL OR position('@' IN v_email) = 0 THEN
    RAISE EXCEPTION 'account has no email address' USING ERRCODE = '22023';
  END IF;
  v_domain := split_part(v_email, '@', 2);

  SELECT * INTO v_tool FROM public.tools WHERE slug = p_tool_slug;
  IF NOT FOUND THEN RAISE EXCEPTION 'unknown tool %', p_tool_slug USING ERRCODE = '22023'; END IF;
  IF NOT v_tool.claimable THEN
    RAISE EXCEPTION '% is open weights and runs on our CPU; there is no listing to claim', v_tool.name USING ERRCODE = '22023';
  END IF;

  SELECT * INTO v_account FROM public.vendor_accounts WHERE created_by = v_uid;
  IF NOT FOUND THEN
    INSERT INTO public.vendor_accounts (name, domain, created_by)
    VALUES (v_domain, v_domain, v_uid) RETURNING * INTO v_account;
  END IF;

  SELECT * INTO v_claim FROM public.tool_claims WHERE tool_slug = v_tool.slug AND claimant = v_uid;
  IF FOUND THEN RETURN v_claim; END IF;

  IF public.domain_matches(v_domain, v_tool.domain) THEN
    INSERT INTO public.tool_claims (tool_slug, category_slug, vendor_account_id, claimant, claimant_email, verification, status, verified_at)
    VALUES (v_tool.slug, v_tool.category_slug, v_account.id, v_uid, v_email, 'email_domain', 'verified', now())
    RETURNING * INTO v_claim;
  ELSE
    INSERT INTO public.tool_claims (tool_slug, category_slug, vendor_account_id, claimant, claimant_email, verification, status)
    VALUES (v_tool.slug, v_tool.category_slug, v_account.id, v_uid, v_email, 'dns_txt', 'pending')
    RETURNING * INTO v_claim;
  END IF;
  RETURN v_claim;
END;
$$;
REVOKE ALL ON FUNCTION public.claim_tool(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.claim_tool(text) TO authenticated;

-- -----------------------------------------------------------------------------
-- submit_api_key(tool_slug, api_key, adapter) → key id. Secret goes to Vault.
-- Never returns, logs or stores the plaintext anywhere else.
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.submit_api_key(p_tool_slug text, p_api_key text, p_adapter text DEFAULT NULL)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_uid        uuid := auth.uid();
  v_key        text := btrim(p_api_key);
  v_tool       public.tools;
  v_claim      public.tool_claims;
  v_adapter    public.adapters;
  v_secret_id  uuid;
  v_key_id     uuid;
  v_old        record;
BEGIN
  IF v_uid IS NULL THEN RAISE EXCEPTION 'not signed in' USING ERRCODE = '42501'; END IF;
  IF v_key IS NULL OR length(v_key) < 8 OR length(v_key) > 4096 THEN
    RAISE EXCEPTION 'that does not look like an API key' USING ERRCODE = '22023';
  END IF;
  IF v_key ~ '\s' THEN RAISE EXCEPTION 'API key contains whitespace' USING ERRCODE = '22023'; END IF;

  SELECT * INTO v_tool FROM public.tools WHERE slug = p_tool_slug;
  IF NOT FOUND THEN RAISE EXCEPTION 'unknown tool %', p_tool_slug USING ERRCODE = '22023'; END IF;

  SELECT * INTO v_claim FROM public.tool_claims
   WHERE tool_slug = v_tool.slug AND claimant = v_uid AND status = 'verified';
  IF NOT FOUND THEN
    RAISE EXCEPTION 'claim % first; the claim must be verified before a key is accepted', v_tool.slug USING ERRCODE = '42501';
  END IF;

  SELECT * INTO v_adapter FROM public.adapters WHERE adapter = COALESCE(p_adapter, v_tool.key_adapter);
  IF NOT FOUND THEN
    RAISE EXCEPTION 'no supported key adapter for %', v_tool.slug USING ERRCODE = '22023';
  END IF;
  IF v_tool.key_adapter IS DISTINCT FROM v_adapter.adapter THEN
    RAISE EXCEPTION 'adapter % does not match the catalog for %', v_adapter.adapter, v_tool.slug USING ERRCODE = '22023';
  END IF;

  -- Resubmitting replaces: revoke the previous live key(s) and drop their secrets.
  FOR v_old IN
    SELECT id, vault_secret_id FROM public.vendor_api_keys
     WHERE tool_slug = v_tool.slug AND vendor_account_id = v_claim.vendor_account_id
       AND status IN ('pending_validation', 'active')
  LOOP
    UPDATE public.vendor_api_keys SET status = 'revoked', revoked_at = now(), vault_secret_id = NULL WHERE id = v_old.id;
    IF v_old.vault_secret_id IS NOT NULL THEN DELETE FROM vault.secrets WHERE id = v_old.vault_secret_id; END IF;
  END LOOP;

  v_key_id := gen_random_uuid();
  v_secret_id := vault.create_secret(
    v_key,
    'vendor_api_key:' || v_key_id::text,
    format('%s key for %s, submitted by claim %s', v_adapter.adapter, v_tool.slug, v_claim.id)
  );

  INSERT INTO public.vendor_api_keys
    (id, tool_slug, vendor_account_id, vault_secret_id, key_last4, key_fingerprint, adapter, auth_scheme, created_by)
  VALUES
    (v_key_id, v_tool.slug, v_claim.vendor_account_id, v_secret_id,
     right(v_key, 4), encode(sha256(convert_to(v_key, 'UTF8')), 'hex'),
     v_adapter.adapter, v_adapter.auth_scheme, v_uid);

  RETURN v_key_id;
END;
$$;
REVOKE ALL ON FUNCTION public.submit_api_key(text, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.submit_api_key(text, text, text) TO authenticated;

-- revoke_api_key(key_id): owner revokes; the Vault row is deleted.
CREATE OR REPLACE FUNCTION public.revoke_api_key(p_key_id uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
  v_row public.vendor_api_keys;
BEGIN
  SELECT * INTO v_row FROM public.vendor_api_keys WHERE id = p_key_id AND created_by = auth.uid();
  IF NOT FOUND THEN RAISE EXCEPTION 'no such key' USING ERRCODE = '42501'; END IF;
  IF v_row.status = 'revoked' THEN RETURN; END IF;
  UPDATE public.vendor_api_keys SET status = 'revoked', revoked_at = now(), vault_secret_id = NULL WHERE id = v_row.id;
  IF v_row.vault_secret_id IS NOT NULL THEN DELETE FROM vault.secrets WHERE id = v_row.vault_secret_id; END IF;
END;
$$;
REVOKE ALL ON FUNCTION public.revoke_api_key(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.revoke_api_key(uuid) TO authenticated;

-- -----------------------------------------------------------------------------
-- Service-role only: read one secret for validation, and the runner view.
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.read_key_secret(p_key_id uuid)
RETURNS TABLE (key_id uuid, tool_slug text, adapter text, auth_scheme text, status public.api_key_status, secret text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = '' AS $$
  SELECT k.id, k.tool_slug, k.adapter, k.auth_scheme, k.status, s.decrypted_secret
    FROM public.vendor_api_keys k
    JOIN vault.decrypted_secrets s ON s.id = k.vault_secret_id
   WHERE k.id = p_key_id AND k.status IN ('pending_validation', 'active', 'invalid');
$$;
REVOKE ALL ON FUNCTION public.read_key_secret(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.read_key_secret(uuid) TO service_role;

-- Runs with the view owner's (postgres) rights so it can read Vault.
-- Only service_role is granted SELECT.
CREATE OR REPLACE VIEW public.active_keys_for_runner WITH (security_invoker = false) AS
  SELECT k.id            AS key_id,
         k.tool_slug,
         t.category_slug,
         k.adapter,
         k.auth_scheme,
         a.key_env,
         k.key_last4,
         k.monthly_budget_micros,
         k.validated_at,
         s.decrypted_secret AS secret
    FROM public.vendor_api_keys k
    JOIN public.tools t ON t.slug = k.tool_slug
    JOIN public.adapters a ON a.adapter = k.adapter
    JOIN vault.decrypted_secrets s ON s.id = k.vault_secret_id
   WHERE k.status = 'active';

REVOKE ALL ON public.active_keys_for_runner FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.active_keys_for_runner TO service_role;

-- Public, secret-free: which tools are claimed / running on a vendor key.
CREATE OR REPLACE VIEW public.tool_claim_status WITH (security_invoker = false) AS
  SELECT t.slug AS tool_slug,
         EXISTS (SELECT 1 FROM public.tool_claims c WHERE c.tool_slug = t.slug AND c.status = 'verified') AS claimed,
         EXISTS (SELECT 1 FROM public.vendor_api_keys k WHERE k.tool_slug = t.slug AND k.status = 'active') AS key_active
    FROM public.tools t;

GRANT SELECT ON public.tool_claim_status TO anon, authenticated, service_role;

-- -----------------------------------------------------------------------------
-- Grants and row-level security
-- Supabase grants anon/authenticated/service_role on new public tables by
-- default privileges; make it explicit and then gate with RLS.
-- -----------------------------------------------------------------------------

REVOKE ALL ON public.adapters, public.tools, public.vendor_accounts, public.tool_claims,
              public.vendor_api_keys, public.key_validation_log FROM PUBLIC, anon, authenticated;

GRANT SELECT ON public.adapters, public.tools TO anon, authenticated;
GRANT SELECT ON public.vendor_accounts, public.tool_claims, public.key_validation_log TO authenticated;
GRANT SELECT, UPDATE (monthly_budget_micros) ON public.vendor_api_keys TO authenticated;
GRANT ALL ON public.adapters, public.tools, public.vendor_accounts, public.tool_claims,
             public.vendor_api_keys, public.key_validation_log TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.key_validation_log_id_seq TO service_role;

ALTER TABLE public.adapters           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tools              ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.vendor_accounts    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tool_claims        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.vendor_api_keys    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.key_validation_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS adapters_public_read ON public.adapters;
CREATE POLICY adapters_public_read ON public.adapters FOR SELECT USING (true);
DROP POLICY IF EXISTS tools_public_read ON public.tools;
CREATE POLICY tools_public_read ON public.tools FOR SELECT USING (true);

DROP POLICY IF EXISTS vendor_accounts_own ON public.vendor_accounts;
CREATE POLICY vendor_accounts_own ON public.vendor_accounts
  FOR SELECT TO authenticated USING (created_by = auth.uid());

DROP POLICY IF EXISTS tool_claims_own ON public.tool_claims;
CREATE POLICY tool_claims_own ON public.tool_claims
  FOR SELECT TO authenticated USING (claimant = auth.uid());

DROP POLICY IF EXISTS vendor_api_keys_own_read ON public.vendor_api_keys;
CREATE POLICY vendor_api_keys_own_read ON public.vendor_api_keys
  FOR SELECT TO authenticated USING (created_by = auth.uid());
DROP POLICY IF EXISTS vendor_api_keys_own_budget ON public.vendor_api_keys;
CREATE POLICY vendor_api_keys_own_budget ON public.vendor_api_keys
  FOR UPDATE TO authenticated USING (created_by = auth.uid()) WITH CHECK (created_by = auth.uid());

DROP POLICY IF EXISTS key_validation_log_own ON public.key_validation_log;
CREATE POLICY key_validation_log_own ON public.key_validation_log
  FOR SELECT TO authenticated
  USING (EXISTS (SELECT 1 FROM public.vendor_api_keys k WHERE k.id = key_validation_log.key_id AND k.created_by = auth.uid()));

-- No INSERT/DELETE policies for users: claims are created by claim_tool(),
-- keys by submit_api_key(), revocation by revoke_api_key(). service_role
-- bypasses RLS (Edge Functions, CI, seed script).

COMMENT ON FUNCTION public.submit_api_key(text, text, text) IS
  'Stores the key in Vault and returns the vendor_api_keys.id. Requires a verified claim on the tool. Never returns the key.';
COMMENT ON VIEW public.active_keys_for_runner IS
  'service_role only. Active vendor keys with the decrypted secret, for scripts/fetch-vendor-keys.mjs in CI.';

