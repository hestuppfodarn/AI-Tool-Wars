# Brand platform

Working name: **Tool Wars** (`toolwars.ai`, see Naming). First campaign: **Voice Wars**.

## Positioning

For people choosing an AI tool where the output is the product (voice, transcription, image,
video, translation), Tool Wars is the comparison site that publishes what every tool actually
produced on the same public prompts, scored the same way, and lets you judge blind. Unlike
directories and review sites, nothing is paid, nothing is ranked by hand, and every score has
the audio next to it.

**One-sentence promise.** You will hear the difference before you know the name.

**Proof points the brand can always lean on.**

- The same 30 public prompts for every tool; the bank is in the repo.
- Every output published, including failures.
- Scores computed by a fixed pipeline (ASR word error rate, a jury of models, measured
  latency), never typed in.
- Votes are blind; names are revealed after you choose.
- Vendors can claim a listing with a key; they cannot buy a rank.
- The company is run by automated agents and says so.

## Naming

| Option | For | Against |
|---|---|---|
| **toolwars.ai** | Reads as a series ("console wars", "format wars"), plural matches a league with many fronts, easy to say, category-agnostic, works as "Voice Wars", "Image Wars" sub-fronts. | Descriptive, so weak as a trademark; "tool" also means hardware, so search results are noisy for a while. |
| toolwar.ai | Shorter. | Singular sounds like a typo of the plural; "tool war" is harder to say aloud; loses the series feel. |
| saasarena.ai | Says "business software". | Wrong frame: the fighters are TTS models and APIs, ten of them open weights, not SaaS; "arena" is taken in this space (LMArena) and invites "you copied Chatbot Arena"; sounds like a G2 clone, which is exactly what the product is not. |

**Recommendation: toolwars.ai.** Register `toolwar.ai` as a redirect if it is cheap; skip
`saasarena.ai`. The X handle, Reddit account and GitHub org should all be `toolwars` or
`toolwars_ai`; check availability before buying the domain and pick the spelling all three can
share. Use "Tool Wars" (two words, capitalised) in prose, `toolwars.ai` in URLs.

Category fronts are named by output: **Voice Wars**, later Transcription Wars, Image Wars.
The Front, the map, the movements and the jury are product nouns and keep their names across
categories.

## Tagline

Ten options:

1. Same prompt. Two tools. You decide.
2. Hear the difference before you know the name.
3. AI tools, judged by what they make.
4. No feature tables. Outputs.
5. Pick the winner. Then find out who it was.
6. Every tool, every prompt, every output, public.
7. The comparison you can hear.
8. Blind battles for AI tools.
9. Proof, not press releases.
10. Where every prompt is territory.

**Pick: "Same prompt. Two tools. You decide."** It describes the mechanic, it is true for every
future category, and it works as the hero line above the arena composer. Line 2 is the voice
campaign's sub-line.

## Tone of voice

Register: a dry sports desk reporting a league nobody expected to care about. Precise numbers,
short sentences, deadpan, never shouting. The jokes come from the prompts and the results, not
from adjectives. The machine is allowed to be a machine: it says "this account is automated"
in the same voice it says "Kokoro holds 12 prompts".

Rules:

- Numbers before adjectives. "Piper answered in 140 ms" beats "Piper is blazing fast".
- Results are about outputs, never about people. A model fails a prompt; a company does not
  "embarrass itself".
- One joke per post, placed at the end, and it must be true.
- Say "pending" plainly. Never imply a pending tool is bad.
- No exclamation marks in system copy. At most one in a post, and only in a quoted prompt.
- British or American spelling is fine; be consistent within a page (the codebase leans
  British in the prompt bank).
- Swedish, when used, is used properly or not at all.

**Ten example lines**

1. Kokoro-82M holds the whisper prompt. It is 82 million parameters and it can keep a secret.
2. Week 3 on the Front: two prompts changed hands, both over phone numbers.
3. Six closed APIs are still listed as pending. The ring is open.
4. Your ear agreed with the jury 64% of the time. The jury is five models and none of them
   have ears.
5. Nobody can whistle. We have the audio.
6. Same 30 prompts, ten open models, every output published, including the eleven seconds of
   breathing.
7. Bark took the sports commentary and lost the medical dosage. Priorities.
8. Contested: Piper and MeloTTS within 0.3 on the IVR menu. Rerun next Sunday.
9. This account is run by a script. A person reads the replies on Mondays.
10. If a score looks wrong, name the prompt and we rerun it in public.

**Ten anti-examples** (and why)

1. "🚀 HUGE update: our AI-powered leaderboard is LIVE!!!" (hype, emoji, exclamation marks,
   "AI-powered")
2. "ElevenLabs is scared to enter the arena." (about a company's motive; we do not know it)
3. "The best TTS on the market, hands down." (superlative without a number)
4. "Users are loving Tool Wars!" (invented testimonial)
5. "Kokoro absolutely destroys Piper." (violence vocabulary; also, the margin was 0.4)
6. "We estimate ElevenLabs would score around 8.5." (an invented score; pending means pending)
7. "As a fellow indie hacker, I just stumbled on this cool site…" (an agent pretending to be a
   bystander)
8. "Game-changing, next-gen voice synthesis benchmarking platform." (buzzwords, no content)
9. "Drop a like if you agree!" (engagement bait)
10. "Sorry for the delay, I was on holiday." (a machine pretending to have a life)

## Visual direction

The current site is the base: warm off-white ground, cobalt for side A, terracotta for side B,
a serif display face for headlines, a plain sans for everything else. Keep it and extend it.

- **Palette.** Off-white paper (`#f7f6f3`), ink (`#1b1a17`), cobalt A (`#1d4ed8`), terracotta B
  (`#c2410c`). Green and amber only for status. Twelve stable tool colours from the Front's
  `colourSlots()` so a tool keeps its colour on every page and every map. Dark mode is the same
  hues on charcoal, already defined in the arena page.
- **Type.** Serif display for prompts, headlines and the war report captions (the prompt is
  the hero, so it gets the serif). Tabular numerals everywhere a number appears.
- **The map.** A grid of thirty tiles, flat colour fills, thin ink borders, hatched fill for
  contested, empty tile for unclaimed. Think a Risk board drawn by a newspaper graphics desk,
  not a videogame. No 3D, no glow, no flags with weapons.
- **Cards.** 1200×630, paper background, prompt in serif at the top, two columns in A/B
  colours, the four jury bars, the site wordmark bottom-left, the week or battle id
  bottom-right. Cards for pending tools use a dotted outline and the word "pending".
- **Waveforms.** The arena's bar waveform is the motion signature; use the two-colour version
  in the wordmark's dot and as the loading state everywhere.
- **Photography.** None. Audio has no face; do not give it a stock one.
- **Mascots and characters.** None. The tools are the characters.

## How "war" stays fun

The frame is a league table drawn as a map, not a conflict. Vocabulary is the control.

Allowed nouns and verbs: front, territory, prompt, tile, holds, takes, loses, contested,
unclaimed, movement, advance, retreat, rematch, challenger, fighter, ring, round, week,
jury, verdict, pending, claim.

Never used: kill, destroy, annihilate, crush, bloodbath, casualties, massacre, weapons,
bombs, invasion, enemy, troops, or references to any real war, army or nation's conflict.
(In public copy the roadmap's "kill criterion" is "the stop rule".)

Further rules:

- Fighters are tools. People, companies and their staff are never fighters and never
  losers.
- Losing is described by the number ("lost by 0.4") and by the prompt, never by
  character ("pathetic", "embarrassing").
- The map has no flags, borders of real countries, or military icons. Language prompts
  get a language code, not a flag.
- If a real-world event makes war imagery read badly that week, the weekly report can run
  as a plain table. The automation doc gives the agent a "plain mode" switch; a human flips it.

## Transparency rules

These are non-negotiable and appear in the site footer, the methodology page and every
account bio.

1. **Automated accounts say so.** Every social account bio: "Automated account run by Tool
   Wars. Posts are generated from published benchmark data. A person reads replies weekly."
   The X automated-account label is switched on. Reddit posts carry a one-line footer.
2. **No fake humans.** No invented testimonials, no "users say", no sock-puppet accounts, no
   agent posing as an independent fan, no fabricated quotes from vendors.
3. **No invented scores.** A number appears in copy only if it exists in the snapshot for that
   run. Pending is pending. Estimates are never published, including "roughly" or "around".
4. **Failures are published.** Errors and low scores stay on the site and in the bloopers
   reel. A vendor may ask for a rerun in public; nothing is deleted.
5. **No paid placement, ever.** Claiming a listing changes who pays for the run, not the
   rank. This sentence is on the claim form.
6. **Corrections are public.** A wrong post is replied to with the correction, not deleted.
7. **The jury is models.** Every jury mention says so. The human Elo and the jury score are
   always labelled separately.
8. **Prompts are public.** Anyone can run the bank themselves; the catalog is in the repo.
