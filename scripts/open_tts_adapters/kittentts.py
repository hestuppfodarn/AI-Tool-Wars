"""KittenTTS nano (KittenML, Apache-2.0): a ~15M-parameter ONNX model, ~25 MB.

Weights: Hugging Face repo `KittenML/kitten-tts-nano-0.1` (config.json names the
model and voices files, type "ONNX1"); downloaded with huggingface_hub into
HF_HOME. The official `kittentts` wheel lives on GitHub releases, not PyPI (the
PyPI name is an unrelated re-implementation), and drags in spaCy through
misaki[en] although it never uses it, so this adapter re-implements its 40-line
inference path directly: espeak-ng phonemes -> character ids -> ONNX session.
English only; other languages are phonemised with the en-us espeak voice, which
is what the official code does too.
"""
from __future__ import annotations

import json
import re

import numpy as np

from _common import hf_download, pick_voice, pkg_version, setup_espeak

SAMPLE_RATE = 24000
VOICES = ["expr-voice-2-m", "expr-voice-2-f", "expr-voice-3-m", "expr-voice-3-f",
          "expr-voice-4-m", "expr-voice-4-f", "expr-voice-5-m", "expr-voice-5-f"]

_session = None
_voices = None
_phonemizer = None
_symbols = None
_repo = None


def _symbol_table():
    pad = "$"
    punctuation = ';:,.!?¡¿—…"«»"" '
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    letters_ipa = ("ɑɐɒæɓʙβɔɕçɗɖðʤəɘɚɛɜɝɞɟʄɡɠɢʛɦɧħɥʜɨɪʝɭɬɫɮʟɱɯɰŋɳɲɴøɵɸθœɶʘɹɺɾɻʀʁɽʂʃʈʧʉʊʋⱱʌɣɤʍχʎʏʑʐʒʔʡʕʢ"
                   "ǀǁǂǃˈˌːˑʼʴʰʱʲʷˠˤ˞↓↑→↗↘'̩'ᵻ")
    symbols = [pad] + list(punctuation) + list(letters) + list(letters_ipa)
    return {s: i for i, s in enumerate(symbols)}


def load(cfg) -> None:
    global _session, _voices, _phonemizer, _symbols, _repo
    import onnxruntime as ort
    import phonemizer

    _repo = cfg.get("model_id", "KittenML/kitten-tts-nano-0.1")
    with open(hf_download(_repo, "config.json"), encoding="utf-8") as f:
        config = json.load(f)
    if config.get("type") != "ONNX1":
        raise RuntimeError(f"unsupported KittenTTS model type {config.get('type')!r}")
    model_path = hf_download(_repo, config["model_file"])
    voices_path = hf_download(_repo, config["voices"])
    setup_espeak()
    _phonemizer = phonemizer.backend.EspeakBackend(language="en-us", preserve_punctuation=True, with_stress=True)
    _voices = np.load(voices_path)
    _session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
    _symbols = _symbol_table()


def model_version(cfg) -> str:
    return f"{_repo} via onnxruntime {pkg_version('onnxruntime')}"


def synth(text, language, instructions, cfg):
    if _session is None:
        load(cfg)
    voice = pick_voice(language, cfg, "expr-voice-5-m")
    if voice not in _voices:
        raise ValueError(f"voice {voice!r} not in {list(_voices.keys())}")
    phonemes = _phonemizer.phonemize([text])[0]
    phonemes = " ".join(re.findall(r"\w+|[^\w\s]", phonemes))
    tokens = [0] + [_symbols[c] for c in phonemes if c in _symbols] + [0]
    if len(tokens) <= 2:
        raise RuntimeError("text phonemised to nothing")
    outputs = _session.run(None, {
        "input_ids": np.array([tokens], dtype=np.int64),
        "style": _voices[voice],
        "speed": np.array([float(cfg.get("speed", 1.0))], dtype=np.float32),
    })
    audio = np.asarray(outputs[0]).reshape(-1)
    # The official code drops 5000 leading and 10000 trailing samples of padding;
    # keep very short outputs intact instead of returning nothing.
    if len(audio) > 30000:
        audio = audio[5000:-10000]
    return audio, SAMPLE_RATE, {"voice": voice, "streaming": False}
