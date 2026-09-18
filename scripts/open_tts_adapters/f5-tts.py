"""F5-TTS v1 Base (SWivid/F5-TTS; code MIT, weights CC-BY-NC-4.0) via the f5-tts package.

Weights from Hugging Face: SWivid/F5-TTS/F5TTS_v1_Base/model_1250000.safetensors
(~1.3 GB, fetched with cached_path into $OPEN_TTS_CACHE/f5-tts) and the
Vocos vocoder charactr/vocos-mel-24khz (via HF_HOME). It is a voice-cloning
model: every synthesis is conditioned on a reference clip plus its
transcript. We use the reference shipped inside the package
(infer/examples/basic/basic_ref_en.wav, run.ref_text) unless run.ref_audio
points at another file. Trained on English + Chinese (Emilia); other
languages are attempted and usually come out as accented gibberish.

A 335M DiT with classifier-free guidance, so cost is proportional to
run.nfe_step (16 here, 32 upstream default): 30-90 s per prompt on a 4-core
CPU. Landmines: f5-tts declares gradio, wandb, bitsandbytes, datasets,
accelerate and torchcodec as hard dependencies (wandb/accelerate/datasets
are imported at api import time); torchaudio>=2.9 needs torchcodec + ffmpeg
to load the reference clip.
"""
from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from _common import cache_dir, pick_voice, pkg_version, set_torch_threads, to_numpy

_tts = None
_model_id = None


def load(cfg) -> None:
    global _tts, _model_id
    from f5_tts.api import F5TTS

    set_torch_threads()
    _model_id = cfg.get("model_id", "F5TTS_v1_Base")
    _tts = F5TTS(model=_model_id, device="cpu", hf_cache_dir=str(cache_dir("f5-tts")))


def model_version(cfg) -> str:
    return f"SWivid/F5-TTS {_model_id} via f5-tts {pkg_version('f5-tts')}"


def _reference(language, cfg):
    if cfg.get("ref_audio"):
        return Path(cfg["ref_audio"]), cfg.get("ref_text", "")
    name = pick_voice(language, cfg, "basic_ref_en")
    ref = Path(str(files("f5_tts").joinpath(f"infer/examples/basic/{name}.wav")))
    ref_text = cfg.get("ref_text_by_voice", {}).get(name) or cfg.get("ref_text", "Some call me nature, others call me mother nature.")
    return ref, ref_text


def synth(text, language, instructions, cfg):
    if _tts is None:
        load(cfg)
    ref, ref_text = _reference(language, cfg)
    wav, sr, _spec = _tts.infer(
        ref_file=str(ref), ref_text=ref_text, gen_text=text,
        nfe_step=int(cfg.get("nfe_step", 16)), cfg_strength=float(cfg.get("cfg_strength", 2.0)),
        speed=float(cfg.get("speed", 1.0)), seed=int(cfg.get("seed", 0)),
        show_info=lambda *a, **k: None, progress=None,
    )
    return to_numpy(wav), int(sr), {"voice": ref.stem, "streaming": False}
