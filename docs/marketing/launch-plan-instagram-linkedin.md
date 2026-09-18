# Launch plan: Instagram and LinkedIn

Companion to `docs/marketing/launch-plan-reddit-x.md`: same six weeks (28 September to
8 November 2026), same day-60 stop rule, same voice (the referee who enjoys the fight,
`docs/marketing/brand.md`). Instagram is the entertainment channel: the audio is the joke.
LinkedIn is the buyer channel: the audio is the invoice. Platform limits are as known in
September 2026; the human re-checks the developer pages in prep week.

## Instagram

### Why it works for an audio product

Instagram is video-first, but a Reel is really an audio track with a picture on it. A blind
"which one is A, which one is B" clip is a game people play with the sound on, which is the
only way to judge a voice. Every Reel is a battle; every carousel is a scorecard; the weekly
map is a square.

### Account

- `@toolwars.ai` (or `@toolwars_ai`), Business account, category "Media/News", linked to a
  Facebook Page only if the API route below requires it (the Instagram-login route does not).
- Bio: "AI voice tools, fighting blind. Same prompt, two tools, you decide. All voices in
  every clip are AI-generated. Automated account; a person reads DMs on Mondays."
  Link: `toolwars.ai/arena`.
- Highlights: "How it works", "The Front", "Bloopers", "Claim" (for vendors).
- **Every clip contains synthetic voice**, so every post carries Meta's AI label (set in the
  app if the API exposes no field) and the caption line "all voices are AI-generated".

### Formats

| Format | Spec | Content | Automated |
|---|---|---|---|
| **Guess reel** | 9:16, 15–30 s, MP4 H.264, burned-in captions, cover frame with the prompt | Two clips back to back with a cobalt and a terracotta waveform; "A or B?"; names and jury score revealed in the last 3 s; caption asks for the vote and links to the challenge URL. | Yes (rendered by the action from `runs.audio_url`) |
| **Blooper reel** | 9:16, 8–20 s | One failed run, the prompt on screen, the waveform, and the ASR transcript scrolling underneath ("Whisper heard: …"). | Yes |
| **Scorecard carousel** | 1:1 or 4:5, 4–10 slides, PNG | Slide 1 the prompt in serif; one slide per top-three tool with the four jury bars; last slide the holder and the link. | Yes |
| **Front map square** | 1:1 PNG | The weekly map with the movement arrows and the open-vs-closed count. | Yes |
| **Story** | 9:16 | The daily battle card with a link sticker to the prompt page. Poll stickers cannot be set through the API, so no Story polls unless a human posts them. | Yes (no interactive stickers) |
| **Collab post** | any | When an open-model author agrees to be a collaborator on the reel featuring their model. | Human asks; agent posts |

Production rules: sound on, always; captions burned in (most viewers start muted); no
music bed (it hides the voice and the music-library licence is app-only); the reveal never
comes before second 10; the prompt text is on screen from frame one.

### Cadence

| Day | Post | Time (UTC) |
|---|---|---|
| Monday | Front map square + Story | 12:30 |
| Wednesday | Guess reel (challenge link in bio and caption) | 16:00 |
| Friday | Blooper reel | 16:00 |
| Saturday | Scorecard carousel (prompt of the week) | 10:00 |
| Daily | Story: the day's battle card | 15:30 |

Four feed posts and seven Stories a week. Hashtags: five per post, fixed set plus the tool
names; no hashtag walls.

### What the Graph API can and cannot do (business account)

Can, through the Content Publishing API (Instagram API with Instagram Login, or the
Facebook-Login route):

- Publish single images, videos as Reels (with `share_to_feed`), carousels of 2–10 items, and
  Stories (image or video, no interactive stickers). Media must sit at a public URL the API
  can fetch; the action publishes it to the site's `cards/` path first.
- Set captions (up to 2,200 characters, 30 hashtags), a cover frame for Reels, user tags on
  images, a location.
- Read insights (`instagram_manage_insights`): reach, plays, saves, shares, follower count.
- Read and reply to comments on own posts (`instagram_manage_comments`).
- Refresh the long-lived token programmatically before its 60-day expiry, so no human step.

Cannot:

- Exceed about 100 API-published posts per 24 hours (the plan uses about ten a week).
- Add music from the Instagram library, filters, effects, interactive stickers, or Remixes.
- Publish to a personal (non-business, non-creator) account.
- Send DMs without the Messaging API and a separate review; the plan sends none.
- Go beyond test users without Meta App Review for the publishing and insights permissions.
  **Human**: submit the review in prep week with a screencast of the action; approval takes
  days to weeks, so the fallback below covers launch week.

Fallback: the action renders the reels, squares and captions into the queue; the human
posts them from the app or with Meta Business Suite's scheduler (free, supports Reels,
carousels and Stories) once a week. Meta Business Suite is the recommended path for the first
two weeks regardless, while App Review is pending.

### Reply and comment policy

Same as X: reply to direct questions on own posts with data and a link; one factual reply per
disagreement; never reply to abuse; never comment on other accounts' posts; no DMs. Comment
replies are drafted by the agent and auto-posted only if they contain no number that is not
in the snapshot and no name of a person.

## LinkedIn

### The angle

The buyer of TTS by the minute runs an IVR, an e-learning catalogue, a radio or podcast ad
pipeline, an audiobook operation, or an accessibility programme. That buyer does not care
who whistles best; they care whether the voice reads "0800 555 0199" as a phone number or
as a year, whether "500 mg every 8 hours" comes out right, and whether the Swedish notice
sounds Swedish. Half the prompt bank was written for exactly these people (`ivr`, `numbers`,
`long-form`, `multilingual`, `ad` tags). LinkedIn posts lead with the prompt that matches a
job, the verdict, and the number.

Second angle: the vendors' own staff are on LinkedIn. A callout on LinkedIn reaches the
product manager who can approve a key, which is half of the stop rule.

### Tone variant: the referee in a blazer

Same verdicts, names, numbers and deadpan; no slang, no swearing, no emoji, no hashtag
walls, full sentences. The joke is one dry sentence at the end. Confrontation is with tools
and with absent vendors as companies, never with a named person, and every callout includes
the free way out (claim the listing).

### Page vs personal profile

- **Company Page: `Tool Wars`.** All automated posting goes here. LinkedIn permits
  organisations to publish through its API; a Page is honest about being an organisation.
  Pages get less organic reach than people, which is the price of not faking a person.
- **Owner's personal profile.** LinkedIn's user agreement bans fake profiles and automated
  personal-profile activity. An agent-run "person" is out. The owner's own profile reposts or
  comments on one Page post a week, by their own click, from the approval queue; the posting
  API for members (`w_member_social`) is not used for the owner's profile, so nothing appears
  under a human's name without a human's hand.
- **Page admin.** A Page needs a real member as admin; that is the owner. A second admin
  (agent) is not possible and not attempted.
- Page "About": "Tool Wars publishes what AI tools actually produce on public prompts, scored
  the same way for every tool. Posts on this Page are generated from published benchmark
  data by automated systems. Replies are read by a person weekly. No paid placement."

### Formats

| Format | Content | Automated |
|---|---|---|
| **Text + one image** | Verdict on one buyer prompt (IVR, dosage, Swedish notice) with the card image. | Yes |
| **Document post (PDF carousel)** | Six to eight pages: the weekly scorecard, one page per movement, last page the pending list and claim link. LinkedIn's best-reaching Page format. | Yes (PDF rendered by the action) |
| **Poll** | "Which failure would cost you more: a phone number read as a year, or a dosage read wrong?" Four options, 7 days. | Yes |
| **Short video** | The Front map animating from last week to this week, 15 s, captions. | Yes |
| **Vendor callout** | Text post mentioning the six pending vendors' Pages (organisation mentions are supported; people are never mentioned). | Yes, once a month; wording fixed |
| **Owner repost** | The owner reposts one Page post a week with a line of their own. | Human |

### Cadence

| Day | Post | Time (UTC) |
|---|---|---|
| Tuesday | Weekly document post (scorecard + movements) | 07:30 |
| Thursday | Buyer-prompt verdict, text + image | 07:30 |
| Every second Thursday | Poll instead of the verdict | 07:30 |
| First Tuesday of the month | Vendor callout | 07:30 |

Two Page posts a week. LinkedIn rewards fewer, longer posts; three is the ceiling.

### API and automation limits

- Product: **Community Management API** (Page posting, comments, organisation statistics).
  Requires applying for access with a live app and a description; **human** applies in prep
  week; approval takes days to weeks. Permissions: `w_organization_social`,
  `r_organization_social`, `rw_organization_admin` (statistics).
- Posts API supports text, single image, multi-image, video, documents (PDF) and polls;
  organisation mentions by URN; no scheduling (the action posts at the cron time instead);
  no articles or newsletters via API.
- Comments: the Page can reply to comments on its own posts through the API; the plan
  drafts them and auto-posts under the same validator as Instagram.
- **Tokens expire after 60 days** and refresh tokens after 365; the refresh requires the
  human to re-authorise about every two months. The action opens a GitHub issue ten days
  before expiry. This is the one recurring human step LinkedIn forces.
- Rate limits are per app per day and far above two posts a week.
- Fallback: LinkedIn's native scheduler (Pages can schedule up to three months ahead); the
  human schedules the queue's two posts a week in one sitting.

### Reply strategy with vendors

- Callouts mention the vendor's Page, state "pending, day N", and give the claim link. Never
  a named employee.
- When a vendor employee comments, the agent replies with data and the claim link, once, and
  the reply is queued for the human if it touches pricing, terms, legal or a request to
  remove anything.
- When a vendor's Page posts a launch or a benchmark, one comment with the relevant prompt
  page, human-approved, within 24 hours.

## Five Instagram captions

**IG1 · guess reel (Wednesday)**

Two AI voices read the same phone number. One of them thinks 0800 is a year. A or B? Sound
on. Names at 0:14. Then go and vote blind on the same line, link in bio: toolwars.ai/arena.
All voices are AI-generated. This account is automated. It still has opinions.

**IG2 · Front map square (Monday)**

Week {n} on the Front. {open_held} of 30 prompts held by open-weight models, {closed_held}
by closed APIs, {pending_count} pending. {mover} took {took_count}. {loser} lost
{lost_count}. Every tile is a prompt; every prompt has a page with all the audio.
Link in bio. All voices are AI-generated.

**IG3 · whistle carousel (Saturday)**

We asked ten AI voices to whistle "Smoke Weed Every Day" and then apologise to my mother.
Swipe for the scorecard. {n_whistled} whistled. {n_apologised} apologised. {n_neither} did
neither and were confident about it. Holder: {holder}. All ten clips at the link in bio, no
names until you have listened. All voices are AI-generated.

**IG4 · blooper reel (Friday)**

{tool} was asked to read a London postcode. Whisper heard: "{what_whisper_heard}". Score
{score} out of 10. It stays published, because everything does. Link in bio for the other
{bloopers_count} failures. All voices are AI-generated. This account is automated; the
postcode is real.

**IG5 · pending callout (first Monday of the month)**

Pending, day {days}: ElevenLabs, OpenAI, Google Cloud, Cartesia, Amazon Polly, Inworld. It
means we have no key. It does not mean they would lose. It does mean ten open models have
been reading their prompts without them for {weeks} weeks. Claiming is free, link in bio.
All voices in our clips are AI-generated.

## Five LinkedIn posts

**L1 · launch (Page, Tuesday of week 1)**

Tool Wars is live. It compares AI text-to-speech tools on what they produce, not on what
their pricing page says.

The method: thirty public prompts, the same for every tool, including the ones your IVR,
e-learning catalogue or ad pipeline actually needs. A phone number read digit by digit. A
postcode. A dosage. A legal disclaimer at speed. A Swedish customer notice. A stage
direction in brackets that must not be spoken.

Every output is published, including failures. Transcript accuracy is measured by an
independent speech-recognition model, instruction following by a jury of models, speed on
the runner. Nothing is paid and nothing is ranked by hand.

Ten open-weight models are on the board today. Six closed APIs are listed as pending until
they supply a key, which is free. Their names are on the board anyway.

If you buy voice by the minute, the only score that matters is the one on your prompt. Send
us the prompt. toolwars.ai

This Page is run by automated systems from published data; a person reads replies weekly.

**L2 · vendor callout (Page, first Tuesday)**

{Vendor Page mentions: ElevenLabs, OpenAI, Google Cloud, Cartesia, Amazon Web Services,
Inworld AI}: your text-to-speech products are listed on Tool Wars as pending, day {days}.

Pending means we have no API key for you. It does not mean you would lose. It means ten
open-weight models have been reading the same thirty public prompts for {weeks} weeks and
your customers can hear them and cannot hear you.

Claiming a listing is free: an API key, validated on one prompt, and every future run
executes on your account. You choose the voice per language. You get a verified mark, an
embeddable badge with your live rank, and a public rerun of any prompt you think we got
wrong. What you do not get is a better rank than the audio earns.

Claim here: {claim_url}. The referee is automated and patient.

**L3 · buyer-prompt verdict, IVR (Page, Thursday)**

We asked ten text-to-speech models to read a support line: "You can reach our support team
at 0800 555 0199, that's 0800 555 0199, Monday to Friday, nine to five."

{n_digit_ok} of ten read the number digit by digit both times, as instructed. {n_year} read
"0800" as a year. {n_dropped} dropped the second repetition, which is the one your caller
was writing down.

Verdict: {holder} holds the prompt at {score} out of 10, +{margin} over {runner_up}. Fastest
to first byte: {fastest} at {ttfb} ms.

If your IVR reads a phone number as a year, your caller hangs up and your vendor's pricing
page still says "natural-sounding". All ten recordings, with transcripts: {prompt_url}.

**L4 · weekly document post (Page, Tuesday)**

Week {n} on the Front: {movements_count} of thirty prompts changed hands.

Page 1: the map. Pages 2 to {k}: each movement, with the two scores and the margin. Last
page: the six pending vendors and the claim link.

Biggest move: {mover} took "{prompt_title}" from {previous_holder} by +{margin}.
Contested and going to a rematch on Sunday: {contested_list}.

Open-weight models hold {open_held} of 30. Closed APIs hold {closed_held}. The gap is not a
quality verdict; it is an attendance record.

Full board with every recording: {front_url}.

**L5 · e-learning and long-form (Page, Thursday)**

Narration buyers: the long-form explainer prompt is 140 words on how interest compounds,
with three numbers and one comparison, and the instruction to keep an even pace.

Results across ten models: {n_full} read every word. {n_skipped} skipped or invented a
clause, which a learner would not notice and an auditor would. {n_ok_numbers} read all three
numbers correctly. Median generation time {median_latency} s.

Verdict: {holder}, {score} out of 10, +{margin} over {runner_up}. The runner-up was faster
by {ttfb_delta} ms and dropped a number, which is a trade nobody in compliance will take.

Every recording and every transcript: {prompt_url}. If your script breaks these models in a
different place, send it; it goes into the public bank and gets scored every week from then
on.
