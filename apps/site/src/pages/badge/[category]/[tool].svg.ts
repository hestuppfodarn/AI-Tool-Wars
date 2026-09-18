import type { APIRoute } from 'astro';
import { loadSnapshot, ratingFor, categoryBySlug } from '../../../lib/snapshot';
import { SITE_NAME } from '../../../lib/site';

export function getStaticPaths() {
  return loadSnapshot().tools.map((t) => ({ params: { category: t.category, tool: t.slug } }));
}

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

export const GET: APIRoute = ({ params }) => {
  const snap = loadSnapshot();
  const category = categoryBySlug(snap, params.category!);
  const tool = snap.tools.find((t) => t.slug === params.tool)!;
  const rating = ratingFor(snap, category.slug, tool.slug);
  const shortCat = category.name.replace(/\s*\(.*\)$/, '');
  const verified = tool.status === 'verified';
  const right = rating ? `#${rating.rank} · ${rating.composite.toFixed(1)} / 10` : 'benchmark pending';
  const sub = rating ? `${shortCat} · ${rating.runs} prompts${verified ? ' · vendor verified' : ''}` : `${shortCat} · ${SITE_NAME}`;
  const accent = rating ? (rating.rank === 1 ? '#15803d' : '#1d4ed8') : '#b45309';
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="260" height="56" viewBox="0 0 260 56" role="img" aria-label="${esc(tool.name)}: ${esc(right)}">
  <rect x="0.5" y="0.5" width="259" height="55" rx="8" fill="#ffffff" stroke="#e4e3df"/>
  <rect x="0.5" y="0.5" width="6" height="55" rx="3" fill="${accent}"/>
  <text x="16" y="23" font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif" font-size="14" font-weight="700" fill="#1c1c1a">${esc(tool.name)}</text>
  <text x="16" y="42" font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif" font-size="11" fill="#6b6a66">${esc(sub)}</text>
  <text x="248" y="23" text-anchor="end" font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif" font-size="13" font-weight="700" fill="${accent}">${esc(right)}</text>
  <text x="248" y="42" text-anchor="end" font-family="ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif" font-size="10" fill="#6b6a66">${esc(SITE_NAME)}</text>
</svg>
`;
  return new Response(svg, { headers: { 'Content-Type': 'image/svg+xml; charset=utf-8', 'Cache-Control': 'public, max-age=3600' } });
};
