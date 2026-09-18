-- Smoke test for migration 0001. Run against a database that has the
-- migration applied:  psql -d arena -v ON_ERROR_STOP=1 -f db/tests/0001_smoke.sql
-- Everything is rolled back at the end.

BEGIN;

-- Seed: one category, two tools, one golden prompt.
INSERT INTO categories (id, slug, name) VALUES
  ('00000000-0000-0000-0000-00000000c001', 'copywriting', 'AI Copywriting');

INSERT INTO tools (id, slug, name, status, endpoint_url) VALUES
  ('00000000-0000-0000-0000-0000000000a1', 'copy-a', 'Copy A', 'seeded', 'https://api.copy-a.example/v1'),
  ('00000000-0000-0000-0000-0000000000b2', 'copy-b', 'Copy B', 'seeded', 'https://api.copy-b.example/v1');

INSERT INTO tool_categories (tool_id, category_id, is_primary) VALUES
  ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-00000000c001', true),
  ('00000000-0000-0000-0000-0000000000b2', '00000000-0000-0000-0000-00000000c001', true);

INSERT INTO prompts (id, category_id, kind, title, body, golden_rank, content_hash) VALUES
  ('00000000-0000-0000-0000-0000000000f1', '00000000-0000-0000-0000-00000000c001', 'golden',
   'Landing hero', 'Write a 20-word hero headline for a B2B invoicing tool. No exclamation marks.', 1,
   prompt_content_hash('Write a 20-word hero headline for a B2B invoicing tool. No exclamation marks.'));

-- Hash normalisation: whitespace/case differences collapse onto one hash.
DO $$
BEGIN
  IF prompt_content_hash('  Hello   World ') <> prompt_content_hash('hello world') THEN
    RAISE EXCEPTION 'prompt_content_hash should normalise whitespace and case';
  END IF;
END $$;

-- Platform seed key (ciphertext is a placeholder; real values come from the proxy's KMS envelope).
INSERT INTO vendor_api_keys (id, tool_id, funding_source, key_ciphertext, key_nonce, kms_key_id, key_fingerprint, status)
VALUES ('00000000-0000-0000-0000-0000000000e1', '00000000-0000-0000-0000-0000000000a1', 'platform',
        '\x00'::bytea, '\x00'::bytea, 'kms/test', 'fp-a', 'active');

-- A second ACTIVE platform key for the same tool must be rejected.
DO $$
BEGIN
  INSERT INTO vendor_api_keys (tool_id, funding_source, key_ciphertext, key_nonce, kms_key_id, key_fingerprint, status)
  VALUES ('00000000-0000-0000-0000-0000000000a1', 'platform', '\x00', '\x00', 'kms/test', 'fp-a2', 'active');
  RAISE EXCEPTION 'expected unique violation for second active key';
EXCEPTION WHEN unique_violation THEN
  NULL;
END $$;

-- Canonical executions for both tools.
INSERT INTO executions (id, tool_id, prompt_id, api_key_id, adapter_version, cache_key, source, status, is_canonical, output_text, ttft_ms, latency_ms) VALUES
  ('00000000-0000-0000-0000-00000000ee01', '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000f1',
   '00000000-0000-0000-0000-0000000000e1', 1, 'exec:a1:hash:1', 'live', 'success', true, 'Invoices that pay themselves.', 120, 900),
  ('00000000-0000-0000-0000-00000000ee02', '00000000-0000-0000-0000-0000000000b2', '00000000-0000-0000-0000-0000000000f1',
   NULL, 1, 'exec:b2:hash:1', 'live', 'success', true, 'Get paid faster with less admin.', 300, 2100);

-- A second canonical execution for the same (tool, prompt, adapter_version) must be rejected.
DO $$
BEGIN
  INSERT INTO executions (tool_id, prompt_id, adapter_version, cache_key, source, status, is_canonical)
  VALUES ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000f1', 1, 'exec:a1:hash:1', 'live', 'success', true);
  RAISE EXCEPTION 'expected unique violation for second canonical execution';
EXCEPTION WHEN unique_violation THEN
  NULL;
END $$;

-- Jury: two judges on each execution.
INSERT INTO jury_evaluations (execution_id, judge_model, constraint_adherence, factuality_integrity, conciseness_utility, execution_velocity) VALUES
  ('00000000-0000-0000-0000-00000000ee01', 'gpt-4o',            9, 8, 9, 9),
  ('00000000-0000-0000-0000-00000000ee01', 'claude-3-7-sonnet', 8, 8, 9, 9),
  ('00000000-0000-0000-0000-00000000ee02', 'gpt-4o',            7, 8, 6, 5),
  ('00000000-0000-0000-0000-00000000ee02', 'claude-3-7-sonnet', 6, 7, 7, 5);

-- Battle in blind mode, ready to vote.
INSERT INTO battles (id, mode, category_id, prompt_id, tool_a_id, tool_b_id, execution_a_id, execution_b_id, status, served_from, session_id)
VALUES ('00000000-0000-0000-0000-00000000bb01', 'blind_random', '00000000-0000-0000-0000-00000000c001', '00000000-0000-0000-0000-0000000000f1',
        '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000b2',
        '00000000-0000-0000-0000-00000000ee01', '00000000-0000-0000-0000-00000000ee02', 'ready', 'cache', gen_random_uuid());

-- Same tool on both sides must be rejected.
DO $$
BEGIN
  INSERT INTO battles (mode, category_id, prompt_id, tool_a_id, tool_b_id, session_id)
  VALUES ('blind_random', '00000000-0000-0000-0000-00000000c001', '00000000-0000-0000-0000-0000000000f1',
          '00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-0000000000a1', gen_random_uuid());
  RAISE EXCEPTION 'expected check violation for identical tools';
EXCEPTION WHEN check_violation THEN
  NULL;
END $$;

-- Vote: A wins. Both start at 1500, K=32 → A +16, B -16.
INSERT INTO votes (id, battle_id, session_id, choice, time_to_vote_ms)
VALUES ('00000000-0000-0000-0000-00000000dd01', '00000000-0000-0000-0000-00000000bb01', gen_random_uuid(), 'a', 8500);

DO $$
DECLARE v votes%ROWTYPE; a numeric; b numeric; st battle_status; hist int;
BEGIN
  SELECT * INTO v FROM votes WHERE id = '00000000-0000-0000-0000-00000000dd01';
  IF v.elo_a_before <> 1500 OR v.elo_b_before <> 1500 THEN RAISE EXCEPTION 'before snapshot wrong: % %', v.elo_a_before, v.elo_b_before; END IF;
  IF v.elo_a_after <> 1516 OR v.elo_b_after <> 1484 THEN RAISE EXCEPTION 'after snapshot wrong: % %', v.elo_a_after, v.elo_b_after; END IF;
  IF v.k_factor <> 32 THEN RAISE EXCEPTION 'k factor wrong: %', v.k_factor; END IF;

  SELECT human_elo INTO a FROM tool_ratings WHERE tool_id = '00000000-0000-0000-0000-0000000000a1';
  SELECT human_elo INTO b FROM tool_ratings WHERE tool_id = '00000000-0000-0000-0000-0000000000b2';
  IF a <> 1516 OR b <> 1484 THEN RAISE EXCEPTION 'ratings wrong: % %', a, b; END IF;

  SELECT status INTO st FROM battles WHERE id = '00000000-0000-0000-0000-00000000bb01';
  IF st <> 'voted' THEN RAISE EXCEPTION 'battle status should be voted, got %', st; END IF;

  SELECT count(*) INTO hist FROM rating_history WHERE vote_id = v.id;
  IF hist <> 2 THEN RAISE EXCEPTION 'expected 2 rating_history rows, got %', hist; END IF;
END $$;

-- A second vote on the same battle must be rejected. The trigger's status
-- guard fires first (battle is already 'voted'); the UNIQUE(battle_id) index
-- is the backstop for uncounted votes that skip the trigger body.
DO $$
BEGIN
  INSERT INTO votes (battle_id, session_id, choice)
  VALUES ('00000000-0000-0000-0000-00000000bb01', gen_random_uuid(), 'b');
  RAISE EXCEPTION 'expected rejection of second vote';
EXCEPTION WHEN check_violation OR unique_violation THEN
  NULL;
END $$;
DO $$
BEGIN
  INSERT INTO votes (battle_id, session_id, choice, is_counted)
  VALUES ('00000000-0000-0000-0000-00000000bb01', gen_random_uuid(), 'b', false);
  RAISE EXCEPTION 'expected unique violation for second (uncounted) vote';
EXCEPTION WHEN unique_violation THEN
  NULL;
END $$;

-- Changing a recorded choice must be rejected.
DO $$
BEGIN
  UPDATE votes SET choice = 'b' WHERE id = '00000000-0000-0000-0000-00000000dd01';
  RAISE EXCEPTION 'expected immutability error';
EXCEPTION WHEN raise_exception THEN
  NULL;
END $$;

-- Voting on a battle that was already revealed must be rejected.
INSERT INTO battles (id, mode, category_id, prompt_id, tool_a_id, tool_b_id, execution_a_id, execution_b_id, status, served_from, session_id, revealed_at)
VALUES ('00000000-0000-0000-0000-00000000bb02', 'head_to_head', '00000000-0000-0000-0000-00000000c001', '00000000-0000-0000-0000-0000000000f1',
        '00000000-0000-0000-0000-0000000000b2', '00000000-0000-0000-0000-0000000000a1',
        '00000000-0000-0000-0000-00000000ee02', '00000000-0000-0000-0000-00000000ee01', 'ready', 'cache', gen_random_uuid(), now());
DO $$
BEGIN
  INSERT INTO votes (battle_id, session_id, choice) VALUES ('00000000-0000-0000-0000-00000000bb02', gen_random_uuid(), 'a');
  RAISE EXCEPTION 'expected check violation for post-reveal vote';
EXCEPTION WHEN check_violation THEN
  NULL;
END $$;

-- An uncounted vote must not move ratings.
UPDATE battles SET revealed_at = NULL WHERE id = '00000000-0000-0000-0000-00000000bb02';
INSERT INTO votes (battle_id, session_id, choice, is_counted, exclusion_reason)
VALUES ('00000000-0000-0000-0000-00000000bb02', gen_random_uuid(), 'a', false, 'vote in <2s');
DO $$
DECLARE a numeric;
BEGIN
  SELECT human_elo INTO a FROM tool_ratings WHERE tool_id = '00000000-0000-0000-0000-0000000000a1';
  IF a <> 1516 THEN RAISE EXCEPTION 'uncounted vote moved rating to %', a; END IF;
END $$;

-- Leaderboard view resolves with jury aggregates after a refresh.
REFRESH MATERIALIZED VIEW leaderboard_jury_scores;
DO $$
DECLARE r record;
BEGIN
  SELECT * INTO r FROM leaderboard WHERE slug = 'copy-a';
  IF r.human_rank <> 1 OR r.jury_rank <> 1 THEN RAISE EXCEPTION 'copy-a should rank 1/1, got %/%', r.human_rank, r.jury_rank; END IF;
  IF r.jury_composite <> 8.63 THEN RAISE EXCEPTION 'copy-a composite expected 8.63, got %', r.jury_composite; END IF;
  IF r.median_latency_ms <> 900 THEN RAISE EXCEPTION 'copy-a median latency expected 900, got %', r.median_latency_ms; END IF;
END $$;

-- arena_app must not be able to read key material.
SET LOCAL ROLE arena_app;
DO $$
BEGIN
  PERFORM key_ciphertext FROM vendor_api_keys LIMIT 1;
  RAISE EXCEPTION 'arena_app should not read key_ciphertext';
EXCEPTION WHEN insufficient_privilege THEN
  NULL;
END $$;
SELECT count(*) FROM vendor_api_keys;  -- metadata columns are readable
RESET ROLE;

SELECT 'smoke test passed' AS result;
ROLLBACK;
