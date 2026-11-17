"""Tests for ra_checker.pipeline: every path from submission to report."""

import pytest
from pipeline_helpers import (
    PROBLEM,
    PROOF,
    TACTICS,
    make_checker,
    parse_answer,
    proof_answer,
    statement_answer,
)
from translation_helpers import OK, SORRY, STATEMENT_OK, UNSOLVED

from ra_checker.llm.client import LLMRefusalError, LLMUnavailableError
from ra_checker.llm.prompts import EXPLAIN_ERROR_VERSION
from ra_checker.models import CheckReport, Submission, VerificationStatus as S
from ra_checker.pipeline import PendingCheck

SUBMISSION = Submission(problem_text=PROBLEM, proof_text=PROOF)


def formalize(*lean, **answers):
    checker, llm, lean_runner = make_checker(*lean, **answers)
    return checker.formalize(SUBMISSION), checker, llm, lean_runner


def test_happy_path_needs_confirmation_then_verifies():
    pending, checker, llm, lean = formalize()
    assert isinstance(pending, PendingCheck)
    assert not pending.statement.confirmed_by_student
    with pytest.raises(ValueError, match="not confirmed"):
        checker.verify(pending)
    assert len(lean.sources) == 1  # only the statement check ran before confirmation

    result = checker.verify(pending.confirmed())
    report = result.report
    assert report.status is S.VERIFIED and report.status_detail == ""
    assert report.statement.confirmed_by_student
    assert report.fidelity.is_faithful
    assert report.prompt_version == "parse_problem.v1, formalize_statement.v1, translate_proof.v1"
    assert report.llm_model == "fake-model"
    assert len(result.proof_attempts) == 1
    assert CheckReport.model_validate_json(report.model_dump_json()) == report


def test_ambiguous_problem_stops_before_lean():
    report, _, _, lean = formalize(parse=parse_answer(ambiguities=["Real or complex sequence?"]))
    assert report.status is S.NEEDS_CLARIFICATION
    assert "Real or complex sequence?" in report.status_detail
    assert lean.sources == []


def test_out_of_scope_problem():
    report, *_ = formalize(parse=parse_answer(in_scope=False, out_of_scope_reason="It is about integrals."))
    assert report.status is S.NEEDS_CLARIFICATION
    assert "outside what the checker currently supports" in report.status_detail
    assert "integrals" in report.status_detail


@pytest.mark.parametrize(
    "error, status",
    [(LLMUnavailableError("network down"), S.RUNTIME_ERROR), (LLMRefusalError("declined"), S.TRANSLATION_FAILED)],
)
def test_parse_failures(error, status):
    report, *_ = formalize(parse=error)
    assert report.status is status and report.analysis is None


def test_statement_that_cannot_be_formalized():
    report, *_ = formalize(statement=statement_answer(cannot_formalize=True, lean_statement="", reason="uses complex numbers"))
    assert report.status is S.TRANSLATION_FAILED
    assert "uses complex numbers" in report.status_detail
    assert report.analysis is not None


def test_lean_failure_is_explained():
    pending, checker, llm, _ = formalize(STATEMENT_OK, UNSOLVED)
    report = checker.verify(pending.confirmed()).report
    assert report.status is S.VERIFICATION_FAILED
    assert report.error_analyses and report.error_analyses[0].step_id == "S3"
    assert report.prompt_version.endswith(EXPLAIN_ERROR_VERSION)
    assert report.diagnostics


def test_placeholder_translation_is_not_blamed_on_the_student():
    block = TACTICS.split("-- [S3]")[0] + "-- [S3]\nsorry"
    pending, checker, _, _ = formalize(STATEMENT_OK, SORRY, proof=proof_answer(block))
    report = checker.verify(pending.confirmed()).report
    assert report.status is S.TRANSLATION_FAILED
    assert report.error_analyses == ()
    assert report.fidelity.omitted_steps == ("S3",)


def test_verified_but_unfaithful_translation_is_recorded():
    block = TACTICS.replace("-- [S2]\n", "")  # S2's tactics now sit under S1
    pending, checker, _, _ = formalize(STATEMENT_OK, OK, proof=proof_answer(block))
    report = checker.verify(pending.confirmed()).report
    assert report.status is S.VERIFIED
    assert not report.fidelity.is_faithful
    assert report.fidelity.omitted_steps == ("S2",)
