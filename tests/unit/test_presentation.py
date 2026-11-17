"""Tests for ra_checker.report.presentation: deterministic student-facing wording."""

import pytest
from pipeline_helpers import TACTICS, make_checker, proof_answer, parse_answer
from translation_helpers import CONTRADICTION, OK, STATEMENT_OK, UNSOLVED

from ra_checker.llm.client import LLMUnavailableError
from ra_checker.models import (
    Confidence,
    ErrorAnalysis,
    ErrorCategory,
    ErrorOrigin,
    FidelitySummary,
    LeanErrorKind,
    Submission,
)
from ra_checker.pipeline import PendingCheck
from ra_checker.report.presentation import (
    NOT_CONFIDENT,
    describe_differences,
    explanation_lines,
    headline,
)

SUBMISSION = Submission(problem_text="Suppose a_n → A. Prove that a_n + 1 → A + 1.", proof_text="Let ε > 0. …")


def report_for(*lean, **answers):
    checker, _, _ = make_checker(*lean, **answers)
    first = checker.formalize(SUBMISSION)
    if isinstance(first, PendingCheck):
        return checker.verify(first.confirmed()).report
    return first


def all_reports():
    return [
        report_for(),
        report_for(STATEMENT_OK, OK, proof=proof_answer(TACTICS.replace("-- [S2]\n", ""))),
        report_for(STATEMENT_OK, UNSOLVED),
        report_for(parse=parse_answer(ambiguities=["Which sequence?"])),
        report_for(parse=LLMUnavailableError("down")),
    ]


def test_headlines_per_status():
    titles = [(h.level, h.title) for h in map(headline, all_reports())]
    assert titles == [
        ("success", "Lean accepted the formalized proof."),
        ("warning", "Lean accepted a formal proof that differs from yours."),
        ("error", "Lean did not accept the formalized proof."),
        ("info", "We need a clarification before checking."),
        ("error", "The check could not be completed."),
    ]


@pytest.mark.parametrize("report", all_reports(), ids=lambda r: r.status.value)
def test_never_claims_the_students_proof_is_correct(report):
    text = " ".join([headline(report).title, headline(report).body]).lower()
    assert "proof is correct" not in text and "your proof is valid" not in text


def test_unfaithful_headline_names_the_steps():
    report = report_for(STATEMENT_OK, OK, proof=proof_answer(TACTICS.replace("-- [S2]\n", "")))
    assert "not translated: S2" in headline(report).body


def test_failure_headline_points_to_the_step():
    assert "step S3" in headline(report_for(STATEMENT_OK, UNSOLVED)).body


def test_describe_differences():
    f = FidelitySummary(statement_confirmed=True, added_steps=("A1",), changed_steps=("S2",))
    assert describe_differences(f) == "added: A1; changed: S2"
    assert describe_differences(FidelitySummary(statement_confirmed=True)) == "no differences"


def _error(origin, confidence):
    return ErrorAnalysis(
        lean_error_kind=LeanErrorKind.TACTIC_FAILED, category=ErrorCategory.MATHEMATICAL_REASONING,
        origin=origin, confidence=confidence, raw_message="linarith failed", explanation="The bound is 2ε.",
    )


def test_explanation_lines_flag_low_confidence():
    classification, text = explanation_lines(_error(ErrorOrigin.STUDENT_REASONING, Confidence.HIGH))
    assert "confidence: high" in classification and text == "The bound is 2ε."
    for origin, confidence in [
        (ErrorOrigin.STUDENT_REASONING, Confidence.LOW),
        (ErrorOrigin.UNDETERMINED, Confidence.MEDIUM),
    ]:
        _, text = explanation_lines(_error(origin, confidence))
        assert text.startswith(NOT_CONFIDENT)


def contradictory_report(*lean):
    checker, _, scripted = make_checker(*lean)
    scripted.probe_results = [CONTRADICTION]
    pending = checker.formalize(SUBMISSION)
    assert pending.statement.contradictory_hypotheses is True
    return checker.verify(pending.confirmed()).report


def test_acceptance_with_contradictory_hypotheses_is_not_presented_as_meaningful():
    report = contradictory_report()
    assert report.status.value == "verified"  # Lean's verdict itself is not changed
    head = headline(report)
    assert head.level == "warning"
    assert "contradict each other" in head.title
    assert "says nothing about your argument" in head.body
    assert "proof is correct" not in f"{head.title} {head.body}".lower()


def test_failure_headline_is_unchanged_by_contradictory_hypotheses():
    assert headline(contradictory_report(STATEMENT_OK, UNSOLVED)).title == "Lean did not accept the formalized proof."
