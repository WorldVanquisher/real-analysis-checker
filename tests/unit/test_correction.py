"""Tests for ra_checker.analysis.correction (Advanced Feature D), fakes only."""

import pytest
from pipeline_helpers import LEAN_STATEMENT, make_checker
from translation_helpers import OK, STATEMENT_OK, UNKNOWN_ID, UNSOLVED

from ra_checker.analysis.correction import (
    CORRECTION_TASK,
    CorrectionOutput,
    CorrectionUnavailable,
    segment_bounds,
)
from ra_checker.analysis.explain import lean_concept_for
from ra_checker.llm.client import LLMUnavailableError
from ra_checker.models import LeanErrorKind, Submission, VerificationStatus as S

SUBMISSION = Submission(problem_text="Suppose a_n → A. Prove that a_n + 1 → A + 1.", proof_text="…")
FIXED = "refine ⟨N, fun n hn => ?_⟩\nsimpa using hN n hn"


def failed_check(*correction_lean, correction=None):
    checker, llm, lean = make_checker(STATEMENT_OK, UNSOLVED, *correction_lean)
    if correction is not None:
        llm.responses[CORRECTION_TASK] = correction
    report = checker.verify(checker.formalize(SUBMISSION).confirmed()).report
    assert report.status is S.VERIFICATION_FAILED and report.error_analyses[0].step_id == "S3"
    return checker, report, llm, lean


def suggestion(code=FIXED, why="Use simpa to finish."):
    return CorrectionOutput(corrected_tactics=code, explanation=why)


def test_verified_correction_replaces_only_the_failing_step():
    checker, report, llm, lean = failed_check(OK, correction=suggestion())
    correction = checker.suggest_correction(report, 0)
    assert correction.verified and correction.status is S.VERIFIED
    assert correction.step_id == "S3" and correction.corrected_code == FIXED
    lines = correction.full_block.split("\n")
    assert lines[:4] == report.translation.tactic_block.split("\n")[:4]  # S1, S2 untouched
    assert "-- [S3]" in lines and correction.full_block.endswith("simpa using hN n hn")
    assert f"theorem student_claim {LEAN_STATEMENT} := by" in lean.sources[-1]  # same locked statement
    assert report.status is S.VERIFICATION_FAILED  # the student's own result never changes
    assert "Lean's error: unsolved goals" in llm.requests[-1].user


def test_rejected_correction_is_labelled_unverified():
    checker, report, *_ = failed_check(UNKNOWN_ID, correction=suggestion("exact made_up"))
    correction = checker.suggest_correction(report, 0)
    assert not correction.verified and correction.status is S.VERIFICATION_FAILED


@pytest.mark.parametrize(
    "code, reason",
    [("native_decide", "safety screen"), ("sorry", "placeholder"), ("  \n", "empty")],
)
def test_unusable_suggestions_never_reach_lean(code, reason):
    checker, report, _, lean = failed_check(correction=suggestion(code))
    runs = len(lean.sources)
    correction = checker.suggest_correction(report, 0)
    assert correction.status is None and reason in correction.reasons[0]
    assert len(lean.sources) == runs


def test_tag_lines_in_the_suggestion_are_dropped():
    checker, report, *_ = failed_check(OK, correction=suggestion("-- [S3]\n" + FIXED))
    correction = checker.suggest_correction(report, 0)
    assert correction.full_block.count("-- [S3]") == 1


def test_unavailable_cases():
    checker, report, *_ = failed_check(correction=LLMUnavailableError("down"))
    with pytest.raises(CorrectionUnavailable, match="No correction could be generated"):
        checker.suggest_correction(report, 0)
    with pytest.raises(CorrectionUnavailable, match="Unknown error"):
        checker.suggest_correction(report, 7)
    ok_checker, *_ = make_checker()
    verified = ok_checker.verify(ok_checker.formalize(SUBMISSION).confirmed()).report
    with pytest.raises(CorrectionUnavailable, match="only when Lean rejected"):
        ok_checker.suggest_correction(verified, 0)


def test_segment_bounds():
    block = "-- [S1]\na\n-- [S2]\nb\nc\n-- [A1]\nd"
    assert segment_bounds(block, "S2") == (3, 5)
    assert segment_bounds(block, "A1") == (6, 7)
    assert segment_bounds(block, None) == (0, 7)


@pytest.mark.parametrize(
    "kind, message, expected",
    [
        (LeanErrorKind.UNSOLVED_GOALS, "unsolved goals", "Goals:"),
        (LeanErrorKind.TACTIC_FAILED, "linarith failed to find a contradiction", "linarith —"),
        (LeanErrorKind.TACTIC_FAILED, "tactic 'rewrite' failed", "rw —"),
        (LeanErrorKind.TYPE_MISMATCH, "Type mismatch", "Types:"),
        (LeanErrorKind.OTHER, "something", None),
    ],
)
def test_lean_concept_is_chosen_by_rules(kind, message, expected):
    concept = lean_concept_for(kind, message)
    assert (concept is None) if expected is None else concept.startswith(expected)
