// validate-key: one cheap live probe of a freshly submitted vendor API key.
//
// Invoked by the claim page right after `submit_api_key` returns a key id
// (POST { key_id } with the user's JWT), or by CI with the service-role key
// to re-check. It reads the secret from Vault through `read_key_secret()`
// (service role only), runs one adapter-specific request, then writes the
// verdict to vendor_api_keys + key_validation_log. The secret is held in
// memory for the duration of one fetch and is never logged, returned, or
// stored anywhere else.
//
// Deploy: npx supabase functions deploy validate-key --project-ref <ref>
// Env (injected by Supabase): SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY

type KeyStatus = 'pending_validation' | 'active' | 'invalid' | 'revoked';

interface SecretRow {
  key_id: string;
  tool_slug: string;
  adapter: string;
  auth_scheme: string;
  status: KeyStatus;
  secret: string;
}

interface ProbeResult {
  probe: string;            // endpoint label for the log
  ok: boolean;
  httpStatus: number | null;
  latencyMs: number;
  error: string | null;     // vendor-facing, already scrubbed
  retryable: boolean;       // 5xx / network: keep pending_validation, do not mark invalid
}

const SUPABASE_URL = Deno.env.get('SUPABASE_URL') ?? '';
const ANON_KEY = Deno.env.get('SUPABASE_ANON_KEY') ?? '';
const SERVICE_KEY = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? '';
const PROBE_TIMEOUT_MS = 15_000;

const CORS: Record<string, string> = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { ...CORS, 'Content-Type': 'application/json' } });
}

/** Minimal PostgREST client: enough for select / rpc / patch / insert. */
async function rest(path: string, init: RequestInit, token: string): Promise<Response> {
  const headers: Record<string, string> = {
    apikey: token === SERVICE_KEY ? SERVICE_KEY : ANON_KEY,
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
    ...(init.headers as Record<string, string> | undefined),
  };
  return fetch(`${SUPABASE_URL}/rest/v1/${path}`, { ...init, headers });
}

/** Replace any occurrence of the secret (or its first 12 chars) in a string. */
function scrub(text: string, secret: string): string {
  if (!text) return text;
  let out = text.split(secret).join('[redacted]');
  const head = secret.slice(0, 12);
  if (head.length >= 8) out = out.split(head).join('[redacted]');
  return out.replace(/(sk-|xi-|key-)[A-Za-z0-9_-]{8,}/g, '$1[redacted]').slice(0, 300);
}

async function timedFetch(url: string, init: RequestInit): Promise<{ res: Response | null; latencyMs: number; err: string | null }> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), PROBE_TIMEOUT_MS);
  const t0 = performance.now();
  try {
    const res = await fetch(url, { ...init, signal: ctrl.signal, redirect: 'manual' });
    return { res, latencyMs: Math.round(performance.now() - t0), err: null };
  } catch (e) {
    const msg = e instanceof Error ? (e.name === 'AbortError' ? `timeout after ${PROBE_TIMEOUT_MS} ms` : e.message) : String(e);
    return { res: null, latencyMs: Math.round(performance.now() - t0), err: msg };
  } finally {
    clearTimeout(timer);
  }
}

// One probe per adapter. Each is the cheapest call that still proves the key
// is accepted by the vendor. Bodies are tiny on purpose.
const PROBES: Record<string, (key: string) => { probe: string; url: string; init: RequestInit }> = {
  inworld: (key) => ({
    probe: 'POST /tts/v1/voice',
    url: 'https://api.inworld.ai/tts/v1/voice',
    init: {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Basic ${key}` },
      body: JSON.stringify({ text: 'Tool Wars key check, hello.', voiceId: 'Ashley', modelId: 'inworld-tts-1', audioConfig: { audioEncoding: 'MP3' } }),
    },
  }),
  openai: (key) => ({
    probe: 'POST /v1/audio/speech',
    url: 'https://api.openai.com/v1/audio/speech',
    init: {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${key}` },
      body: JSON.stringify({ model: 'gpt-4o-mini-tts', voice: 'alloy', input: 'Key check.', response_format: 'mp3' }),
    },
  }),
  elevenlabs: (key) => ({
    probe: 'GET /v1/user',
    url: 'https://api.elevenlabs.io/v1/user',
    init: { method: 'GET', headers: { 'xi-api-key': key } },
  }),
  cartesia: (key) => ({
    probe: 'GET /voices',
    url: 'https://api.cartesia.ai/voices',
    init: { method: 'GET', headers: { 'X-API-Key': key, 'Cartesia-Version': '2024-11-13' } },
  }),
  openai_chat: (key) => ({
    probe: 'POST /v1/chat/completions',
    url: 'https://api.openai.com/v1/chat/completions',
    init: {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${key}` },
      body: JSON.stringify({ model: 'gpt-4o-mini', messages: [{ role: 'user', content: 'hi' }], max_tokens: 1 }),
    },
  }),
  anthropic: (key) => ({
    probe: 'POST /v1/messages',
    url: 'https://api.anthropic.com/v1/messages',
    init: {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-api-key': key, 'anthropic-version': '2023-06-01' },
      body: JSON.stringify({ model: 'claude-opus-5', max_tokens: 1, messages: [{ role: 'user', content: 'hi' }] }),
    },
  }),
  gemini: (key) => ({
    probe: 'POST /v1beta/models/gemini-2.0-flash:generateContent',
    url: 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent',
    init: {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'x-goog-api-key': key },
      body: JSON.stringify({ contents: [{ parts: [{ text: 'hi' }] }], generationConfig: { maxOutputTokens: 1 } }),
    },
  }),
};

async function runProbe(adapter: string, secret: string): Promise<ProbeResult> {
  const build = PROBES[adapter];
  if (!build) return { probe: 'none', ok: false, httpStatus: null, latencyMs: 0, error: `no probe for adapter ${adapter}`, retryable: false };
  const { probe, url, init } = build(secret);
  const { res, latencyMs, err } = await timedFetch(url, init);
  if (!res) return { probe, ok: false, httpStatus: null, latencyMs, error: scrub(err ?? 'network error', secret), retryable: true };

  // Drain the body without keeping audio around; keep a short text excerpt for errors.
  let excerpt = '';
  try {
    const ct = res.headers.get('content-type') ?? '';
    if (ct.includes('json') || ct.startsWith('text/')) excerpt = (await res.text()).slice(0, 200);
    else await res.arrayBuffer();
  } catch { /* body errors are not the key's fault */ }

  if (res.ok) return { probe, ok: true, httpStatus: res.status, latencyMs, error: null, retryable: false };
  const retryable = res.status >= 500 || res.status === 429;
  const label = res.status === 401 || res.status === 403 ? 'vendor rejected the key'
    : res.status === 402 ? 'vendor reports no credit on this key'
    : res.status === 429 ? 'vendor rate-limited the probe'
    : res.status >= 500 ? 'vendor error'
    : 'vendor refused the request';
  return { probe, ok: false, httpStatus: res.status, latencyMs, error: scrub(`${label} (HTTP ${res.status}) ${excerpt}`.trim(), secret), retryable };
}

Deno.serve(async (req: Request): Promise<Response> => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS });
  if (req.method !== 'POST') return json({ error: 'POST only' }, 405);
  if (!SUPABASE_URL || !ANON_KEY || !SERVICE_KEY) return json({ error: 'function env missing' }, 500);

  const auth = req.headers.get('Authorization') ?? '';
  const token = auth.replace(/^Bearer\s+/i, '');
  if (!token) return json({ error: 'missing Authorization' }, 401);

  let keyId = '';
  try { keyId = String((await req.json())?.key_id ?? ''); } catch { /* fallthrough */ }
  if (!/^[0-9a-f-]{36}$/i.test(keyId)) return json({ error: 'key_id (uuid) required' }, 400);

  // Ownership: a user may only validate a key row RLS lets them see.
  // The service role (CI re-checks) skips this.
  if (token !== SERVICE_KEY) {
    const own = await rest(`vendor_api_keys?id=eq.${keyId}&select=id`, { method: 'GET' }, token);
    if (!own.ok) return json({ error: 'not signed in' }, 401);
    const rows = (await own.json()) as Array<{ id: string }>;
    if (rows.length !== 1) return json({ error: 'no such key' }, 404);
  }

  // Secret, service role only, straight from Vault.
  const sec = await rest('rpc/read_key_secret', { method: 'POST', body: JSON.stringify({ p_key_id: keyId }) }, SERVICE_KEY);
  if (!sec.ok) return json({ error: `read_key_secret failed (${sec.status})` }, 500);
  const rows = (await sec.json()) as SecretRow[];
  if (rows.length !== 1) return json({ error: 'key not found or revoked' }, 404);
  const row = rows[0];

  const result = await runProbe(row.adapter, row.secret);
  const newStatus: KeyStatus = result.ok ? 'active' : result.retryable ? 'pending_validation' : 'invalid';

  const patch = await rest(`vendor_api_keys?id=eq.${keyId}`, {
    method: 'PATCH',
    headers: { Prefer: 'return=minimal' },
    body: JSON.stringify({
      status: newStatus,
      validated_at: result.ok ? new Date().toISOString() : null,
      last_error: result.error,
    }),
  }, SERVICE_KEY);
  const log = await rest('key_validation_log', {
    method: 'POST',
    headers: { Prefer: 'return=minimal' },
    body: JSON.stringify({
      key_id: keyId, adapter: row.adapter, probe: result.probe, ok: result.ok,
      http_status: result.httpStatus, latency_ms: result.latencyMs, error: result.error, actor: 'edge:validate-key',
    }),
  }, SERVICE_KEY);

  // Structured log line: ids and outcome only.
  console.log(JSON.stringify({ fn: 'validate-key', key_id: keyId, tool: row.tool_slug, adapter: row.adapter, probe: result.probe, ok: result.ok, http: result.httpStatus, ms: result.latencyMs, status: newStatus, patched: patch.ok, logged: log.ok }));

  return json({ key_id: keyId, tool_slug: row.tool_slug, adapter: row.adapter, status: newStatus, probe: result.probe, http_status: result.httpStatus, latency_ms: result.latencyMs, error: result.error });
});

// Module marker: keeps this file a module under tsc and Deno alike.
export {};
