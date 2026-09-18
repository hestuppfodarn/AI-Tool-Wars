// verify-dns: the ownership path for claimants whose email domain does not
// match the tool's website domain.
//
// The claim page shows the claimant a token; they publish
//   TXT  <tool domain>            toolwars-verify=<token>
// (or on _toolwars.<tool domain>) and press "Check DNS". This function looks
// the record up over DNS-over-HTTPS (Cloudflare, then Google as a fallback)
// and, on a match, flips the claim to verified / dns_txt with the service
// role. Nothing else changes; keys still go through submit_api_key.
//
// Invoked with the user's JWT: POST { claim_id }.
// Deploy: npx supabase functions deploy verify-dns --project-ref <ref>

interface ClaimRow {
  id: string;
  tool_slug: string;
  status: 'pending' | 'verified' | 'rejected';
  dns_token: string;
  tools: { domain: string | null } | null;
}

interface DohAnswer { name: string; type: number; data: string }
interface DohResponse { Status: number; Answer?: DohAnswer[] }

const SUPABASE_URL = Deno.env.get('SUPABASE_URL') ?? '';
const ANON_KEY = Deno.env.get('SUPABASE_ANON_KEY') ?? '';
const SERVICE_KEY = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY') ?? '';
const RESOLVERS = ['https://cloudflare-dns.com/dns-query', 'https://dns.google/resolve'];

const CORS: Record<string, string> = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { ...CORS, 'Content-Type': 'application/json' } });
}

async function rest(path: string, init: RequestInit, token: string): Promise<Response> {
  const headers: Record<string, string> = {
    apikey: token === SERVICE_KEY ? SERVICE_KEY : ANON_KEY,
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
    ...(init.headers as Record<string, string> | undefined),
  };
  return fetch(`${SUPABASE_URL}/rest/v1/${path}`, { ...init, headers });
}

/** TXT records for a name, as plain strings (quoted chunks joined). */
async function txtRecords(name: string): Promise<string[]> {
  let lastErr = 'no resolver answered';
  for (const base of RESOLVERS) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 8_000);
    try {
      const res = await fetch(`${base}?name=${encodeURIComponent(name)}&type=TXT`, {
        headers: { accept: 'application/dns-json' }, signal: ctrl.signal,
      });
      if (!res.ok) { lastErr = `${base}: HTTP ${res.status}`; continue; }
      const body = (await res.json()) as DohResponse;
      if (body.Status !== 0 && body.Status !== 3) { lastErr = `${base}: rcode ${body.Status}`; continue; }
      return (body.Answer ?? [])
        .filter((a) => a.type === 16)
        .map((a) => a.data.replace(/"\s+"/g, '').replace(/^"|"$/g, ''));
    } catch (e) {
      lastErr = `${base}: ${e instanceof Error ? e.message : String(e)}`;
    } finally {
      clearTimeout(timer);
    }
  }
  throw new Error(lastErr);
}

Deno.serve(async (req: Request): Promise<Response> => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS });
  if (req.method !== 'POST') return json({ error: 'POST only' }, 405);
  if (!SUPABASE_URL || !ANON_KEY || !SERVICE_KEY) return json({ error: 'function env missing' }, 500);

  const token = (req.headers.get('Authorization') ?? '').replace(/^Bearer\s+/i, '');
  if (!token || token === SERVICE_KEY) return json({ error: 'a signed-in user must call this' }, 401);

  let claimId = '';
  try { claimId = String((await req.json())?.claim_id ?? ''); } catch { /* fallthrough */ }
  if (!/^[0-9a-f-]{36}$/i.test(claimId)) return json({ error: 'claim_id (uuid) required' }, 400);

  // RLS: the user only sees their own claim. tools is public.
  const own = await rest(`tool_claims?id=eq.${claimId}&select=id,tool_slug,status,dns_token,tools(domain)`, { method: 'GET' }, token);
  if (!own.ok) return json({ error: 'not signed in' }, 401);
  const rows = (await own.json()) as ClaimRow[];
  if (rows.length !== 1) return json({ error: 'no such claim' }, 404);
  const claim = rows[0];
  if (claim.status === 'verified') return json({ verified: true, already: true });
  if (claim.status === 'rejected') return json({ verified: false, error: 'claim was rejected' }, 409);
  const domain = claim.tools?.domain;
  if (!domain) return json({ verified: false, error: 'this tool has no verifiable domain; ask for manual review' }, 422);

  const expected = `toolwars-verify=${claim.dns_token}`;
  const names = [domain, `_toolwars.${domain}`];
  const seen: Record<string, string[]> = {};
  let found = false;
  try {
    for (const name of names) {
      const records = await txtRecords(name);
      seen[name] = records.map((r) => (r.startsWith('toolwars-verify=') ? r.replace(/=.*/, '=…') : r.slice(0, 40)));
      if (records.some((r) => r.trim() === expected)) { found = true; break; }
    }
  } catch (e) {
    return json({ verified: false, error: `DNS lookup failed: ${e instanceof Error ? e.message : String(e)}` }, 502);
  }

  if (!found) {
    return json({ verified: false, checked: names, seen, expected: `TXT ${domain} "${expected}"`, hint: 'DNS changes can take up to an hour to propagate; check again later.' });
  }

  const patch = await rest(`tool_claims?id=eq.${claimId}&status=eq.pending`, {
    method: 'PATCH',
    headers: { Prefer: 'return=representation' },
    body: JSON.stringify({ status: 'verified', verification: 'dns_txt', verified_at: new Date().toISOString() }),
  }, SERVICE_KEY);
  if (!patch.ok) return json({ verified: false, error: `could not update claim (${patch.status})` }, 500);

  console.log(JSON.stringify({ fn: 'verify-dns', claim_id: claimId, tool: claim.tool_slug, domain, verified: true }));
  return json({ verified: true, tool_slug: claim.tool_slug, domain });
});

// Module marker: keeps this file a module under tsc and Deno alike.
export {};
