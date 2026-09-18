# Open-weight TTS adapters

Adapters for `scripts/run-open-tts.py`, one file per catalog tool whose `adapter` is
`open:<slug>`. Each exposes `synth(text, language, instructions, cfg) -> (audio, sample_rate[, meta])`
and optionally `load(cfg)` (eager model load, once per worker process) and `model_version(cfg)`.
`_common.py` holds the shared helpers (cache dirs, voice lookup, downloads, espeak setup).

Every model has its own `requirements/open-tts/<slug>.txt`; install exactly one per virtualenv,
the pins conflict (transformers 4.27 / 4.46 / 4.57 / 5.2 / 5.17 and torch 2.6 / 2.14 across the set).
Weights are cached under `OPEN_TTS_CACHE` (default `~/.cache/open-tts`); the runner points
`HF_HOME`, `TTS_HOME`, `NLTK_DATA`, `TORCH_HOME` and `XDG_CACHE_HOME` inside it so one CI cache key
covers everything. `TTS_TIMEOUT_S` (default 300) caps each prompt; `TTS_LOAD_TIMEOUT_S` (default 1800)
caps download + load. Bracketed stage directions such as `[Now, sadly:]` are stripped before synthesis
for every model here (none of them understands them). Non-English prompts are always attempted; a
model that cannot do the language either produces accented nonsense (recorded as a success, scored by
the ASR step) or raises (recorded as an error). Both are legitimate findings.

Tested end to end in the authoring environment (Hugging Face blocked, GitHub + PyPI open): **kokoro**
and **piper**. The other eight were written against the libraries' source in site-packages and
import-checked where the dependency set could be installed; their first real run is CI.

## kokoro — Kokoro-82M (hexgrad, Apache-2.0)

Weights: `kokoro-v1.0.onnx` (310 MB, fp32) and `voices-v1.0.bin` (27 MB) from the GitHub release
`thewh1teagle/kokoro-onnx` tag `model-files-v1.0`, into `KOKORO_CACHE`. ONNX Runtime on CPU, ~2 s per
140-character prompt on 4 cores (about 4x real time), so the full bank is a couple of minutes.
Phonemisation is espeak-ng from the `espeakng-loader` wheel for all languages; voices exist for en-US,
en-GB, es, fr, hi, it, pt-BR, ja, zh. Swedish and German get espeak phonemes read by the English voice.
Japanese uses `misaki`'s pyopenjtalk G2P (kanji-aware) because espeak's `ja` voice spells kanji out;
`run.japanese_g2p: "espeak"` disables that. Quirk: the requirements list unidic-lite explicitly rather
than `misaki[ja]`, whose `unidic` dependency needs a separate 500 MB dictionary download and fails
otherwise with `no such file or directory: .../unidic/dicdir/mecabrc`.

## piper — Piper (Rhasspy / Michael Hansen, MIT; voices carry their own licences)

Voices are per-language VITS ONNX files (20-75 MB) from `huggingface.co/rhasspy/piper-voices`,
fetched with `piper.download_voices` into `PIPER_CACHE`. If that fails (or `PIPER_VOICE_SOURCE=github`),
the adapter falls back to the legacy 2023 tarballs on the GitHub release `rhasspy/piper` v0.0.2 (same
speakers, older 16 kHz exports; the mapping is `LEGACY` in the adapter). That fallback is what was
tested here: 20-200 ms per prompt, with a real time-to-first-audio because `synthesize()` yields a
chunk per sentence (`streaming: true`). The `piper-tts` 1.x wheel bundles espeak-ng. Voices for
en-US, en-GB, sv-SE, es-ES, de-DE, fr-FR are configured; there is no Japanese voice, so the ja prompt
is read by the English voice (espeak spells the characters, producing a long clip). The German voice
logs `Missing phoneme from id map` for a combining cedilla; harmless.

## kittentts — KittenTTS Nano 0.1 (KittenML, Apache-2.0)

15M-parameter ONNX model, ~25 MB, from the Hugging Face repo `KittenML/kitten-tts-nano-0.1`
(`config.json` names the model and `voices.npz`). The official wheel is only on GitHub releases (the
PyPI `kittentts` is an unrelated re-implementation) and imports `misaki[en]`, which drags in spaCy
without using it, so the adapter re-implements its 40-line inference path directly on onnxruntime +
phonemizer + espeakng-loader. English only, eight `expr-voice-*` presets, well under a second per
prompt. Quirk: the official code trims 5000 leading and 10000 trailing samples; the adapter keeps clips
shorter than 30000 samples untouched so "Okay." does not come back empty. Untested here (HF blocked).

## speecht5 — SpeechT5 TTS (Microsoft, MIT)

`microsoft/speecht5_tts` (~585 MB) + `microsoft/speecht5_hifigan` (~50 MB) through transformers 5.17,
plus one 512-d x-vector from the dataset `Matthijs/cmu-arctic-xvectors` (row 7306, the female "slt"
speaker; set `voice_by_language.default` to another row index or an `.npy` name from the repo).
~145M parameters, a few seconds per sentence on CPU. English only. Quirk: the character tokenizer has
no digits, so numbers vanish unless spelled out; `run.normalize_numbers` (default on) runs num2words
over amounts, percentages, ordinals and integers before synthesis. Loading the x-vector needs the
`datasets` package. Untested here.

## melotts — MeloTTS (MyShell.ai, MIT)

One model per language from `myshell-ai/MeloTTS-English|Spanish|French|Japanese|...` (~200 MB each)
plus the BERT encoders they use for prosody (bert-base-uncased and per-language BERTs, 400-700 MB
each), all through HF_HOME. Real-time or faster on CPU; the estimate is dominated by downloads and
model loads. Speakers: EN-US, EN-BR, EN_INDIA, EN-AU, EN-Default in the English model, one speaker in
each other model. Swedish and German have no model and fall back to English. Needs NLTK's POS tagger
(downloaded into `NLTK_DATA` on load) and MeCab + unidic-lite for Japanese. Landmines: not on PyPI
(installed from GitHub at a pinned commit); pins transformers==4.27.4, librosa==0.9.1, gruut 2.2.3 and
needs numpy<2, so it is the most isolated venv of the set. Resolution verified, import not.

## xtts-v2 — XTTS-v2 (Coqui, Coqui Public Model License: non-commercial)

~1.9 GB (`model.pth`, `vocab.json`, `speakers_xtts.pth`) fetched by the coqui-tts model manager from
`huggingface.co/coqui/XTTS-v2` into `TTS_HOME`. `COQUI_TOS_AGREED=1` skips the interactive licence
prompt; the CPML still forbids commercial use of the outputs, which the catalog flags. Built-in studio
speaker "Ana Florence" instead of a cloning clip. 17 languages (en, es, fr, de, it, pt, pl, tr, ru, nl,
cs, ar, zh-cn, ja, hu, ko, hi); Swedish is refused by the model, recorded as an error unless
`run.unsupported_language: "fallback"`. ~470M parameters, 10-30 s per prompt on 4 cores. Landmines
found here: coqui-tts 0.27.5 fails to import under transformers 5.x (`isin_mps_friendly` removed),
hence transformers 4.57.6; with torch>=2.9 the `TTS` package refuses to import without `torchcodec`
(which needs system ffmpeg); torch itself is an extra (`coqui-tts[cpu]`), not a base dependency;
Japanese needs `cutlet` + `fugashi[unidic-lite]`. Import verified with that pin set.

## parler-tts-mini — Parler-TTS Mini v1 (Hugging Face, Apache-2.0)

`parler-tts/parler-tts-mini-v1` (~3.5 GB with the DAC codec) through HF_HOME. Description-conditioned:
the prompt's `instructions` are appended to a named-speaker description (`run.voice_description`, Jon
by default), making it the only open model here that consumes the style instructions directly.
English only. 880M parameters generating 9 codebooks at 86 Hz autoregressively: 1-3 minutes per prompt
on a 4-core CPU, so budget an hour for the bank. Landmine: parler-tts 0.2.3 pins transformers==4.46.1;
resolution with torch 2.14 verified, import not.

## bark-small — Bark small (Suno, MIT)

`suno/bark-small` (~1.7 GB incl. EnCodec and speaker presets) through transformers' `BarkModel`.
Three autoregressive stages make it slow, 30-90 s per prompt on CPU, and each generation is capped at
about 13 s of audio; the adapter splits longer scripts at sentence boundaries into chunks of
`run.chunk_chars` characters and joins them with 0.2 s of silence. Speaker presets exist per language
(`v2/<lang>_speaker_N`); Swedish has none and uses the English preset. Output is sampled and seeded
from `run.seed`. Bark understands `[laughs]`-style tags, not free-form stage directions, so those are
stripped like everywhere else. Untested here.

## f5-tts — F5-TTS v1 Base (SWivid; code MIT, weights CC-BY-NC-4.0)

`SWivid/F5-TTS/F5TTS_v1_Base/model_1250000.safetensors` (~1.3 GB, via cached_path into
`$OPEN_TTS_CACHE/f5-tts`) plus the Vocos vocoder `charactr/vocos-mel-24khz` (HF_HOME). Voice cloning
from a reference clip; the adapter uses the clip shipped inside the package
(`infer/examples/basic/basic_ref_en.wav`) with its transcript in `run.ref_text`. Trained on English +
Chinese. 335M-parameter DiT with classifier-free guidance, cost proportional to `run.nfe_step` (16
here, upstream default 32): 30-90 s per prompt on 4 cores. Landmines: `f5-tts` declares gradio, wandb,
bitsandbytes, datasets, accelerate and torchcodec as hard dependencies, and `f5_tts.api` imports
wandb, accelerate and datasets at import time (verified: import fails without them), so they cannot be
skipped; torchaudio>=2.9 loads the reference clip through torchcodec, which needs ffmpeg. Import
verified with the full dependency set minus gradio.

## chatterbox — Chatterbox Multilingual (Resemble AI, MIT)

`ResembleAI/chatterbox` through HF_HOME: the multilingual variant (~3.5 GB: `t3_mtl23ls_v2.safetensors`,
`s3gen.pt`, `ve.pt`, `conds.pt`) by default, `run.variant: "english"` for the original. `conds.pt`
is a built-in reference voice, so no cloning clip is needed (a WAV path in `voice_by_language` clones
that speaker instead). 23 languages including Swedish, German, French, Spanish and Japanese; unknown
language ids are refused by the model and recorded as errors unless `run.unsupported_language:
"fallback"`. `run.exaggeration`, `cfg_weight` and `temperature` map to the model's controls; the free-text
instructions are not used. ~500M-parameter Llama backbone with CFG (two sequences per step) plus a
flow-matching decoder: 1-3 minutes per prompt on a 4-core CPU, the heaviest model in the set.
Landmines: chatterbox-tts 0.1.7 hard-pins torch==2.6.0, transformers==5.2.0, numpy<2 (Python <3.13)
and gradio==6.8.0; Python 3.11 or 3.12 only. Resolution verified by a pip dry run, import not.

## Candidates left out

OuteTTS 1.0 (llama.cpp GGUF backend; resolves, but `llama-cpp-python==0.3.9` builds from source on the
runner and the audio codec path is heavy), Dia-1.6B and Orpheus-3B (too large for a 4-core CPU inside
the time budget).
