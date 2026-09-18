-- Smoke test for supabase/migrations/0001_claims.sql on plain PostgreSQL with
-- scripts/tests/supabase-stubs.sql applied first. Prints "claims smoke test
-- passed" at the end; any failed assertion raises and aborts (ON_ERROR_STOP).
--
-- Impersonation: SET LOCAL ROLE + request.jwt.claims, the same mechanism
-- PostgREST uses on Supabase.

BEGIN;

-- Seed two tools and two users.
INSERT INTO public.tools (slug, category_slug, name, vendor, website, domain, adapter, claimable, key_adapter) VALUES
  ('elevenlabs', 'voice', 'ElevenLabs', 'ElevenLabs', 'https://elevenlabs.io', 'elevenlabs.io', 'elevenlabs', true, 'elevenlabs'),
  ('cartesia',   'voice', 'Cartesia Sonic', 'Cartesia', 'https://cartesia.ai', 'cartesia.ai', 'cartesia', true, 'cartesia'),
  ('google-cloud-tts', 'voice', 'Google Cloud TTS', 'Google Cloud', 'https://cloud.google.com/text-to-speech', 'cloud.google.com', 'http_json', true, NULL),
  ('piper',      'voice', 'Piper', 'Rhasspy', 'https://github.com/rhasspy/piper', NULL, 'open:piper', false, NULL)
ON CONFLICT (slug) DO NOTHING;

INSERT INTO auth.users (id, email) VALUES
  ('00000000-0000-0000-0000-00000000000a', 'Alice@ElevenLabs.io'),
  ('00000000-0000-0000-0000-00000000000b', 'bob@gmail.com'),
  ('00000000-0000-0000-0000-00000000000c', 'carol@google.com')
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------- Alice
SET LOCAL ROLE authenticated;
SET LOCAL request.jwt.claims = '{"sub": "00000000-0000-0000-0000-00000000000a", "role": "authenticated"}';

DO $$
DECLARE c public.tool_claims; k uuid; n int;
BEGIN
  -- email domain matches → verified immediately
  c := public.claim_tool('elevenlabs');
  IF c.status <> 'verified' OR c.verification <> 'email_domain' THEN RAISE EXCEPTION 'alice/elevenlabs should auto-verify, got %/%', c.status, c.verification; END IF;
  IF c.claimant_email <> 'alice@elevenlabs.io' THEN RAISE EXCEPTION 'email not lower-cased: %', c.claimant_email; END IF;

  -- idempotent
  IF (public.claim_tool('elevenlabs')).id <> c.id THEN RAISE EXCEPTION 'claim_tool not idempotent'; END IF;

  -- other domain → pending with a DNS token
  c := public.claim_tool('cartesia');
  IF c.status <> 'pending' OR c.verification <> 'dns_txt' OR length(c.dns_token) < 32 THEN RAISE EXCEPTION 'alice/cartesia should be pending dns_txt'; END IF;

  -- open-weights tool is not claimable
  BEGIN
    PERFORM public.claim_tool('piper');
    RAISE EXCEPTION 'piper should not be claimable';
  EXCEPTION WHEN invalid_parameter_value THEN NULL; END;

  -- key on an unverified claim is refused
  BEGIN
    PERFORM public.submit_api_key('cartesia', 'sk_cartesia_0123456789');
    RAISE EXCEPTION 'key on pending claim should be refused';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;

  -- key on the verified claim is accepted, secret lands in vault
  k := public.submit_api_key('elevenlabs', 'xi-secret-key-ABCDEFGH1234');
  SELECT count(*) INTO n FROM public.vendor_api_keys WHERE id = k AND status = 'pending_validation' AND key_last4 = '1234' AND vault_secret_id IS NOT NULL;
  IF n <> 1 THEN RAISE EXCEPTION 'key row missing or wrong'; END IF;

  -- resubmit revokes the old one and keeps exactly one live key
  PERFORM public.submit_api_key('elevenlabs', 'xi-secret-key-ROTATED-9999');
  SELECT count(*) INTO n FROM public.vendor_api_keys WHERE tool_slug = 'elevenlabs' AND status IN ('pending_validation', 'active');
  IF n <> 1 THEN RAISE EXCEPTION 'expected one live key, got %', n; END IF;
  SELECT count(*) INTO n FROM public.vendor_api_keys WHERE id = k AND status = 'revoked' AND vault_secret_id IS NULL;
  IF n <> 1 THEN RAISE EXCEPTION 'old key should be revoked with its secret dropped'; END IF;

  -- a user can see own metadata but never a secret column
  SELECT count(*) INTO n FROM public.vendor_api_keys;
  IF n <> 2 THEN RAISE EXCEPTION 'alice should see her 2 key rows, saw %', n; END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'vendor_api_keys' AND column_name ~* 'cipher|decrypted|secret$|plaintext') THEN
    RAISE EXCEPTION 'vendor_api_keys must not carry a secret column';
  END IF;

  -- runner view and secret reader are off limits to users
  BEGIN
    PERFORM * FROM public.active_keys_for_runner;
    RAISE EXCEPTION 'authenticated must not read active_keys_for_runner';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN
    PERFORM * FROM public.read_key_secret(k);
    RAISE EXCEPTION 'authenticated must not call read_key_secret';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN
    PERFORM * FROM vault.secrets;
    RAISE EXCEPTION 'authenticated must not read vault.secrets';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;

  -- users cannot insert claims or keys directly (no policy)
  BEGIN
    INSERT INTO public.tool_claims (tool_slug, category_slug, vendor_account_id, claimant, claimant_email, verification, status, verified_at)
    SELECT 'cartesia', 'voice', id, '00000000-0000-0000-0000-00000000000a', 'x', 'manual', 'verified', now() FROM public.vendor_accounts;
    RAISE EXCEPTION 'direct claim insert must fail';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;

  -- budget is the one column a user may update; status is not
  UPDATE public.vendor_api_keys SET monthly_budget_micros = 5000000 WHERE tool_slug = 'elevenlabs' AND status = 'pending_validation';
  BEGIN
    UPDATE public.vendor_api_keys SET status = 'active' WHERE tool_slug = 'elevenlabs';
    RAISE EXCEPTION 'user must not flip key status';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END;
$$;

-- ---------------------------------------------------------------- Bob (gmail)
SET LOCAL request.jwt.claims = '{"sub": "00000000-0000-0000-0000-00000000000b", "role": "authenticated"}';
DO $$
DECLARE c public.tool_claims; n int;
BEGIN
  c := public.claim_tool('elevenlabs');
  IF c.status <> 'pending' THEN RAISE EXCEPTION 'gmail claimant must stay pending'; END IF;
  SELECT count(*) INTO n FROM public.tool_claims;
  IF n <> 1 THEN RAISE EXCEPTION 'bob should see only his own claim, saw %', n; END IF;
  SELECT count(*) INTO n FROM public.vendor_api_keys;
  IF n <> 0 THEN RAISE EXCEPTION 'bob must not see alice''s keys'; END IF;
  SELECT count(*) INTO n FROM public.vendor_accounts;
  IF n <> 1 THEN RAISE EXCEPTION 'bob should see only his own account, saw %', n; END IF;
END;
$$;

-- ---------------------------------------------------------------- Carol (parent domain)
SET LOCAL request.jwt.claims = '{"sub": "00000000-0000-0000-0000-00000000000c", "role": "authenticated"}';
DO $$
DECLARE c public.tool_claims;
BEGIN
  c := public.claim_tool('google-cloud-tts');
  IF c.status <> 'verified' THEN RAISE EXCEPTION 'google.com should verify cloud.google.com'; END IF;
  BEGIN
    PERFORM public.submit_api_key('google-cloud-tts', 'ya29.some-google-token-value');
    RAISE EXCEPTION 'tool without key_adapter must refuse keys';
  EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
END;
$$;

-- ---------------------------------------------------------------- anon
SET LOCAL ROLE anon;
SET LOCAL request.jwt.claims = '{"role": "anon"}';
DO $$
DECLARE n int;
BEGIN
  SELECT count(*) INTO n FROM public.tools; IF n < 4 THEN RAISE EXCEPTION 'anon should read tools'; END IF;
  SELECT count(*) INTO n FROM public.tool_claim_status WHERE tool_slug = 'elevenlabs' AND claimed;
  IF n <> 1 THEN RAISE EXCEPTION 'tool_claim_status should show elevenlabs claimed'; END IF;
  BEGIN
    PERFORM * FROM public.tool_claims; RAISE EXCEPTION 'anon must not read claims';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN
    PERFORM public.claim_tool('elevenlabs'); RAISE EXCEPTION 'anon must not claim';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN
    PERFORM * FROM public.active_keys_for_runner; RAISE EXCEPTION 'anon must not read runner view';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
END;
$$;

-- ---------------------------------------------------------------- service role (Edge Function / CI)
SET LOCAL ROLE service_role;
SET LOCAL request.jwt.claims = '{"role": "service_role"}';
DO $$
DECLARE k uuid; s record; n int;
BEGIN
  SELECT id INTO k FROM public.vendor_api_keys WHERE tool_slug = 'elevenlabs' AND status = 'pending_validation';
  SELECT * INTO s FROM public.read_key_secret(k);
  IF s.secret <> 'xi-secret-key-ROTATED-9999' OR s.adapter <> 'elevenlabs' OR s.auth_scheme <> 'header:xi-api-key' THEN
    RAISE EXCEPTION 'read_key_secret returned the wrong thing';
  END IF;

  -- nothing active yet → runner view empty
  SELECT count(*) INTO n FROM public.active_keys_for_runner; IF n <> 0 THEN RAISE EXCEPTION 'no active keys expected'; END IF;

  -- validate-key marks it active and logs
  UPDATE public.vendor_api_keys SET status = 'active', validated_at = now(), last_error = NULL WHERE id = k;
  INSERT INTO public.key_validation_log (key_id, adapter, probe, ok, http_status, latency_ms) VALUES (k, 'elevenlabs', 'GET /v1/user', true, 200, 123);

  SELECT * INTO s FROM public.active_keys_for_runner;
  IF s.secret <> 'xi-secret-key-ROTATED-9999' OR s.key_env <> 'ELEVENLABS_API_KEY' OR s.key_last4 <> '9999' THEN
    RAISE EXCEPTION 'active_keys_for_runner wrong: %', s;
  END IF;
END;
$$;

-- ---------------------------------------------------------------- Alice again: sees status + log, revokes
SET LOCAL ROLE authenticated;
SET LOCAL request.jwt.claims = '{"sub": "00000000-0000-0000-0000-00000000000a", "role": "authenticated"}';
DO $$
DECLARE k uuid; n int;
BEGIN
  SELECT id INTO k FROM public.vendor_api_keys WHERE tool_slug = 'elevenlabs' AND status = 'active';
  SELECT count(*) INTO n FROM public.key_validation_log WHERE key_id = k AND ok; IF n <> 1 THEN RAISE EXCEPTION 'alice should see her validation log'; END IF;
  PERFORM public.revoke_api_key(k);
  SELECT count(*) INTO n FROM public.vendor_api_keys WHERE id = k AND status = 'revoked' AND vault_secret_id IS NULL;
  IF n <> 1 THEN RAISE EXCEPTION 'revoke failed'; END IF;
END;
$$;

RESET ROLE;
DO $$
DECLARE n int;
BEGIN
  SELECT count(*) INTO n FROM vault.secrets; IF n <> 0 THEN RAISE EXCEPTION 'vault should be empty after revokes, has %', n; END IF;
  SELECT count(*) INTO n FROM public.active_keys_for_runner; IF n <> 0 THEN RAISE EXCEPTION 'runner view should be empty'; END IF;
END;
$$;

ROLLBACK;
\echo claims smoke test passed
