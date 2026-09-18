# Viral mechanics: what makes a battle worth sharing

Fifteen features, each specified against the snapshot the site already renders from
(`runs`, `ratings`, `pairs`, `previous_holders` → Front holders via `apps/site/src/lib/front.ts`).
Where a feature needs data the snapshot does not have yet, the gap is named. Ranked at the end.

Conventions: effort S = under a day, M = one to three days, L = a week or more, for one engineer
(human or agent). "Vote store" means a minimal table of arena votes
(`battle_id, prompt_hash, tool_a, tool_b, choice, jury_winner, visitor_id, created_at`);
it does not exist yet (`db/` has the schema, nothing is wired) and is the one prerequisite
several features share.

## The shape of a shareable battle

A battle spreads when it produces one of four things: a surprise ("the 82M model beat the paid
API"), a joke the viewer can pass on ("nobody can whistle"), a score about the viewer ("your ear
agrees with the jury 71% of the time"), or a challenge ("bet you can't tell which is which").
Every feature below is built to output at least one of those, in a form that fits in a single
image plus 280 characters.

## The features

### 1. Battle result cards (OG image + copy-to-clipboard text)

- **What the user sees.** After the reveal, a 1200×630 card: the prompt line in the serif face,
  two columns (cobalt A / terracotta B), tool names, who won by human vote, who won by jury,
  the four jury bars, TTFB, and the site URL. A "Copy for X" button puts a ready post on the
  clipboard. Every `X vs Y` page and every prompt page gets a static card too, so any link
  unfurls as a result, not a logo.
- **Why it spreads.** Cards are the unit of sharing on X, Discord, Slack, LinkedIn and Reddit
  thumbnails. A result card is an argument in one image; a logo is not.
- **Effort.** M (render pipeline: Satori or headless Chromium at build time; per-battle cards
  rendered on demand or on vote).
- **Data.** `runs` (scores, composite, ttft_ms, transcript), `pairs.verdict` for the static
  pair cards, `prompts.text`; battle cards additionally need the vote store.
- **Spec.** `GET /cards/{category}/{pair-slug}.png` and `/cards/battle/{battle_id}.png`
  rendered from a single `<Card>` component with a fixed 1200×630 layout; `og:image` on every
  pair, tool, prompt and battle page; "Copy for X" copies
  `“{prompt}” — {winner} beat {loser} ({human}/{jury}) {url}`.

### 2. Per-prompt mini leaderboards ("who whistles best")

- **What the user sees.** Every prompt in the bank has its own page: the prompt, the current
  holder, the top three with margins, every tool's audio in a row, and a one-line title in the
  prompt's own voice ("Who whistles best", "Who can read a phone number", "Who speaks Swedish").
  The silly prompts get a dedicated index page: "The Silly Front".
- **Why it spreads.** The whole leaderboard is a table; one prompt is a story. "Kokoro can't
  whisper but Bark can" is a sentence people repeat. Also the most linkable SEO unit
  ("best TTS for phone numbers").
- **Effort.** S. `holders()` already computes holder, margin and top three per prompt.
- **Data.** `runs` per prompt, Front `holders()`, `prompts` (title, tags, language).
- **Spec.** Route `/{category}/prompt/{prompt_id}/` rendering `PromptFront.top`, all runs for the
  prompt with audio players, holder badge, and a `share_title` field added to the prompt
  catalog (falls back to `title`); index `/{category}/prompts/silly/` filtered on tag `silly`.

### 3. Challenge a friend (link that loads the same prompt and pair)

- **What the user sees.** After voting, "Send this battle": a link
  `/arena?p={prompt_hash}&a={tool}&b={tool}&s={seed}`. The friend gets the same line, same two
  outputs, same blind order, votes, then sees "You picked A. {name} picked B. The jury says…".
- **Why it spreads.** Direct 1:1 sharing with a built-in disagreement is the strongest loop a
  blind test has; it is how Wordle spread. Each link is a personal challenge, not an ad.
- **Effort.** S for the link (stateless, everything is in the URL and the cached audio); M to
  show the friend's vote (needs the vote store).
- **Data.** Cached run audio for the two tools on that prompt (`runs.audio_url`, or the arena's
  own output cache); vote store for the "you vs them" line.
- **Spec.** Arena reads `p,a,b,s` from the query string, replays the pair in the seeded order,
  and after voting renders `/arena/result/{battle_id}` which compares the two votes and offers
  "Send it on" with a fresh seed.

### 4. The Front as a weekly map image

- **What the user sees.** A 30-tile grid (one per prompt, grouped by tag row: numbers, emotion,
  multilingual, silly…), each tile coloured by the holder's stable colour slot, contested tiles
  hatched, unclaimed tiles empty. Arrows on tiles that changed hands this week. Caption: "Week 3:
  Kokoro takes two IVR prompts from Piper; Bark loses the whisper".
- **Why it spreads.** A map that changes every week is a serial. People follow serials. It is
  also the only image on the internet that shows open vs closed TTS as territory.
- **Effort.** M (SVG render of the grid from `holders()` + `movements()`; the site already has
  the Front component, this is the static-image twin).
- **Data.** Front `holders()`, `movements()` from `previous_holders`, `colourSlots()`.
- **Spec.** Build step writes `/front/{category}/week-{iso-week}.png` and `latest.png` from the
  same data as the Front page; movement arrows from `movements()`; the exporter already emits
  `previous_holders`.

### 5. Prompt of the week war (public tally)

- **What the user sees.** One prompt is "the prompt of the week". A banner on the arena and a
  page `/war/{iso-week}/` with a live tally: votes per tool on that prompt, jury pick, and a
  countdown. Sunday night the winner is declared and gets a "Week N" badge on its tool page.
- **Why it spreads.** A week-long contest with a live scoreboard invites repeat visits and gives
  X and Reddit a fixed post every week ("Poll closes Sunday: who reads the medical dosage
  best?").
- **Effort.** M (vote store + one page + a weekly rollover job).
- **Data.** Vote store filtered by `prompt_hash` and week; `runs` for the jury pick; the
  catalog's prompt of the week (a `week_of` field or a `data/marketing/war.json` schedule).
- **Spec.** `war.json` lists `{iso_week, prompt_id}`; `/war/{week}/` aggregates votes where
  `prompt_hash` matches and `created_at` is in the week; rollover job writes the winner into a
  `war_history` list the tool page renders as badges.

### 6. Roast mode prompts

- **What the user sees.** A "Roast" chip group in the arena: prompts written to expose failure
  modes and be funny when they fail. "Read this phone number without turning it into a year",
  "Say 'unbelievable' like you mean it", "Whisper. Actually whisper.", "Pronounce Clerkenwell",
  "Read the bracketed stage direction out loud. Bonus points if you don't." Each roast prompt is
  also in the public bank so it gets a jury score and a holder.
- **Why it spreads.** Failure audio is funnier than success audio and the internet shares
  what is funny. The roast prompts are the natural Reddit clip bait.
- **Effort.** S (content plus a tag).
- **Data.** `prompts` with tag `roast`; `runs` for the audio; Front holder for the caption.
- **Spec.** Add ten prompts tagged `roast` to `data/catalog/voice/prompts.json` with
  `constraints` written as pass/fail checks the jury can score; arena chip group reads the tag.

### 7. Personal ear test score

- **What the user sees.** After five votes: "Your ear agrees with the jury 60% of the time, and
  with other humans 70%." A profile line, no login, stored under an anonymous visitor id. Shown
  on a card: "Golden ear: 84%" with a share button.
- **Why it spreads.** It is a score about the viewer. Scores about the viewer get shared
  (Spotify Wrapped, typing tests). It also quietly validates the jury.
- **Effort.** S once the vote store exists (one aggregate query and one card).
- **Data.** Vote store (`choice` vs `jury_winner` and vs majority human vote per pair).
- **Spec.** `GET /api/me/ear` returns `{votes, jury_agreement, human_agreement, percentile}`
  for the visitor cookie; rendered in the reveal panel after vote five and as
  `/cards/ear/{visitor_hash}.png`.

### 8. Streaks

- **What the user sees.** "3 in a row with the jury" and a daily streak ("Day 4"). A streak
  break is announced deadpan: "Streak over. The jury and you disagree about Bark."
- **Why it spreads.** Retention rather than spread; it feeds the ear test and the daily post.
  Low direct virality, cheap.
- **Effort.** S (localStorage first, vote store later).
- **Data.** Vote store or localStorage; `jury_winner` per battle.
- **Spec.** Streak counters in the reveal panel; daily streak keyed on UTC date; both included
  in the ear-test card.

### 9. Vendor "claim to fight" callout

- **What the user sees.** On every pending closed tool's page and card: "ElevenLabs has not
  entered the ring. Pending since {date}." with a button "Work there? Claim the listing"
  that links to the claim form. On the leaderboard a divider: "Fighting (10 open models)" and
  "Not yet fighting (6 closed APIs, pending)".
- **Why it spreads.** The honest "pending" state is a storyline: open models are being scored
  in public while the paid APIs have not shown up. That is quote-tweet material, and it is the
  direct lever on the day-60 vendor-key criterion in `docs/roadmap.md`.
- **Effort.** S (copy plus the existing pending state and claim CTA).
- **Data.** `tools.status === 'pending'`, days since catalog entry, `PUBLIC_CONTACT_EMAIL`.
- **Spec.** Pending tools render a `ClaimCallout` with `pending_since` (add to catalog) and
  the claim link; the leaderboard groups by `status`; the OG card for a pending tool reads
  "Pending. Claim to fight."

### 10. Embeds

- **What the user sees.** Two embeds: the existing badge (`/badge/{category}/{tool}.svg`)
  and a battle embed `<iframe src="/embed/battle?p=…&a=…&b=…">` that plays two anonymous
  clips and votes inline. Also a prompt-page embed showing the mini leaderboard.
- **Why it spreads.** Bloggers, newsletters and docs sites embed things that update
  themselves. Every embed is a backlink, which is the organic-click criterion.
- **Effort.** M (iframe route with postMessage vote, CSP, and a copy-snippet UI).
- **Data.** Same as the arena and prompt pages; vote store for embedded votes with an
  `origin` column.
- **Spec.** `/embed/battle` and `/embed/prompt/{id}` as chrome-less routes; votes from embeds
  record `origin`; snippet shown on every prompt page and in the reveal panel.

### 11. Open vs closed scoreboard

- **What the user sees.** One number at the top of the category page: "Open models hold 30 of
  30 prompts. Closed APIs hold 0 (pending)." Updated weekly; it becomes interesting the day the
  first closed key arrives.
- **Why it spreads.** It is the cleanest headline in the product and it writes itself every
  week.
- **Effort.** S.
- **Data.** Front `territory()` joined to `tools.open_weights`.
- **Spec.** `openVsClosed(snapshot, category)` returning `{open_held, closed_held, contested,
  unclaimed}`; rendered as a stat tile and included in the Front map caption.

### 12. Bloopers reel (published failures)

- **What the user sees.** `/bloopers/`: every run with `status: 'error'` or a WER above 0.5,
  with the audio, the transcript the ASR heard, and the prompt. Titles like "Bark was asked to
  read a postcode and produced eleven seconds of breathing".
- **Why it spreads.** The runner publishes failures anyway ("never hidden"); making them a
  page turns a policy into content. Failures are the most clipped audio in any TTS thread.
- **Effort.** S.
- **Data.** `runs` with `status`, `error`, `wer`, `transcript`, `audio_url`.
- **Spec.** Route listing runs where `status === 'error' || wer > 0.5`, newest first, with a
  copy-link button and OG card per blooper; caption generated from a fixed template, never
  from the LLM freehand.

### 13. Language cup

- **What the user sees.** A small bracket per non-English prompt (Swedish, Spanish, German,
  French, Japanese): who holds it, with a flag row on the Front map. "Sweden: held by Kokoro.
  Piper contested."
- **Why it spreads.** Native speakers are the best judges and the most motivated sharers
  ("finally someone tested Swedish"). It is the hook for r/sweden and language subreddits.
- **Effort.** S.
- **Data.** `prompts.language`, Front holders, runs with transcripts for the native-speaker
  "does this sound right" vote.
- **Spec.** `/{category}/language/{code}/` grouping prompts by `language`; the arena gets a
  language filter so a challenge link can be "the Swedish one".

### 14. Human vs jury disagreement meter

- **What the user sees.** Per tool: "Humans rate it higher than the jury by 0.8" or the
  reverse. A page "Where the jury is wrong" listing prompts with the largest gap.
- **Why it spreads.** It is the one place the product argues with itself in public, which
  reads as honesty and starts threads.
- **Effort.** S once the vote store exists.
- **Data.** Vote store aggregated to a human Elo per tool; `ratings.composite`.
- **Spec.** Nightly job computes Elo from votes into `data/metrics/elo.json`; the exporter
  attaches `human_elo` to `ratings`; a `gap` column and a `/disagreements/` page.

### 15. Nominate a prompt

- **What the user sees.** "Nominate a prompt for the bank" form; nominees are voted on
  weekly; the winner enters the public bank and gets the nominator's handle on the prompt page.
- **Why it spreads.** Contributors share what they contributed. It also feeds the roast and
  silly groups without an agent having to invent them.
- **Effort.** M (form, moderation queue, weekly promotion job with a human legal check on
  content).
- **Data.** New `nominations` table; catalog write on promotion.
- **Spec.** Form posts to `nominations`; an agent screens for policy (no real people, no
  slurs, under 400 chars); weekly poll on X picks one; promotion opens a PR that edits
  `prompts.json`, which a human merges.

## Ranking: expected virality per unit effort

| # | Feature | Virality | Effort | Needs vote store | Score |
|---|---|---|---|---|---|
| 2 | Per-prompt mini leaderboards | High | S | No | 1 |
| 3 | Challenge a friend | High | S (M with friend's vote) | Partly | 2 |
| 1 | Battle result cards | High | M | Partly | 3 |
| 4 | Weekly Front map | High | M | No | 4 |
| 9 | Vendor claim callout | Medium, but hits the kill criterion | S | No | 5 |
| 12 | Bloopers reel | High | S | No | 6 |
| 11 | Open vs closed scoreboard | Medium | S | No | 7 |
| 6 | Roast mode prompts | Medium | S | No | 8 |
| 5 | Prompt of the week war | Medium-high | M | Yes | 9 |
| 13 | Language cup | Medium | S | No | 10 |
| 7 | Ear test score | Medium-high | S after store | Yes | 11 |
| 10 | Embeds | Medium, long tail | M | Partly | 12 |
| 14 | Disagreement meter | Medium | S after store | Yes | 13 |
| 8 | Streaks | Low | S | No | 14 |
| 15 | Nominate a prompt | Medium | M + human | Yes | 15 |

Virality is a judgement; the ordering leans towards features that need no vote store because
the first six weeks run on the static snapshot and open-model runs, and towards features that
produce an image every week without a human.

## Launch five

1. **Per-prompt mini leaderboards** (2), including the silly index. Ship first; everything
   else links to these pages.
2. **Battle result cards** (1), static pair and prompt cards first, per-battle cards when
   the vote store lands.
3. **Challenge a friend** (3), stateless version.
4. **Weekly Front map** (4), with the open-vs-closed caption (11 rides along, it is a
   one-line function).
5. **Vendor claim callout** (9), because it is a day's work and it is the lever on the
   vendor-key half of the stop rule.

Bloopers (12) and roast prompts (6) are content, not engineering, and go in as soon as the
first open-model run is published. The vote store is the first engineering item after launch
week; it unlocks 5, 7, 8, 14 and the per-battle version of 1 and 3.
