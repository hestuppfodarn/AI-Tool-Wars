"""Unit tests for the WER / accuracy port in scripts/score-open.py.

Run with `python3 -m pytest scripts/tests` or plain `python3 scripts/tests/test_wer.py`.
The expected values mirror scripts/score-voice.mjs (normalize / wer / accuracyScore).
"""
import importlib.util
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location("score_open", Path(__file__).resolve().parent.parent / "score-open.py")
score_open = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(score_open)

normalize, wer, accuracy_score, naturalness_score = (
    score_open.normalize, score_open.wer, score_open.accuracy_score, score_open.naturalness_score)


def test_identical_text_is_zero():
    assert wer("The cat sat down.", "the cat sat down") == 0


def test_one_substitution_in_four_words():
    assert wer("the cat sat down", "the dog sat down") == 0.25


def test_stage_directions_are_stripped():
    assert normalize("[Now, sadly:] The house was empty.") == "the house was empty"
    assert wer("[Now, sadly:] The house was empty.", "the house was empty") == 0


def test_punctuation_and_whitespace():
    assert normalize("“Hello,” she said — twice… (really?)") == "hello she said twice really"
    assert normalize("  a\t b\n\nc ") == "a b c"


def test_empty_reference():
    assert wer("", "") == 0
    assert wer("[only a direction]", "something") == 1


def test_wer_rounding_matches_js():
    # score-voice.mjs: Math.round(wer * 1000) / 1000, halves round up.
    assert score_open.js_round(1 / 3, 3) == 0.333
    assert score_open.js_round(0.0005, 3) == 0.001


def test_accuracy_score():
    assert accuracy_score(0) == 10
    assert accuracy_score(0.25) == 5.5
    assert accuracy_score(0.6) == 1
    assert accuracy_score(0.5) == 1
    assert accuracy_score(0.1) == 8.2


def test_naturalness_mapping():
    assert naturalness_score(1.0) == 1
    assert naturalness_score(4.5) == 10
    assert naturalness_score(2.75) == 5.5
    assert naturalness_score(0.2) == 1      # clamped
    assert naturalness_score(4.9) == 10     # clamped


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok    {name}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {name}: {e}")
    print(f"{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
