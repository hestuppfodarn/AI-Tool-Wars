"""SpeechT5 TTS (microsoft/speecht5_tts, MIT) through transformers.

Weights from Hugging Face: microsoft/speecht5_tts (~585 MB), the HiFi-GAN
vocoder microsoft/speecht5_hifigan (~50 MB) and one x-vector speaker
embedding from the dataset Matthijs/cmu-arctic-xvectors (row 7306 is the
usual female "slt" speaker). All go through HF_HOME.

English only, ~145M parameters, a few seconds per sentence on CPU. The
character tokenizer has no digits, so numbers are silently dropped unless
they are spelled out first; run.normalize_numbers (default true) does that
with num2words, which is what any deployment of this model has to do.
"""
from __future__ import annotations

import re

import numpy as np

from _common import hf_download, pick_voice, pkg_version, set_torch_threads

SAMPLE_RATE = 16000

_processor = _model = _vocoder = None
_speakers: dict = {}


def load(cfg) -> None:
    global _processor, _model, _vocoder
    from transformers import SpeechT5ForTextToSpeech, SpeechT5HifiGan, SpeechT5Processor

    set_torch_threads()
    model_id = cfg.get("model_id", "microsoft/speecht5_tts")
    _processor = SpeechT5Processor.from_pretrained(model_id)
    _model = SpeechT5ForTextToSpeech.from_pretrained(model_id).eval()
    _vocoder = SpeechT5HifiGan.from_pretrained(cfg.get("vocoder_id", "microsoft/speecht5_hifigan")).eval()
    _speaker(pick_voice("en-US", cfg, "7306"), cfg)


def model_version(cfg) -> str:
    return f"{cfg.get('model_id', 'microsoft/speecht5_tts')} + {cfg.get('vocoder_id', 'microsoft/speecht5_hifigan')} via transformers {pkg_version('transformers')}"


def _speaker(voice: str, cfg):
    """A 512-d x-vector: dataset row index ("7306") or an .npy name in the dataset repo."""
    import torch

    if voice in _speakers:
        return _speakers[voice]
    dataset = cfg.get("speaker_dataset", "Matthijs/cmu-arctic-xvectors")
    if voice.isdigit():
        from datasets import load_dataset

        rows = load_dataset(dataset, split="validation")
        vec = np.asarray(rows[int(voice)]["xvector"], dtype=np.float32)
    else:
        vec = np.load(hf_download(dataset, f"spkrec-xvect/{voice}.npy", repo_type="dataset")).astype(np.float32)
    _speakers[voice] = torch.tensor(vec).unsqueeze(0)
    return _speakers[voice]


def normalize_numbers(text: str) -> str:
    from num2words import num2words

    def money(m):
        amount = float(m.group(1).replace(",", ""))
        return " " + num2words(amount, to="currency", currency="USD", lang="en") + " "

    def ordinal(m):
        return num2words(int(m.group(1)), to="ordinal", lang="en")

    def number(m):
        raw = m.group(0).replace(",", "")
        try:
            value = float(raw) if "." in raw else int(raw)
            return " " + num2words(value, lang="en") + " "
        except Exception:
            return raw

    text = re.sub(r"\$\s?([\d,]+(?:\.\d+)?)", money, text)
    text = text.replace("%", " percent")
    text = re.sub(r"\b(\d+)(?:st|nd|rd|th)\b", ordinal, text)
    text = re.sub(r"\d[\d,]*(?:\.\d+)?", number, text)
    return re.sub(r"\s+", " ", text).strip()


def synth(text, language, instructions, cfg):
    import torch

    if _model is None:
        load(cfg)
    voice = pick_voice(language, cfg, "7306")
    if cfg.get("normalize_numbers", True):
        text = normalize_numbers(text)
    inputs = _processor(text=text, return_tensors="pt")
    with torch.inference_mode():
        speech = _model.generate_speech(inputs["input_ids"], _speaker(voice, cfg), vocoder=_vocoder)
    return speech.cpu().numpy(), SAMPLE_RATE, {"voice": f"cmu-arctic-xvector:{voice}", "streaming": False}
