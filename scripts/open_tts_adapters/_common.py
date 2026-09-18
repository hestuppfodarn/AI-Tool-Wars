"""Shared helpers for the open-weight TTS adapters.

Every adapter module exposes:

    synth(text, language, instructions, cfg) -> (audio, sample_rate[, meta])

where `audio` is a float numpy array in [-1, 1], an int16 numpy array, raw WAV
bytes, or a path to a WAV file. `meta` is an optional dict that may carry
`voice`, `ttft_ms` and `streaming` when the adapter measured them itself.

Optionally an adapter also exposes:

    load(cfg)            -> None   # eager model load; called once per worker
    model_version(cfg)   -> str    # library + weights identifier for runs.json
    STYLE_TAGS = False             # True if bracketed stage directions are kept

Weights go under one cache root so CI can restore it between runs:
OPEN_TTS_CACHE (default ~/.cache/open-tts). Hugging Face downloads follow
HF_HOME, which the runner points inside that root unless it is already set.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import urllib.request
from pathlib import Path


def cache_root() -> Path:
    root = Path(os.environ.get("OPEN_TTS_CACHE") or Path.home() / ".cache" / "open-tts")
    root.mkdir(parents=True, exist_ok=True)
    return root


def cache_dir(name: str) -> Path:
    """Per-model cache dir; `<NAME>_CACHE` overrides (e.g. KOKORO_CACHE, PIPER_CACHE)."""
    override = os.environ.get(f"{name.upper().replace('-', '_')}_CACHE")
    path = Path(override) if override else cache_root() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def lang_base(language: str) -> str:
    """'sv-SE' -> 'sv'."""
    return (language or "en").split("-")[0].lower()


def pick_voice(language: str, cfg: dict, fallback: str | None = None) -> str | None:
    """Same lookup order as the Node runner: exact tag, base language, default."""
    table = cfg.get("voice_by_language") or {}
    return table.get(language) or table.get(lang_base(language)) or table.get("default") or fallback


def pick_by_language(table: dict | None, language: str, default=None):
    """Exact tag, then base language, then 'default' key, then `default`."""
    table = table or {}
    for key in (language, lang_base(language), "default"):
        if key in table:
            return table[key]
    return default


def download(url: str, dest: Path, sha256: str | None = None, timeout: int = 120) -> Path:
    """Download `url` to `dest` atomically unless it already exists (and matches the hash)."""
    dest = Path(dest)
    if dest.exists() and dest.stat().st_size > 0:
        if sha256 is None or _sha256(dest) == sha256:
            return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=dest.name + ".", dir=dest.parent)
    os.close(fd)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ai-tool-wars-open-tts/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as res, open(tmp, "wb") as out:
            shutil.copyfileobj(res, out, length=1 << 20)
        if sha256 is not None and _sha256(Path(tmp)) != sha256:
            raise RuntimeError(f"checksum mismatch for {url}")
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return dest


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def hf_download(repo_id: str, filename: str, repo_type: str | None = None, revision: str | None = None) -> str:
    """hf_hub_download honouring HF_HOME (set by the runner to the shared cache root)."""
    from huggingface_hub import hf_hub_download

    return hf_hub_download(repo_id=repo_id, filename=filename, repo_type=repo_type, revision=revision)


def setup_espeak() -> None:
    """Point `phonemizer` at the espeak-ng bundled in the espeakng-loader wheel (no apt needed)."""
    import espeakng_loader
    from phonemizer.backend.espeak.wrapper import EspeakWrapper

    lib = os.environ.get("PHONEMIZER_ESPEAK_LIBRARY") or espeakng_loader.get_library_path()
    EspeakWrapper.set_library(lib)
    EspeakWrapper.set_data_path(espeakng_loader.get_data_path())


def to_numpy(audio):
    """torch tensor / list / numpy -> 1-D float32 numpy array."""
    import numpy as np

    try:
        import torch

        if isinstance(audio, torch.Tensor):
            audio = audio.detach().cpu().float().numpy()
    except ImportError:
        pass
    arr = np.asarray(audio)
    if arr.ndim > 1:
        # (channels, n) or (n, channels): keep the long axis as time, average the rest
        arr = arr.mean(axis=0 if arr.shape[0] < arr.shape[-1] else 1)
    return arr.astype("float32", copy=False).reshape(-1)


def pkg_version(name: str) -> str:
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:
        return "unknown"


def cpu_threads() -> int:
    return int(os.environ.get("TTS_THREADS") or os.cpu_count() or 4)


def set_torch_threads() -> None:
    try:
        import torch

        torch.set_num_threads(cpu_threads())
    except Exception:
        pass
