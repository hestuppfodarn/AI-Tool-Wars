import { z } from 'astro/zod';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';

// ---------------------------------------------------------------------------
// Snapshot schema. This is the contract between the data pipeline
// (scripts/export-snapshot.mjs, later the runner/scorer) and the site.
// ---------------------------------------------------------------------------

const Metric = z.object({
  key: z.string(),
  label: z.string(),
  description: z.string(),
});

export const CategorySchema = z.object({
  slug: z.string(),
  name: z.string(),
  description: z.string(),
  output_modality: z.enum(['audio', 'text', 'image', 'video']),
  metrics: z.array(Metric).min(1),
});

export const ToolSchema = z.object({
  slug: z.string(),
  name: z.string(),
  vendor: z.string(),
  website: z.string().url(),
  description: z.string(),
  category: z.string(),
  status: z.enum(['pending', 'executed', 'benchmarked', 'verified']),
});

export const PromptSchema = z.object({
  id: z.string(),
  category: z.string(),
  rank: z.number().int(),
  title: z.string(),
  language: z.string(),
  tags: z.array(z.string()),
  text: z.string(),
  instructions: z.string().optional(),
  constraints: z.array(z.string()),
});

export const RunSchema = z.object({
  category: z.string(),
  tool: z.string(),
  prompt_id: z.string(),
  run_at: z.string(),
  audio_url: z.string().nullable(),
  transcript: z.string().nullable().optional(),
  ttft_ms: z.number().nullable(),
  latency_ms: z.number().nullable(),
  scores: z.record(z.string(), z.number()),
  composite: z.number().nullable(),   // null until the scorer has run
  status: z.enum(['success', 'error']).default('success'),
  error: z.string().nullable().optional(),
  wer: z.number().nullable().optional(),
  judge_rationale: z.string().nullable().optional(),
});

export const RatingSchema = z.object({
  category: z.string(),
  tool: z.string(),
  runs: z.number().int(),
  composite: z.number(),
  scores: z.record(z.string(), z.number()),
  median_ttft_ms: z.number().nullable(),
  median_latency_ms: z.number().nullable(),
  rank: z.number().int(),
});

export const PairSchema = z.object({
  category: z.string(),
  slug: z.string(),
  a: z.string(),
  b: z.string(),
  verdict: z
    .object({ headline: z.string(), summary: z.string() })
    .nullable(),
});

export const SnapshotSchema = z.object({
  version: z.literal(1),
  generated_at: z.string(),
  source: z.enum(['catalog', 'demo', 'db']),
  demo: z.boolean(),
  categories: z.array(CategorySchema),
  tools: z.array(ToolSchema),
  prompts: z.array(PromptSchema),
  runs: z.array(RunSchema),
  ratings: z.array(RatingSchema),
  pairs: z.array(PairSchema),
});

export type Snapshot = z.infer<typeof SnapshotSchema>;
export type Category = z.infer<typeof CategorySchema>;
export type Tool = z.infer<typeof ToolSchema>;
export type Prompt = z.infer<typeof PromptSchema>;
export type Run = z.infer<typeof RunSchema>;
export type Rating = z.infer<typeof RatingSchema>;
export type Pair = z.infer<typeof PairSchema>;

// ---------------------------------------------------------------------------
// Loader. SNAPSHOT=demo swaps in the fictional dataset for layout previews.
// ---------------------------------------------------------------------------

let cached: Snapshot | null = null;

/** Walk up from cwd to the repo root (the directory that holds data/catalog). */
function repoRoot(): string {
  let dir = resolve(process.cwd());
  for (let i = 0; i < 6; i++) {
    if (existsSync(join(dir, 'data', 'catalog'))) return dir;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  throw new Error(`Could not find repo root (data/catalog) above ${process.cwd()}`);
}

export function loadSnapshot(): Snapshot {
  if (cached) return cached;
  const path = process.env.SNAPSHOT_PATH
    ?? join(repoRoot(), 'data', process.env.SNAPSHOT === 'demo' ? 'fixtures/demo-snapshot.json' : 'snapshot.json');
  const raw = JSON.parse(readFileSync(path, 'utf8'));
  const parsed = SnapshotSchema.safeParse(raw);
  if (!parsed.success) {
    throw new Error(`Invalid snapshot at ${path}:\n${parsed.error.toString()}`);
  }
  cached = parsed.data;
  return cached;
}

// ---------------------------------------------------------------------------
// Query helpers.
// ---------------------------------------------------------------------------

export function categoryBySlug(s: Snapshot, slug: string): Category {
  const c = s.categories.find((c) => c.slug === slug);
  if (!c) throw new Error(`Unknown category ${slug}`);
  return c;
}

export function toolBySlug(s: Snapshot, slug: string): Tool {
  const t = s.tools.find((t) => t.slug === slug);
  if (!t) throw new Error(`Unknown tool ${slug}`);
  return t;
}

export function toolsIn(s: Snapshot, category: string): Tool[] {
  return s.tools.filter((t) => t.category === category);
}

export function promptsIn(s: Snapshot, category: string): Prompt[] {
  return s.prompts.filter((p) => p.category === category).sort((a, b) => a.rank - b.rank);
}

export function pairsIn(s: Snapshot, category: string): Pair[] {
  return s.pairs.filter((p) => p.category === category);
}

export function pairsFor(s: Snapshot, category: string, tool: string): Pair[] {
  return pairsIn(s, category).filter((p) => p.a === tool || p.b === tool);
}

export function ratingFor(s: Snapshot, category: string, tool: string): Rating | null {
  return s.ratings.find((r) => r.category === category && r.tool === tool) ?? null;
}

export function ratingsIn(s: Snapshot, category: string): Rating[] {
  return s.ratings.filter((r) => r.category === category).sort((a, b) => a.rank - b.rank);
}

export function runFor(s: Snapshot, category: string, tool: string, promptId: string): Run | null {
  return s.runs.find((r) => r.category === category && r.tool === tool && r.prompt_id === promptId) ?? null;
}

/** Latest run date for a set of tools in a category, or null when nothing has run. */
export function lastRunAt(s: Snapshot, category: string, tools: string[]): string | null {
  const dates = s.runs
    .filter((r) => r.category === category && tools.includes(r.tool))
    .map((r) => r.run_at)
    .sort();
  return dates.length ? dates[dates.length - 1] : null;
}
