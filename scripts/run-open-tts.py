#!/usr/bin/env python3
"""Runner for open-weight text-to-speech models that need no API key.

Python twin of scripts/run-voice.mjs: executes the golden prompt bank against
one catalog tool whose adapter is "open:<slug>", writes 16-bit PCM WAV files
and a runs.json with the same fields the Node runner writes, so the exporter
and scorer treat both alike.

    python scripts/run-open-tts.py --tool kokoro [--limit 3] [--prompts voice-001,voice-002]
                                   [--force] [--out-dir data/runs/voice/kokoro] [--timeout 300]

Each model's Python dependencies live in requirements/open-tts/<slug>.txt;
install exactly one of them per virtualenv (they conflict with each other).

Synthesis runs in a worker subprocess that loads the model once. A prompt that
exceeds TTS_TIMEOUT_S (default 300) is recorded as an error, the worker is
killed and a fresh one is started for the next prompt. Nothing is retried
silently and failures are always written to runs.json.

Exit codes: 0 ran, 1 every attempted prompt failed, 3 adapter dependencies
missing (install its requirements file), 2 usage error.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import multiprocessing as mp
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADAPTERS_DIR = ROOT / "scripts" / "open_tts_adapters"
CATEGORY = "voice"

# --- helpers ------------------------------------------------------------------

STAGE_DIRECTION = re.compile(r"\[[^\]]*\]")


def strip_stage_directions(text: str) -> str:
    """Remove bracketed notes like "[Now, sadly:]" that are not meant to be spoken."""
    return re.sub(r"\s+", " ", STAGE_DIRECTION.sub(" ", text)).strip()


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def load_env_file(path: Path) -> None:
    """Tiny .env loader, same rules as the Node runner (never overrides the environment)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$", line)
        if m and os.environ.get(m.group(1)) is None:
            os.environ[m.group(1)] = m.group(2).strip().strip("\"'")


def default_cache_env() -> None:
    """Route every library's weight cache under one root so CI can cache it."""
    root = Path(os.environ.get("OPEN_TTS_CACHE") or Path.home() / ".cache" / "open-tts")
    root.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("OPEN_TTS_CACHE", str(root))
    os.environ.setdefault("HF_HOME", str(root / "hf"))            # huggingface_hub / transformers
    os.environ.setdefault("TTS_HOME", str(root / "coqui"))        # coqui-tts model manager
    os.environ.setdefault("NLTK_DATA", str(root / "nltk_data"))   # MeloTTS POS tagger
    os.environ.setdefault("TORCH_HOME", str(root / "torch"))
    os.environ.setdefault("XDG_CACHE_HOME", str(root / "xdg"))    # cached_path (F5-TTS, MeloTTS)
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("COQUI_TOS_AGREED", "1")                # XTTS-v2 CPML prompt (non-commercial licence)
    os.environ.setdefault("PYTHONUNBUFFERED", "1")


def adapter_path(slug: str) -> Path:
    return ADAPTERS_DIR / f"{slug}.py"


def import_adapter(path: Path):
    name = "open_tts_adapter_" + re.sub(r"[^0-9a-zA-Z_]", "_", path.stem)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def write_pcm16(audio, sample_rate: int, out_path: Path) -> int:
    """Normalise whatever the adapter returned into a 16-bit PCM WAV; returns byte size."""
    import numpy as np
    import soundfile as sf

    if isinstance(audio, (bytes, bytearray)):
        import io

        data, sample_rate = sf.read(io.BytesIO(bytes(audio)), dtype="float32", always_2d=False)
    elif isinstance(audio, (str, os.PathLike)):
        data, sample_rate = sf.read(str(audio), dtype="float32", always_2d=False)
    else:
        data = np.asarray(audio)
        if data.dtype.kind in "iu":
            data = data.astype("float32") / float(np.iinfo(data.dtype).max)
        data = data.astype("float32", copy=False)
    data = np.nan_to_num(data)
    if data.ndim > 1:
        data = data.mean(axis=1 if data.shape[1] < data.shape[0] else 0)
    data = np.clip(data.reshape(-1), -1.0, 1.0)
    if data.size == 0:
        raise RuntimeError("adapter returned empty audio")
    sf.write(str(out_path), data, int(sample_rate), subtype="PCM_16", format="WAV")
    return out_path.stat().st_size


# --- worker process -------------------------------------------------------------

def _worker_main(conn, adapter_file: str, cfg: dict) -> None:
    """Loads the adapter (and model) once, then serves synth jobs over the pipe."""
    try:
        import numpy  # noqa: F401  (base requirement)
        import soundfile  # noqa: F401
        from _common import set_torch_threads  # type: ignore

        set_torch_threads()
        adapter = import_adapter(Path(adapter_file))
        if hasattr(adapter, "load"):
            adapter.load(cfg)
        version = adapter.model_version(cfg) if hasattr(adapter, "model_version") else None
        style_tags = bool(getattr(adapter, "STYLE_TAGS", False))
    except ImportError as e:
        conn.send(("import_error", f"{type(e).__name__}: {e}"))
        return
    except Exception as e:  # download / load failure: reported, not hidden
        conn.send(("load_error", f"{type(e).__name__}: {str(e)[:400]}\n{traceback.format_exc()[-600:]}"))
        return
    conn.send(("ready", {"model_version": version, "style_tags": style_tags}))

    while True:
        job = conn.recv()
        if job is None:
            return
        try:
            t0 = time.perf_counter()
            result = adapter.synth(job["text"], job["language"], job["instructions"], cfg)
            latency_ms = round((time.perf_counter() - t0) * 1000)
            audio, sample_rate = result[0], int(result[1])
            meta = dict(result[2]) if len(result) > 2 and result[2] else {}
            size = write_pcm16(audio, sample_rate, Path(job["out_path"]))
            conn.send(("ok", {
                "bytes": size,
                "sample_rate": sample_rate,
                "latency_ms": latency_ms,
                "ttft_ms": int(meta["ttft_ms"]) if meta.get("ttft_ms") is not None else latency_ms,
                "streaming": bool(meta.get("streaming", False)),
                "voice": meta.get("voice"),
            }))
        except Exception as e:
            conn.send(("err", f"{type(e).__name__}: {str(e)[:400]}"))


class Worker:
    """One model-loaded subprocess; killed and respawned after a timeout."""

    def __init__(self, adapter_file: Path, cfg: dict, load_timeout_s: float):
        self.adapter_file = str(adapter_file)
        self.cfg = cfg
        self.load_timeout_s = load_timeout_s
        self.proc = None
        self.conn = None
        self.info = None

    def start(self):
        ctx = mp.get_context("spawn")
        parent, child = ctx.Pipe()
        self.proc = ctx.Process(target=_worker_main, args=(child, self.adapter_file, self.cfg), daemon=True)
        self.proc.start()
        child.close()
        self.conn = parent
        t0 = time.perf_counter()
        if not self.conn.poll(self.load_timeout_s):
            self.kill()
            raise TimeoutError(f"model load exceeded {self.load_timeout_s:.0f}s")
        kind, payload = self.conn.recv()
        if kind == "import_error":
            self.kill()
            raise ImportError(payload)
        if kind == "load_error":
            self.kill()
            raise RuntimeError(payload)
        self.info = payload
        self.load_ms = round((time.perf_counter() - t0) * 1000)
        return self

    def alive(self) -> bool:
        return self.proc is not None and self.proc.is_alive()

    def request(self, job: dict, timeout_s: float) -> dict:
        self.conn.send(job)
        if not self.conn.poll(timeout_s):
            self.kill()
            raise TimeoutError(f"synthesis exceeded {timeout_s:.0f}s (TTS_TIMEOUT_S); worker killed")
        kind, payload = self.conn.recv()
        if kind == "ok":
            return payload
        raise RuntimeError(payload)

    def kill(self):
        if self.proc is not None and self.proc.is_alive():
            self.proc.terminate()
            self.proc.join(10)
            if self.proc.is_alive():
                self.proc.kill()
                self.proc.join(5)
        self.proc = None
        self.conn = None

    def close(self):
        try:
            if self.conn is not None:
                self.conn.send(None)
                self.proc.join(15)
        except Exception:
            pass
        self.kill()


# --- main -----------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Run the voice prompt bank against one open-weight TTS model.")
    ap.add_argument("--tool", required=True, help="catalog slug (adapter must be open:<slug>)")
    ap.add_argument("--limit", type=int, help="only the first N prompts by rank")
    ap.add_argument("--prompts", help="comma-separated prompt ids")
    ap.add_argument("--force", action="store_true", help="re-run prompts that already succeeded")
    ap.add_argument("--out-dir", help="default data/runs/voice/<slug>")
    ap.add_argument("--timeout", type=float, default=float(os.environ.get("TTS_TIMEOUT_S", "300")),
                    help="per-prompt synthesis timeout in seconds (env TTS_TIMEOUT_S, default 300)")
    ap.add_argument("--load-timeout", type=float, default=float(os.environ.get("TTS_LOAD_TIMEOUT_S", "1800")),
                    help="model download+load timeout in seconds (env TTS_LOAD_TIMEOUT_S, default 1800)")
    args = ap.parse_args(argv)

    load_env_file(ROOT / ".env")
    default_cache_env()

    tools = json.loads((ROOT / "data/catalog" / CATEGORY / "tools.json").read_text(encoding="utf-8"))
    prompts = json.loads((ROOT / "data/catalog" / CATEGORY / "prompts.json").read_text(encoding="utf-8"))
    tool = next((t for t in tools if t["slug"] == args.tool), None)
    if not tool:
        print(f"unknown tool {args.tool}", file=sys.stderr)
        return 2
    adapter_name = str(tool.get("adapter", ""))
    if not adapter_name.startswith("open:"):
        print(f"{tool['slug']} uses adapter '{adapter_name}', not an open:<slug> adapter; use scripts/run-voice.mjs", file=sys.stderr)
        return 2
    slug = adapter_name.split(":", 1)[1]
    adapter_file = adapter_path(slug)
    if not adapter_file.exists():
        print(f"no adapter file {adapter_file}", file=sys.stderr)
        return 2
    cfg = dict(tool.get("run") or {})
    cfg.setdefault("model_id", tool.get("model_hint"))

    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "data/runs" / CATEGORY / tool["slug"]
    out_dir.mkdir(parents=True, exist_ok=True)
    runs_path = out_dir / "runs.json"
    runs = json.loads(runs_path.read_text(encoding="utf-8")) if runs_path.exists() else []
    by_id = {r["prompt_id"]: r for r in runs}

    selected = sorted(prompts, key=lambda p: p["rank"])
    if args.prompts:
        ids = set(args.prompts.split(","))
        selected = [p for p in selected if p["id"] in ids]
    if args.limit:
        selected = selected[: args.limit]

    def save():
        ordered = sorted(by_id.values(), key=lambda r: r["prompt_id"])
        runs_path.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    ok = failed = skipped = 0
    consecutive_load_failures = 0
    worker = Worker(adapter_file, cfg, args.load_timeout)
    model_id = cfg.get("model_id")
    aborted = None

    try:
        for p in selected:
            prev = by_id.get(p["id"])
            if prev and prev.get("status") == "success" and not args.force:
                skipped += 1
                continue
            sys.stdout.write(f"{p['id']} {p['title']:<34} ")
            sys.stdout.flush()
            run_at = iso_now()
            text = p["text"]
            try:
                if not worker.alive():
                    try:
                        worker.start()
                    except ImportError as e:
                        print(f"FAIL {str(e)[:120]}")
                        print(f"\nadapter '{slug}' cannot import its library: {e}\n"
                              f"install it with: pip install -r requirements/open-tts/{slug}.txt", file=sys.stderr)
                        return 3
                    consecutive_load_failures = 0
                    print(f"[model loaded in {worker.load_ms} ms: {worker.info.get('model_version')}]")
                    sys.stdout.write(f"{p['id']} {p['title']:<34} ")
                    sys.stdout.flush()
                if not worker.info.get("style_tags"):
                    text = strip_stage_directions(text)
                job = {"text": text, "language": p["language"], "instructions": p.get("instructions"),
                       "out_path": str(out_dir / f"{p['id']}.wav")}
                r = worker.request(job, args.timeout)
                from_cfg_voice = None
                try:
                    sys.path.insert(0, str(ADAPTERS_DIR))
                    from _common import pick_voice  # type: ignore

                    from_cfg_voice = pick_voice(p["language"], cfg)
                finally:
                    if sys.path and sys.path[0] == str(ADAPTERS_DIR):
                        sys.path.pop(0)
                by_id[p["id"]] = {
                    "prompt_id": p["id"], "run_at": run_at, "status": "success",
                    "audio": f"{p['id']}.wav", "bytes": r["bytes"],
                    "ttft_ms": r["ttft_ms"], "latency_ms": r["latency_ms"],
                    "voice": r.get("voice") or from_cfg_voice, "model": model_id, "endpoint": "local",
                    "streaming": r["streaming"], "device": "cpu",
                    "model_version": worker.info.get("model_version"), "sample_rate": r["sample_rate"],
                }
                ok += 1
                print(f"ok  ttfb {r['ttft_ms']:>5} ms  total {r['latency_ms']:>5} ms  {r['bytes']} B")
            except Exception as e:
                msg = str(e).splitlines()[0][:500] if str(e) else type(e).__name__
                by_id[p["id"]] = {"prompt_id": p["id"], "run_at": run_at, "status": "error",
                                  "error": msg, "model": model_id, "endpoint": "local", "device": "cpu"}
                failed += 1
                print(f"FAIL {msg[:120]}")
                if not worker.alive():
                    consecutive_load_failures += 1
                    if consecutive_load_failures >= 2:
                        aborted = "model failed to load twice; aborting (check the requirements file and network)"
                        print(str(e), file=sys.stderr)
                if failed >= 5 and ok == 0:
                    aborted = "5 consecutive failures with no success; aborting"
            finally:
                # wav left behind by a failed attempt must not masquerade as a result
                if by_id.get(p["id"], {}).get("status") == "error":
                    stale = out_dir / f"{p['id']}.wav"
                    if stale.exists():
                        stale.unlink()
                save()
            if aborted:
                print(aborted, file=sys.stderr)
                break
    finally:
        worker.close()

    print(f"\n{tool['slug']}: {ok} ok, {failed} failed, {skipped} skipped (already run). Runs in {runs_path}")
    return 1 if failed and not ok else 0


if __name__ == "__main__":
    sys.path.insert(0, str(ADAPTERS_DIR))  # lets adapters `from _common import ...`
    sys.exit(main())
