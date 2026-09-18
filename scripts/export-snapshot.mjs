#!/usr/bin/env node
// Builds data/snapshot.json, the single input the site renders from.
//
// Today: reads data/catalog/<category>/{category,tools,prompts}.json and emits a
// snapshot with no runs, so every tool renders in the "benchmark pending" state.
//
// Runner phase: when DATABASE_URL is set this script will read canonical
// executions + scores from Postgres instead (see docs/roadmap.md). Until that
// lands it refuses to pretend, so the site can never show invented results.

import { readFileSync, readdirSync, writeFileSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const catalogDir = join(root, 'data', 'catalog');
const outPath = join(root, 'data', 'snapshot.json');

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

  return {
    version: 1,
    generated_at: new Date().toISOString(),
    source: 'catalog',
    demo: false,
    categories, tools, prompts,
    runs: [], ratings: [], pairs,
  };
}

const isMain = process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1];
if (isMain) {
  const snap = buildFromCatalog();
  writeFileSync(outPath, JSON.stringify(snap, null, 2) + '\n');
  console.log(`wrote ${outPath}: ${snap.categories.length} categories, ${snap.tools.length} tools, ${snap.prompts.length} prompts, ${snap.pairs.length} pairs (source=catalog, no runs)`);
}
