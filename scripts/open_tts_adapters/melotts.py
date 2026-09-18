"""MeloTTS (myshell-ai/MeloTTS, MIT): one VITS-family model per language.

Weights from Hugging Face repos myshell-ai/MeloTTS-English / -Spanish /
-French / -Japanese / -Chinese / -Korean (~200 MB each) plus the BERT
encoders they use for prosody (bert-base-uncased and per-language BERTs,
~400-700 MB each), all through HF_HOME. Real-time or faster on CPU.

Speakers: the English model has EN-US, EN-BR, EN_INDIA, EN-AU, EN-Default;
the others have a single speaker named after the language code. Languages
without a model (Swedish, German in this bank) fall back to the English
model, which is the honest result. Needs NLTK's POS tagger (downloaded on
first load into NLTK_DATA) and MeCab + unidic-lite for Japanese.
Landmine: the package pins transformers==4.27.4, librosa==0.9.1 and needs
numpy<2, so it must live in its own virtualenv.
"""
from __future__ import annotations

from _common import lang_base, pick_voice, pkg_version, set_torch_threads

LANG_MODEL = {"en": "EN", "es": "ES", "fr": "FR", "zh": "ZH", "ja": "JP", "ko": "KR"}

_models: dict = {}


def _model_for(code: str):
    if code not in _models:
        from melo.api import TTS

        _models[code] = TTS(language=code, device="cpu")
    return _models[code]


def load(cfg) -> None:
    set_torch_threads()
    try:
        import nltk

        for pkg in ("averaged_perceptron_tagger_eng", "averaged_perceptron_tagger", "cmudict"):
            nltk.download(pkg, quiet=True)
    except Exception:
        pass
    _model_for("EN")


def model_version(cfg) -> str:
    return f"myshell-ai/MeloTTS ({', '.join(sorted(_models))}) via melotts {pkg_version('melotts')}"


def synth(text, language, instructions, cfg):
    base = lang_base(language)
    code = LANG_MODEL.get(base, "EN")
    model = _model_for(code)
    spk2id = model.hps.data.spk2id
    voice = pick_voice(language, cfg, "EN-US")
    if voice not in spk2id:
        voice = next(iter(spk2id))
    audio = model.tts_to_file(text, spk2id[voice], output_path=None, speed=float(cfg.get("speed", 1.0)), quiet=True)
    return audio, int(model.hps.data.sampling_rate), {"voice": f"{code}/{voice}", "streaming": False}
