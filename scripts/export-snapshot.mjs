#!/usr/bin/env node
// Builds data/snapshot.json, the single input the site renders from.
//
// Today: reads data/catalog/<category>/{category,tools,prompts}.json plus any
// recorded runs under data/runs/<category>/<tool>/runs.json (written by
// scripts/run-voice.mjs). Runs carry audio + timings but no scores until the
// scorer exists, so tools with runs render as "outputs recorded, scoring pending".
// Audio files are copied into apps/site/public/runs/ (gitignored) at export time.
//
// Runner phase: when DATABASE_URL is set this script will read canonical
// executions + scores from Postgres instead (see docs/roadmap.md). Until that
// lands it refuses to pretend, so the site can never show invented results.

import { readFileSync, readdirSync, writeFileSync, existsSync, cpSync, rmSync, mkdirSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const catalogDir = join(root, 'data', 'catalog');
const outPath = join(root, 'data', 'snapshot.json');
const runsDir = join(root, 'data', 'runs');
const publicRunsDir = join(root, 'apps', 'site', 'public', 'runs');

if (process.env.DATABASE_URL) {
  console.error('DATABASE_URL is set but the Postgres exporter is not implemented yet. Unset it to build from the catalog.');
  process.exit(2);
}

const readJson = (p) => JSON.parse(readFileSync(p, 'utf8'));

export function pairSlug(a, b) {
  return `${a}-vs-${b}`;
}

export function buildFromCatalog() {
  const categories = [];
  const tools = [];
  const prompts = [];
  const pairs = [];

  for (const dir of readdirSync(catalogDir, { withFileTypes: true }).filter((d) => d.isDirectory())) {
    const base = join(catalogDir, dir.name);
    const category = readJson(join(base, 'category.json'));
    const catTools = readJson(join(base, 'tools.json'));
    const catPrompts = readJson(join(base, 'prompts.json'));

    categories.push({
      slug: category.slug,
      name: category.name,
      description: category.description,
      output_modality: category.output_modality,
      metrics: category.metrics,
    });

    for (const t of catTools) {
      tools.push({
        slug: t.slug, name: t.name, vendor: t.vendor, website: t.website,
        description: t.description, category: category.slug, status: 'pending',
      });
    }

    for (const p of catPrompts) {
      prompts.push({
        id: p.id, category: category.slug, rank: p.rank, title: p.title, language: p.language,
        tags: p.tags ?? [], text: p.text, instructions: p.instructions, constraints: p.constraints ?? [],
      });
    }

    for (let i = 0; i < catTools.length; i++) {
      for (let j = i + 1; j < catTools.length; j++) {
        pairs.push({
          category: category.slug,
          slug: pairSlug(catTools[i].slug, catTools[j].slug),
          a: catTools[i].slug, b: catTools[j].slug, verdict: null,
        });
      }
    }
  }

  const runs = collectRuns(tools);
  addVelocity(runs);
  const ratings = aggregateRatings(runs, tools, categories);
  for (const pair of pairs) pair.verdict = buildVerdict(pair, ratings, tools, categories, prompts);

  return {
    version: 1,
    generated_at: new Date().toISOString(),
    source: 'catalog',
    demo: false,
    categories, tools, prompts,
    runs, ratings, pairs,
  };
}

const mean = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);
const median = (xs) => { const s = xs.slice().sort((a, b) => a - b); return s.length ? s[Math.floor(s.length / 2)] : null; };
const r1 = (x) => (x == null ? null : Math.round(x * 10) / 10);
const r2 = (x) => (x == null ? null : Math.round(x * 100) / 100);

/**
 * Velocity is a rank, not an absolute: for each prompt, tools are compared on the
 * same text, so latency is comparable. Score = 10 for the fastest, 1 for the
 * slowest, linear in between on the mean of TTFB and total-latency ranks.
 * Needs at least two tools on a prompt; otherwise null.
 */
function addVelocity(runs) {
  const groups = new Map();
  for (const r of runs) {
    if (r.status !== 'success' || r.ttft_ms == null || r.latency_ms == null) continue;
    const k = `${r.category}:${r.prompt_id}`;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(r);
  }
  for (const group of groups.values()) {
    if (group.length < 2) { for (const r of group) r.scores.velocity = null; continue; }
    const rankScore = (key) => {
      const sorted = group.slice().sort((a, b) => a[key] - b[key]);
      const n = sorted.length;
      return new Map(sorted.map((r, i) => [r, 10 - (9 * i) / (n - 1)]));
    };
    const byTtft = rankScore('ttft_ms'), byLat = rankScore('latency_ms');
    for (const r of group) r.scores.velocity = r1((byTtft.get(r) + byLat.get(r)) / 2);
  }
  for (const r of runs) {
    const present = Object.values(r.scores ?? {}).filter((v) => typeof v === 'number');
    r.composite = present.length ? r2(mean(present)) : null;
  }
}

function aggregateRatings(runs, tools, categories) {
  const ratings = [];
  for (const cat of categories) {
    const keys = cat.metrics.map((m) => m.key);
    const rows = [];
    for (const tool of tools.filter((t) => t.category === cat.slug)) {
      const ok = runs.filter((r) => r.tool === tool.slug && r.category === cat.slug && r.status === 'success');
      const scoredRuns = ok.filter((r) => r.composite != null);
      if (!scoredRuns.length) continue;
      const scores = {};
      for (const k of keys) {
        const vals = scoredRuns.map((r) => r.scores?.[k]).filter((v) => typeof v === 'number');
        if (vals.length) scores[k] = r2(mean(vals));
      }
      rows.push({
        category: cat.slug, tool: tool.slug, runs: scoredRuns.length,
        composite: r2(mean(Object.values(scores))), scores,
        median_ttft_ms: median(ok.map((r) => r.ttft_ms).filter((v) => v != null)),
        median_latency_ms: median(ok.map((r) => r.latency_ms).filter((v) => v != null)),
        rank: 0,
      });
      if (tool.status === 'executed' || tool.status === 'pending') tool.status = 'benchmarked';
    }
    rows.sort((a, b) => b.composite - a.composite);
    rows.forEach((r, i) => { r.rank = i + 1; });
    ratings.push(...rows);
  }
  return ratings;
}

/** Templated verdict from the numbers. An LLM can rewrite this later; it must never contradict it. */
function buildVerdict(pair, ratings, tools, categories, prompts) {
  const ra = ratings.find((r) => r.category === pair.category && r.tool === pair.a);
  const rb = ratings.find((r) => r.category === pair.category && r.tool === pair.b);
  if (!ra || !rb) return null;
  const cat = categories.find((c) => c.slug === pair.category);
  const name = (slug) => tools.find((t) => t.slug === slug).name;
  const label = Object.fromEntries(cat.metrics.map((m) => [m.key, m.label.toLowerCase()]));
  const [w, l] = ra.composite >= rb.composite ? [ra, rb] : [rb, ra];
  const n = prompts.filter((p) => p.category === pair.category).length;
  const diffs = cat.metrics.map((m) => ({ k: m.key, d: (w.scores[m.key] ?? 0) - (l.scores[m.key] ?? 0) })).filter((x) => w.scores[x.k] != null && l.scores[x.k] != null);
  const lead = diffs.filter((x) => x.d > 0.3).sort((x, y) => y.d - x.d).slice(0, 2).map((x) => label[x.k]);
  const trail = diffs.filter((x) => x.d < -0.3).map((x) => label[x.k]);
  const parts = [];
  if (lead.length) parts.push(`${name(w.tool)} is ahead on ${lead.join(' and ')}.`);
  if (trail.length) parts.push(`${name(l.tool)} wins on ${trail.join(' and ')}.`);
  if (ra.median_ttft_ms != null && rb.median_ttft_ms != null) parts.push(`Median time to first byte: ${name(pair.a)} ${ra.median_ttft_ms} ms, ${name(pair.b)} ${rb.median_ttft_ms} ms.`);
  const scoredNote = w.runs < n || l.runs < n ? ` Scored on ${Math.min(w.runs, l.runs)} of ${n} prompts so far.` : '';
  const shortCat = cat.name.replace(/\s*\(.*\)$/, '');
  const tied = Math.abs(w.composite - l.composite) < 0.15;
  return {
    headline: tied
      ? `${name(pair.a)} and ${name(pair.b)} tie at ${w.composite.toFixed(1)} on the ${n}-prompt ${shortCat} bank.`
      : `${name(w.tool)} leads ${name(l.tool)} ${w.composite.toFixed(1)} to ${l.composite.toFixed(1)} on the ${n}-prompt ${shortCat} bank.`,
    summary: parts.join(' ') + scoredNote,
  };
}

/** Merge data/runs/<category>/<tool>/runs.json files; copies audio to the site's public dir. */
function collectRuns(tools) {
  const out = [];
  rmSync(publicRunsDir, { recursive: true, force: true });
  if (!existsSync(runsDir)) return out;
  for (const cat of readdirSync(runsDir, { withFileTypes: true }).filter((d) => d.isDirectory())) {
    for (const toolDir of readdirSync(join(runsDir, cat.name), { withFileTypes: true }).filter((d) => d.isDirectory())) {
      const file = join(runsDir, cat.name, toolDir.name, 'runs.json');
      if (!existsSync(file)) continue;
      const tool = tools.find((t) => t.slug === toolDir.name && t.category === cat.name);
      if (!tool) { console.warn(`runs for unknown tool ${cat.name}/${toolDir.name}; skipped`); continue; }
      const recorded = readJson(file);
      let successes = 0;
      for (const r of recorded) {
        const success = r.status === 'success';
        if (success) successes++;
        out.push({
          category: cat.name, tool: tool.slug, prompt_id: r.prompt_id, run_at: r.run_at,
          audio_url: success && r.audio ? `runs/${cat.name}/${tool.slug}/${r.audio}` : null,
          transcript: r.transcript ?? null,
          ttft_ms: success ? r.ttft_ms ?? null : null,
          latency_ms: success ? r.latency_ms ?? null : null,
          scores: success ? Object.fromEntries(Object.entries(r.scores ?? {}).filter(([, v]) => typeof v === 'number')) : {},
          composite: null,
          wer: r.wer ?? null,
          judge_rationale: r.judge?.rationale ?? null,
          status: success ? 'success' : 'error',
          error: success ? null : (r.error ?? 'unknown error'),
        });
      }
      if (successes > 0 && tool.status === 'pending') tool.status = 'executed';
      mkdirSync(join(publicRunsDir, cat.name, tool.slug), { recursive: true });
      cpSync(join(runsDir, cat.name, toolDir.name), join(publicRunsDir, cat.name, tool.slug), { recursive: true, filter: (src) => !src.endsWith('runs.json') });
    }
  }
  return out;
}

const isMain = process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1];
if (isMain) {
  const snap = buildFromCatalog();
  writeFileSync(outPath, JSON.stringify(snap, null, 2) + '\n');
  console.log(`wrote ${outPath}: ${snap.categories.length} categories, ${snap.tools.length} tools, ${snap.prompts.length} prompts, ${snap.pairs.length} pairs, ${snap.runs.length} runs, ${snap.ratings.length} rated tools (source=catalog)`);
}
