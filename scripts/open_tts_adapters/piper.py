"""Piper (rhasspy/piper, MIT; voices CC-BY / per-voice) through the piper-tts wheel.

Voices are VITS ONNX models, one per language/speaker, 20-75 MB each.
Primary source: huggingface.co/rhasspy/piper-voices via
`piper.download_voices` (names like `en_US-lessac-medium`). Fallback source:
the legacy tarballs on the GitHub release rhasspy/piper v0.0.2 (older 16 kHz
exports of the same speakers, same file format); used automatically when the
Hugging Face download fails or when PIPER_VOICE_SOURCE=github. Cache:
PIPER_CACHE or $OPEN_TTS_CACHE/piper.

Runs at many times real time on one CPU core; `synthesize()` yields one chunk
per sentence, so the first chunk gives a real time-to-first-audio.
"""
from __future__ import annotations

import os
import tarfile
import time

import numpy as np

from _common import cache_dir, download, pick_voice, pkg_version

LEGACY_RELEASE = "https://github.com/rhasspy/piper/releases/download/v0.0.2/"
# modern voice name -> (legacy tarball stem, file stem inside the tarball)
LEGACY = {
    "en_US-lessac-medium": ("voice-en-us-lessac-medium", "en-us-lessac-medium"),
    "en_US-ryan-medium": ("voice-en-us-ryan-medium", "en-us-ryan-medium"),
    "en_GB-alan-medium": ("voice-en-gb-alan-low", "en-gb-alan-low"),
    "en_GB-alan-low": ("voice-en-gb-alan-low", "en-gb-alan-low"),
    "sv_SE-nst-medium": ("voice-sv-se-nst-medium", "sv-se-nst-medium"),
    "es_ES-carlfm-x-low": ("voice-es-carlfm-x-low", "es-carlfm-x-low"),
    "es_ES-davefx-medium": ("voice-es-carlfm-x-low", "es-carlfm-x-low"),
    "es_ES-mls_10246-low": ("voice-es-mls_10246-low", "es-mls_10246-low"),
    "fr_FR-siwis-medium": ("voice-fr-siwis-medium", "fr-siwis-medium"),
    "de_DE-thorsten-medium": ("voice-de-thorsten-low", "de-thorsten-low"),
    "de_DE-thorsten-low": ("voice-de-thorsten-low", "de-thorsten-low"),
}

_voices: dict = {}
_resolved: dict = {}


def _legacy(voice: str, d):
    if voice not in LEGACY:
        raise FileNotFoundError(f"no legacy GitHub release mapping for piper voice {voice}")
    tar_stem, file_stem = LEGACY[voice]
    onnx = d / f"{file_stem}.onnx"
    if not onnx.exists():
        tar_path = download(LEGACY_RELEASE + tar_stem + ".tar.gz", d / (tar_stem + ".tar.gz"))
        with tarfile.open(tar_path) as tf:
            tf.extractall(d)
    return onnx, f"{file_stem} (legacy v0.0.2)"


def _resolve(voice: str):
    """Returns (onnx_path, label) for a voice name, downloading if needed."""
    if voice in _resolved:
        return _resolved[voice]
    d = cache_dir("piper")
    modern = d / f"{voice}.onnx"
    result = None
    source = os.environ.get("PIPER_VOICE_SOURCE", "hf").lower()
    if modern.exists() and (d / f"{voice}.onnx.json").exists():
        result = (modern, voice)
    elif source == "github":
        result = _legacy(voice, d)
    else:
        try:
            from piper.download_voices import download_voice

            download_voice(voice, d)
            result = (modern, voice)
        except Exception as e:  # HF unreachable or unknown voice: try the GitHub mirror
            try:
                result = _legacy(voice, d)
            except Exception as e2:
                raise RuntimeError(f"piper voice {voice}: HF download failed ({e}); legacy fallback failed ({e2})")
    _resolved[voice] = result
    return result


def _voice(name: str):
    if name not in _voices:
        from piper import PiperVoice

        onnx, label = _resolve(name)
        _voices[name] = (PiperVoice.load(str(onnx)), label)
    return _voices[name]


def load(cfg) -> None:
    """Load every configured voice up front so per-language voice loads do not count as latency."""
    names = {pick_voice("en-US", cfg, "en_US-lessac-medium"), *(cfg.get("voice_by_language") or {}).values()}
    for name in sorted(names):
        _voice(name)


def model_version(cfg) -> str:
    default = pick_voice("en-US", cfg, "en_US-lessac-medium")
    label = _resolved.get(default, (None, default))[1]
    return f"piper-tts {pkg_version('piper-tts')} / {label}"


def synth(text, language, instructions, cfg):
    from piper import SynthesisConfig

    name = pick_voice(language, cfg, "en_US-lessac-medium")
    voice, label = _voice(name)
    syn = SynthesisConfig(length_scale=float(cfg.get("length_scale", 1.0)))
    t0 = time.perf_counter()
    chunks, ttft_ms, sr = [], None, voice.config.sample_rate
    for chunk in voice.synthesize(text, syn):
        if ttft_ms is None:
            ttft_ms = round((time.perf_counter() - t0) * 1000)
        chunks.append(chunk.audio_float_array)
        sr = chunk.sample_rate
    if not chunks:
        raise RuntimeError("piper produced no audio (text phonemised to nothing?)")
    audio = np.concatenate(chunks)
    return audio, sr, {"voice": label, "ttft_ms": ttft_ms, "streaming": True}
