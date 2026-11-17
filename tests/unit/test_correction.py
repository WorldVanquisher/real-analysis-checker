"""Tests for ra_checker.analysis.correction (Advanced Feature D), fakes only."""

import pytest
from pipeline_helpers import LEAN_STATEMENT, TACTICS, make_checker
from translation_helpers import OK, STATEMENT_OK, UNKNOWN_ID, UNSOLVED

from ra_checker.analysis.correction import CORRECTION_TASK, CorrectionOutput, CorrectionUnavailable
from ra_checker.analysis.explain import lean_concept_for
from ra_checker.llm.client import LLMUnavailableError
from ra_checker.models import LeanErrorKind, Submission, VerificationStatus as S

SUBMISSION = Submission(problem_text="Suppose a_n → A. Prove that a_n + 1 → A + 1.", proof_text="…")
HEAD, S3_CODE = TACTICS.split("-- [S3]\n")
FIXED_S3 = "refine ⟨N, fun n hn => ?_⟩\nsimpa using hN n hn"
FIXED_PROOF = f"{HEAD}-- [S3]\n{FIXED_S3}"


def failed_check(*correction_lean, correction=None):
    checker, llm, lean = make_checker(STATEMENT_OK, UNSOLVED, *correction_lean)
    if correction is not None:
        llm.responses[CORRECTION_TASK] = correction
    report = checker.verify(checker.formalize(SUBMISSION).confirmed()).report
    assert report.status is S.VERIFICATION_FAILED and report.error_analyses[0].step_id == "S3"
    return checker, report, llm, lean


def suggestion(proof=FIXED_PROOF, why="Finish with simpa."):
    return CorrectionOutput(corrected_proof=proof, explanation=why)


def test_verified_correction_and_its_changes_come_from_the_code():
    checker, report, llm, lean = failed_check(OK, correction=suggestion())
    correction = checker.suggest_correction(report, 0)
    assert correction.verified and correction.focus_step == "S3"
    assert [c.step_id for c in correction.changes] == ["S3"]
    assert correction.changes[0].before == S3_CODE and correction.changes[0].after == FIXED_S3
    assert correction.full_block == FIXED_PROOF
    assert f"theorem student_claim {LEAN_STATEMENT} := by" in lean.sources[-1]  # same locked statement
    assert report.status is S.VERIFICATION_FAILED  # the student's own result never changes
    request = llm.requests[-1].user
    assert "<lean_proof>\n" + TACTICS in request and "Lean's error: unsolved goals" in request


def test_correction_may_fix_an_earlier_step():
    # Lean fails at S3, but the cause is in S2 (as with ε instead of ε/2).
    earlier = FIXED_PROOF.replace("obtain ⟨N, hN⟩ := ha ε hε", "obtain ⟨N, hN⟩ := ha (ε / 2) (half_pos hε)")
    checker, report, *_ = failed_check(OK, correction=suggestion(earlier))
    correction = checker.suggest_correction(report, 0)
    assert correction.verified
    assert [c.step_id for c in correction.changes] == ["S2", "S3"]  # in proof order


def test_rejected_correction_is_labelled_unverified():
    checker, report, *_ = failed_check(UNKNOWN_ID, correction=suggestion(FIXED_PROOF + "\nexact made_up"))
    correction = checker.suggest_correction(report, 0)
    assert not correction.verified and correction.status is S.VERIFICATION_FAILED


@pytest.mark.parametrize(
    "proof, reason",
    [
        (FIXED_PROOF + "\nnative_decide", "safety screen"),
        (f"{HEAD}-- [S3]\nsorry", "placeholder"),
        (TACTICS, "did not change anything"),
        (FIXED_S3, "step structure"),  # tags removed
        (FIXED_PROOF + "\n-- [A1]\nrfl", "step structure"),  # a step added
        (FIXED_PROOF.replace("-- [S1]", "-- [S9]"), "step structure"),  # unknown step
    ],
)
def test_unusable_suggestions_never_reach_lean(proof, reason):
    checker, report, _, lean = failed_check(correction=suggestion(proof))
    runs = len(lean.sources)
    correction = checker.suggest_correction(report, 0)
    assert correction.status is None and reason in correction.reasons[0]
    assert len(lean.sources) == runs


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
