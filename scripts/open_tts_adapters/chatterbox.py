"""Chatterbox (ResembleAI/chatterbox, MIT) via the chatterbox-tts package.

Weights from Hugging Face repo ResembleAI/chatterbox through HF_HOME:
multilingual variant (default) ~3.5 GB (t3_mtl23ls_v2.safetensors, s3gen.pt,
ve.pt, conds.pt), English variant ~2 GB. `conds.pt` is a built-in reference
voice, so no cloning clip is needed (run.voice_by_language "builtin"; a path
to a WAV clones that speaker instead). run.exaggeration / cfg_weight /
temperature map to the model's controls; the prompt's free-text
instructions are not consumed.

23 languages including Swedish, German, French, Spanish and Japanese; the
model validates the language id, so run.unsupported_language decides
between an error record (default) and an English fallback. ~500M-parameter
Llama backbone with CFG (two sequences per step) plus a flow-matching
decoder: 1-3 minutes per prompt on a 4-core CPU, the heaviest model here.
Landmines: hard pins torch==2.6.0, transformers==5.2.0, numpy<2 (Python
<3.13) and even gradio==6.8.0; Python 3.11 or 3.12 only.
"""
from __future__ import annotations

from _common import lang_base, pick_voice, pkg_version, set_torch_threads, to_numpy

_model = None
_variant = None
_supported = None


def load(cfg) -> None:
    global _model, _variant, _supported
    set_torch_threads()
    _variant = cfg.get("variant", "multilingual")
    if _variant == "multilingual":
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        _model = ChatterboxMultilingualTTS.from_pretrained(device="cpu")
        _supported = sorted(_model.get_supported_languages().keys())
    else:
        from chatterbox.tts import ChatterboxTTS

        _model = ChatterboxTTS.from_pretrained(device="cpu")
        _supported = ["en"]


def model_version(cfg) -> str:
    return f"ResembleAI/chatterbox ({_variant}) via chatterbox-tts {pkg_version('chatterbox-tts')}"


def synth(text, language, instructions, cfg):
    import torch

    if _model is None:
        load(cfg)
    lang = lang_base(language)
    if _variant == "multilingual" and lang not in _supported:
        if cfg.get("unsupported_language", "error") == "fallback":
            lang = cfg.get("fallback_language", "en")
        else:
            raise ValueError(f"Chatterbox multilingual does not support '{lang}' (supported: {', '.join(_supported)})")
    voice = pick_voice(language, cfg, "builtin")
    prompt_path = None if voice == "builtin" else voice
    kwargs = dict(
        audio_prompt_path=prompt_path,
        exaggeration=float(cfg.get("exaggeration", 0.5)),
        cfg_weight=float(cfg.get("cfg_weight", 0.5)),
        temperature=float(cfg.get("temperature", 0.8)),
    )
    torch.manual_seed(int(cfg.get("seed", 0)))
    with torch.inference_mode():
        if _variant == "multilingual":
            wav = _model.generate(text, language_id=lang, **kwargs)
        else:
            wav = _model.generate(text, **kwargs)
    return to_numpy(wav), int(_model.sr), {"voice": voice, "streaming": False}
