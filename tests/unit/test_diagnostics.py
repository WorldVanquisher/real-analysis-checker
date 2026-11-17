"""Tests for ra_checker.lean.diagnostics against real Lean 4.36 output.

Fixtures in tests/fixtures/lean_output/ were captured with
`RA_CAPTURE_FIXTURES=1 pytest -m lean` (machine paths scrubbed).
"""

from pathlib import Path

import pytest

from ra_checker.lean.diagnostics import parse_lean_output
from ra_checker.models import Severity

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "lean_output"
NAME = "student_claim"
STANDARD = ("propext", "Classical.choice", "Quot.sound")
WITH_SORRY_AX = ("propext", "sorryAx", "Classical.choice", "Quot.sound")


def parse_fixture(name: str):
    return parse_lean_output((FIXTURES / f"{name}.txt").read_text(encoding="utf-8"), NAME)


@pytest.mark.parametrize("name", ["verified_positivity", "verified_epsilon_n"])
def test_clean_runs(name):
    out = parse_fixture(name)
    assert out.diagnostics == ()
    assert out.axioms == STANDARD
    assert not out.uses_sorry
    assert out.unparsed == ""


@pytest.mark.parametrize(
    "name, line, column, message, goal_fragment",
    [
        ("unsolved_goals", 5, 57, "unsolved goals", "⊢ x < x + 1"),
        ("linarith_failed", 7, 2, "linarith failed to find a contradiction", "⊢ False"),
        ("type_mismatch", 7, 2, "Type mismatch\n  hx\nhas type", None),
        ("unknown_identifier", 7, 8, "Unknown identifier `pow_pos_of_made_up_lemma`", None),
        ("syntax_error", 7, 12, "unexpected token '#print'", None),
    ],
)
def test_single_error_cases(name, line, column, message, goal_fragment):
    out = parse_fixture(name)
    assert len(out.errors) == 1
    error = out.errors[0]
    assert (error.line, error.column, error.severity) == (line, column, Severity.ERROR)
    assert error.message.startswith(message)
    if goal_fragment is None:
        assert error.goal_state is None
    else:
        assert goal_fragment in error.goal_state
        assert "depends on axioms" not in error.goal_state  # axiom line is not a continuation
    # Lean's error recovery inserts sorryAx; that is not a placeholder.
    assert out.axioms == WITH_SORRY_AX
    assert not out.uses_sorry
    assert out.unparsed == ""


def test_type_mismatch_keeps_expected_and_actual_types():
    error = parse_fixture("type_mismatch").errors[0]
    assert "but is expected to have type\n  0 < x ^ 2" in error.message


def test_sorry_placeholder():
    out = parse_fixture("sorry_placeholder")
    assert out.errors == ()
    assert [d.severity for d in out.diagnostics] == [Severity.WARNING]
    assert out.uses_sorry
    assert "sorryAx" in out.axioms


@pytest.mark.parametrize(
    "name, nonstandard",
    [
        ("native_decide_axiom", "student_claim._native.native_decide.ax_1_1"),
        ("injected_axiom", "cheat"),
    ],
)
def test_unsound_tricks_show_up_as_axioms(name, nonstandard):
    out = parse_fixture(name)
    assert out.errors == ()
    assert nonstandard in out.axioms


def test_axiom_report_for_other_declarations_is_ignored():
    out = parse_lean_output("'helper' depends on axioms: [cheat]\n", NAME)
    assert out.axioms is None


def test_missing_axiom_report_gives_none():
    assert parse_lean_output("", NAME).axioms is None


def test_no_axioms_and_wrapped_lists():
    assert parse_lean_output(f"'{NAME}' does not depend on any axioms\n", NAME).axioms == ()
    wrapped = f"'{NAME}' depends on axioms: [propext,\n  Classical.choice,\n  Quot.sound]\n"
    assert parse_lean_output(wrapped, NAME).axioms == STANDARD


def test_info_header_form_is_also_understood():
    text = f"/tmp/x/Check.lean:9:0: info: '{NAME}' depends on axioms: [propext]\n"
    out = parse_lean_output(text, NAME)
    assert out.axioms == ("propext",)
    assert out.diagnostics[0].severity is Severity.INFO


def test_windows_paths_crlf_and_stray_text():
    text = (
        "something unexpected\r\n"
        "C:\\Users\\someone\\Temp\\ra_checker_x\\Check.lean:3:4: error: boom\r\n"
        "  detail line\r\n"
    )
    out = parse_lean_output(text, NAME)
    assert out.unparsed == "something unexpected"
    assert out.errors[0].message == "boom\n  detail line"
    assert (out.errors[0].line, out.errors[0].column) == (3, 4)


def test_stderr_is_parsed_too():
    out = parse_lean_output("", NAME, stderr="/tmp/a/Check.lean:1:0: error: bad import\n")
    assert out.errors[0].message == "bad import"
