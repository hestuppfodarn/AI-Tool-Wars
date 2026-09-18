#!/usr/bin/env python3
"""Runner for open-weight text models (GGUF via llama.cpp) that need no API key.

Text twin of scripts/run-open-tts.py: executes a text category's prompt bank
against one catalog tool whose adapter is "open-llm:<slug>", writes the raw
completion to <prompt-id>.md and a runs.json with the same envelope the other
runners write (prompt_id, run_at, status, ttft_ms, latency_ms, model, ...),
so the exporter and scorer treat every category alike.

    python3 scripts/run-open-llm.py --category legal --tool llama-3.2-3b
                                    [--limit 3] [--prompts legal-001,legal-002] [--force]
                                    [--out-dir data/runs/legal/llama-3.2-3b] [--timeout 600]
                                    [--threads 4] [--model-path local.gguf] [--catalog-dir DIR]

Catalog contract (data/catalog/<category>/tools.json):
    "adapter": "open-llm:<slug>",
    "run": {"gguf_repo": "<hf repo>", "gguf_file": "<file>.gguf", "context": 8192,
            "max_tokens": 700, "temperature": 0.2, "system": "..."}
Optional run keys: "gguf_url" (direct https URL instead of Hugging Face),
"gguf_revision", "seed" (default 42), "top_p", "top_k", "min_p", "repeat_penalty",
"chat_format" (a llama-cpp-python format name such as "chatml" or "llama-3"; default is
the Jinja template embedded in the GGUF, else llama-2), "stop" (extra stop strings).

Prompt framing: system = run.system (if any); user = prompt.instructions +
blank line + prompt.text (the text may embed a document). Nothing else is added.

Dependencies: requirements/open-llm/base.txt (llama-cpp-python CPU build +
huggingface_hub). The GGUF is downloaded once with huggingface_hub and cached
under HF_HOME (default ~/.cache/huggingface; OPEN_LLM_CACHE=<dir> moves it to
<dir>/hf). Set HF_HUB_OFFLINE=1 to fail fast instead of downloading.

Generation runs in a worker subprocess that loads the model once and drives
llama.cpp token by token (the chat is rendered with the template embedded in the
GGUF, exactly as llama-cpp-python's create_chat_completion would, then tokenised
once and fed to Llama.generate()), so ttft_ms is the real time to the first sampled
token and tokens_in/tokens_out are exact. Sampling matches llama-cpp-python's chat
defaults unless run overrides them: top_k 40, top_p 0.95, min_p 0.05,
repeat_penalty 1.1, seed 42. A prompt that
exceeds LLM_TIMEOUT_S (default 600) is recorded as an error; the worker is
killed and a fresh one is started for the next prompt. Nothing is retried
silently and failures are always written to runs.json. Successful prompts are
skipped on re-runs unless --force. After 5 failures with no success the run
aborts.

runs.json entry (success):
    prompt_id, run_at, status "success", output "<prompt-id>.md", output_chars,
    output_words, tokens_in (rendered prompt tokens), tokens_out, ttft_ms, latency_ms,
    tokens_per_s (decode rate: tokens after the first / seconds after the first token),
    finish_reason, model (gguf_repo), model_version, device "cpu",
    endpoint "local", threads, error null
runs.json entry (error): prompt_id, run_at, status "error", error, model,
    model_version, device, endpoint

Exit codes: 0 ran, 1 every attempted prompt failed, 2 usage error,
3 llama_cpp is not importable (pip install -r requirements/open-llm/base.txt).
"""
from __future__ import annotations

import argparse
import codecs
import importlib.util
import json
import multiprocessing as mp
import os
import re
import shutil
import sys
import tempfile
import time
import traceback
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADAPTER_PREFIX = "open-llm:"
WORD = re.compile(r"\w+(?:[.'’\-]\w+)*", re.UNICODE)  # "7.2", "don't", "re-run" are one word


# --- helpers ------------------------------------------------------------------

def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def load_env_file(path: Path) -> None:
    """Tiny .env loader, same rules as the other runners (never overrides the environment)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$", line)
        if m and os.environ.get(m.group(1)) is None:
            os.environ[m.group(1)] = m.group(2).strip().strip("\"'")


def default_cache_env() -> None:
    """GGUFs live in the huggingface_hub cache so CI can restore ~/.cache/huggingface.

    Precedence: HF_HOME if already set; else OPEN_LLM_CACHE/hf if OPEN_LLM_CACHE is set;
    else huggingface_hub's own default (~/.cache/huggingface).
    """
    cache = os.environ.get("OPEN_LLM_CACHE")
    if cache and not os.environ.get("HF_HOME"):
        os.environ["HF_HOME"] = str(Path(cache) / "hf")
    if os.environ.get("HF_HOME"):
        Path(os.environ["HF_HOME"]).mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("PYTHONUNBUFFERED", "1")


def cpu_threads() -> int:
    return int(os.environ.get("LLM_THREADS") or os.cpu_count() or 4)


def word_count(text: str) -> int:
    return len(WORD.findall(text))


def build_messages(prompt: dict, cfg: dict) -> list[dict]:
    """system = tool's run.system; user = instructions + blank line + text."""
    messages = []
    system = (cfg.get("system") or "").strip()
    if system:
        messages.append({"role": "system", "content": system})
    parts = [str(prompt.get("instructions") or "").strip(), str(prompt.get("text") or "").strip()]
    user = "\n\n".join(p for p in parts if p)
    messages.append({"role": "user", "content": user})
    return messages


def download_url(url: str, dest: Path, timeout: int = 300) -> Path:
    """Direct download (run.gguf_url) into the cache, atomic, skipped when present."""
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=dest.name + ".", dir=dest.parent)
    os.close(fd)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ai-tool-wars-open-llm/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as res, open(tmp, "wb") as out:
            shutil.copyfileobj(res, out, length=1 << 20)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return dest


def resolve_model_path(cfg: dict) -> str:
    """Local path from --model-path / OPEN_LLM_MODEL_PATH, else run.gguf_url, else Hugging Face."""
    explicit = cfg.get("model_path") or os.environ.get("OPEN_LLM_MODEL_PATH")
    if explicit:
        if not Path(explicit).exists():
            raise FileNotFoundError(f"model file not found: {explicit}")
        return str(explicit)
    gguf_file = cfg.get("gguf_file")
    if not gguf_file:
        raise ValueError("run.gguf_file is missing in the catalog entry")
    if cfg.get("gguf_url"):
        root = Path(os.environ.get("OPEN_LLM_CACHE") or Path.home() / ".cache" / "open-llm")
        return str(download_url(cfg["gguf_url"], root / "url" / gguf_file))
    if not cfg.get("gguf_repo"):
        raise ValueError("run.gguf_repo is missing in the catalog entry")
    from huggingface_hub import hf_hub_download

    return hf_hub_download(repo_id=cfg["gguf_repo"], filename=gguf_file, revision=cfg.get("gguf_revision"))


# --- worker process -------------------------------------------------------------

DEFAULT_SAMPLING = {"top_k": 40, "top_p": 0.95, "min_p": 0.05, "repeat_penalty": 1.1}


def render_chat(llm, messages: list[dict], cfg: dict) -> tuple[str, list[str], bool]:
    """(prompt text, stop strings, template_added_bos) the way llama-cpp-python renders
    a chat: run.chat_format names one of its built-in formats; otherwise the GGUF's
    tokenizer.chat_template (Jinja) is used; otherwise the llama-2 format."""
    from llama_cpp import llama_chat_format as cf

    name = cfg.get("chat_format")
    template = None if name else (llm.metadata or {}).get("tokenizer.chat_template")
    if template:
        eos_id, bos_id = llm.token_eos(), llm.token_bos()
        eos = llm._model.token_get_text(eos_id) if eos_id != -1 else ""
        bos = llm._model.token_get_text(bos_id) if bos_id != -1 else ""
        formatter = cf.Jinja2ChatFormatter(template=template, eos_token=eos, bos_token=bos, stop_token_ids=[eos_id])
        resp = formatter(messages=messages)
    else:
        # llama-cpp-python registers "llama-2" as format_llama2, "mistral-instruct" as
        # format_mistral_instruct, "chatml" as format_chatml: try both spellings.
        name = str(name or "llama-2")
        fn = getattr(cf, "format_" + name.replace("-", "_"), None) or getattr(cf, "format_" + name.replace("-", ""), None)
        if fn is None:
            known = ", ".join(sorted(n[7:] for n in dir(cf) if n.startswith("format_")))
            raise ValueError(f"unknown chat_format {name!r}; llama-cpp-python has: {known}")
        resp = fn(messages=messages)
    stop = resp.stop if isinstance(resp.stop, list) else ([resp.stop] if resp.stop else [])
    return resp.prompt, [str(x) for x in stop if x], bool(getattr(resp, "added_special", False))


def generate_text(llm, messages: list[dict], cfg: dict, timeout_s: float) -> dict:
    """Token-by-token generation with exact timings. Raises on timeout / empty output."""
    import llama_cpp

    prompt, stops, added_bos = render_chat(llm, messages, cfg)
    stops = stops + [str(x) for x in (cfg.get("stop") or [])]
    tokens = llm.tokenize(prompt.encode("utf-8"), add_bos=not added_bos, special=True)
    max_tokens = int(cfg.get("max_tokens") or 700)
    n_ctx = llm.n_ctx()
    if len(tokens) + max_tokens > n_ctx:
        raise ValueError(f"prompt ({len(tokens)} tokens) + max_tokens ({max_tokens}) exceed context {n_ctx}")
    sampling = {k: float(cfg.get(k, v)) for k, v in DEFAULT_SAMPLING.items()}
    sampling["top_k"] = int(sampling["top_k"])
    temperature = float(cfg.get("temperature", 0.2))

    # Drop the KV cache so ttft_ms always includes full prompt evaluation
    # (llama-cpp-python would otherwise reuse a shared prefix and make ttft
    # depend on prompt order).
    llm.reset()
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    deadline = time.perf_counter() + timeout_s
    t0 = time.perf_counter()
    pieces, ttft_ms, tokens_out, finish, timed_out = [], None, 0, "length", False
    for tok in llm.generate(tokens, temp=temperature, reset=True, **sampling):
        if ttft_ms is None:
            ttft_ms = round((time.perf_counter() - t0) * 1000)
        if llama_cpp.llama_token_is_eog(llm._model.vocab, tok):
            finish = "stop"
            break
        tokens_out += 1
        pieces.append(decoder.decode(llm.detokenize([tok], special=False)))
        if stops:
            tail = "".join(pieces[-8:])
            cut = [tail.find(x) for x in stops if x in tail]
            if cut:
                whole = "".join(pieces)
                idx = whole.rfind(tail) + min(cut)
                pieces, finish = [whole[:idx]], "stop"
                break
        if tokens_out >= max_tokens:
            break
        if time.perf_counter() > deadline:
            timed_out = True
            break
    pieces.append(decoder.decode(b"", final=True))
    latency_ms = round((time.perf_counter() - t0) * 1000)
    text = "".join(pieces)
    if timed_out:
        raise TimeoutError(f"generation exceeded {timeout_s:g}s (LLM_TIMEOUT_S) after {tokens_out} tokens")
    if not text.strip():
        raise RuntimeError("empty completion")
    decode_s = (latency_ms - (ttft_ms or 0)) / 1000
    tps = round((tokens_out - 1) / decode_s, 2) if tokens_out > 1 and decode_s > 0 else None
    return {"text": text, "tokens_in": len(tokens), "tokens_out": tokens_out,
            "ttft_ms": ttft_ms if ttft_ms is not None else latency_ms, "latency_ms": latency_ms,
            "tokens_per_s": tps, "finish_reason": finish}


def _worker_main(conn, cfg: dict) -> None:
    """Downloads + loads the GGUF once, then serves completion jobs over the pipe."""
    try:
        import llama_cpp
        from llama_cpp import Llama
    except ImportError as e:
        conn.send(("import_error", f"{type(e).__name__}: {e}"))
        return
    try:
        path = resolve_model_path(cfg)
        threads = int(cfg.get("threads") or cpu_threads())
        llm = Llama(model_path=path, n_ctx=int(cfg.get("context") or 8192), n_threads=threads,
                    n_threads_batch=threads, n_gpu_layers=0, seed=int(cfg.get("seed", 42)), verbose=False)
        # One-token warm-up so the first real prompt does not pay llama.cpp's
        # one-off thread-pool / graph allocation in its ttft_ms.
        for _ in llm.generate(llm.tokenize(b"Hi", add_bos=True), temp=0.0):
            break
        llm.reset()
        meta = getattr(llm, "metadata", {}) or {}
        name = meta.get("general.name") or Path(path).stem
        version = f"{Path(path).name} ({name}; llama-cpp-python {llama_cpp.__version__})"
        chat = "chat_format " + cfg["chat_format"] if cfg.get("chat_format") else \
            ("gguf chat template" if meta.get("tokenizer.chat_template") else "llama-2 fallback format")
    except Exception as e:  # download / load failure: reported, not hidden
        conn.send(("load_error", f"{type(e).__name__}: {str(e)[:400]}\n{traceback.format_exc()[-600:]}"))
        return
    conn.send(("ready", {"model_version": version, "threads": threads, "model_path": path, "chat": chat}))

    while True:
        job = conn.recv()
        if job is None:
            return
        try:
            r = generate_text(llm, job["messages"], cfg, float(job["timeout_s"]))
            text = r.pop("text")
            Path(job["out_path"]).write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
            r.update({"output_chars": len(text), "output_words": word_count(text)})
            conn.send(("ok", r))
        except Exception as e:
            conn.send(("err", f"{type(e).__name__}: {str(e)[:400]}"))


class Worker:
    """One model-loaded subprocess; killed and respawned after a timeout."""

    def __init__(self, cfg: dict, load_timeout_s: float):
        self.cfg = cfg
        self.load_timeout_s = load_timeout_s
        self.proc = None
        self.conn = None
        self.info = None
        self.load_ms = None

    def start(self):
        ctx = mp.get_context("spawn")
        parent, child = ctx.Pipe()
        self.proc = ctx.Process(target=_worker_main, args=(child, self.cfg), daemon=True)
        self.proc.start()
        child.close()
        self.conn = parent
        t0 = time.perf_counter()
        if not self.conn.poll(self.load_timeout_s):
            self.kill()
            raise TimeoutError(f"model download+load exceeded {self.load_timeout_s:g}s (LLM_LOAD_TIMEOUT_S)")
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
        # The worker stops itself at the deadline between tokens; the grace period
        # covers a single token (or prompt evaluation) that never returns.
        if not self.conn.poll(timeout_s + 30):
            self.kill()
            raise TimeoutError(f"generation exceeded {timeout_s:g}s (LLM_TIMEOUT_S); worker killed")
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
    ap = argparse.ArgumentParser(description="Run a text category's prompt bank against one open-weight GGUF model.")
    ap.add_argument("--category", required=True, help="catalog category, e.g. legal (data/catalog/<category>/)")
    ap.add_argument("--tool", required=True, help="catalog slug (adapter must be open-llm:<slug>)")
    ap.add_argument("--limit", type=int, help="only the first N prompts by rank")
    ap.add_argument("--prompts", help="comma-separated prompt ids")
    ap.add_argument("--force", action="store_true", help="re-run prompts that already succeeded")
    ap.add_argument("--out-dir", help="default data/runs/<category>/<slug>")
    ap.add_argument("--catalog-dir", help="default data/catalog/<category> (tests point this at a fixture)")
    ap.add_argument("--model-path", help="use this local GGUF instead of downloading run.gguf_repo/gguf_file "
                                         "(env OPEN_LLM_MODEL_PATH)")
    ap.add_argument("--threads", type=int, help="llama.cpp threads (env LLM_THREADS, default: all cores)")
    ap.add_argument("--timeout", type=float, default=float(os.environ.get("LLM_TIMEOUT_S", "600")),
                    help="per-prompt generation timeout in seconds (env LLM_TIMEOUT_S, default 600)")
    ap.add_argument("--load-timeout", type=float, default=float(os.environ.get("LLM_LOAD_TIMEOUT_S", "1800")),
                    help="model download+load timeout in seconds (env LLM_LOAD_TIMEOUT_S, default 1800)")
    args = ap.parse_args(argv)

    if importlib.util.find_spec("llama_cpp") is None:
        print("llama_cpp is not importable; install it with: pip install -r requirements/open-llm/base.txt",
              file=sys.stderr)
        return 3

    load_env_file(ROOT / ".env")
    default_cache_env()

    catalog_dir = Path(args.catalog_dir) if args.catalog_dir else ROOT / "data/catalog" / args.category
    tools_path, prompts_path = catalog_dir / "tools.json", catalog_dir / "prompts.json"
    if not tools_path.exists() or not prompts_path.exists():
        print(f"no catalog at {catalog_dir} (need tools.json and prompts.json)", file=sys.stderr)
        return 2
    tools = json.loads(tools_path.read_text(encoding="utf-8"))
    prompts = json.loads(prompts_path.read_text(encoding="utf-8"))
    tool = next((t for t in tools if t["slug"] == args.tool), None)
    if not tool:
        print(f"unknown tool {args.tool} in {tools_path}", file=sys.stderr)
        return 2
    adapter_name = str(tool.get("adapter", ""))
    if not adapter_name.startswith(ADAPTER_PREFIX):
        print(f"{tool['slug']} uses adapter '{adapter_name}', not an {ADAPTER_PREFIX}<slug> adapter", file=sys.stderr)
        return 2
    cfg = dict(tool.get("run") or {})
    if args.model_path:
        cfg["model_path"] = args.model_path
    if args.threads:
        cfg["threads"] = args.threads
    if not cfg.get("model_path") and not os.environ.get("OPEN_LLM_MODEL_PATH") and not cfg.get("gguf_file"):
        print(f"{tool['slug']}: run.gguf_file is missing in the catalog entry", file=sys.stderr)
        return 2
    model_id = cfg.get("gguf_repo") or tool.get("model_hint")

    out_dir = Path(args.out_dir) if args.out_dir else ROOT / "data/runs" / args.category / tool["slug"]
    out_dir.mkdir(parents=True, exist_ok=True)
    runs_path = out_dir / "runs.json"
    runs = json.loads(runs_path.read_text(encoding="utf-8")) if runs_path.exists() else []
    by_id = {r["prompt_id"]: r for r in runs}

    selected = sorted(prompts, key=lambda p: p["rank"])
    if args.prompts:
        ids = set(s.strip() for s in args.prompts.split(",") if s.strip())
        selected = [p for p in selected if p["id"] in ids]
    if args.limit:
        selected = selected[: args.limit]

    def save():
        ordered = sorted(by_id.values(), key=lambda r: r["prompt_id"])
        runs_path.write_text(json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    ok = failed = skipped = 0
    consecutive_load_failures = 0
    worker = Worker(cfg, args.load_timeout)
    aborted = None
    model_version = None

    try:
        for p in selected:
            prev = by_id.get(p["id"])
            if prev and prev.get("status") == "success" and not args.force:
                skipped += 1
                continue
            run_at = iso_now()
            out_path = out_dir / f"{p['id']}.md"
            try:
                if not worker.alive():
                    print(f"loading {tool['slug']} model (first prompt or after a timeout) ...")
                    try:
                        worker.start()
                    except ImportError as e:
                        print(f"\nllama_cpp cannot be imported in the worker: {e}\n"
                              f"install it with: pip install -r requirements/open-llm/base.txt", file=sys.stderr)
                        return 3
                    except Exception:
                        sys.stdout.write(f"{p['id']} {p['title']:<34} ")
                        raise
                    consecutive_load_failures = 0
                    model_version = worker.info.get("model_version")
                    print(f"model loaded in {worker.load_ms} ms ({worker.info.get('threads')} threads, "
                          f"{worker.info.get('chat')}): {model_version}")
                sys.stdout.write(f"{p['id']} {p['title']:<34} ")
                sys.stdout.flush()
                job = {"messages": build_messages(p, cfg), "out_path": str(out_path), "timeout_s": args.timeout}
                r = worker.request(job, args.timeout)
                by_id[p["id"]] = {
                    "prompt_id": p["id"], "run_at": run_at, "status": "success",
                    "output": out_path.name, "output_chars": r["output_chars"], "output_words": r["output_words"],
                    "tokens_in": r["tokens_in"], "tokens_out": r["tokens_out"],
                    "ttft_ms": r["ttft_ms"], "latency_ms": r["latency_ms"], "tokens_per_s": r["tokens_per_s"],
                    "finish_reason": r["finish_reason"],
                    "model": model_id, "model_version": model_version,
                    "device": "cpu", "endpoint": "local", "threads": worker.info.get("threads"),
                    "error": None,
                }
                ok += 1
                print(f"ok  ttft {r['ttft_ms']:>5} ms  total {r['latency_ms']:>6} ms  "
                      f"{r['tokens_out']} tok  {r['tokens_per_s'] or 0:.1f} tok/s  {r['output_chars']} chars")
            except Exception as e:
                msg = str(e).splitlines()[0][:500] if str(e) else type(e).__name__
                by_id[p["id"]] = {"prompt_id": p["id"], "run_at": run_at, "status": "error", "error": msg,
                                  "model": model_id, "model_version": model_version,
                                  "device": "cpu", "endpoint": "local"}
                failed += 1
                print(f"FAIL {msg[:120]}")
                if not worker.alive():
                    consecutive_load_failures += 1
                    if consecutive_load_failures >= 2:
                        aborted = "model failed to load twice; aborting (check the catalog entry and network)"
                        print(str(e), file=sys.stderr)
                if failed >= 5 and ok == 0:
                    aborted = "5 failures with no success; aborting"
            finally:
                # an .md left behind by a failed attempt must not masquerade as a result
                if by_id.get(p["id"], {}).get("status") == "error" and out_path.exists():
                    out_path.unlink()
                save()
            if aborted:
                print(aborted, file=sys.stderr)
                break
    finally:
        worker.close()

    print(f"\n{tool['slug']}: {ok} ok, {failed} failed, {skipped} skipped (already run). Runs in {runs_path}")
    return 1 if failed and not ok else 0


if __name__ == "__main__":
    sys.exit(main())
