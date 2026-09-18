import type { Snapshot } from './snapshot';
import { promptsIn, ratingsIn, toolsIn } from './snapshot';

// ---------------------------------------------------------------------------
// The front.
//
// Every prompt in a category is a piece of territory. The tool with the highest
// composite score on that prompt holds it. Everything here is a pure function of
// the snapshot: `run.composite` per (tool, prompt) from `snapshot.runs`, and the
// category's ratings for tie-breaking in the territory table.
//
// Rules, in order:
//   - a run counts only when status is 'success' and composite is a number;
//   - a prompt nobody has a scored run on is unclaimed (holder null, contested []);
//   - a prompt with exactly one scored tool is held by that tool with no margin;
//   - an exact tie at the top (within TIE_EPSILON) is contested: holder null,
//     `contested` lists the tied tools;
//   - otherwise the top tool holds it with `margin` = its composite minus the
//     runner-up's.
//
// Head to head (frontLine) uses a wider band: the two tools are within
// CONTESTED_BAND of each other on the prompt -> contested.
//
// Data contract for movements (not yet produced by the exporter):
//
//   Snapshot.previous_holders?: {
//     [category: string]: {
//       run_at: string;                                  // ISO date of the previous export
//       holders: { [promptId: string]: string | null };  // tool slug, or null for unclaimed/contested
//     }
//   }
//
// The exporter can produce it by keeping the previous snapshot's `holders()`
// output (one line per category, computed with this file's rules) before it
// overwrites data/snapshot.json. `movements()` compares that map with the
// current front and lists prompts whose holder changed; a prompt missing from
// the map is skipped, so a partial map is fine. The optional field is declared
// in snapshot.ts and the Movements component renders nothing when it is absent.
// ---------------------------------------------------------------------------

export const TIE_EPSILON = 1e-6;
export const CONTESTED_BAND = 0.3;

export interface Scored {
  tool: string;
  composite: number;
}

export interface PromptFront {
  prompt_id: string;
  /** Tool slug holding the prompt; null when unclaimed or contested. */
  holder: string | null;
  /** Tools sharing the top composite when it is a tie; empty otherwise. */
  contested: string[];
  /** Holder composite minus runner-up; null when unclaimed, contested or unopposed. */
  margin: number | null;
  /** Best three scored tools on this prompt, descending. */
  top: Scored[];
  /** Number of tools with a scored run on this prompt. */
  scored: number;
}

export interface TerritoryRow {
  tool: string;
  held: number;
  contested: number;
  /** Category composite from ratings; null while unbenchmarked. */
  composite: number | null;
}

export type Side = 'a' | 'b' | 'contested' | null;

export interface FrontLineTile {
  prompt_id: string;
  holder: Side;
  a: number | null;
  b: number | null;
  /** a minus b when both scored, else null. */
  delta: number | null;
}

export interface FrontLine {
  tiles: FrontLineTile[];
  counts: { a: number; b: number; contested: number; unclaimed: number };
}

export interface Movement {
  prompt_id: string;
  from: string | null;
  to: string | null;
}

export type PreviousHolders = Record<string, string | null>;

/** composite per (tool, prompt) for one category, scored successful runs only. */
function scoredRuns(s: Snapshot, category: string): Map<string, Scored[]> {
  const byPrompt = new Map<string, Scored[]>();
  for (const r of s.runs) {
    if (r.category !== category || r.status !== 'success' || r.composite == null) continue;
    const list = byPrompt.get(r.prompt_id) ?? [];
    const existing = list.find((x) => x.tool === r.tool);
    if (existing) {
      // Several runs for the same (tool, prompt): keep the best one.
      existing.composite = Math.max(existing.composite, r.composite);
    } else {
      list.push({ tool: r.tool, composite: r.composite });
    }
    byPrompt.set(r.prompt_id, list);
  }
  for (const list of byPrompt.values()) list.sort((x, y) => y.composite - x.composite || x.tool.localeCompare(y.tool));
  return byPrompt;
}

function frontFor(promptId: string, scored: Scored[]): PromptFront {
  const top = scored.slice(0, 3);
  if (scored.length === 0) return { prompt_id: promptId, holder: null, contested: [], margin: null, top, scored: 0 };
  const best = scored[0].composite;
  const tied = scored.filter((x) => Math.abs(x.composite - best) <= TIE_EPSILON);
  if (tied.length > 1) {
    return { prompt_id: promptId, holder: null, contested: tied.map((x) => x.tool), margin: null, top, scored: scored.length };
  }
  const margin = scored.length > 1 ? best - scored[1].composite : null;
  return { prompt_id: promptId, holder: scored[0].tool, contested: [], margin, top, scored: scored.length };
}

/** Who holds each prompt in the category. Every prompt in the bank gets an entry. */
export function holders(s: Snapshot, category: string): Map<string, PromptFront> {
  const runs = scoredRuns(s, category);
  const out = new Map<string, PromptFront>();
  for (const p of promptsIn(s, category)) out.set(p.id, frontFor(p.id, runs.get(p.id) ?? []));
  return out;
}

/** Tools ranked by prompts held, then contested, then composite, then name. Includes tools holding nothing. */
export function territory(s: Snapshot, category: string): TerritoryRow[] {
  const fronts = holders(s, category);
  const ratings = new Map(ratingsIn(s, category).map((r) => [r.tool, r.composite]));
  const rows = toolsIn(s, category).map<TerritoryRow>((t) => ({
    tool: t.slug,
    held: 0,
    contested: 0,
    composite: ratings.get(t.slug) ?? null,
  }));
  const byTool = new Map(rows.map((r) => [r.tool, r]));
  for (const f of fronts.values()) {
    if (f.holder) { const row = byTool.get(f.holder); if (row) row.held++; }
    for (const t of f.contested) { const row = byTool.get(t); if (row) row.contested++; }
  }
  const names = new Map(toolsIn(s, category).map((t) => [t.slug, t.name]));
  return rows.sort(
    (x, y) => y.held - x.held || y.contested - x.contested || (y.composite ?? -1) - (x.composite ?? -1)
      || (names.get(x.tool) ?? x.tool).localeCompare(names.get(y.tool) ?? y.tool),
  );
}

/** The line between two tools: one tile per prompt, plus counts. */
export function frontLine(s: Snapshot, category: string, a: string, b: string): FrontLine {
  const runs = scoredRuns(s, category);
  const counts = { a: 0, b: 0, contested: 0, unclaimed: 0 };
  const tiles = promptsIn(s, category).map<FrontLineTile>((p) => {
    const list = runs.get(p.id) ?? [];
    const sa = list.find((x) => x.tool === a)?.composite ?? null;
    const sb = list.find((x) => x.tool === b)?.composite ?? null;
    let holder: Side = null;
    let delta: number | null = null;
    if (sa != null && sb != null) {
      delta = sa - sb;
      holder = Math.abs(delta) <= CONTESTED_BAND + TIE_EPSILON ? 'contested' : delta > 0 ? 'a' : 'b';
    } else if (sa != null) holder = 'a';
    else if (sb != null) holder = 'b';
    if (holder === null) counts.unclaimed++; else counts[holder]++;
    return { prompt_id: p.id, holder, a: sa, b: sb, delta };
  });
  return { tiles, counts };
}

/** Prompts whose holder changed since `previous`. Prompts absent from `previous` are skipped. */
export function movements(current: Map<string, PromptFront>, previous: PreviousHolders | undefined | null): Movement[] {
  if (!previous) return [];
  const out: Movement[] = [];
  for (const [id, f] of current) {
    if (!(id in previous)) continue;
    const from = previous[id] ?? null;
    if (from !== f.holder) out.push({ prompt_id: id, from, to: f.holder });
  }
  return out;
}

/** Stable colour slot per tool (1..12) from catalog order, so a tool keeps its colour on every page. */
export function colourSlots(s: Snapshot, category: string): Map<string, number> {
  return new Map(toolsIn(s, category).map((t, i) => [t.slug, (i % 12) + 1]));
}

export function fmtMargin(m: number | null): string {
  if (m == null) return '';
  return `+${m.toFixed(1)}`;
}
