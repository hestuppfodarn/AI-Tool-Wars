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

  return {
    version: 1,
    generated_at: new Date().toISOString(),
    source: 'catalog',
    demo: false,
    categories, tools, prompts,
    runs, ratings: [], pairs,
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
          transcript: null,
          ttft_ms: success ? r.ttft_ms ?? null : null,
          latency_ms: success ? r.latency_ms ?? null : null,
          scores: {}, composite: null,
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
  console.log(`wrote ${outPath}: ${snap.categories.length} categories, ${snap.tools.length} tools, ${snap.prompts.length} prompts, ${snap.pairs.length} pairs, ${snap.runs.length} runs (source=catalog)`);
}
