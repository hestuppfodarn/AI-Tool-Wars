#!/usr/bin/env node
// Scores recorded voice runs in place (data/runs/voice/<tool>/runs.json).
//
//   node scripts/score-voice.mjs --tool inworld-tts [--asr openai|none] [--judge openai|none]
//                                [--force] [--openai-base-url URL]
//
// Metrics written per run under `scores`:
//   accuracy   : from word error rate between prompt text and an ASR transcript (1-10)
//   adherence  : LLM judge over transcript + the prompt's explicit constraints (1-10)
//   naturalness: left null until a MOS predictor backend exists (excluded from composite)
// `velocity` is NOT computed here: it is a rank across tools, so the exporter derives it.
//
// Backends are pluggable and keyed off env vars. With --asr none --judge none the
// script only (re)computes accuracy from transcripts already present.

import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const envPath = join(root, '.env');
if (existsSync(envPath)) for (const line of readFileSync(envPath, 'utf8').split('\n')) {
  const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
  if (m && process.env[m[1]] === undefined) process.env[m[1]] = m[2].replace(/^["']|["']$/g, '');
}
const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, arr) => {
  if (a.startsWith('--')) acc.push([a.slice(2), arr[i + 1] && !arr[i + 1].startsWith('--') ? arr[i + 1] : 'true']); return acc; }, []));
if (!args.tool) { console.error('usage: score-voice.mjs --tool <slug> [--asr openai|none] [--judge openai|none] [--force]'); process.exit(1); }

const category = 'voice';
const prompts = JSON.parse(readFileSync(join(root, 'data/catalog', category, 'prompts.json'), 'utf8'));
const catDef = JSON.parse(readFileSync(join(root, 'data/catalog', category, 'category.json'), 'utf8'));
const runDir = join(root, 'data/runs', category, args.tool);
const runsPath = join(runDir, 'runs.json');
if (!existsSync(runsPath)) { console.error(`no runs at ${runsPath}`); process.exit(1); }
const runs = JSON.parse(readFileSync(runsPath, 'utf8'));
const byPrompt = new Map(prompts.map((p) => [p.id, p]));

const asrBackend = args.asr ?? (process.env.OPENAI_API_KEY ? 'openai' : 'none');
const judgeBackend = args.judge ?? (process.env.OPENAI_API_KEY ? 'openai' : 'none');
const openaiBase = args['openai-base-url'] ?? process.env.OPENAI_BASE_URL ?? 'https://api.openai.com';
const openaiKey = process.env.OPENAI_API_KEY;
if ((asrBackend === 'openai' || judgeBackend === 'openai') && !openaiKey) { console.error('OPENAI_API_KEY missing for openai backend'); process.exit(3); }

// ---------------------------------------------------------------------------
// Text normalisation + WER. Deliberately simple and documented in methodology:
// lowercase, strip punctuation, collapse whitespace. Digits stay digits; ASR
// models normally emit digits for spoken numbers, so "0800" round-trips.
// ---------------------------------------------------------------------------
export function normalize(text) {
  return text.toLowerCase()
    .replace(/\[[^\]]*\]/g, ' ')            // stage directions like [Now, sadly:] are not spoken
    .replace(/[“”"‘’'.,!?;:()\-–—…/]/g, ' ')
    .replace(/\s+/g, ' ').trim();
}
export function wer(reference, hypothesis) {
  const r = normalize(reference).split(' ').filter(Boolean);
  const h = normalize(hypothesis).split(' ').filter(Boolean);
  if (!r.length) return h.length ? 1 : 0;
  const d = Array.from({ length: r.length + 1 }, (_, i) => [i, ...Array(h.length).fill(0)]);
  for (let j = 1; j <= h.length; j++) d[0][j] = j;
  for (let i = 1; i <= r.length; i++) for (let j = 1; j <= h.length; j++)
    d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (r[i - 1] === h[j - 1] ? 0 : 1));
  return d[r.length][h.length] / r.length;
}
/** WER 0 -> 10, WER >= 0.5 -> 1, linear between. */
export function accuracyScore(w) { return Math.round((10 - 9 * Math.min(1, w / 0.5)) * 10) / 10; }

// ---------------------------------------------------------------------------
// Backends
// ---------------------------------------------------------------------------
async function transcribeOpenAI(file, language) {
  const form = new FormData();
  form.append('file', new Blob([readFileSync(file)]), file.split('/').pop());
  form.append('model', process.env.ASR_MODEL ?? 'whisper-1');
  form.append('response_format', 'json');
  if (language) form.append('language', language.split('-')[0]);
  const res = await fetch(`${openaiBase}/v1/audio/transcriptions`, { method: 'POST', headers: { Authorization: `Bearer ${openaiKey}` }, body: form });
  if (!res.ok) throw new Error(`ASR HTTP ${res.status}: ${(await res.text()).slice(0, 200)}`);
  return (await res.json()).text ?? '';
}

async function judgeOpenAI(prompt, run, transcript) {
  const model = process.env.JUDGE_MODEL ?? 'gpt-4o-mini';
  const rubric = catDef.jury_rubric ?? {};
  const sys = `You are scoring a text-to-speech output for instruction following. You cannot hear the audio; you see the prompt, its explicit constraints, an ASR transcript of the audio, and timing metadata. Score 1-10 how well the output followed the constraints that can be judged from this evidence (words spoken, digits read individually, stage directions not spoken, language, omissions/additions). Constraints you cannot judge from text (tone, pauses, volume) count as neutral. Respond with JSON only: {"score": <1-10>, "rationale": "<one sentence>"}. ${rubric.judge_note ?? ''}`;
  const user = JSON.stringify({ prompt_text: prompt.text, direction: prompt.instructions ?? null, language: prompt.language, constraints: prompt.constraints, transcript, ttft_ms: run.ttft_ms, latency_ms: run.latency_ms, audio_bytes: run.bytes });
  const res = await fetch(`${openaiBase}/v1/chat/completions`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${openaiKey}` },
    body: JSON.stringify({ model, temperature: 0, response_format: { type: 'json_object' }, messages: [{ role: 'system', content: sys }, { role: 'user', content: user }] }),
  });
  if (!res.ok) throw new Error(`judge HTTP ${res.status}: ${(await res.text()).slice(0, 200)}`);
  const json = await res.json();
  const parsed = JSON.parse(json.choices?.[0]?.message?.content ?? '{}');
  const score = Number(parsed.score);
  if (!(score >= 1 && score <= 10)) throw new Error(`judge returned bad score: ${JSON.stringify(parsed).slice(0, 100)}`);
  return { score: Math.round(score * 10) / 10, rationale: String(parsed.rationale ?? '').slice(0, 400), model };
}

// ---------------------------------------------------------------------------
let scored = 0, skipped = 0, failed = 0;
for (const run of runs) {
  if (run.status !== 'success') { skipped++; continue; }
  const prompt = byPrompt.get(run.prompt_id);
  if (!prompt) { skipped++; continue; }
  run.scores ??= {};
  const already = run.transcript && run.scores.accuracy != null && (judgeBackend === 'none' || run.scores.adherence != null);
  if (already && args.force !== 'true') { skipped++; continue; }
  process.stdout.write(`${run.prompt_id} `);
  try {
    if ((!run.transcript || args.force === 'true') && asrBackend === 'openai') {
      run.transcript = await transcribeOpenAI(join(runDir, run.audio), prompt.language);
      run.asr_model = process.env.ASR_MODEL ?? 'whisper-1';
    }
    if (run.transcript != null) {
      run.wer = Math.round(wer(prompt.text, run.transcript) * 1000) / 1000;
      run.scores.accuracy = accuracyScore(run.wer);
    }
    if (judgeBackend === 'openai' && run.transcript != null && (run.scores.adherence == null || args.force === 'true')) {
      const j = await judgeOpenAI(prompt, run, run.transcript);
      run.scores.adherence = j.score;
      run.judge = { model: j.model, rationale: j.rationale, version: 'v1' };
    }
    if (run.scores.naturalness === undefined) run.scores.naturalness = null;
    run.scored_at = new Date().toISOString();
    scored++;
    console.log(`wer ${run.wer ?? '–'}  accuracy ${run.scores.accuracy ?? '–'}  adherence ${run.scores.adherence ?? '–'}`);
  } catch (e) {
    failed++;
    console.log(`FAIL ${String(e.message ?? e).slice(0, 140)}`);
  }
  writeFileSync(runsPath, JSON.stringify(runs, null, 2) + '\n');
}
console.log(`\n${args.tool}: ${scored} scored, ${failed} failed, ${skipped} skipped (asr=${asrBackend}, judge=${judgeBackend})`);
process.exit(failed && !scored ? 1 : 0);
