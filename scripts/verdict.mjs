#!/usr/bin/env node
// Day-60 continue/stop check. Reads:
//   data/metrics/clicks.json   {"pages": {"/voice/elevenlabs-vs-openai-tts/": {"clicks": 12, "impressions": 340}, ...}, "window_days": 60}
//   data/catalog/voice/tools.json  (tools with vendor_key_received: true count as keys handed over)
// Criteria (docs/roadmap.md): >= 2 vendors supplied a key AND organic clicks > 0.
import { readFileSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const tools = JSON.parse(readFileSync(join(root, 'data/catalog/voice/tools.json'), 'utf8'));
const metricsPath = join(root, 'data/metrics/clicks.json');
const metrics = existsSync(metricsPath) ? JSON.parse(readFileSync(metricsPath, 'utf8')) : { pages: {}, window_days: 0 };

const keys = tools.filter((t) => t.vendor_key_received === true).map((t) => t.slug);
const clicks = Object.values(metrics.pages ?? {}).reduce((a, p) => a + (p.clicks ?? 0), 0);
const impressions = Object.values(metrics.pages ?? {}).reduce((a, p) => a + (p.impressions ?? 0), 0);
const pagesWithClicks = Object.entries(metrics.pages ?? {}).filter(([, p]) => (p.clicks ?? 0) > 0).map(([k]) => k);

const keysOk = keys.length >= 2;
const clicksOk = clicks > 0;
const verdict = keysOk && clicksOk ? 'CONTINUE' : 'STOP';

console.log(`Verdict: ${verdict}`);
console.log(`- vendor keys received: ${keys.length} (${keys.join(', ') || 'none'}) → ${keysOk ? 'pass' : 'fail'} (need 2)`);
console.log(`- organic clicks in ${metrics.window_days ?? '?'} days: ${clicks} on ${pagesWithClicks.length} pages, ${impressions} impressions → ${clicksOk ? 'pass' : 'fail'} (need > 0)`);
if (!existsSync(metricsPath)) console.log('- note: data/metrics/clicks.json is missing; clicks counted as 0');
process.exit(verdict === 'CONTINUE' ? 0 : 2);
