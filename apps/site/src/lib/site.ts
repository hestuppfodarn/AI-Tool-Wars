// Site-wide constants and link helpers.

export const SITE_NAME = process.env.SITE_NAME || 'AI Tool Wars';
export const CONTACT_EMAIL = process.env.PUBLIC_CONTACT_EMAIL || 'vendors@saasarena.ai';

const base = (import.meta.env.BASE_URL || '/').replace(/\/+$/, '');

/** Prefix an internal path with the configured base; leave absolute URLs alone. */
export function href(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  const clean = path.replace(/^\/+/, '');
  if (clean === '') return `${base}/`;
  return `${base}/${clean}`.replace(/\/?$/, '/');
}

/** Asset URL: like href() but without a forced trailing slash. */
export function asset(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  return `${base}/${path.replace(/^\/+/, '')}`;
}

/** Absolute URL for embeds, honouring site + base. */
export function absolute(site: URL | undefined, path: string): string {
  const origin = site ? site.origin : '';
  return origin + asset(path) + (path.endsWith('/') ? '' : '');
}

export function fmtDate(iso: string | null): string {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString('en-GB', { year: 'numeric', month: 'short', day: 'numeric' });
}

/** Whole days from an ISO date (YYYY-MM-DD, UTC midnight) to now; never negative. */
export function daysSince(isoDate: string, now: Date = new Date()): number {
  const [y, m, d] = isoDate.split('-').map(Number);
  const start = Date.UTC(y, m - 1, d);
  return Math.max(0, Math.floor((now.getTime() - start) / 86_400_000));
}

/** "day 0", "day 21": the counter as it reads in the brand's copy. */
export function fmtDay(n: number): string {
  return `day ${n}`;
}

/** Copy nouns per output modality, so pages read "hear" for audio and "read" for text. */
export function modalityWords(modality: string): { verb: string; noun: string; outputs: string } {
  switch (modality) {
    case 'audio': return { verb: 'Listen to', noun: 'clip', outputs: 'audio' };
    case 'text': return { verb: 'Read', noun: 'answer', outputs: 'text outputs' };
    case 'app': return { verb: 'Open', noun: 'app', outputs: 'generated apps' };
    default: return { verb: 'See', noun: 'output', outputs: 'outputs' };
  }
}

export function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return '–';
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}

export function fmtScore(n: number | null | undefined): string {
  if (n == null) return '–';
  return n.toFixed(1);
}

export function claimMailto(toolName: string, categoryName: string): string {
  const subject = encodeURIComponent(`Claim ${toolName} on ${SITE_NAME} (${categoryName})`);
  const body = encodeURIComponent(
    `Hi,\n\nI represent ${toolName}. We'd like to claim our listing and provide an API key so our results are run on our own account.\n\nContact name:\nRole:\nBest way to send the key securely:\n`
  );
  return `mailto:${CONTACT_EMAIL}?subject=${subject}&body=${body}`;
}
