# Launch plan: Reddit and X, six weeks

Companion: `docs/marketing/launch-plan-instagram-linkedin.md` (same calendar, two more
channels). Voice for every draft: the referee who enjoys the fight, `docs/marketing/brand.md`.

Launch Monday **28 September 2026**. Day 60 is **27 November 2026**, when
`scripts/verdict.mjs` decides. Every item below is executable by an agent on a schedule unless
marked **human**. Subreddit rules are quoted as known in September 2026; the agent re-reads the
sidebar and wiki of each subreddit the day before posting and the human-approved queue is the
fallback whenever a rule is unclear.

## Preconditions (prep week, 21 to 27 September)

| Item | Owner | Notes |
|---|---|---|
| Domain `toolwars.ai`, `SITE_URL`, mailbox `hello@toolwars.ai` | human | Roadmap Phase 1 open item. |
| First open-model run published (10 tools × 30 prompts, `benchmark-open.yml`) | agent | Nothing is posted until real audio is live. |
| Prompt pages, static cards, Front map image, claim callout | agent | The launch five from `docs/product/viral-mechanics.md`. |
| Ten `roast` prompts and the silly chips added to the bank | agent, **human** merges | Human check is for content policy only. |
| X account `@toolwars_ai` (or `@toolwars`), automated label on, linked to the owner's account | **human** creates, agent fills | See X setup. |
| X developer app, Free tier | **human** applies | Approval can take days; apply first. |
| Reddit account `toolwars-bot` with disclosure in bio | **human** creates | Will not be old enough to post in most subreddits until week 5; see account strategy. |
| Owner's own Reddit account, aged, some karma | **human** | Posts the week 1 and 2 Reddit threads via the queue. |
| Vendor outreach emails for the six pending tools | agent | `docs/outreach/vendor-claim-email.md`, adapted: the tool is pending, not live. |
| Search Console verified for `toolwars.ai` | **human** | Needed for the day-60 clicks number. |

## Account strategy

- **X:** one account, fully automated, labelled automated. This is normal on X and allowed by its
  automation rules as long as the label is on and the account does not spam mentions.
- **Reddit:** two accounts, both disclosed. The **owner's personal account** posts the launch
  threads in weeks 1 to 4 from the approval queue (Reddit communities respond to "I built this"
  from a person and most subreddits gate new accounts by age and karma). The **bot account**
  starts by replying inside those threads with data (links to prompt pages, reruns), gains its
  karma honestly, and takes over scheduled results posts in permissive subreddits from week 5.
  Never two accounts in the same thread pretending to be unrelated: the bot's bio names the
  owner's account and the owner's posts say the bot will answer data questions.

## Reddit

### Subreddits

| Subreddit | Why | Self-promotion rule as known | How the plan respects it |
|---|---|---|---|
| r/LocalLLaMA | The home of open-weight models; Kokoro, Chatterbox, F5 threads regularly top the sub. | Self-promotion tolerated when the content is substantive and open; low-effort product pitches removed; "Resources"/"Discussion" flair; AutoMod filters young accounts. | One results post in week 1 (open models only, full method, repo link), one every two weeks after. Never the arena as a "product"; always the data. |
| r/speechtech | Small, expert, benchmark-friendly. | Few rules; on-topic technical content welcome. | Methodology post week 2; ask for critique of WER and jury setup. |
| r/TextToSpeech, r/SpeechSynthesis | Niche TTS users. | Permissive; no spam. | Prompt-specific posts (whisper, numbers, Swedish). One per two weeks each. |
| r/artificial | Large general AI audience. | "Original projects" allowed with the Project flair; no repeated promo; engage in comments. | One post, week 2, the blind-test angle; bot answers data questions only. |
| r/ArtificialInteligence | Large, permissive, lower signal. | No low-effort self-promotion. | One post, week 3, the "company run by agents, stop rule on day 60" angle. |
| r/MachineLearning | Credibility. | `[P]` flair for projects with code; commercial pitches removed; mods strict. | One `[P]` post in week 5 once the multi-judge jury or naturalness backend exists; method and repo, no arena marketing. |
| r/AI_Agents, r/LLMDevs | Agent-run-company angle. | Build-in-public posts allowed; disclose affiliation. | One post each, weeks 3 and 4, about the automation loop (`docs/marketing/automation.md` is the content). |
| r/SideProject, r/indiehackers | Launch audience. | Self-promotion allowed, disclose you built it, engage. | Week 1 launch post; week 6 "what happened" retrospective. |
| r/startups | Founders. | No self-promotion outside the monthly "Share your startup" thread. | Comment in that thread only, month of launch. |
| r/InternetIsBeautiful | Free useful sites. | Own-site submissions need mod approval first; must be free, no signup. | **human** modmails in week 2; post only if approved. |
| r/webdev | Showoff Saturday thread. | Self-promotion only in that thread. | One comment, first Saturday of October. |
| r/sweden, r/Svenska | The Swedish prompt (`voice-008`); native ears. | r/sweden: no advertising ("ingen reklam"), posts in Swedish; r/Svenska: language topics, low tolerance for promo. | Week 4, framed as a question ("which one sounds Swedish?") with audio, no product pitch, **human**-posted in Swedish. If mods remove it, do not repost. |
| r/ElevenLabs, r/OpenAI, vendor subs | Only after that vendor claims or is run on our key. | Vendor communities; off-topic promo removed. | Not before a real run of that vendor exists. |
| r/VoiceActing | Hostile to synthetic voice. | Never. | Never. |

### Post formats that work there

1. **Results post.** "We ran N models on the same 30 prompts, here is who holds what." A table
   in the body, three audio links, the method in five lines, the repo, the caveats (no
   naturalness score yet, single judge model), and an ask ("which prompt should we add?").
2. **One-prompt post.** "Which open TTS model can actually whisper? We asked ten." One prompt,
   every output, the holder, the funniest failure. Short.
3. **Ask-for-prompts thread.** "What line breaks your TTS? We will add the top five to the
   public bank and run them weekly." Contributors come back to see their prompt scored.
4. **Method critique thread.** For r/speechtech and r/MachineLearning: what is wrong with
   scoring TTS by Whisper WER plus an LLM jury? Genuine question, then change the method.
5. **Retrospective.** Week 6: numbers, what worked, the stop rule and its date.

Never: link-only posts, the same body in two subreddits on the same day, titles with
"revolutionary", "game-changing" or the word "free" as bait.

### Disclosure wording for the bot account

Bio: "Automated account run by Tool Wars (toolwars.ai), a benchmark of AI voice tools.
Posts and replies are generated from published data. A person (u/{owner}) reads this inbox
on Mondays."

Footer on every post and reply by the bot:

> This account is automated. Numbers come from the public run at {snapshot_url}; the prompt
> bank and pipeline are on GitHub. Corrections: reply here or email hello@toolwars.ai.

Footer on the owner's posts:

> Disclosure: I registered the company; agents run the benchmark and write most of the posts.
> u/toolwars-bot will answer data questions in this thread; I answer everything else.

### What the agent may and may not do on Reddit

May:

- Post from the disclosed bot account in the subreddits marked permissive above, at most
  **one post per subreddit per 14 days** and **three subreddit posts per week** in total.
- Reply inside its own threads to direct questions, with data and links, at most **20 replies
  per day** and never twice in a row without a reply in between.
- Read its own posts' scores and comments through the API for the KPI file.
- Edit its own post to add a correction, marked "Edit:" with the date.

May not:

- Vote on anything, ever, from any account. Vote manipulation is a site-wide ban.
- Comment in other people's threads unless the thread mentions Tool Wars or a user tags the
  account.
- Send direct messages or chat requests.
- Run more than one bot account, or post from the owner's account without the owner's click.
- Post in any subreddit the plan lists as human-approved or prohibited.
- Argue. One factual reply per disagreement, then stop.
- Exceed the Reddit API rate limit (100 requests per minute per OAuth client on the free
  tier) or scrape.
- Post while the "plain mode" flag in the automation config is on.

Reddit's Data API terms allow free access for non-commercial use under 100 QPM; posting a
company's own content is borderline. **Human** decision in prep week: apply for the API as a
low-volume bot, or keep Reddit fully on the approval queue (a person clicks post) for the
whole six weeks. The plan works either way; the queue route only costs the human ten
minutes a week.

## X

### Account setup

- Handle `@toolwars_ai` (fallback `@toolwars`, `@toolwarsai`), name "Tool Wars", bio:
  "Blind battles between AI voice tools. Same prompt, two tools, you decide. Automated account;
  posts are generated from published benchmark data. A person reads replies on Mondays."
  Link: `toolwars.ai`. Avatar: the two-colour dot. Header: the latest Front map, replaced
  weekly by the agent.
- **Automated label on**: Settings → Your account → Account information → Automation, managed
  by the owner's account. X's automation rules require labelling and prohibit unsolicited
  automated mentions, bulk following and trend-jacking; the plan does none of those.
- Pinned post: the "How it works" thread (draft X1).
- Follow only: the ten open-model authors and orgs, the six pending vendors, and TTS
  researchers the agent finds in the model cards. No follow-back loops.

### Cadence

| Slot | Content | Time (UTC) | Automated? |
|---|---|---|---|
| Daily | One battle card (image + one line + link) | 15:00 | Yes |
| Monday | Weekly Front report thread with the map | 12:00, after the Sunday open run and Monday closed run | Yes |
| Tuesday | Prompt of the week poll (7-day poll, closes next Tuesday) | 12:00 | Yes |
| Thursday | Blooper or one-prompt post | 15:00 replaces the card | Yes |
| First Monday of the month | Pending vendors callout | 13:00 | Yes |
| Monday | Reply sweep: human reads mentions, drafts go to the queue, agent posts them | any | Human reads, agent posts |
| On event | A vendor posts about a release or benchmark | within 24 h | Queue: human approves the one reply |

Roughly 45 posts a month plus replies.

### Thread templates

**Weekly Front report** (Monday):

1. `Week {n} on the Front. {open_held}/30 prompts held by open models, {closed_held} by
   closed APIs ({pending_count} still pending). {movements_count} prompts changed hands.`
   + map image
2. `Moved: {prompt_title}: {from} → {to} (+{margin}).` (one post per movement, max 5)
3. `Contested: {list}. Within 0.3, rerun Sunday.`
4. `Biggest margin on the board: {tool} on "{prompt_title}" by +{margin}.`
5. `Funniest failure this week: {blooper_caption}` + audio link
6. `Full board, every output, every failure: {front_url}. Vendors not yet fighting can claim
   here: {claim_url}.`

**Daily battle card**: image + `"{prompt_text_short}" · {winner} over {loser} by {margin},
{ttfb_winner} ms to first byte · {prompt_url}` + one deadpan line from the template bank.

**Prompt of the week poll**: `Prompt of the week: "{prompt_text}". Listen to all ten, then
vote. Names hidden on the site until you do. {war_url}` with a four-option poll listing four
tools (rotated weekly; the poll is a signal, the site tally is the record).

### Reply strategy

- **Vendors (closed, pending).** One factual reply per vendor per month, only on their own
  posts about voice quality or benchmarks: "{Tool} is listed as pending on our public
  30-prompt bank; a key gets it in the ring: {claim_url}". Never on posts about people,
  funding, layoffs or incidents.
- **Open-model authors.** Tag them in the Monday thread when their model holds or takes
  territory. Thank them when they reply. Rerun on request, publicly.
- **Voice-AI accounts and reviewers.** Reply with the relevant prompt page when they compare
  tools. No "check out our site"; the link is the argument.
- **Critics.** One reply with the data and an offer to rerun. If the criticism is right, post
  the correction as a reply to the original post and update the site.
- **Never** reply to abuse, politics, or anything about a named person.

### X API cost and automation

X changes its pricing often; the human verifies at `developer.x.com` in prep week. As known:

| Tier | Price | Write | Read | Fits the plan? |
|---|---|---|---|---|
| Free | $0 | Post creation including media and polls, capped around 1,500 posts/month at the app level (the cap has moved before; check) | Effectively none (no mentions, no search) | Yes for posting: about 45 posts plus replies a month. |
| Basic | about $200/month | 3,000 posts/month per user | About 10,000 posts read/month; mentions and search | Only needed to detect mentions automatically. Not at launch. |
| Pro | about $5,000/month | high | 1M reads | No. |
| Pay-per-use | announced 2025; per-request pricing | | | Evaluate in week 6 if mention reading is the bottleneck. |

Decision: **Free tier.** Posting, media upload and polls are automated; mention reading is
done by the human once a week in the app (ten minutes), with replies drafted into the queue
for the agent to post. If mentions exceed what a weekly sweep can handle, that is a good
problem; move to Basic then.

### Fallback if the API is too expensive or the app is not approved

The agent writes the same posts and images into the queue file
(`docs/marketing/automation.md` describes the format). Once a week the human opens the queue,
approves in bulk, and schedules them with X's built-in "Schedule post" on the web (free, up to
a few weeks ahead) or a scheduler's free plan (Buffer or Typefully both cover one X account
at this volume). Cards are attached from the `cards/` folder the action publishes. The only
thing lost is same-day timing on reruns; the daily card still goes out on time because it was
scheduled a week ahead.

## Six-week calendar

Cards go daily from day 1 and the Monday thread runs every week; the table lists what is
added.

| Week | Dates | Reddit | X | Product | Vendor loop |
|---|---|---|---|---|---|
| 1 | 28 Sep–4 Oct | Mon: r/LocalLLaMA results post (R1, owner). Wed: r/SideProject launch (R4, owner). Sat: r/webdev Showoff comment. | Mon: pinned How-it-works (X1) + launch post (X8). Tue: first poll. Thu: whistle post (X6). | Launch five live. Vote store started. | Six outreach emails sent (agent), day 0. |
| 2 | 5–11 Oct | Tue: r/speechtech method critique (R6 short form, bot allowed if mods reply positively to modmail; else owner). Thu: r/artificial blind-test post (R3, owner). Human modmails r/InternetIsBeautiful. | Mon: Front report with first movements. Thu: blooper (X7). | Vote store live: challenge link shows the friend's vote; ear test after five votes. | Track opens/replies. |
| 3 | 12–18 Oct | Tue: r/LocalLLaMA one-prompt post (R2). Thu: r/AI_Agents "company run by agents" (R7). | Mon: report. Wed: pending callout (X5, first Monday slot moved to keep week 1 clean). | Prompt-of-the-week war page; bloopers reel. | Follow-up email at day 14 (agent). |
| 4 | 19–25 Oct | Tue: r/Svenska Swedish prompt (R5, owner, in Swedish). Thu: r/LLMDevs automation post. | Mon: report with language cup line. | Language cup pages; embeds (badge already exists). | Any vendor reply: agent triages, human on legal. |
| 5 | 26 Oct–1 Nov | Bot account is 30+ days old: takes over r/TextToSpeech and r/SpeechSynthesis posts. Wed: r/MachineLearning `[P]` (owner) if the jury is multi-model by then; else skip. Comment in r/startups monthly thread. | Mon: report. Thu: ear-test card post inviting shares. | Disagreement meter if votes > 2,000. | Second vendor callout month. |
| 6 | 2–8 Nov | Thu: r/SideProject retrospective with numbers and the stop date (owner). r/ArtificialInteligence agents-and-stop-rule post if not done in week 3. | Mon: report. Fri: six-week numbers thread, same figures as the retrospective. | Nominate-a-prompt if capacity. | KPI review; early-signal check (below). |

Weeks 7 to 8 (to day 60): the loop continues unchanged; nothing new is built unless a vendor
key arrives, in which case that vendor's first run is the week's story.

## Fifteen ready-to-post drafts

Voice: the referee who enjoys the fight (`docs/marketing/brand.md`). Placeholders in `{braces}`
are filled from the snapshot by the automation and validated against it; any draft with an
unfilled placeholder is not posted. Prompt text is real; numbers are not, yet. Ten more drafts
for Instagram and LinkedIn are in `docs/marketing/launch-plan-instagram-linkedin.md`.

### Reddit

**R1 · r/LocalLLaMA · results post · owner's account**

Title: We ran 10 open-weight TTS models (Kokoro, Piper, XTTS-v2, Bark, F5, Chatterbox, MeloTTS, Parler, SpeechT5, KittenTTS) on the same 30 prompts on GitHub CI. Every output is public. Here is who holds what, and who fell over.

Body:

> Same 30 prompts for every model: IVR menus, a phone number digit by digit, a London
> postcode, a bedtime story, a whisper, an angry customer, Swedish, Japanese, heteronyms ("I
> read it yesterday, I will read it tomorrow"), and a stage direction in brackets that is not
> supposed to be spoken. {n_spoke_brackets} of ten spoke the brackets.
>
> Scoring: Whisper transcript → word error rate → accuracy. An LLM judge checks the explicit
> constraints (digits as digits, pause here, tone shift there). TTFB and total time measured on
> the runner. Naturalness is blank until we wire a MOS predictor. Blank beats guessed.
>
> The board on {run_date}: {tool_1} holds {held_1} prompts. {tool_2} holds {held_2}. {tool_3}
> holds {held_3}. {contested_count} prompts are contested, within 0.3, and get a rematch
> Sunday.
>
> Verdicts we did not expect: {surprise_1}. {surprise_2}. {surprise_3}.
>
> Every prompt has its own page with all ten outputs, including the {bloopers_count} failures,
> which stay up: {front_url}. Prompt bank, runners and scorer: {repo_url}. Think a model was
> configured badly? Name the voice or the setting. We rerun it in public and post the result
> whichever way it goes.
>
> Six closed APIs (ElevenLabs, OpenAI, Google, Cartesia, Polly, Inworld) are on the board as
> pending. We have no keys. They have been told. Open models are fighting alone until they
> show up.
>
> What line breaks your TTS? Top five go into the bank next week and get scored forever.
>
> Disclosure: I registered the company; agents run the benchmark and write most of the posts.
> u/toolwars-bot answers data questions in this thread; I answer everything else.

**R2 · r/LocalLLaMA · one-prompt post · bot account (week 3) or owner**

Title: Which open TTS model can actually whisper? We asked ten. {n_whispered} could. Audio inside.

Body:

> The prompt: "Shh. The baby's finally asleep. Let's go downstairs and I'll make us some tea."
> Instruction: whispered or very soft delivery. Constraints: noticeably lower volume than the
> model's own baseline, every word intelligible.
>
> Verdict: {holder} holds it, +{margin} over {runner_up}. {n_whispered} of ten whispered.
> {n_shouted} read it at full volume to a sleeping baby. {n_failed} produced audio Whisper
> could not transcribe, which is one way to keep a secret.
>
> All ten clips, side by side, no names until you have listened: {prompt_url}. Check your
> ear against the jury in the arena: {arena_url}. The jury has no ears. You do. Settle it.
>
> This account is automated. Numbers come from the public run at {snapshot_url}; the prompt
> bank and pipeline are on GitHub. Corrections: reply here or email hello@toolwars.ai.

**R3 · r/artificial · Project flair · owner's account**

Title: Blind test: type a line, two AI voices say it, you pick the better one, then the names come out. Ten open models, public prompts, public scores, no hedging.

Body:

> It is a blind A/B for text-to-speech. You type a line, or take one of ours ("read my WiFi
> password like it's a state secret"), two anonymous models say it, you vote, then you see who
> they were, the Elo move, and what a jury of judge models thought.
>
> After five votes it tells you how often your ear agreed with the jury. Mine is {owner_ear}%.
> The jury cannot hear. One of us is wrong and I am not sure it is the jury.
>
> {arena_url}. No signup. Every prompt in the public bank has a page with every output, and
> failures stay published. Six paid APIs are listed as pending because they have not handed
> over a key. Their names are on the board anyway.
>
> Disclosure: I registered the company; agents run the benchmark and write most of the posts.

**R4 · r/SideProject · launch · owner's account**

Title: I registered a company and handed it to agents. They benchmark AI voice tools in public, name the vendors who have not shown up, and will shut the company on day 60 if nobody clicks.

Body:

> Tool Wars (toolwars.ai) compares AI tools on what they produce. First category: text to
> speech. Ten open-weight models run on GitHub CI against the same 30 prompts every week; every
> output is public; a fixed pipeline scores them; the best tool on each prompt holds it, and a
> map shows who took what from whom this week. You can also fight two of them blind with your
> own line.
>
> The company has no employees. I bought the domain and I approve anything legal. Agents run
> the benchmark, write the posts (this one is mine; the Monday reports are not), email the
> vendors, and on 27 November a job checks two numbers: did two vendors hand over an API key,
> and did anyone arrive from search. If either is zero, it stops. No pivot, no "learnings".
>
> What I want from you: prompts. What line makes TTS fall over? Numbers, names, accents, stage
> directions, your ex's name. Top five go into the public bank.
>
> Disclosure: agents run most of this; u/toolwars-bot answers data questions.

**R5 · r/Svenska (or r/sweden) · owner's account, in Swedish · week 4**

Titel: Vi lät tio AI-röster (öppna modeller) läsa samma svenska mening. {n_sv_ok} av tio lät svenska. Vilken?

Text:

> Meningen: "{voice_008_text}"
>
> Alla tio klipp, utan namn tills ni röstat: {language_url_sv}. Just nu håller {holder_sv} den
> svenska meningen med {margin_sv} poäng, men "håller" betyder att en jury av språkmodeller
> tycker det. Juryn har aldrig varit i Sverige. Ni har.
>
> Vad hör ni? Fel vokal, engelskt sje-ljud, fel betoning på "beräknas"? Skriv tidsstämpel.
> Den som har fel åker ur.
>
> Öppenhet: jag registrerade bolaget; agenter kör benchmarken. Inget säljs, inget kostar.

**R6 · r/speechtech (week 2) and r/MachineLearning `[P]` (week 5)**

Title: [P] Open TTS benchmark: 30 public prompts, Whisper WER for accuracy, LLM jury for constraint adherence, measured latency; 10 open-weight models rerun weekly on CI. Tell us what is wrong with it.

Body:

> Pipeline and data: {repo_url}. Snapshot: {snapshot_url}.
>
> Method. Accuracy: Whisper transcript vs prompt, WER → 1–10. Adherence: an LLM judge reads
> the transcript plus audio metadata against the prompt's explicit constraints (digits read as
> digits, pauses, language, bracketed directions not spoken). Speed: TTFB and total latency
> ranked across all runs. Naturalness: blank on purpose until UTMOS/NISQA is in the runner.
>
> Weaknesses we already know and would like torn apart: (1) WER rewards models Whisper likes;
> (2) one judge model today, five planned; (3) the judge reads, it does not hear; (4) CPU
> runners penalise GPU-first models; (5) voice selection per model is ours, not the author's.
>
> Which of these invalidates the ranking, and what replaces it? We change the pipeline in the
> open. Run history stays. Nobody gets a rerun in private.
>
> Disclosure: posted by the project's owner; the benchmark is run and mostly written by
> agents.

**R7 · r/AI_Agents · week 3 · owner's account**

Title: Our company has no humans in the loop. Agents run a public TTS benchmark, write the weekly reports, email vendors, and a scheduled job decides on day 60 whether to stop. Here is the loop, guardrails included.

Body:

> Weekly: Sunday CI runs ten open TTS models on 30 prompts; Monday it scores them; the
> exporter diffs who holds each prompt against last week; a render job draws the map; a
> drafting job fills fixed templates with the numbers and refuses to post any number that is
> not in the snapshot; posts go to X and Instagram automatically and to a queue a person
> approves for Reddit and LinkedIn.
>
> Guardrails that matter: no vote from any account, no DMs, no unsolicited replies, every
> account labelled automated, no invented numbers, one factual reply per disagreement, then
> silence. The full automation doc is public: {automation_doc_url}.
>
> Things that still need a person: buying domains, accepting API terms, anything a lawyer
> would want to see, and Swedish.
>
> Ask me anything about the loop; the bot answers anything about the data, and it is faster
> than me.

### X

**X1 · pinned "How it works" thread**

1. Tool Wars: same prompt, two tools, you decide. Blind battles between AI voice tools, scored
   in public, names named. Five posts.
2. Thirty public prompts. Phone numbers, postcodes, a whisper, a bedtime story, an angry
   customer, Swedish, Japanese, a stage direction in brackets that must not be spoken. Most
   models speak the brackets.
3. Every tool reads all thirty. Every output is published, including the failures. Nothing is
   paid, nothing is ranked by hand, nothing is deleted.
4. Scores: transcript accuracy (an ASR model listens), instruction following (a jury of
   models reads), speed (measured). Naturalness is blank until we can measure it. Blank beats
   guessed.
5. The Front: every prompt is territory held by the best tool on it. Monday reports show
   what moved. Ten open models are fighting; six closed APIs are pending until they claim:
   {claim_url}. This account is automated and does not mind saying so.

**X2 · weekly Front report** (template, see Thread templates)

Week {n} on the Front. {open_held}/30 prompts held by open-weight models, {closed_held} by
closed APIs, {pending_count} still pending. {movements_count} prompts changed hands.
{biggest_mover} took the most. {biggest_loser} lost the most. Map below, receipts in the
thread. {front_url}

**X3 · daily battle card** (template)

"{prompt_text_short}" · {winner} beat {loser} by +{margin} · {ttfb_winner} ms to first byte.
{deadpan_line} {prompt_url}

Deadpan line bank (rotated, all true by construction): "The jury has no ears." · "Both were
told not to read the brackets." · "Contested last week. Not any more." · "82 million
parameters. Behave." · "Rematch Sunday." · "Names hidden until you vote. Then not."

**X4 · prompt of the week poll**

Prompt of the week: "Take 500 mg of amoxicillin every 8 hours for 10 days." Ten models read a
dosage. {n_wrong_dose} got the dose wrong. Listen blind, then vote. The site tally is the
record; this poll is the trailer. {war_url}
Poll: {tool_a} / {tool_b} / {tool_c} / {tool_d}

**X5 · monthly pending callout**

Pending, day {days}: {pending_list}. Pending means we have no key. It does not mean you would
lose. It does mean ten open models have been reading your prompts without you for {weeks}
weeks. Claiming is free and takes a key: {claim_url}

**X6 · the whistle post (launch week)**

We asked ten AI voices to whistle "Smoke Weed Every Day" and then apologise to my mother.
{n_whistled} whistled. {n_apologised} apologised. {n_both} did both. {n_neither} did neither
and were confident about it. Audio, ranked, no names until you vote: {prompt_url}

**X7 · blooper post**

{tool} was asked to read a London postcode. It produced {duration} seconds of
{what_whisper_heard}. Score: {score}. Published, because everything is: {blooper_url}

**X8 · launch day**

Tool Wars is live. Ten open-weight text-to-speech models, thirty public prompts, every output
published, blind battles you can play with your own line. Six closed APIs are pending; their
names are on the board anyway. Same prompt. Two tools. You decide. {arena_url}

## KPIs

Floors are the "worry" line; targets are what a working launch looks like. The agent writes
the numbers into `data/metrics/marketing.json` weekly (Reddit via API, X via the human's
weekly analytics export until a read tier exists, Instagram via the Graph API insights
endpoints, LinkedIn via the Community Management API's organisation statistics, site via the
analytics the site uses). Instagram and LinkedIn cadence, formats and drafts are in
`docs/marketing/launch-plan-instagram-linkedin.md`.

| Metric | Week 2 floor / target | Week 4 floor / target | Week 6 floor / target |
|---|---|---|---|
| Site sessions (cumulative) | 500 / 2,000 | 2,000 / 6,000 | 4,000 / 12,000 |
| Battles played | 300 / 1,500 | 1,500 / 5,000 | 3,000 / 10,000 |
| Votes recorded | 150 / 800 | 800 / 3,000 | 2,000 / 6,000 |
| Challenge links opened by a second visitor | 20 / 100 | 100 / 500 | 300 / 1,200 |
| Card or link shares (referrals from X, Reddit, Discord, Slack) | 30 / 150 | 150 / 600 | 400 / 1,500 |
| Reddit: posts surviving 48 h with score > 10 | 1 / 2 | 3 / 5 | 5 / 8 |
| Reddit: one post over 100 upvotes | – / 0 | 0 / 1 | 1 / 2 |
| X followers | 50 / 200 | 200 / 600 | 400 / 1,200 |
| X: Monday thread impressions | 500 / 3,000 | 2,000 / 10,000 | 4,000 / 20,000 |
| Instagram followers | 30 / 150 | 150 / 500 | 300 / 1,200 |
| Instagram: Reel plays per week (median) | 200 / 1,000 | 500 / 3,000 | 1,000 / 8,000 |
| Instagram: saves + shares per week | 5 / 30 | 20 / 100 | 40 / 250 |
| LinkedIn Page followers | 20 / 100 | 100 / 300 | 200 / 600 |
| LinkedIn: post impressions per week | 300 / 1,500 | 1,000 / 5,000 | 2,000 / 10,000 |
| LinkedIn: vendor-side reactions or comments (people at the six pending vendors) | 0 / 1 | 1 / 3 | 2 / 6 |
| Search Console impressions (cumulative) | 100 / 500 | 500 / 3,000 | 2,000 / 10,000 |
| Search Console clicks (cumulative) | 1 / 10 | 10 / 60 | 40 / 200 |
| Inbound links from other domains (embeds, blogs) | 1 / 3 | 3 / 10 | 8 / 25 |
| Vendor replies (of 6) | 0 / 1 | 1 / 2 | 2 / 3 |
| Vendor keys received | 0 / 0 | 0 / 1 | 1 / 2 |
| Prompt nominations received | 5 / 30 | 30 / 100 | 60 / 200 |

## Stop rule

The decision is the day-60 job in `docs/roadmap.md`: on 27 November 2026 `scripts/verdict.mjs`
prints CONTINUE only if **at least two vendors have supplied an API key** and **the pages have
received any organic search clicks** (`data/metrics/clicks.json`). Marketing does not change
that test and adds no second test.

What marketing adds is an **early signal at week 6** so the last two weeks are spent on the
right lever:

- If vendor replies < 1 by week 6: the agent switches the monthly pending callout to
  fortnightly, adds the open-model authors' public endorsements (if any) to the vendor
  follow-up, and the human sends one personal email per vendor. Nothing else changes.
- If Search Console impressions < 500 by week 6: the agent stops adding social posts and
  spends the remaining engineering slots on prompt pages and embeds (the indexable units),
  because clicks come from pages, not threads.
- If both floors are missed at week 6, the loop still runs to day 60 unchanged; the verdict
  job decides, not a person and not this document.
