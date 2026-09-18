// Build-time configuration for the claims backend (Supabase). Server-side only:
// this module runs in Astro frontmatter during the static build, never in the
// browser. The public URL + anon key are safe to embed in the page; the anon
// key can do nothing that RLS does not allow.
//
// Sources, in order of preference:
//   1. data/supabase.public.json = {"url": "...", "anon_key": "..."}, committed
//      by .github/workflows/setup-supabase.yml after it creates the project.
//   2. PUBLIC_SUPABASE_URL + PUBLIC_SUPABASE_ANON_KEY in the build environment.
// With neither present the claim page renders its "claims open soon" state and
// the claim CTA falls back to mailto, so the build never breaks.

import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';

export interface SupabasePublicConfig {
  url: string;
  anonKey: string;
  source: 'file' | 'env' | 'none';
}

function repoRoot(): string | null {
  let dir = resolve(process.cwd());
  for (let i = 0; i < 6; i++) {
    if (existsSync(join(dir, 'data', 'catalog'))) return dir;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

function fromFile(): SupabasePublicConfig | null {
  try {
    const root = repoRoot();
    if (!root) return null;
    const path = join(root, 'data', 'supabase.public.json');
    if (!existsSync(path)) return null;
    const raw = JSON.parse(readFileSync(path, 'utf8')) as { url?: unknown; anon_key?: unknown };
    const url = typeof raw.url === 'string' ? raw.url.trim() : '';
    const anonKey = typeof raw.anon_key === 'string' ? raw.anon_key.trim() : '';
    return url && anonKey ? { url, anonKey, source: 'file' } : null;
  } catch {
    return null;
  }
}

function fromEnv(): SupabasePublicConfig | null {
  const url = String(import.meta.env.PUBLIC_SUPABASE_URL ?? '').trim();
  const anonKey = String(import.meta.env.PUBLIC_SUPABASE_ANON_KEY ?? '').trim();
  return url && anonKey ? { url, anonKey, source: 'env' } : null;
}

function load(): SupabasePublicConfig {
  const cfg = fromFile() ?? fromEnv();
  if (!cfg) return { url: '', anonKey: '', source: 'none' };
  if (!/^https:\/\/[a-z0-9.-]+(:\d+)?$/i.test(cfg.url.replace(/\/+$/, ''))) {
    console.warn(`[supabase] ignoring config from ${cfg.source}: url must be https origin, got ${cfg.url}`);
    return { url: '', anonKey: '', source: 'none' };
  }
  return { ...cfg, url: cfg.url.replace(/\/+$/, '') };
}

export const supabaseConfig: SupabasePublicConfig = load();
export const SUPABASE_URL = supabaseConfig.url;
export const SUPABASE_ANON_KEY = supabaseConfig.anonKey;
/** True when the claim page can talk to a backend; otherwise the CTA keeps its mailto. */
export const claimsEnabled = supabaseConfig.source !== 'none';
