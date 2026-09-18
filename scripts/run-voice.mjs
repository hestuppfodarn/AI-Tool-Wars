#!/usr/bin/env node
// Minimal voice runner: executes the golden prompt bank against one tool and
// records audio + timings under data/runs/voice/<tool>/. No scoring here; the
// exporter merges these runs into the snapshot so the site shows real outputs
// with the scorecard still pending.
//
//   node scripts/run-voice.mjs --tool inworld-tts [--limit 3] [--prompts voice-001,voice-002]
//                              [--force] [--base-url http://localhost:9999]
//
// Secrets come from .env (gitignored) or the environment. Never from the catalog.

import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

// --- tiny .env loader (no dependency) ---------------------------------------
const envPath = join(root, '.env');
if (existsSync(envPath)) {
  for (const line of readFileSync(envPath, 'utf8').split('\n')) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
    if (m && process.env[m[1]] === undefined) process.env[m[1]] = m[2].replace(/^["']|["']$/g, '');
  }
}

// --- args --------------------------------------------------------------------
const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, a, i, arr) => {
    if (a.startsWith('--')) acc.push([a.slice(2), arr[i + 1] && !arr[i + 1].startsWith('--') ? arr[i + 1] : 'true']);
    return acc;
  }, [])
);
if (!args.tool) { console.error('usage: run-voice.mjs --tool <slug> [--limit N] [--prompts a,b] [--force] [--base-url URL]'); process.exit(1); }

const category = 'voice';
const tools = JSON.parse(readFileSync(join(root, 'data/catalog', category, 'tools.json'), 'utf8'));
const prompts = JSON.parse(readFileSync(join(root, 'data/catalog', category, 'prompts.json'), 'utf8'));
const tool = tools.find((t) => t.slug === args.tool);
if (!tool) { console.error(`unknown tool ${args.tool}`); process.exit(1); }

// --- adapters ----------------------------------------------------------------
// Each adapter: { env, defaultBaseUrl, synth(prompt, cfg, ctx) -> { bytes, ext, ttft_ms, latency_ms, meta } }

const adapters = {
  inworld: {
    env: 'INWORLD_API_KEY',
    defaultBaseUrl: 'https://api.inworld.ai',
    async synth(prompt, cfg, { key, baseUrl, timeoutMs }) {
      const voice = cfg.voice_by_language?.[prompt.language] ?? cfg.voice_by_language?.[prompt.language.split('-')[0]] ?? cfg.voice_by_language?.default ?? 'Ashley';
      const encoding = cfg.audio_encoding ?? 'MP3';
      const body = JSON.stringify({
        text: prompt.text,
        voiceId: voice,
        modelId: cfg.model_id ?? 'inworld-tts-1',
        audioConfig: { audioEncoding: encoding },
      });
      const headers = { 'Content-Type': 'application/json', Authorization: `Basic ${key}` };
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), timeoutMs);
      const t0 = performance.now();
      let ttft = null;
      const chunks = [];
      try {
        // Streaming endpoint: newline-delimited JSON, each line {"result":{"audioContent":"<base64>"}}.
        let res = await fetch(`${baseUrl}/tts/v1/voice:stream`, { method: 'POST', headers, body, signal: ctrl.signal });
        if (res.status === 404 || res.status === 405) {
          // Fall back to the unary endpoint; TTFB then equals total latency.
          res = await fetch(`${baseUrl}/tts/v1/voice`, { method: 'POST', headers, body, signal: ctrl.signal });
          if (!res.ok) throw new Error(`HTTP ${res.status}: ${(await res.text()).slice(0, 300)}`);
          const json = await res.json();
          const t1 = performance.now();
          return { bytes: Buffer.from(json.audioContent, 'base64'), ext: encoding.toLowerCase(), ttft_ms: Math.round(t1 - t0), latency_ms: Math.round(t1 - t0), meta: { voice, model: cfg.model_id, endpoint: 'unary' } };
        }
        if (!res.ok) throw new Error(`HTTP ${res.status}: ${(await res.text()).slice(0, 300)}`);
        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = '';
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          let nl;
          while ((nl = buf.indexOf('\n')) >= 0) {
            const line = buf.slice(0, nl).trim(); buf = buf.slice(nl + 1);
            if (!line) continue;
            const obj = JSON.parse(line);
            const b64 = obj.result?.audioContent ?? obj.audioContent;
            if (b64) { if (ttft === null) ttft = Math.round(performance.now() - t0); chunks.push(Buffer.from(b64, 'base64')); }
            if (obj.error) throw new Error(`stream error: ${JSON.stringify(obj.error).slice(0, 300)}`);
          }
        }
        if (buf.trim()) { const obj = JSON.parse(buf); const b64 = obj.result?.audioContent ?? obj.audioContent; if (b64) chunks.push(Buffer.from(b64, 'base64')); }
        const t1 = performance.now();
        if (!chunks.length) throw new Error('no audio in stream');
        return { bytes: Buffer.concat(chunks), ext: encoding.toLowerCase(), ttft_ms: ttft ?? Math.round(t1 - t0), latency_ms: Math.round(t1 - t0), meta: { voice, model: cfg.model_id, endpoint: 'stream' } };
      } finally { clearTimeout(timer); }
    },
  },
};

const adapter = adapters[tool.adapter];
if (!adapter) { console.error(`no adapter '${tool.adapter}' for ${tool.slug}; adapters: ${Object.keys(adapters).join(', ')}`); process.exit(1); }
const key = process.env[adapter.env];
if (!key) { console.error(`missing ${adapter.env} (put it in .env)`); process.exit(1); }
const baseUrl = args['base-url'] ?? adapter.defaultBaseUrl;
const timeoutMs = Number(args.timeout ?? 60000);

// --- run ---------------------------------------------------------------------
const outDir = join(root, 'data/runs', category, tool.slug);
mkdirSync(outDir, { recursive: true });
const runsPath = join(outDir, 'runs.json');
const runs = existsSync(runsPath) ? JSON.parse(readFileSync(runsPath, 'utf8')) : [];
const byId = new Map(runs.map((r) => [r.prompt_id, r]));

let selected = prompts.slice().sort((a, b) => a.rank - b.rank);
if (args.prompts) { const ids = new Set(args.prompts.split(',')); selected = selected.filter((p) => ids.has(p.id)); }
if (args.limit) selected = selected.slice(0, Number(args.limit));

const maxChars = Number(args['max-chars'] ?? 20000);
let charsUsed = 0, ok = 0, failed = 0, skipped = 0;

for (const p of selected) {
  const prev = byId.get(p.id);
  if (prev?.status === 'success' && args.force !== 'true') { skipped++; continue; }
  if (charsUsed + p.text.length > maxChars) { console.error(`char budget ${maxChars} reached; stopping`); break; }
  charsUsed += p.text.length;
  process.stdout.write(`${p.id} ${p.title.padEnd(34)} `);
  const run_at = new Date().toISOString();
  try {
    const r = await adapter.synth(p, tool.run ?? {}, { key, baseUrl, timeoutMs });
    const file = `${p.id}.${r.ext}`;
    writeFileSync(join(outDir, file), r.bytes);
    byId.set(p.id, { prompt_id: p.id, run_at, status: 'success', audio: file, bytes: r.bytes.length, ttft_ms: r.ttft_ms, latency_ms: r.latency_ms, ...r.meta });
    ok++;
    console.log(`ok  ttfb ${String(r.ttft_ms).padStart(5)} ms  total ${String(r.latency_ms).padStart(5)} ms  ${r.bytes.length} B`);
  } catch (e) {
    byId.set(p.id, { prompt_id: p.id, run_at, status: 'error', error: String(e.message ?? e).slice(0, 500) });
    failed++;
    console.log(`FAIL ${String(e.message ?? e).slice(0, 120)}`);
    if (failed >= 5 && ok === 0) { console.error('5 consecutive failures with no success; aborting (check key / endpoint)'); break; }
  }
  writeFileSync(runsPath, JSON.stringify([...byId.values()].sort((a, b) => a.prompt_id.localeCompare(b.prompt_id)), null, 2) + '\n');
}
console.log(`\n${tool.slug}: ${ok} ok, ${failed} failed, ${skipped} skipped (already run). Runs in ${runsPath}`);
process.exit(failed && !ok ? 1 : 0);
