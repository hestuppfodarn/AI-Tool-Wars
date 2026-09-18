# Marketing automation: the weekly loop with no human

How an agent runs the channels in `docs/marketing/launch-plan-reddit-x.md` and
`docs/marketing/launch-plan-instagram-linkedin.md` from the repository, on a schedule, with
guardrails that are code rather than intentions. Everything below is a spec; none of it is
built yet. It does not touch the benchmark pipeline; it consumes what the pipeline already
publishes.

## The loop

The benchmark already runs on a schedule: open models Sunday 06:41 UTC
(`benchmark-open.yml`), closed APIs Monday 05:17 UTC (`benchmark.yml`), each followed by the
site deploy (`site.yml`). Marketing hangs off the deploy.

| When (UTC) | Step | Produces |
|---|---|---|
| Sun 06:41 / Mon 05:17 | Benchmark runs, scores, exports `data/snapshot.json` with `previous_holders` | Snapshot |
| After each deploy | **Render**: cards, Front map, IG squares and reels, LinkedIn PDF | `cards/` published on the site |
| After render | **Facts**: deterministic fact sheet from the snapshot | `data/marketing/facts/{date}.json` |
| After facts | **Draft**: templates + fact sheet → posts; validate; write queue | `data/marketing/queue.json` (a commit or PR) |
| Mon 12:00 | **Publish auto lane**: X Front thread, IG map square, X poll (Tue) | Posts, `log.jsonl` |
| Daily 15:00 | **Publish auto lane**: daily card to X and IG Story | Posts |
| Tue/Thu 07:30 | **Publish auto lane**: LinkedIn document post / verdict | Posts |
| Any time | **Publish queued lane**: whatever a human approved since last run | Posts |
| Mon (human, 10 min) | Read X mentions and DMs, approve queue, note corrections | Approvals, reply drafts |
| Weekly | **Metrics**: pull channel numbers, write `data/metrics/marketing.json` | KPI file |
| Day 60 | `scripts/verdict.mjs` (unchanged) | The decision |

If the Sunday run failed or the snapshot is older than eight days, the Monday report is not
posted and an issue is opened. A stale report is worse than no report.

## Inputs

| Input | Source | Used for |
|---|---|---|
| `runs` | `data/snapshot.json` | Per-prompt scores, audio URLs, transcripts, TTFB, failures (bloopers) |
| `ratings` | snapshot | Ranks, composites, medians for scorecards |
| `pairs` | snapshot | Static pair cards and the `X vs Y` links |
| Front holders, territory, movements | `apps/site/src/lib/front.ts` applied to snapshot + `previous_holders` | The map, the Monday thread, the LinkedIn document |
| `tools.status`, `open_weights`, `pending_since` | catalog via snapshot | Pending callouts, open-vs-closed line |
| Vote aggregates | vote store (once it exists) | Prompt-of-the-week tally, ear-test cards, human-vs-jury lines |
| New battles | vote store, battles with `share=true` | Battle cards worth posting (highest disagreement between humans and jury) |
| Prompt of the week schedule | `data/marketing/war.json` | Which prompt the poll and carousel feature |
| Template banks | `data/marketing/templates/` | Post skeletons and the deadpan line bank |
| Config | `data/marketing/config.json` | `paused`, `plain_mode`, per-channel enable, rate limits |
| Mentions and comments | X (human export until a read tier), IG and LinkedIn comment APIs, Reddit API | Reply drafts |

## Outputs

| Output | Where | Notes |
|---|---|---|
| Card PNGs (1200×630), IG squares (1080×1080), Story/Reel MP4s (1080×1920), LinkedIn PDF | `apps/site/public/cards/{category}/…`, deployed with the site | Public URLs; Instagram fetches media by URL |
| Front map PNG per ISO week | `cards/front/{category}/{iso-week}.png` and `latest.png` | Also the X header and IG Monday square |
| Fact sheet | `data/marketing/facts/{date}.json` | Every number any post may contain |
| Post queue | `data/marketing/queue.json` | Drafts with lane, channel, status |
| Post log | `data/marketing/log.jsonl` | One line per published post with URL, channel, fact-sheet hash |
| Replies | queue entries with `in_reply_to` | Same validator as posts |
| Metrics | `data/metrics/marketing.json` | Weekly KPI numbers per channel |
| Issues | GitHub issues | Stale snapshot, token expiry, validator rejections, mention needing a human |

## The approval model: three lanes

**Auto**: posted by the action with no human. **Queue**: written to the queue and posted only
after a human marks it approved (a GitHub Environment with a required reviewer gates the
job, so approval is a click in the Actions tab or an edit to the queue file). **Never**: not
implemented; there is no code path.

| Action | X | Instagram | LinkedIn Page | Reddit |
|---|---|---|---|---|
| Weekly Front report / document | Auto | Auto | Auto | Queue |
| Daily battle card / Story | Auto | Auto | – | – |
| Prompt-of-the-week poll | Auto | – | Auto (fortnightly) | – |
| Blooper post | Auto | Auto | – | Queue |
| One-prompt "who whispers best" | Auto | Auto (reel) | Auto (buyer prompts only) | Queue |
| Monthly pending callout naming vendors | Auto (fixed wording) | Auto (fixed wording) | Auto (fixed wording, Page mentions only) | Never |
| Reply to a question on own post, data only | Auto | Auto | Auto | Auto from week 5 (bot account), Queue before |
| Reply that touches pricing, terms, legal, removal requests, or a named person | Queue | Queue | Queue | Queue |
| Comment on someone else's post | Queue | Never | Queue | Queue |
| New results post in a community | – | – | – | Queue |
| Owner's personal profile or account | Never (agent) | Never | Never (human click only) | Never (human click only) |
| Direct messages | Never | Never | Never | Never |
| Voting, liking, following campaigns, follow-back | Never | Never | Never | Never (voting is a site-wide ban) |
| Any post with a number not in the fact sheet | Never | Never | Never | Never |
| Any post while `paused` is true | Never | Never | Never | Never |

Human touchpoints, all optional except the first: approve the queue weekly (ten minutes);
re-authorise LinkedIn every 60 days (an issue reminds them); flip `plain_mode` or `paused`
when the world needs it; answer anything legal.

## Guardrails (implemented as `validate-posts.mjs`, run before every publish)

1. **Number provenance.** Every numeral, percentage, millisecond and margin in a post must
   appear in the fact sheet for that run, matched by value and unit. A post failing this is
   rejected, logged, and never retried with a different number.
2. **Placeholder check.** Any `{…}` left in the text rejects the post.
3. **Vocabulary.** A denylist from `docs/marketing/brand.md` (kill, destroy, annihilate,
   crush, bloodbath, casualties, massacre, weapons, bombs, invasion, enemy, troops, and the
   names of real conflicts) rejects the post. Exclamation marks: at most one, only inside a
   quoted prompt.
4. **People.** No @-mention of a personal account and no personal name outside the model
   author credit line in the Monday thread. Organisation mentions are allowed from an
   allowlist (the catalog's vendors and model authors).
5. **Disclosure.** Every Reddit post and every reply carries the automated footer; every IG
   caption carries "all voices are AI-generated"; bios are checked monthly against the
   canonical text.
6. **Dedupe.** The same body (after placeholder fill) is not posted to the same channel
   within 30 days; the same subreddit is not posted to within 14 days.
7. **Rate limits.** X: 3 posts/hour, 15/day. IG: 2 feed posts/day, 3 Stories/day. LinkedIn:
   1 post/day. Reddit: 3 subreddit posts/week, 20 replies/day, one reply per thread per
   hour. All far below the platforms' own caps.
8. **Freshness.** No report from a snapshot older than eight days; no card from a run that
   has `status: 'error'` unless it is explicitly a blooper post.
9. **Plain mode.** With `plain_mode: true` every template switches to its table-only
   variant: no map, no "front", "takes", "holds" vocabulary; numbers and links only.
10. **Corrections.** A correction is a reply to the original post with the fixed number and
    the word "Correction"; the original is not deleted. The queue entry type `correction`
    bypasses the 30-day dedupe but not the provenance check.
11. **Replies.** The agent replies only inside threads it started, only to comments that
    contain a question mark or a tag of the account, at most once per commenter per thread,
    and never to a comment that the moderation classifier flags as abuse or that names a
    person.
12. **Escalation.** Anything mentioning lawyers, takedowns, trademarks, defamation, pricing
    negotiations, partnerships or press becomes a GitHub issue labelled `human` and gets no
    automated reply.

## Drafting: templates first, model second

The drafting job is deliberately dull. It fills fixed templates from the fact sheet. An LLM
is used for two things only: choosing which facts are the story (ranking movements and
bloopers by how surprising they are, given the fact sheet) and writing the single deadpan
line, from a prompt that includes the brand rules and the fact sheet and forbids new
numbers. Output goes through the validator like everything else. If the model's line is
rejected, the post ships with a line from the template bank instead. The fact sheet is
produced by plain code from the snapshot; the model never sees the snapshot directly and
never computes a number.

Fact sheet shape (one per run):

```json
{
  "run_date": "2026-10-05",
  "iso_week": "2026-W41",
  "category": "voice",
  "territory": [{ "tool": "kokoro", "name": "Kokoro-82M", "held": 12, "contested": 2 }],
  "movements": [{ "prompt_id": "voice-003", "title": "Phone number digit by digit", "from": "piper", "to": "kokoro", "margin": 0.9 }],
  "open_held": 30, "closed_held": 0, "pending": ["elevenlabs", "openai-tts", "…"], "pending_days": 21,
  "prompt_fronts": [{ "prompt_id": "voice-016", "holder": "kokoro", "margin": 0.6, "top": [] }],
  "bloopers": [{ "tool": "bark-small", "prompt_id": "voice-004", "duration_s": 11, "transcript": "…", "score": 1.2, "url": "…" }],
  "fastest": { "tool": "piper", "ttft_ms": 140 },
  "counts": { "voice-016": { "whispered": 4, "shouted": 5, "failed": 1 } }
}
```

Per-prompt counts like `whispered` come from the jury's constraint verdicts in
`runs.scores` and `judge_rationale`; a count the pipeline cannot derive is simply absent, and
a template that needs it is skipped for that week.

## The queue file

`data/marketing/queue.json`, committed by the drafting job (as a PR when the run touches
Reddit or LinkedIn, as a direct commit otherwise), edited by the human to approve:

```json
{
  "version": 1,
  "items": [
    {
      "id": "2026-W41-x-front",
      "channel": "x",
      "lane": "auto",
      "status": "ready",
      "not_before": "2026-10-05T12:00:00Z",
      "thread": ["Week 2 on the Front. 30/30 prompts held by open-weight models…", "Moved: Phone number digit by digit: Piper → Kokoro (+0.9)."],
      "media": ["cards/front/voice/2026-W41.png"],
      "facts": "data/marketing/facts/2026-10-05.json",
      "validated": true
    },
    {
      "id": "2026-W41-reddit-localllama-whisper",
      "channel": "reddit",
      "subreddit": "LocalLLaMA",
      "lane": "queue",
      "status": "pending_approval",
      "title": "Which open TTS model can actually whisper? We asked ten. 4 could. Audio inside.",
      "body": "…",
      "account": "toolwars-bot",
      "approved_by": null
    }
  ]
}
```

`status` moves `draft → ready → posted | rejected | expired`; queue items expire after
14 days unposted so a stale draft is never published. Every posted item is appended to
`data/marketing/log.jsonl` with the platform URL and the fact-sheet hash, which is what makes
a later correction possible.

## Minimal tooling

Scripts (all under `scripts/marketing/`, Node, same conventions as the existing scripts):

| Script | Does |
|---|---|
| `facts.mjs` | Snapshot + `front.ts` rules → fact sheet JSON. Pure, tested against the demo snapshot. |
| `render-cards.mjs` | Fact sheet + snapshot → PNGs (Satori + resvg, or headless Chromium against `/cards/*` routes), MP4 reels (ffmpeg: waveform from the run audio, burned-in captions), LinkedIn PDF (the same card pages). |
| `draft-posts.mjs` | Templates + fact sheet (+ one constrained LLM call) → queue items. |
| `validate-posts.mjs` | The guardrails above; exits non-zero on any rejection. Also run in CI on every PR that touches `data/marketing/`. |
| `post.mjs --channel x|instagram|linkedin|reddit --lane auto|queue` | Publishes due items, writes the log, never retries a validator failure. |
| `metrics.mjs` | Pulls channel numbers into `data/metrics/marketing.json`. |
| `replies.mjs` | Reads comments on own posts (IG, LinkedIn, Reddit; X from a human-provided export), drafts replies into the queue with the right lane. |

Workflow `.github/workflows/marketing.yml`:

- `draft`: `workflow_run` on `site.yml` success → facts → render → draft → validate → commit
  queue and cards (cards are committed to `apps/site/public/cards/` and picked up by the next
  deploy, or uploaded to the Pages artifact directly).
- `publish-auto`: cron `0 12 * * 1` (Monday report), `0 15 * * *` (daily card),
  `30 7 * * 2,4` (LinkedIn), `0 12 * * 2` (poll); environment `social-auto` (no reviewers);
  runs `post.mjs --lane auto`.
- `publish-queued`: cron every 6 hours; environment `social-approved` with the owner as
  required reviewer; the job waits for the click; runs `post.mjs --lane queue`. Approving the
  deployment is the approval.
- `metrics`: cron Monday 09:00.
- `tokens`: cron daily; refreshes the Instagram long-lived token when under 10 days from
  expiry; opens an issue 10 days before the LinkedIn token expires.

Secrets (repository secrets, never in `.env` committed, rotated if pasted anywhere):
`X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET`; `IG_USER_ID`,
`IG_ACCESS_TOKEN`; `LINKEDIN_ORG_URN`, `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_REFRESH_TOKEN`;
`REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USERNAME`, `REDDIT_PASSWORD` (bot account
only; the owner's account is never in a secret); `OPENAI_API_KEY` (already present, for the
drafting call). Channel enable flags live in `config.json`, so a missing secret disables a
channel cleanly instead of failing the job.

Config `data/marketing/config.json`:

```json
{ "paused": false, "plain_mode": false, "channels": { "x": true, "instagram": true, "linkedin": true, "reddit": "queue" },
  "limits": { "x_per_day": 15, "ig_feed_per_day": 2, "linkedin_per_day": 1, "reddit_posts_per_week": 3, "reddit_replies_per_day": 20 } }
```

## Failure behaviour

| Failure | Agent does |
|---|---|
| Benchmark run failed or snapshot stale | Skips the report, posts nothing, opens an issue |
| Validator rejects a post | Logs it, ships the template fallback if one exists, otherwise skips; opens an issue if rejections exceed three in a week |
| Platform API error | Retries twice with backoff, then leaves the item `ready` for the next run; never double-posts (idempotency key = item id) |
| Token expired | Channel disabled, issue opened, other channels continue |
| A vendor or anyone asks for a rerun | Rerun is a benchmark workflow dispatch with the tool and prompt; the result is posted as a reply either way |
| A takedown, legal or press request | Issue labelled `human`, no reply, channel keeps running |
| The world has a bad week | Human sets `plain_mode` (tables only) or `paused` (nothing); the loop resumes when unset |
