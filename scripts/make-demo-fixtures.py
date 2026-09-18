#!/usr/bin/env python3
"""Generate a FICTIONAL dataset for previewing the populated site layout.

Writes data/fixtures/demo-snapshot.json and one short tone per fictional tool
under apps/site/public/audio/demo/ (gitignored). Every tool name, score and
clip is invented. The site shows a noindex banner whenever this snapshot is
used, and nothing here is ever merged into data/snapshot.json.
"""
import json, math, random, struct, wave
from itertools import combinations
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "data" / "catalog" / "voice"
OUT = ROOT / "data" / "fixtures" / "demo-snapshot.json"
AUDIO_DIR = ROOT / "apps" / "site" / "public" / "audio" / "demo"

rng = random.Random(42)

category = json.loads((CATALOG / "category.json").read_text())
prompts = json.loads((CATALOG / "prompts.json").read_text())
metric_keys = [m["key"] for m in category["metrics"]]

# Fictional tools with a rough "personality" per metric so the pages look varied.
DEMO_TOOLS = [
    {"slug": "aria-voice",     "name": "Aria Voice",     "vendor": "Aria Labs (fictional)",     "bias": {"accuracy": 1.2, "naturalness": 1.0, "adherence": 0.8, "velocity": 0.6}, "ttft": 180, "lat": 1400, "hz": 330},
    {"slug": "cobalt-speech",  "name": "Cobalt Speech",  "vendor": "Cobalt (fictional)",        "bias": {"accuracy": 0.6, "naturalness": 1.4, "adherence": 0.7, "velocity": 0.2}, "ttft": 420, "lat": 2600, "hz": 392},
    {"slug": "meridian-tts",   "name": "Meridian TTS",   "vendor": "Meridian Cloud (fictional)","bias": {"accuracy": 0.9, "naturalness": 0.3, "adherence": 1.1, "velocity": 1.1}, "ttft": 140, "lat": 1100, "hz": 440},
    {"slug": "northwind-audio","name": "Northwind Audio","vendor": "Northwind (fictional)",     "bias": {"accuracy": 0.2, "naturalness": 0.5, "adherence": 0.4, "velocity": 1.4}, "ttft": 90,  "lat": 800,  "hz": 494},
    {"slug": "quill-voice",    "name": "Quill Voice",    "vendor": "Quill (fictional)",         "bias": {"accuracy": 0.7, "naturalness": 0.8, "adherence": 1.3, "velocity": 0.4}, "ttft": 300, "lat": 2000, "hz": 523},
]

def tone(path: Path, hz: float, seconds=1.2, rate=16000):
    n = int(seconds * rate)
    frames = bytearray()
    for i in range(n):
        env = min(1.0, i / (0.05 * rate), (n - i) / (0.2 * rate))  # fade in/out
        v = 0.35 * env * math.sin(2 * math.pi * hz * i / rate)
        frames += struct.pack("<h", int(v * 32767))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(bytes(frames))

def clamp(x, lo=1.0, hi=10.0): return max(lo, min(hi, x))

AUDIO_DIR.mkdir(parents=True, exist_ok=True)
run_at = datetime(2026, 9, 12, 6, 0, tzinfo=timezone.utc).isoformat()

tools, runs, ratings = [], [], []
for t in DEMO_TOOLS:
    tone(AUDIO_DIR / f"{t['slug']}.wav", t["hz"])
    tools.append({"slug": t["slug"], "name": t["name"], "vendor": t["vendor"], "website": "https://example.com",
                  "description": f"{t['name']} is a fictional text-to-speech API used to preview this site's layout.",
                  "category": "voice", "status": "verified" if t["slug"] in ("aria-voice", "meridian-tts") else "benchmarked"})
    per_metric = {k: [] for k in metric_keys}
    ttfts, lats = [], []
    for p in prompts:
        scores = {}
        for k in metric_keys:
            base = 6.0 + 2.5 * t["bias"][k]
            scores[k] = round(clamp(rng.gauss(base, 0.9)), 1)
            per_metric[k].append(scores[k])
        ttft = max(40, int(rng.gauss(t["ttft"], t["ttft"] * 0.25)))
        lat = max(ttft + 100, int(rng.gauss(t["lat"], t["lat"] * 0.2)))
        ttfts.append(ttft); lats.append(lat)
        composite = round(sum(scores.values()) / len(scores), 2)
        runs.append({"category": "voice", "tool": t["slug"], "prompt_id": p["id"], "run_at": run_at,
                     "audio_url": f"audio/demo/{t['slug']}.wav", "transcript": None,
                     "ttft_ms": ttft, "latency_ms": lat, "scores": scores, "composite": composite})
    avg = {k: round(sum(v) / len(v), 2) for k, v in per_metric.items()}
    ratings.append({"category": "voice", "tool": t["slug"], "runs": len(prompts),
                    "composite": round(sum(avg.values()) / len(avg), 2), "scores": avg,
                    "median_ttft_ms": sorted(ttfts)[len(ttfts) // 2], "median_latency_ms": sorted(lats)[len(lats) // 2], "rank": 0})

ratings.sort(key=lambda r: -r["composite"])
for i, r in enumerate(ratings): r["rank"] = i + 1
by_slug = {r["tool"]: r for r in ratings}
names = {t["slug"]: t["name"] for t in tools}
labels = {m["key"]: m["label"].lower() for m in category["metrics"]}

pairs = []
for a, b in combinations([t["slug"] for t in DEMO_TOOLS], 2):
    ra, rb = by_slug[a], by_slug[b]
    winner, loser = (a, b) if ra["composite"] >= rb["composite"] else (b, a)
    rw, rl = by_slug[winner], by_slug[loser]
    diffs = sorted(((rw["scores"][k] - rl["scores"][k], k) for k in metric_keys), reverse=True)
    lead = [k for d, k in diffs if d > 0.3][:2]
    trail = [k for d, k in diffs if d < -0.3]
    headline = f"{names[winner]} leads {names[loser]} {rw['composite']:.1f} to {rl['composite']:.1f} on the {len(prompts)}-prompt voice bank."
    parts = []
    if lead: parts.append(f"{names[winner]} is ahead on " + " and ".join(labels[k] for k in lead) + ".")
    if trail: parts.append(f"{names[loser]} wins on " + " and ".join(labels[k] for k in trail) + ".")
    parts.append(f"Median time to first byte: {names[a]} {ra['median_ttft_ms']} ms, {names[b]} {rb['median_ttft_ms']} ms.")
    pairs.append({"category": "voice", "slug": f"{a}-vs-{b}", "a": a, "b": b,
                  "verdict": {"headline": headline, "summary": " ".join(parts)}})

snapshot = {
    "version": 1, "generated_at": datetime.now(timezone.utc).isoformat(), "source": "demo", "demo": True,
    "categories": [{k: category[k] for k in ("slug", "name", "description", "output_modality", "metrics")}],
    "tools": tools,
    "prompts": [{"id": p["id"], "category": "voice", "rank": p["rank"], "title": p["title"], "language": p["language"],
                 "tags": p.get("tags", []), "text": p["text"], "instructions": p.get("instructions"), "constraints": p.get("constraints", [])} for p in prompts],
    "runs": runs, "ratings": ratings, "pairs": pairs,
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")
print(f"wrote {OUT}: {len(tools)} fictional tools, {len(runs)} runs, {len(pairs)} pairs; audio in {AUDIO_DIR}")
