-- Test-only stand-ins for the Supabase-managed pieces that
-- supabase/migrations/0001_claims.sql depends on, so the migration can be
-- applied and exercised on a plain PostgreSQL 16 (no Supabase). Never run
-- this against a real Supabase project.
--
-- What is stubbed, and how it differs from the real thing:
--   * roles anon, authenticated, service_role: created NOLOGIN. On Supabase
--     service_role has BYPASSRLS; here it is granted explicitly.
--   * auth.users: id + email only. auth.uid() / auth.role() / auth.jwt() read
--     request.jwt.claims exactly like Supabase's, so tests impersonate a user
--     with SET LOCAL request.jwt.claims = '{"sub": "...", "role": "authenticated"}'.
--   * vault.secrets stores the secret in PLAINTEXT (the real one is encrypted
--     with a key managed by pgsodium/Supabase). vault.decrypted_secrets exposes
--     the same columns as the real view. vault.create_secret has the same
--     signature as the real function.
--
-- Usage (see docs/claims.md):
--   psql -v ON_ERROR_STOP=1 -f scripts/tests/supabase-stubs.sql
--   psql -v ON_ERROR_STOP=1 -f supabase/migrations/0001_claims.sql
--   psql -v ON_ERROR_STOP=1 -f scripts/tests/claims-smoke.sql

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')          THEN CREATE ROLE anon NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role')  THEN CREATE ROLE service_role NOLOGIN BYPASSRLS; END IF;
END;
$$;

GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;

CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE IF NOT EXISTS auth.users (
  id     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email  text UNIQUE
);

CREATE OR REPLACE FUNCTION auth.jwt() RETURNS jsonb
LANGUAGE sql STABLE AS $$
  SELECT coalesce(nullif(current_setting('request.jwt.claims', true), ''), '{}')::jsonb;
$$;

CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid
LANGUAGE sql STABLE AS $$
  SELECT nullif(auth.jwt() ->> 'sub', '')::uuid;
$$;

CREATE OR REPLACE FUNCTION auth.role() RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT nullif(auth.jwt() ->> 'role', '');
$$;

GRANT USAGE ON SCHEMA auth TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION auth.jwt(), auth.uid(), auth.role() TO anon, authenticated, service_role;

CREATE SCHEMA IF NOT EXISTS vault;
CREATE TABLE IF NOT EXISTS vault.secrets (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name         text UNIQUE,
  description  text NOT NULL DEFAULT '',
  secret       text NOT NULL,             -- PLAINTEXT in this stub only
  key_id       uuid,
  nonce        bytea,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE VIEW vault.decrypted_secrets AS
  SELECT id, name, description, secret, secret AS decrypted_secret, key_id, nonce, created_at, updated_at
    FROM vault.secrets;

CREATE OR REPLACE FUNCTION vault.create_secret(new_secret text, new_name text DEFAULT NULL, new_description text DEFAULT '', new_key_id uuid DEFAULT NULL)
RETURNS uuid LANGUAGE sql AS $$
  INSERT INTO vault.secrets (name, description, secret, key_id)
  VALUES (new_name, coalesce(new_description, ''), new_secret, new_key_id)
  RETURNING id;
$$;

-- Like Supabase: only the owner (postgres) touches vault; app roles get nothing.
REVOKE ALL ON SCHEMA vault FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA vault FROM PUBLIC;
