"""Bark small (suno/bark-small, MIT) through transformers' BarkModel.

Weights from Hugging Face (~1.7 GB incl. the EnCodec codec and speaker
presets), through HF_HOME. Three autoregressive stages (semantic, coarse,
fine) make it slow: 30-90 s per prompt on a 4-core CPU, and each generation
is capped at roughly 13 s of audio, so longer scripts are split into chunks
of run.chunk_chars characters at sentence boundaries and joined with a short
silence. Speaker presets exist per language (v2/<lang>_speaker_N); Swedish
has none and uses the English preset. Bark understands tags like [laughs],
not free-form stage directions, so bracketed notes are stripped. Output is
sampled (do_sample), seeded from run.seed for repeatability.
"""
from __future__ import annotations

import re

import numpy as np

from _common import pick_voice, pkg_version, set_torch_threads, to_numpy

_processor = _model = None
_model_id = None


def load(cfg) -> None:
    global _processor, _model, _model_id
    from transformers import AutoProcessor, BarkModel

    set_torch_threads()
    _model_id = cfg.get("model_id", "suno/bark-small")
    _processor = AutoProcessor.from_pretrained(_model_id)
    _model = BarkModel.from_pretrained(_model_id).to("cpu").eval()


def model_version(cfg) -> str:
    return f"{_model_id} via transformers {pkg_version('transformers')}"


def chunk_text(text: str, max_chars: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?。！？])\s+", text.strip())
    chunks, cur = [], ""
    for s in sentences:
        if cur and len(cur) + 1 + len(s) > max_chars:
            chunks.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        chunks.append(cur)
    return chunks or [text]


def synth(text, language, instructions, cfg):
    import torch

    if _model is None:
        load(cfg)
    preset = pick_voice(language, cfg, "v2/en_speaker_6")
    sr = int(_model.generation_config.sample_rate)
    torch.manual_seed(int(cfg.get("seed", 0)))
    parts = []
    gap = np.zeros(int(sr * float(cfg.get("chunk_gap_s", 0.2))), dtype=np.float32)
    for chunk in chunk_text(text, int(cfg.get("chunk_chars", 220))):
        inputs = _processor(chunk, voice_preset=preset, return_tensors="pt")
        with torch.inference_mode():
            out = _model.generate(**inputs)
        if parts:
            parts.append(gap)
        parts.append(to_numpy(out))
    return np.concatenate(parts), sr, {"voice": preset, "streaming": False}
