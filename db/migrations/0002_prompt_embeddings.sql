-- =============================================================================
-- Migration 0002 (OPTIONAL): semantic near-duplicate lookup for custom prompts.
--
-- Requires the pgvector extension. Skip this migration if pgvector is not
-- installed; nothing in 0001 or the proxy's core path depends on it.
--
-- Purpose: when a user types a custom prompt, the proxy first tries an exact
-- content_hash match (Tier-1). If that misses, it can embed the prompt and look
-- for a golden prompt within a small cosine distance in the same category. A
-- close-enough golden neighbour is served from cache and the battle is tagged
-- served_from='cache' — extending the ~80% cache hit-rate to paraphrases.
-- =============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE prompts
  ADD COLUMN embedding vector(1536),              -- text-embedding-3-small; change dim if you swap models
  ADD COLUMN embedding_model text;

-- HNSW gives good recall at this scale (thousands of golden prompts, not millions).
CREATE INDEX prompts_embedding_hnsw_idx
  ON prompts USING hnsw (embedding vector_cosine_ops)
  WHERE kind = 'golden' AND is_active AND embedding IS NOT NULL;

-- Nearest active golden prompt in a category. Caller decides the threshold
-- (0.08–0.12 cosine distance is a reasonable starting band; tune per category).
CREATE OR REPLACE FUNCTION nearest_golden_prompt(
  p_category_id uuid,
  p_embedding   vector(1536),
  p_max_distance double precision DEFAULT 0.10
) RETURNS TABLE (prompt_id uuid, distance double precision)
LANGUAGE sql STABLE AS $$
  SELECT p.id, p.embedding <=> p_embedding AS distance
  FROM prompts p
  WHERE p.category_id = p_category_id
    AND p.kind = 'golden' AND p.is_active AND p.embedding IS NOT NULL
  ORDER BY p.embedding <=> p_embedding
  LIMIT 1
$$;

-- Keep only rows within threshold; wrapper so callers get NULL instead of a far neighbour.
CREATE OR REPLACE FUNCTION match_golden_prompt(
  p_category_id uuid,
  p_embedding   vector(1536),
  p_max_distance double precision DEFAULT 0.10
) RETURNS uuid
LANGUAGE sql STABLE AS $$
  SELECT prompt_id FROM nearest_golden_prompt(p_category_id, p_embedding, p_max_distance)
  WHERE distance <= p_max_distance
$$;

COMMIT;
