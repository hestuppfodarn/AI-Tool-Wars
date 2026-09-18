"""XTTS-v2 (coqui/XTTS-v2, Coqui Public Model License: non-commercial) via coqui-tts.

Weights (~1.9 GB: model.pth, vocab, speakers_xtts.pth) are fetched by the
coqui-tts model manager from huggingface.co/coqui/XTTS-v2 into TTS_HOME,
which the runner points at $OPEN_TTS_CACHE/coqui. COQUI_TOS_AGREED=1 skips
the interactive licence prompt; the licence itself still forbids commercial
use of the outputs.

Uses a built-in studio speaker (run.voice_by_language, e.g. "Ana Florence")
instead of a cloning clip. 17 languages; Swedish is not one of them, and the
model refuses unknown language codes, so run.unsupported_language decides
between recording an error (default) or falling back to English.
~470M parameters, roughly 10-30 s per prompt on a 4-core CPU. Japanese needs
cutlet + fugashi[unidic-lite]. Requires transformers<5 (0.27.x imports
`isin_mps_friendly`, removed in 5.x) and torchcodec with torch>=2.9.
"""
from __future__ import annotations

import os

from _common import lang_base, pick_voice, pkg_version, set_torch_threads, to_numpy

KNOWN_LANGUAGES = ["en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru", "nl", "cs", "ar", "zh-cn", "ja", "hu", "ko", "hi"]
LANG_ALIAS = {"zh": "zh-cn"}

_tts = None
_languages = None


def load(cfg) -> None:
    global _tts, _languages
    os.environ.setdefault("COQUI_TOS_AGREED", "1")
    from TTS.api import TTS

    set_torch_threads()
    _tts = TTS(model_name=cfg.get("model_id", "tts_models/multilingual/multi-dataset/xtts_v2"), progress_bar=False).to("cpu")
    try:
        _languages = list(_tts.synthesizer.tts_config.languages)
    except Exception:
        _languages = KNOWN_LANGUAGES


def model_version(cfg) -> str:
    return f"{cfg.get('model_id', 'xtts_v2')} via coqui-tts {pkg_version('coqui-tts')}"


def synth(text, language, instructions, cfg):
    import torch

    if _tts is None:
        load(cfg)
    lang = lang_base(language)
    lang = LANG_ALIAS.get(lang, lang)
    if lang not in _languages:
        if cfg.get("unsupported_language", "error") == "fallback":
            lang = cfg.get("fallback_language", "en")
        else:
            raise ValueError(f"XTTS-v2 does not support language '{lang}' (supported: {', '.join(_languages)})")
    voice = pick_voice(language, cfg, "Ana Florence")
    torch.manual_seed(int(cfg.get("seed", 0)))
    with torch.inference_mode():
        wav = _tts.tts(text=text, speaker=voice, language=lang, split_sentences=bool(cfg.get("split_sentences", True)))
    return to_numpy(wav), int(_tts.synthesizer.output_sample_rate), {"voice": voice, "streaming": False}
