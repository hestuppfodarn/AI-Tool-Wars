"""Parler-TTS Mini v1 (parler-tts/parler-tts-mini-v1, Apache-2.0).

Weights from Hugging Face (~3.5 GB for the 880M-parameter model plus the DAC
codec), through HF_HOME. The model is conditioned on a free-text description
of the speaker and delivery, so this is the one open model here that gets the
prompt's `instructions` verbatim (run.use_instructions), appended to a named
speaker description (run.voice_description with {voice} = Jon, Lea, Gary,
Jenna, Mike, Laura ...). English only; autoregressive over 9 codebooks at
86 Hz, so on a 4-core CPU expect one to three minutes per prompt.
Requires transformers==4.46.1 (hard pin in the parler-tts package).
"""
from __future__ import annotations

from _common import pick_voice, pkg_version, set_torch_threads, to_numpy

_model = _tok = _desc_tok = None
_model_id = None


def load(cfg) -> None:
    global _model, _tok, _desc_tok, _model_id
    from parler_tts import ParlerTTSForConditionalGeneration
    from transformers import AutoTokenizer

    set_torch_threads()
    _model_id = cfg.get("model_id", "parler-tts/parler-tts-mini-v1")
    _model = ParlerTTSForConditionalGeneration.from_pretrained(_model_id).to("cpu").eval()
    _tok = AutoTokenizer.from_pretrained(_model_id)
    try:  # v1.1+ tokenizes the description with the text encoder's own tokenizer
        _desc_tok = AutoTokenizer.from_pretrained(_model.config.text_encoder._name_or_path)
    except Exception:
        _desc_tok = _tok


def model_version(cfg) -> str:
    return f"{_model_id} via parler-tts {pkg_version('parler-tts')} / transformers {pkg_version('transformers')}"


def synth(text, language, instructions, cfg):
    import torch

    if _model is None:
        load(cfg)
    voice = pick_voice(language, cfg, "Jon")
    template = cfg.get("voice_description", "{voice}'s voice is clear and natural, with a very close recording that almost has no background noise.")
    description = template.format(voice=voice)
    if cfg.get("use_instructions", True) and instructions:
        description = f"{description} {instructions.strip()}"
    desc = _desc_tok(description, return_tensors="pt")
    prompt = _tok(text, return_tensors="pt")
    torch.manual_seed(int(cfg.get("seed", 0)))
    with torch.inference_mode():
        generation = _model.generate(
            input_ids=desc.input_ids, attention_mask=desc.attention_mask,
            prompt_input_ids=prompt.input_ids, prompt_attention_mask=prompt.attention_mask,
        )
    audio = to_numpy(generation)
    return audio, int(_model.config.sampling_rate), {"voice": voice, "streaming": False}
