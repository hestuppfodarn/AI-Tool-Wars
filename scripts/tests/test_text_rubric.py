"""Unit tests for the rubric evaluator in scripts/score-text.py.

Run with `python3 -m pytest scripts/tests` or plain `python3 scripts/tests/test_text_rubric.py`.
Every rubric type of the contract in data/catalog/legal/category.json (must_include,
must_not_include, regex, max_words, min_words, language, format x six values) plus the
extensions (format_json, format_markdown_table, cites_only) has a hit and a miss case, and
the metric, conciseness and empty-output formulas are pinned to exact values.
"""
import importlib.util
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location("score_text", Path(__file__).resolve().parent.parent / "score-text.py")
score_text = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(score_text)

evaluate_item, score = score_text.evaluate_item, score_text.score_text
conciseness_score, detect_language, norm = score_text.conciseness_score, score_text.detect_language, score_text.norm

SV = "Avtalet kan sägas upp med tre månaders uppsägningstid och hyran betalas i förskott varje månad."
EN = "The parties agree that the fees are payable within 14 days of the invoice and that notice is required."


def hit(item, text, lang=None):
    ok, _note = evaluate_item(item, text, lang)
    return ok


# --- normalisation -------------------------------------------------------------------
def test_norm_quotes_dashes_case_whitespace():
    assert norm("  “Thirty” days’  notice — 2024–2025 ") == '"thirty" days\' notice - 2024-2025'
    assert norm("Ångström") == norm("Ångström")   # NFC


def test_words_is_split_on_raw_output():
    assert score_text.word_count("| a | b |\n|---|---|\n| c | d |") == 10
    assert score_text.word_count("  one\ttwo\n\nthree  ") == 3


# --- must_include ------------------------------------------------------------------
def test_must_include_string_is_case_and_whitespace_insensitive():
    assert hit({"type": "must_include", "value": "30 Days"}, "Notice of  30 days is required.")
    assert not hit({"type": "must_include", "value": "30 days"}, "Notice of one month.")


def test_must_include_list_means_any_alternative_and_kind_alias():
    item = {"kind": "must_include", "value": ["clause 7.3", "7.3"]}
    assert hit(item, "See 7.3(ii).")
    assert not hit(item, "See clause 7.4.")


def test_must_include_match_all():
    item = {"type": "must_include", "value": ["Acme", "Nordic"], "match": "all"}
    assert hit(item, "Acme sells to Nordic.")
    assert not hit(item, "Acme sells to someone.")


def test_must_include_curly_quotes_normalised():
    assert hit({"type": "must_include", "value": "days' notice"}, "thirty days’ notice")


# --- must_not_include -----------------------------------------------------------------
def test_must_not_include():
    item = {"type": "must_not_include", "value": ["clause 9", "7.5"]}
    assert hit(item, "Clause 7.3 applies.")
    assert not hit(item, "See CLAUSE 9.")


# --- regex -------------------------------------------------------------------------
def test_regex_runs_on_normalised_text_ignorecase_multiline():
    assert hit({"type": "regex", "value": r"\b(24|twenty-?four)\b[^.]{0,20}months"}, "a Twenty-Four month tail")
    assert hit({"type": "regex", "value": r"^clause\s*4"}, "Summary:\nClause 4 says...")
    assert not hit({"type": "regex", "value": r"clause\s*99"}, "Clause 4 says...")


def test_regex_list_is_any_and_flags_override():
    assert hit({"type": "regex", "value": [r"nope", r"\b14 days\b"]}, "within 14 days")
    assert hit({"type": "regex", "value": r"clause 4", "flags": ""}, "Clause 4")   # text is lowercased anyway


# --- word counts ----------------------------------------------------------------------
def test_max_and_min_words_inclusive():
    five = "one two three four five"
    assert hit({"type": "max_words", "value": 5}, five)
    assert not hit({"type": "max_words", "value": 4}, five)
    assert hit({"type": "min_words", "value": 5}, five)
    assert not hit({"type": "min_words", "value": 6}, five)


# --- language ----------------------------------------------------------------------
def test_language_detection_heuristic():
    assert detect_language(EN) == "en"
    assert detect_language(SV) == "sv"
    assert detect_language("Der Vertrag kann mit einer Frist von drei Monaten gekündigt werden.") == "de"
    assert detect_language("Le contrat peut être résilié avec un préavis de trois mois par les parties.") == "fr"
    assert detect_language("El contrato puede ser terminado con un plazo de tres meses por las partes.") == "es"
    assert detect_language("") is None
    assert detect_language("xyzzy plugh 12345") is None


def test_language_tie_goes_to_prompt_language():
    tie = "sin le"       # one es stopword, one fr stopword
    assert detect_language(tie) is None
    assert detect_language(tie, "fr-FR") == "fr"
    assert detect_language(tie, "en") is None
    assert hit({"type": "language", "value": "fr"}, tie, "fr")
    assert not hit({"type": "language", "value": "fr"}, tie, "sv")


def test_language_item_accepts_region_tags():
    assert hit({"type": "language", "value": "sv-SE"}, SV)
    assert not hit({"type": "language", "value": "en"}, SV)
    assert not hit({"type": "language", "value": "xx"}, SV)


# --- format --------------------------------------------------------------------------
def test_format_json():
    assert hit({"type": "format", "value": "json"}, '{"a": 1}')
    assert hit({"type": "format", "value": "json"}, 'Sure:\n```json\n{"a": [1, 2]}\n```\nDone.')
    assert hit({"type": "format", "value": "json"}, 'Result: {"a": {"b": 1}} end')
    assert not hit({"type": "format", "value": "json"}, "no json here {oops")


TABLE = "Intro\n\n| Villkor | Värde |\n|---|---|\n| Uppsägningstid | tre månader |\n| Hyra | förskott |\n"


def test_format_markdown_table():
    assert hit({"type": "format", "value": "markdown_table"}, TABLE)
    assert hit({"type": "format", "value": "markdown_table"}, "| a | b |\n| :--- | ---: |\n| 1 | 2 |")
    assert not hit({"type": "format", "value": "markdown_table"}, "| a | b |\nno separator row")
    assert not hit({"type": "format", "value": "markdown_table"}, "a | b\n---|---\n1 | 2")   # rows need outer pipes


def test_format_lists_and_headings():
    assert hit({"type": "format", "value": "numbered_list"}, "1. a\n2. b\n3) c")
    assert not hit({"type": "format", "value": "numbered_list"}, "1. a\n2. b")
    assert hit({"type": "format", "value": "bullet_list"}, "- a\n* b\n• c\n")
    assert not hit({"type": "format", "value": "bullet_list"}, "- a\n- b\nc")
    assert hit({"type": "format", "value": "headings"}, "# A\ntext\n## B")
    assert not hit({"type": "format", "value": "headings"}, "# A only")


def test_format_tracked_changes_and_unknown():
    assert hit({"type": "format", "value": "tracked_changes"}, "The term is [-12-]{+24+} months.")
    assert not hit({"type": "format", "value": "tracked_changes"}, "The term is [-12-] months.")
    assert not hit({"type": "format", "value": "tracked_changes"}, "The term is {+24+} months.")
    assert not hit({"type": "format", "value": "pdf"}, "anything")


# --- extensions -----------------------------------------------------------------------
def test_format_json_extension_required_keys():
    item = {"type": "format_json", "value": ["supplier", "customer"]}
    assert hit(item, '{"supplier": "Acme", "customer": "Nordic", "extra": 1}')
    assert not hit(item, '{"supplier": "Acme"}')
    assert not hit(item, '["supplier", "customer"]')
    assert hit({"type": "format_json", "value": True}, "[1, 2]")


def test_format_markdown_table_extension():
    assert hit({"type": "format_markdown_table", "value": True}, TABLE)
    assert hit({"type": "format_markdown_table", "value": 2}, TABLE)
    assert not hit({"type": "format_markdown_table", "value": 3}, TABLE)
    assert hit({"type": "format_markdown_table", "value": ["villkor", "VÄRDE"]}, TABLE)
    assert not hit({"type": "format_markdown_table", "value": ["villkor", "pris"]}, TABLE)


def test_cites_only_allowed_set():
    item = {"type": "cites_only", "value": ["Clause 4", "Clause 7.2"]}
    assert hit(item, "Clause 4 allows termination; clause 7.2 sets the fee (see § 7.2).")
    assert not hit(item, "Clause 4 and Section 12 apply.")
    assert hit(item, "No citations at all.")                       # vacuous by default
    assert not hit({**item, "min": 1}, "No citations at all.")      # unless a minimum is set
    assert hit({"type": "cites_only", "value": ["A", "B"], "pattern": r"\[(\w)\]"}, "As [A] and [B] say.")
    assert not hit({"type": "cites_only", "value": ["A", "B"], "pattern": r"\[(\w)\]"}, "As [C] says.")


# --- unknown type ------------------------------------------------------------------
def test_unknown_type_is_a_miss_under_adherence():
    r = score("anything", [{"id": "x", "type": "telepathy", "value": 1}])
    assert r["rubric_hits"][0]["hit"] is False and r["rubric_hits"][0]["metric"] == "adherence"
    assert r["scores"]["adherence"] == 0
    assert r["scores"]["accuracy"] is None


# --- formulas ----------------------------------------------------------------------
def test_weighted_metric_scores_and_rubric_hits_shape():
    rubric = [
        {"id": "a", "type": "must_include", "value": "yes", "weight": 3},        # hit
        {"id": "b", "type": "regex", "value": "nope", "weight": 1},              # miss
        {"id": "c", "type": "must_not_include", "value": "bad"},                 # hit, accuracy, weight 1
        {"id": "d", "type": "max_words", "value": 1, "weight": 2},               # miss (3 words)
        {"id": "e", "type": "language", "value": "en"},                          # miss (no stopwords)
    ]
    r = score("yes we can", rubric)
    assert r["scores"]["accuracy"] == 8       # 10 * 4/5
    assert r["scores"]["adherence"] == 0      # 10 * 0/3
    assert r["scores"]["velocity"] is None
    assert [h["hit"] for h in r["rubric_hits"]] == [True, False, True, False, False]
    assert [h["metric"] for h in r["rubric_hits"]] == ["accuracy", "accuracy", "accuracy", "adherence", "adherence"]
    assert set(r["rubric_hits"][0]) == {"id", "type", "metric", "weight", "hit", "note"}
    assert r["words"] == 3


def test_metric_rounding_halves_up():
    r = score("x", [{"id": "a", "type": "must_include", "value": "x", "weight": 1},
                    {"id": "b", "type": "must_include", "value": "q", "weight": 7}])
    assert r["scores"]["accuracy"] == 1.3     # 10/8 = 1.25 -> 1.3


def test_no_rubric_gives_null_metrics():
    r = score("some words here", [])
    assert r["scores"] == {"accuracy": None, "adherence": None, "conciseness": None, "velocity": None}
    assert r["target_words"] == 300


def test_conciseness_formula():
    assert conciseness_score(None, 100, 100) is None
    assert conciseness_score(10, 100, 100) == 10          # at target, perfect accuracy
    assert conciseness_score(10, 50, 100) == 10           # shorter than target is not rewarded further
    assert conciseness_score(10, 200, 100) == 5           # 2x target: density 0.5
    assert conciseness_score(6, 150, 100) == 4            # 0.6 / 1.5
    assert conciseness_score(0, 100, 100) == 1            # floor
    assert conciseness_score(10, 0, 100) == 1             # empty output
    assert conciseness_score(7.5, 100, 100) == 7.5


def test_conciseness_target_precedence():
    rubric = [{"id": "l", "type": "must_include", "value": "w"}, {"id": "m", "type": "max_words", "value": 200},
              {"id": "n", "type": "max_words", "value": 50}]
    text = " ".join(["w"] * 100)
    assert score(text, rubric)["target_words"] == 50                                      # smallest max_words
    assert score(text, rubric, {"target_words": 80})["target_words"] == 80                # prompt wins
    assert score(text, rubric, {"target_words": 80})["scores"]["conciseness"] == 8        # 1 / (100/80)
    assert score(text, [{"id": "l", "type": "must_include", "value": "w"}])["target_words"] == 300


def test_empty_output_rules():
    rubric = [{"id": "a", "type": "must_include", "value": "x"}, {"id": "b", "type": "must_not_include", "value": "y"},
              {"id": "c", "type": "min_words", "value": 1}, {"id": "d", "type": "max_words", "value": 5}]
    r = score("   \n", rubric)
    assert r["scores"] == {"accuracy": 0, "adherence": 5, "conciseness": 1, "velocity": None}
    only_mni = [{"id": "b", "type": "must_not_include", "value": "y"}]
    assert score("", only_mni)["scores"] == {"accuracy": 10, "adherence": None, "conciseness": 1, "velocity": None}
    assert score("", [{"id": "c", "type": "min_words", "value": 1}])["scores"]["conciseness"] is None


def test_zero_weight_items_are_recorded_but_do_not_score():
    r = score("x", [{"id": "a", "type": "must_include", "value": "x", "weight": 0}])
    assert r["rubric_hits"][0]["hit"] is True
    assert r["scores"]["accuracy"] is None


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except AssertionError as e:
                failures += 1
                print(f"FAIL {name}: {e}")
    print(f"\n{failures} failure(s)")
    sys.exit(1 if failures else 0)
