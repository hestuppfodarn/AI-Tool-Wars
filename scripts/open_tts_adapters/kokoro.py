"""Kokoro-82M (hexgrad/Kokoro-82M, Apache-2.0) through kokoro-onnx.

Weights: ONNX export + voice styles from the thewh1teagle/kokoro-onnx GitHub
release "model-files-v1.0" (no Hugging Face access needed):
  kokoro-v1.0.onnx  ~310 MB fp32   voices-v1.0.bin  ~27 MB
Cache: KOKORO_CACHE or $OPEN_TTS_CACHE/kokoro.

Phonemisation is espeak-ng (bundled in the espeakng-loader wheel) for every
language. Kokoro was trained on en-us, en-gb, es, fr, hi, it, pt-br, ja and zh;
Swedish and German text still gets phonemised and voiced by an English voice,
which is the honest result for those prompts. Japanese uses misaki's
pyopenjtalk G2P when `misaki[ja]` is installed (espeak's ja is kana-only and
reads kanji badly); set run.japanese_g2p to "espeak" to disable that.
"""
from __future__ import annotations

from _common import cache_dir, download, lang_base, pick_voice, pkg_version

RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
# BCP-47 tag / base language -> espeak-ng voice used for phonemisation
ESPEAK_LANG = {
    "en-US": "en-us", "en-GB": "en-gb", "en": "en-us", "es": "es", "fr": "fr-fr", "it": "it",
    "pt": "pt-br", "hi": "hi", "ja": "ja", "zh": "cmn", "de": "de", "sv": "sv",
}

_model = None
_files = None


def _weights(cfg):
    global _files
    if _files is None:
        d = cache_dir("kokoro")
        model_file = cfg.get("model_file", "kokoro-v1.0.onnx")
        voices_file = cfg.get("voices_file", "voices-v1.0.bin")
        _files = (
            download(cfg.get("model_url") or RELEASE + model_file, d / model_file),
            download(cfg.get("voices_url") or RELEASE + voices_file, d / voices_file),
        )
    return _files


def load(cfg) -> None:
    global _model
    from kokoro_onnx import Kokoro

    model_path, voices_path = _weights(cfg)
    _model = Kokoro(str(model_path), str(voices_path))


def model_version(cfg) -> str:
    model_path, _ = _weights(cfg)
    return f"kokoro-onnx {pkg_version('kokoro-onnx')} / {model_path.name} (thewh1teagle/kokoro-onnx model-files-v1.0)"


def _espeak_lang(language: str) -> str:
    return ESPEAK_LANG.get(language) or ESPEAK_LANG.get(lang_base(language)) or lang_base(language)


def synth(text, language, instructions, cfg):
    if _model is None:
        load(cfg)
    voice = pick_voice(language, cfg, "af_heart")
    lang = _espeak_lang(language)
    speed = float(cfg.get("speed", 1.0))
    meta = {"voice": voice, "streaming": False}

    if lang == "ja" and cfg.get("japanese_g2p", "misaki") == "misaki":
        try:
            from misaki import ja as misaki_ja
        except ImportError:
            misaki_ja = None
        if misaki_ja is not None:
            phonemes, _ = misaki_ja.JAG2P()(text)
            audio, sr = _model.create(phonemes, voice=voice, speed=speed, lang=lang, is_phonemes=True)
            meta["g2p"] = "misaki"
            return audio, sr, meta

    audio, sr = _model.create(text, voice=voice, speed=speed, lang=lang)
    return audio, sr, meta
