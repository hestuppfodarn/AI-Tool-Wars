#!/usr/bin/env python3
"""Keyless scorer for recorded voice runs (data/runs/voice/<tool>/runs.json).

    python3 scripts/score-open.py --tool inworld-tts [--force]
                                  [--asr faster-whisper|whisper|none] [--asr-model small]
                                  [--mos dnsmos|squim|none]

Same contract as scripts/score-voice.mjs (the exporter and site need no changes),
but every model runs locally on a CPU runner and nothing needs an API key:

  transcript, asr_model  : local Whisper (faster-whisper int8 by default, or openai-whisper)
  wer, scores.accuracy   : normalize()/wer()/accuracy_score() ported verbatim from score-voice.mjs
  mos, scores.naturalness: reference-free MOS predictor, rescaled to 1-10 (see below)
  scores.adherence       : left untouched (null when absent); no keyless judge exists yet
  scored_at              : ISO timestamp of the last scoring pass
`velocity` is NOT computed here: it is a rank across tools, so the exporter derives it.

MOS -> naturalness mapping (documented in methodology):
  naturalness = clamp(1 + 9 * (mos - 1.0) / (4.5 - 1.0), 1, 10), rounded to one decimal.
  i.e. linear, MOS 1.0 -> 1, MOS 2.75 -> 5.5, MOS 4.5 -> 10; values outside 1.0..4.5 clamp.
  Backends:
    dnsmos (default): Microsoft DNSMOS P.835 (`speechmos` wheel ships the ONNX weights, no
             download). `mos` = OVRL after the P.835 polynomial fit, the value used above;
             SIG, BAK and the P.808 model's MOS are stored alongside in run["mos"].
    squim  : torchaudio SQUIM_OBJECTIVE (needs torch + torchaudio; weights come from
             download.pytorch.org on first use). `mos` = predicted PESQ (wideband MOS-LQO,
             1.02..4.64), mapped with the same formula; STOI and SI-SDR are stored in run["mos"].

Runs are written back after every prompt. A successful run is skipped when nothing is left
to do for the selected backends (transcript present when --asr is on, accuracy present when
a transcript exists, naturalness present when --mos is on) unless --force. With --asr none
accuracy is only (re)computed from transcripts already in the file, like score-voice.mjs.
Exit status is 1 only when something was attempted and nothing succeeded.

Model cache locations for CI caching:
  faster-whisper: $HF_HOME/hub (default ~/.cache/huggingface/hub), repo Systran/faster-whisper-<size>
  openai-whisper: ~/.cache/whisper/<size>.pt
  squim         : $TORCH_HOME/hub/checkpoints (default ~/.cache/torch/hub/checkpoints)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATEGORY = "voice"

# ---------------------------------------------------------------------------
# Text normalisation + WER: a faithful port of score-voice.mjs. Keep in sync.
# lowercase, drop [stage directions], strip punctuation, collapse whitespace.
# Digits stay digits; ASR models normally emit digits for spoken numbers.
# ---------------------------------------------------------------------------
_STAGE = re.compile(r"\[[^\]]*\]")
_PUNCT = re.compile(r"[“”\"‘’'.,!?;:()\-–—…/]")
_WS = re.compile(r"\s+")


def js_round(x: float, decimals: int = 0) -> float:
    """JavaScript Math.round semantics (halves go up), scaled like Math.round(x*k)/k."""
    k = 10 ** decimals
    v = math.floor(x * k + 0.5) / k
    return int(v) if v.is_integer() else v  # JSON.stringify writes 10, not 10.0


def normalize(text: str) -> str:
    text = text.lower()
    text = _STAGE.sub(" ", text)
    text = _PUNCT.sub(" ", text)
    return _WS.sub(" ", text).strip()


def wer(reference: str, hypothesis: str) -> float:
    r = [w for w in normalize(reference).split(" ") if w]
    h = [w for w in normalize(hypothesis).split(" ") if w]
    if not r:
        return 1.0 if h else 0.0
    d = [[i] + [0] * len(h) for i in range(len(r) + 1)]
    for j in range(1, len(h) + 1):
        d[0][j] = j
    for i in range(1, len(r) + 1):
        for j in range(1, len(h) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (0 if r[i - 1] == h[j - 1] else 1))
    return d[len(r)][len(h)] / len(r)


def accuracy_score(w: float) -> float:
    """WER 0 -> 10, WER >= 0.5 -> 1, linear between (one decimal)."""
    return js_round(10 - 9 * min(1.0, w / 0.5), 1)


# ---------------------------------------------------------------------------
# MOS -> 1-10
# ---------------------------------------------------------------------------
MOS_LOW, MOS_HIGH = 1.0, 4.5


def naturalness_score(mos: float) -> float:
    """Linear: MOS 1.0 -> 1, MOS 4.5 -> 10, clamped, one decimal."""
    s = 1 + 9 * (mos - MOS_LOW) / (MOS_HIGH - MOS_LOW)
    return js_round(max(1.0, min(10.0, s)), 1)


# ---------------------------------------------------------------------------
# Audio loading: 16 kHz mono float32 in [-1, 1]. libsndfile (>= 1.1) decodes
# wav/flac/ogg/mp3 without ffmpeg; PyAV (a faster-whisper dependency) is the
# fallback for anything else.
# ---------------------------------------------------------------------------
TARGET_SR = 16000


def load_audio_16k(path: str):
    import numpy as np

    audio = None
    try:
        import soundfile as sf

        data, sr = sf.read(path, dtype="float32", always_2d=True)
        audio = data.mean(axis=1)
        if sr != TARGET_SR:
            import librosa

            audio = librosa.resample(audio, orig_sr=sr, target_sr=TARGET_SR)
    except Exception as first:  # noqa: BLE001 - any decode failure falls through to PyAV
        try:
            from faster_whisper.audio import decode_audio

            audio = decode_audio(path, sampling_rate=TARGET_SR)
        except Exception as second:  # noqa: BLE001
            raise RuntimeError(f"cannot decode {path}: soundfile: {first}; pyav: {second}") from second
    audio = np.asarray(audio, dtype="float32").reshape(-1)
    if not audio.size:
        raise RuntimeError(f"decoded zero samples from {path}")
    return np.clip(audio, -1.0, 1.0)


# ---------------------------------------------------------------------------
# ASR backends. transcribe(audio_16k, language) -> transcript; .label -> run["asr_model"].
# ---------------------------------------------------------------------------
class FasterWhisperASR:
    def __init__(self, size: str, compute_type: str, threads: int):
        from faster_whisper import WhisperModel

        self.size = size
        self.label = f"faster-whisper-{size}-{compute_type}"
        # download_root=None -> huggingface_hub cache ($HF_HOME/hub). local_files_only honours
        # HF_HUB_OFFLINE=1 so a pre-populated cache works with the network cut off.
        self.model = WhisperModel(size, device="cpu", compute_type=compute_type, cpu_threads=threads,
                                  local_files_only=os.environ.get("HF_HUB_OFFLINE") == "1")

    def transcribe(self, audio, language: str | None) -> str:
        segments, _info = self.model.transcribe(
            audio, language=language, beam_size=5, vad_filter=False, condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segments if s.text.strip())


class OpenAIWhisperASR:
    def __init__(self, size: str, threads: int):
        import torch
        import whisper

        torch.set_num_threads(threads)
        self.label = f"whisper-{size}"
        self.model = whisper.load_model(size, device="cpu")  # ~/.cache/whisper/<size>.pt

    def transcribe(self, audio, language: str | None) -> str:
        # Pass the decoded array so openai-whisper does not shell out to ffmpeg.
        result = self.model.transcribe(audio, language=language, fp16=False, beam_size=5,
                                       condition_on_previous_text=False)
        return str(result.get("text", "")).strip()


# ---------------------------------------------------------------------------
# MOS backends. score(audio_16k) -> (mos_for_mapping, raw_dict stored as run["mos"]).
# ---------------------------------------------------------------------------
class DNSMOSBackend:
    label = "dnsmos"

    def __init__(self):
        from speechmos import dnsmos  # ONNX weights ship inside the wheel

        self._run = dnsmos.run

    def score(self, audio):
        r = self._run(audio, TARGET_SR)
        raw = {"backend": self.label, "ovrl": round(float(r["ovrl_mos"]), 3), "sig": round(float(r["sig_mos"]), 3),
               "bak": round(float(r["bak_mos"]), 3), "p808": round(float(r["p808_mos"]), 3)}
        return raw["ovrl"], raw


class SquimBackend:
    label = "squim"

    def __init__(self, threads: int):
        import torch
        from torchaudio.pipelines import SQUIM_OBJECTIVE

        torch.set_num_threads(threads)
        self._torch = torch
        self.model = SQUIM_OBJECTIVE.get_model()  # downloads to $TORCH_HOME/hub/checkpoints
        self.model.eval()

    def score(self, audio):
        torch = self._torch
        with torch.no_grad():
            wav = torch.from_numpy(audio).unsqueeze(0)
            stoi, pesq, si_sdr = self.model(wav)
        raw = {"backend": self.label, "pesq": round(float(pesq[0]), 3), "stoi": round(float(stoi[0]), 3),
               "si_sdr": round(float(si_sdr[0]), 3)}
        return raw["pesq"], raw


# ---------------------------------------------------------------------------
class Lazy:
    """Build a backend on first use; remember a construction failure so every run reports it."""

    def __init__(self, factory):
        self._factory, self._obj, self._err = factory, None, None

    def get(self):
        if self._err:
            raise self._err
        if self._obj is None:
            try:
                self._obj = self._factory()
            except Exception as e:  # noqa: BLE001
                self._err = RuntimeError(f"backend unavailable: {type(e).__name__}: {str(e)[:200]}")
                raise self._err
        return self._obj


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def fmt(v) -> str:
    return "–" if v is None else str(v)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tool", required=True, help="tool slug under data/runs/voice/")
    ap.add_argument("--force", action="store_true", help="re-score runs that already have scores")
    ap.add_argument("--asr", choices=["faster-whisper", "whisper", "none"], default="faster-whisper")
    ap.add_argument("--asr-model", default="small", help="Whisper size: tiny, base, small, medium (default small)")
    ap.add_argument("--compute-type", default="int8", help="faster-whisper compute type on CPU (default int8)")
    ap.add_argument("--mos", choices=["dnsmos", "squim", "none"], default="dnsmos")
    ap.add_argument("--threads", type=int, default=max(1, os.cpu_count() or 1))
    args = ap.parse_args(argv)

    prompts = json.loads((ROOT / "data/catalog" / CATEGORY / "prompts.json").read_text(encoding="utf-8"))
    by_prompt = {p["id"]: p for p in prompts}
    run_dir = ROOT / "data/runs" / CATEGORY / args.tool
    runs_path = run_dir / "runs.json"
    if not runs_path.exists():
        print(f"no runs at {runs_path}", file=sys.stderr)
        return 1
    runs = json.loads(runs_path.read_text(encoding="utf-8"))

    if args.asr == "faster-whisper":
        asr = Lazy(lambda: FasterWhisperASR(args.asr_model, args.compute_type, args.threads))
    elif args.asr == "whisper":
        asr = Lazy(lambda: OpenAIWhisperASR(args.asr_model, args.threads))
    else:
        asr = None
    if args.mos == "dnsmos":
        mos = Lazy(DNSMOSBackend)
    elif args.mos == "squim":
        mos = Lazy(lambda: SquimBackend(args.threads))
    else:
        mos = None

    def save():
        runs_path.write_text(json.dumps(runs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    scored = failed = skipped = 0
    for run in runs:
        if run.get("status") != "success":
            skipped += 1
            continue
        prompt = by_prompt.get(run.get("prompt_id"))
        if not prompt:
            skipped += 1
            continue
        scores = run.setdefault("scores", {})
        need_asr = asr is not None and not run.get("transcript")
        need_acc = run.get("transcript") is not None and scores.get("accuracy") is None
        need_mos = mos is not None and scores.get("naturalness") is None
        if not (need_asr or need_acc or need_mos or args.force):
            skipped += 1
            continue
        sys.stdout.write(f"{run['prompt_id']} ")
        sys.stdout.flush()
        t0 = time.time()
        try:
            audio_path = str(run_dir / run["audio"])
            need_audio = (asr is not None or mos is not None) and (need_asr or need_mos or args.force)
            audio = load_audio_16k(audio_path) if need_audio else None

            if asr is not None and (need_asr or args.force):
                backend = asr.get()
                lang = (prompt.get("language") or "").split("-")[0] or None
                run["transcript"] = backend.transcribe(audio, lang)
                run["asr_model"] = backend.label
            if run.get("transcript") is not None:
                run["wer"] = js_round(wer(prompt["text"], run["transcript"]), 3)
                scores["accuracy"] = accuracy_score(run["wer"])

            if mos is not None and (scores.get("naturalness") is None or args.force):
                value, raw = mos.get().score(audio)
                run["mos"] = raw
                scores["naturalness"] = naturalness_score(value)
            scores.setdefault("naturalness", None)
            scores.setdefault("adherence", None)  # no keyless judge yet; never overwritten here

            run["scored_at"] = now_iso()
            scored += 1
            print(f"wer {fmt(run.get('wer'))}  accuracy {fmt(scores.get('accuracy'))}  "
                  f"naturalness {fmt(scores.get('naturalness'))}  adherence {fmt(scores.get('adherence'))}  "
                  f"({time.time() - t0:.1f}s)")
        except Exception as e:  # noqa: BLE001 - failures are recorded per run, never hidden
            failed += 1
            print(f"FAIL {str(e)[:140]}")
        save()

    print(f"\n{args.tool}: {scored} scored, {failed} failed, {skipped} skipped "
          f"(asr={args.asr}{'/' + args.asr_model if args.asr != 'none' else ''}, mos={args.mos})")
    return 1 if failed and not scored else 0


if __name__ == "__main__":
    sys.exit(main())
