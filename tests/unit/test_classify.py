"""Tests for ra_checker.analysis.classify, including every real Lean fixture."""

from pathlib import Path

import pytest

from ra_checker.analysis.classify import LEAN_SIDE_KINDS, classify_lean_error
from ra_checker.lean.diagnostics import parse_lean_output
from ra_checker.models import LeanErrorKind as K

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "lean_output"


@pytest.mark.parametrize(
    "fixture, kind",
    [
        ("syntax_error", K.SYNTAX),
        ("unknown_identifier", K.UNKNOWN_IDENTIFIER),
        ("unsolved_goals", K.UNSOLVED_GOALS),
        ("type_mismatch", K.TYPE_MISMATCH),
        ("linarith_failed", K.TACTIC_FAILED),
    ],
)
def test_real_lean_messages(fixture, kind):
    output = parse_lean_output((FIXTURES / f"{fixture}.txt").read_text(encoding="utf-8"), "student_claim")
    assert classify_lean_error(output.errors[0].message) is kind


@pytest.mark.parametrize(
    "message, kind",
    [
        ("unknown constant 'Real.foo'", K.UNKNOWN_IDENTIFIER),
        ("Application type mismatch\n  f x", K.TYPE_MISMATCH),
        ("type mismatch\n  h", K.TYPE_MISMATCH),
        ("unexpected end of input; expected ':='", K.SYNTAX),
        ("positivity failed to prove positivity", K.TACTIC_FAILED),
        ("simp made no progress", K.TACTIC_FAILED),
        ("tactic 'rewrite' failed, did not find instance of the pattern", K.TACTIC_FAILED),
        ("failed to synthesize\n  OrderedField ℕ", K.TACTIC_FAILED),
        ("something entirely new", K.OTHER),
        ("", K.OTHER),
    ],
)
def test_other_messages(message, kind):
    assert classify_lean_error(message) is kind


def test_only_syntax_and_unknown_names_are_lean_side():
    assert LEAN_SIDE_KINDS == {K.SYNTAX, K.UNKNOWN_IDENTIFIER}
