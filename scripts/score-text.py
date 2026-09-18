#!/usr/bin/env python3
"""Keyless, deterministic scorer for recorded text runs (data/runs/<category>/<tool>/runs.json).

    python3 scripts/score-text.py --category legal --tool llama-3.2-3b-instruct [--force]
                                  [--catalog-dir DIR] [--runs-dir DIR]

Text twin of scripts/score-open.py. Every successful run's <prompt-id>.md is checked
against the prompt's `rubric` (data/catalog/<category>/prompts.json) with plain string,
regex, word-count, language and format rules, so scoring needs no model, no network and
no API key, and re-running it always gives the same numbers. It implements the
`rubric_contract` published in data/catalog/<category>/category.json (version 1):

  normalisation   NFC, curly quotes and dashes mapped to straight ones, lowercased,
                  whitespace collapsed. Substring and regex checks run on that text
                  (regex with re.IGNORECASE | re.MULTILINE). words = len(output.split()).
  item            {id, type, value, weight?} ("kind" is accepted as an alias of "type")
  metric          accuracy : must_include, must_not_include, regex, cites_only
                  adherence: max_words, min_words, language, format
  score           per metric: 10 x sum(weight x hit) / sum(weight), one decimal
                  (weight default 1); null when the metric has no items
  conciseness     target = prompt.target_words, else the smallest max_words item, else 300
                  density = (accuracy / 10) / max(1, words / target)
                  conciseness = max(1, round(10 x min(1, density), 1)); null if accuracy is null
  empty output    accuracy 0 (10 if the accuracy items are all must_not_include),
                  adherence per the rules, conciseness 1
  velocity        left null: it is a rank across tools, so the exporter derives it

Item types (`value` per type):
  must_include      "text" or ["alt 1", "alt 2"]: the normalised output contains the value,
                    or at least one alternative ("match": "all" requires every entry)
  must_not_include  "text" or ["a", "b"]: none of the values occurs
  regex             "pattern" or ["p1", "p2"]: re.search matches (any); item "flags"
                    overrides the default "im"
  max_words / min_words   int, inclusive bound on words
  language          "en" | "sv" | "de" | "fr" | "es" (a region tag such as "sv-SE" is
                    reduced to its base): the stopword-ratio detector's top language equals
                    the value; a tie goes to the prompt's language
  format            "json" (whole output or the first ``` fenced block parses),
                    "markdown_table" (a |...| line plus a dashes-and-pipes separator line),
                    "numbered_list" (>= 3 lines starting "1." or "1)"),
                    "bullet_list" (>= 3 lines starting "-", "*" or "•"),
                    "headings" (>= 2 lines starting "#"),
                    "tracked_changes" (>= 1 "[-...-]" deletion and >= 1 "{+...+}" insertion)
  extensions        format_json (true or ["key", ...]: like format json, optionally with
                    required top-level keys), format_markdown_table (true, a minimum number
                    of data rows, or ["header", ...]), cites_only (["Clause 4", ...]: every
                    citation found by CITATION, or item "pattern", is an allowed reference;
                    item "min" requires at least that many citations)
An unknown type is recorded as a miss under adherence so a typo in the catalog cannot
silently inflate a score.

Written back into runs.json per successful run:
  scores.{accuracy, adherence, conciseness} (+ velocity null if absent),
  rubric_hits: [{id, type, metric, weight, hit, note}], words, target_words, scored_at.
A run whose output file cannot be read gets score_error instead and is counted as failed.
Exit status is 1 only when something was attempted and nothing succeeded.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ACCURACY_TYPES = ("must_include", "must_not_include", "regex", "cites_only")
ADHERENCE_TYPES = ("max_words", "min_words", "language", "format", "format_json", "format_markdown_table")
FORMATS = ("json", "markdown_table", "numbered_list", "bullet_list", "headings", "tracked_changes")
DEFAULT_TARGET_WORDS = 300

WS = re.compile(r"\s+")
CITATION = re.compile(
    r"(?:clauses?|sections?|articles?|paragraphs?|sec\.|art\.|para\.|§§?)\s*(\d+(?:\.\d+)*[a-z]?(?:\(\w+\))*)",
    re.IGNORECASE)
CITATION_NUMBER = re.compile(r"\d+(?:\.\d+)*[a-z]?(?:\(\w+\))*")
FENCE = re.compile(r"```[a-zA-Z0-9_-]*[ \t]*\r?\n?(.*?)```", re.DOTALL)
TABLE_ROW = re.compile(r"^\|.*\|$")
TABLE_SEPARATOR = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$")
NUMBERED = re.compile(r"^\s*\d+[.)]\s+\S")
BULLET = re.compile(r"^\s*[-*•]\s+\S")
HEADING = re.compile(r"^\s*#{1,6}\s+\S")
DELETION = re.compile(r"\[-.+?-\]", re.DOTALL)
INSERTION = re.compile(r"\{\+.+?\+\}", re.DOTALL)
TOKEN = re.compile(r"\w+(?:['’-]\w+)*", re.UNICODE)

# Small, mostly language-exclusive function words. Shared words (e.g. "in", "a") are
# listed for one language only or left out so votes stay distinctive.
STOPWORDS = {
    "en": {"the", "and", "of", "to", "is", "are", "that", "this", "with", "for", "from", "not", "be", "by", "on",
           "it", "as", "or", "was", "were", "will", "shall", "must", "may", "which", "their", "any", "party",
           "agreement", "within", "days", "under", "has", "have", "been", "at", "an", "if", "would", "should"},
    "sv": {"och", "att", "det", "som", "är", "av", "för", "med", "inte", "den", "till", "på", "ett", "en", "har",
           "kan", "ska", "skall", "från", "eller", "om", "vid", "enligt", "får", "denna", "detta", "vara",
           "avtalet", "parterna", "månader", "dagar", "utan", "endast", "också", "mellan", "under", "sägas", "hyran"},
    "de": {"und", "der", "die", "das", "ist", "nicht", "mit", "für", "von", "zu", "auf", "dem", "den", "ein",
           "eine", "sich", "wird", "werden", "oder", "auch", "bei", "nach", "aus", "als", "kann", "muss", "diese",
           "vertrag", "vertrages", "tage", "monate", "innerhalb", "gemäß", "sowie", "durch", "zwischen"},
    "fr": {"le", "la", "les", "et", "des", "est", "une", "pas", "que", "qui", "dans", "pour", "par", "sur", "avec",
           "ce", "cette", "ne", "au", "aux", "du", "sont", "être", "ou", "doit", "peut", "contrat", "jours",
           "mois", "selon", "entre", "sans", "également", "partie", "parties", "délai"},
    "es": {"el", "los", "las", "y", "es", "una", "un", "no", "que", "en", "para", "por", "con", "se", "del",
           "al", "su", "sus", "son", "ser", "o", "debe", "puede", "contrato", "días", "meses", "según", "entre",
           "sin", "también", "parte", "partes", "plazo", "este", "esta", "como", "más"},
}


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def js_round(x: float, decimals: int = 0) -> float:
    """JavaScript Math.round semantics (halves go up), scaled like Math.round(x*k)/k."""
    k = 10 ** decimals
    v = math.floor(x * k + 0.5) / k
    return int(v) if v.is_integer() else v


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def word_count(text: str) -> int:
    """The contract's definition: len(output.split()) on the raw output."""
    return len(text.split())


def norm(text: str) -> str:
    """NFC, straight quotes/dashes, lowercase, whitespace collapsed to single spaces."""
    text = unicodedata.normalize("NFC", text)
    for a, b in (("’", "'"), ("‘", "'"), ("‚", "'"), ("“", '"'), ("”", '"'), ("„", '"'),
                 ("–", "-"), ("—", "-"), ("‑", "-"), (" ", " ")):
        text = text.replace(a, b)
    return WS.sub(" ", text).strip().lower()


def as_list(value) -> list:
    return list(value) if isinstance(value, (list, tuple)) else [value]


def lang_base(tag) -> str:
    return str(tag or "").split("-")[0].split("_")[0].lower()


def item_type(item: dict) -> str:
    return str(item.get("type") or item.get("kind") or "")


# ---------------------------------------------------------------------------
# detectors
# ---------------------------------------------------------------------------
def language_scores(text: str) -> dict[str, float]:
    """Ratio of stopword hits per language over the output's tokens (0 when no tokens)."""
    toks = [t.lower() for t in TOKEN.findall(unicodedata.normalize("NFC", text))]
    if not toks:
        return {lang: 0.0 for lang in STOPWORDS}
    return {lang: sum(1 for t in toks if t in sw) / len(toks) for lang, sw in STOPWORDS.items()}


def detect_language(text: str, tie_break: str | None = None) -> str | None:
    """Top language by stopword ratio. A tie goes to `tie_break` (the prompt's language)
    when it is among the tied languages; None when nothing matched or the tie stands."""
    scores = language_scores(text)
    best = max(scores.values())
    if best <= 0:
        return None
    top = sorted(lang for lang, s in scores.items() if s == best)
    if len(top) == 1:
        return top[0]
    tb = lang_base(tie_break)
    return tb if tb in top else None


def extract_json(text: str):
    """The whole output, else the first ``` fenced block, else the first balanced {...}/[...]."""
    candidates = [text.strip()]
    m = FENCE.search(text)
    if m:
        candidates.append(m.group(1).strip())
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start != -1:
            depth = 0
            for i in range(start, len(text)):
                if text[i] == opener:
                    depth += 1
                elif text[i] == closer:
                    depth -= 1
                    if depth == 0:
                        candidates.append(text[start:i + 1])
                        break
    for c in candidates:
        if not c:
            continue
        try:
            return json.loads(c)
        except ValueError:
            continue
    raise ValueError("no JSON document found")


def split_row(line: str) -> list[str]:
    cells = line.strip()
    if cells.startswith("|"):
        cells = cells[1:]
    if cells.endswith("|"):
        cells = cells[:-1]
    return [c.strip() for c in cells.split("|")]


def markdown_tables(text: str) -> list[dict]:
    """Every markdown table as {"headers": [...], "rows": [[...], ...]} (header row, then a
    dashes-and-pipes separator line, then the contiguous |...| rows)."""
    lines = [ln.strip() for ln in text.splitlines()]
    tables = []
    i = 0
    while i < len(lines) - 1:
        if "|" in lines[i] and TABLE_SEPARATOR.match(lines[i + 1]):
            headers = split_row(lines[i])
            rows = []
            j = i + 2
            while j < len(lines) and "|" in lines[j] and lines[j]:
                rows.append(split_row(lines[j]))
                j += 1
            tables.append({"headers": headers, "rows": rows})
            i = j
        else:
            i += 1
    return tables


def check_format(fmt: str, text: str) -> tuple[bool, str]:
    lines = text.splitlines()
    if fmt == "json":
        try:
            extract_json(text)
            return (True, "valid JSON")
        except ValueError as e:
            return (False, str(e))
    if fmt == "markdown_table":
        stripped = [ln.strip() for ln in lines]
        rows = sum(1 for ln in stripped if TABLE_ROW.match(ln) and not TABLE_SEPARATOR.match(ln))
        seps = sum(1 for ln in stripped if TABLE_SEPARATOR.match(ln) and "|" in ln)
        ok = rows >= 1 and seps >= 1
        return (ok, f"{rows} table row(s), {seps} separator(s)")
    if fmt == "numbered_list":
        n = sum(1 for ln in lines if NUMBERED.match(ln))
        return (n >= 3, f"{n} numbered line(s), need 3")
    if fmt == "bullet_list":
        n = sum(1 for ln in lines if BULLET.match(ln))
        return (n >= 3, f"{n} bullet line(s), need 3")
    if fmt == "headings":
        n = sum(1 for ln in lines if HEADING.match(ln))
        return (n >= 2, f"{n} heading line(s), need 2")
    if fmt == "tracked_changes":
        d, i = len(DELETION.findall(text)), len(INSERTION.findall(text))
        return (d >= 1 and i >= 1, f"{d} deletion(s), {i} insertion(s)")
    return (False, f"unknown format {fmt!r}")


def norm_citation(ref: str) -> str:
    """'Clause 7.2', '§ 7.2', '7.2' -> '7.2' (the number part, lowercase)."""
    m = CITATION_NUMBER.search(ref)
    return (m.group(0) if m else ref).strip().lower()


# ---------------------------------------------------------------------------
# rubric evaluation: evaluate_item(item, text, prompt_language) -> (hit, note)
# ---------------------------------------------------------------------------
def evaluate_item(item: dict, text: str, prompt_language: str | None = None) -> tuple[bool, str]:
    kind = item_type(item)
    value = item.get("value")
    n = norm(text)

    if kind == "must_include":
        alts = [norm(str(v)) for v in as_list(value)]
        hits = [a for a in alts if a and a in n]
        if item.get("match") == "all":
            missing = [a for a in alts if a not in hits]
            return (not missing, "all present" if not missing else "missing: " + ", ".join(missing))
        return (bool(hits), "found: " + hits[0] if hits else "none of: " + ", ".join(alts))

    if kind == "must_not_include":
        found = [norm(str(v)) for v in as_list(value) if norm(str(v)) and norm(str(v)) in n]
        return (not found, "found forbidden: " + ", ".join(found) if found else "absent")

    if kind == "regex":
        flags = 0
        for ch in str(item.get("flags", "im")).lower():
            flags |= {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL, "x": re.VERBOSE}.get(ch, 0)
        for pattern in as_list(value):
            m = re.search(str(pattern), n, flags)
            if m:
                return (True, f"matched {m.group(0)[:60]!r}")
        return (False, "no match")

    if kind in ("max_words", "min_words"):
        count = word_count(text)
        limit = int(value)
        ok = count <= limit if kind == "max_words" else count >= limit
        return (ok, f"{count} words, limit {limit}")

    if kind == "language":
        want = lang_base(value)
        if want not in STOPWORDS:
            return (False, f"unsupported language {value!r}")
        got = detect_language(text, prompt_language)
        return (got == want, f"detected {got or 'unknown'}, wanted {want}")

    if kind == "format":
        return check_format(str(value), text)

    if kind == "format_json":
        try:
            doc = extract_json(text)
        except ValueError as e:
            return (False, str(e))
        if isinstance(value, (list, tuple)):
            if not isinstance(doc, dict):
                return (False, "JSON is not an object")
            missing = [k for k in value if k not in doc]
            return (not missing, "keys present" if not missing else "missing keys: " + ", ".join(map(str, missing)))
        return (True, "valid JSON")

    if kind == "format_markdown_table":
        tables = markdown_tables(text)
        if not tables:
            return (False, "no markdown table")
        if isinstance(value, bool) or value is None:
            ok = any(t["rows"] for t in tables)
            return (ok, "table with rows" if ok else "table has no data rows")
        if isinstance(value, int):
            best = max(len(t["rows"]) for t in tables)
            return (best >= value, f"{best} data rows, need {value}")
        wanted = [norm(str(v)) for v in as_list(value)]
        for t in tables:
            headers = [norm(h) for h in t["headers"]]
            missing = [w for w in wanted if not any(w in h for h in headers)]
            if not missing and t["rows"]:
                return (True, "headers " + ", ".join(t["headers"]))
        return (False, "no table with headers " + ", ".join(wanted) + " and data rows")

    if kind == "cites_only":
        pattern = re.compile(item["pattern"], re.IGNORECASE) if item.get("pattern") else CITATION
        allowed = {norm_citation(str(v)) for v in as_list(value)}
        cited = []
        for m in pattern.finditer(text):
            ref = m.group(1) if m.groups() else m.group(0)
            cited.append(norm_citation(ref))
        minimum = int(item.get("min", 0))
        if len(cited) < minimum:
            return (False, f"{len(cited)} citation(s), need {minimum}")
        bad = sorted({c for c in cited if c not in allowed})
        if bad:
            return (False, "cites outside the source: " + ", ".join(bad))
        return (True, f"{len(cited)} citation(s), all allowed" if cited else "no citations")

    return (False, f"unknown type {kind!r}")


def metric_of(kind: str) -> str | None:
    if kind in ACCURACY_TYPES:
        return "accuracy"
    if kind in ADHERENCE_TYPES:
        return "adherence"
    return None


def weight_of(item: dict) -> float:
    try:
        w = float(item.get("weight", 1))
    except (TypeError, ValueError):
        w = 1.0
    return max(w, 0.0)


def metric_score(hits: list[dict], metric: str):
    """10 x sum(weight x hit) / sum(weight) over the items of `metric`; None without items."""
    items = [h for h in hits if h["metric"] == metric and h["weight"] > 0]
    total = sum(h["weight"] for h in items)
    if total <= 0:
        return None
    return js_round(10 * sum(h["weight"] for h in items if h["hit"]) / total, 1)


def conciseness_target(prompt: dict, rubric: list[dict]) -> int:
    if isinstance(prompt.get("target_words"), (int, float)) and prompt["target_words"] > 0:
        return int(prompt["target_words"])
    limits = [int(i["value"]) for i in rubric if item_type(i) == "max_words" and i.get("value") is not None]
    return min(limits) if limits else DEFAULT_TARGET_WORDS


def conciseness_score(accuracy, words: int, target: int):
    """density = (accuracy / 10) / max(1, words / target); max(1, round(10 x min(1, density), 1))."""
    if accuracy is None:
        return None
    if words <= 0:
        return 1
    density = (accuracy / 10) / max(1.0, words / max(target, 1))
    return max(1, js_round(10 * min(1.0, density), 1))


def score_text(text: str, rubric: list[dict], prompt: dict | None = None) -> dict:
    """Pure function used by main() and the tests: scores + rubric_hits + words + target_words."""
    prompt = prompt or {}
    hits = []
    for idx, item in enumerate(rubric or []):
        kind = item_type(item)
        metric = metric_of(kind) or "adherence"   # a typo counts as a miss, never vanishes
        hit, note = evaluate_item(item, text, prompt.get("language"))
        hits.append({"id": str(item.get("id") or f"item-{idx + 1}"), "type": kind, "metric": metric,
                     "weight": weight_of(item), "hit": bool(hit), "note": note})
    words = word_count(text)
    target = conciseness_target(prompt, rubric or [])
    accuracy = metric_score(hits, "accuracy")
    adherence = metric_score(hits, "adherence")
    if not text.strip() and accuracy is not None:
        acc_types = {h["type"] for h in hits if h["metric"] == "accuracy" and h["weight"] > 0}
        accuracy = 10 if acc_types == {"must_not_include"} else 0
    conciseness = conciseness_score(accuracy, words, target)
    if not text.strip() and conciseness is not None:
        conciseness = 1
    return {
        "scores": {"accuracy": accuracy, "adherence": adherence, "conciseness": conciseness, "velocity": None},
        "rubric_hits": hits,
        "words": words,
        "target_words": target,
    }


# ---------------------------------------------------------------------------
def fmt(v) -> str:
    return "–" if v is None else str(v)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--category", required=True, help="catalog category, e.g. legal")
    ap.add_argument("--tool", required=True, help="tool slug under data/runs/<category>/")
    ap.add_argument("--force", action="store_true", help="re-score runs that already have scores")
    ap.add_argument("--catalog-dir", help="default data/catalog/<category> (tests point this at a fixture)")
    ap.add_argument("--runs-dir", help="default data/runs/<category>/<tool>")
    args = ap.parse_args(argv)

    catalog_dir = Path(args.catalog_dir) if args.catalog_dir else ROOT / "data/catalog" / args.category
    prompts_path = catalog_dir / "prompts.json"
    if not prompts_path.exists():
        print(f"no prompts at {prompts_path}", file=sys.stderr)
        return 1
    prompts = json.loads(prompts_path.read_text(encoding="utf-8"))
    by_prompt = {p["id"]: p for p in prompts}
    run_dir = Path(args.runs_dir) if args.runs_dir else ROOT / "data/runs" / args.category / args.tool
    runs_path = run_dir / "runs.json"
    if not runs_path.exists():
        print(f"no runs at {runs_path}", file=sys.stderr)
        return 1
    runs = json.loads(runs_path.read_text(encoding="utf-8"))

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
        if run.get("rubric_hits") is not None and run.get("scored_at") and not args.force:
            skipped += 1
            continue
        sys.stdout.write(f"{run['prompt_id']} ")
        sys.stdout.flush()
        t0 = time.time()
        try:
            out_name = run.get("output")
            if not out_name:
                raise RuntimeError("run has no output file")
            text = (run_dir / out_name).read_text(encoding="utf-8")
            result = score_text(text, prompt.get("rubric") or [], prompt)
            scores = run.setdefault("scores", {})
            for k in ("accuracy", "adherence", "conciseness"):
                scores[k] = result["scores"][k]
            scores.setdefault("velocity", None)  # the exporter's rank; never computed here
            run["rubric_hits"] = result["rubric_hits"]
            run["words"] = result["words"]
            run["target_words"] = result["target_words"]
            run.pop("score_error", None)
            run["scored_at"] = now_iso()
            scored += 1
            n_hit = sum(1 for h in result["rubric_hits"] if h["hit"])
            print(f"accuracy {fmt(scores['accuracy'])}  adherence {fmt(scores['adherence'])}  "
                  f"conciseness {fmt(scores['conciseness'])}  rubric {n_hit}/{len(result['rubric_hits'])}  "
                  f"{result['words']} words / target {result['target_words']}  ({time.time() - t0:.2f}s)")
        except Exception as e:  # noqa: BLE001 - failures are recorded per run, never hidden
            failed += 1
            run["score_error"] = f"{type(e).__name__}: {str(e)[:200]}"
            print(f"FAIL {str(e)[:140]}")
        save()

    print(f"\n{args.tool}: {scored} scored, {failed} failed, {skipped} skipped")
    return 1 if failed and not scored else 0


if __name__ == "__main__":
    sys.exit(main())
