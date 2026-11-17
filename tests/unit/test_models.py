"""Tests for ra_checker.models: validation, immutability, JSON round-trips and
the invariant that VERIFIED needs real Lean evidence."""

import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from ra_checker.models import (
    CheckReport,
    Confidence,
    Diagnostic,
    ErrorAnalysis,
    ErrorCategory,
    ErrorOrigin,
    FidelitySummary,
    FormalStatement,
    LeanErrorKind,
    LeanRun,
    ProblemAnalysis,
    ProofStep,
    ProofTranslation,
    Severity,
    StepMapping,
    StepStatus,
    Submission,
    VerificationStatus,
)

STATEMENT = "(fun n : ℕ => (1 : ℝ) / (n + 1)) ⟶ 0"  # placeholder text; Lean syntax is B3/B5


def submission() -> Submission:
    return Submission(
        problem_text="Prove that 1/(n+1) converges to 0.",
        proof_text="Let ε > 0. Choose N > 1/ε. Then for n ≥ N, 1/(n+1) < ε.",
    )


def analysis() -> ProblemAnalysis:
    return ProblemAnalysis(
        hypotheses=(),
        goal="1/(n+1) → 0",
        proof_steps=(
            ProofStep(id="S1", text="Let ε > 0."),
            ProofStep(id="S2", text="Choose N > 1/ε."),
            ProofStep(id="S3", text="Then for n ≥ N, 1/(n+1) < ε."),
        ),
        in_scope=True,
        topic="sequences",
    )


def statement(confirmed: bool = True) -> FormalStatement:
    return FormalStatement(
        lean_statement=STATEMENT,
        back_translation="The sequence 1/(n+1) converges to 0.",
        confirmed_by_student=confirmed,
    )


def translation() -> ProofTranslation:
    return ProofTranslation(
        tactic_block="  -- [S1]\n  intro ε hε\n  -- [A1]\n  positivity",
        step_map=(
            StepMapping(step_id="S1", status=StepStatus.TRANSLATED),
            StepMapping(step_id="S2", status=StepStatus.CHANGED, note="N made explicit"),
            StepMapping(step_id="S3", status=StepStatus.OMITTED),
            StepMapping(step_id="A1", status=StepStatus.ADDED, note="positivity side goal"),
        ),
    )


def lean_run(**overrides) -> LeanRun:
    fields = dict(
        source=f"import Mathlib\ntheorem student_claim : {STATEMENT} := by\n  sorry\n",
        exit_code=0,
        duration_s=4.2,
        lean_version="4.x",
    )
    fields.update(overrides)
    return LeanRun(**fields)


def verified_report(**overrides) -> CheckReport:
    fields = dict(
        submission=submission(),
        status=VerificationStatus.VERIFIED,
        analysis=analysis(),
        statement=statement(),
        translation=translation(),
        lean_run=lean_run(),
        fidelity=FidelitySummary.from_translation(statement(), translation()),
        llm_model="claude-opus-5-5",
        prompt_version="v1",
    )
    fields.update(overrides)
    return CheckReport(**fields)


def failed_report() -> CheckReport:
    return CheckReport(
        submission=submission(),
        status=VerificationStatus.VERIFICATION_FAILED,
        status_detail="Lean reported an unsolved goal at step S3.",
        analysis=analysis(),
        statement=statement(),
        translation=translation(),
        lean_run=lean_run(exit_code=1),
        diagnostics=(
            Diagnostic(
                line=7,
                column=2,
                severity=Severity.ERROR,
                message="unsolved goals",
                goal_state="⊢ 1 / (↑n + 1) < ε",
                step_id="S3",
            ),
        ),
        error_analyses=(
            ErrorAnalysis(
                lean_error_kind=LeanErrorKind.UNSOLVED_GOALS,
                category=ErrorCategory.UNRESOLVED_GOAL,
                origin=ErrorOrigin.UNDETERMINED,
                confidence=Confidence.LOW,
                raw_message="unsolved goals",
                explanation="The final inequality was not proved.",
                step_id="S3",
                line=7,
            ),
        ),
        fidelity=FidelitySummary.from_translation(statement(), translation()),
    )


# ------------------------------------------------------------------ round trips


@pytest.mark.parametrize("make", [verified_report, failed_report])
def test_report_round_trips_through_json(make):
    report = make()
    restored = CheckReport.model_validate_json(report.model_dump_json())
    assert restored == report


def test_created_at_is_timezone_aware_and_ids_are_unique():
    a, b = failed_report(), failed_report()
    assert a.created_at.tzinfo is not None
    assert a.id != b.id


def test_naive_created_at_is_rejected():
    with pytest.raises(ValidationError, match="timezone-aware"):
        verified_report(created_at=datetime(2026, 1, 1))


# ------------------------------------------------------- VERIFIED needs evidence


def test_verified_report_with_full_evidence_is_accepted():
    assert verified_report().status is VerificationStatus.VERIFIED


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"lean_run": None}, "no Lean run"),
        ({"lean_run": lean_run(exit_code=None, timed_out=True)}, "timed out"),
        ({"lean_run": lean_run(exit_code=1)}, "exited with code 1"),
        (
            {
                "diagnostics": (
                    Diagnostic(line=3, column=0, severity=Severity.ERROR, message="x"),
                )
            },
            "Lean reported errors",
        ),
        ({"statement": statement(confirmed=False)}, "not confirmed"),
        ({"statement": None}, "not confirmed"),
        (
            {"lean_run": lean_run(source="theorem other : True := trivial")},
            "did not check the confirmed statement",
        ),
        ({"translation": None}, "no proof translation"),
        ({"fidelity": None}, "no fidelity summary"),
    ],
)
def test_verified_without_evidence_is_rejected(overrides, reason):
    with pytest.raises(ValidationError, match="requires real Lean evidence") as excinfo:
        verified_report(**overrides)
    assert reason in str(excinfo.value)


def test_warnings_do_not_block_verified():
    report = verified_report(
        diagnostics=(
            Diagnostic(line=2, column=0, severity=Severity.WARNING, message="unused variable"),
        )
    )
    assert report.status is VerificationStatus.VERIFIED


def test_tampered_json_cannot_claim_verified():
    data = json.loads(failed_report().model_dump_json())
    data["status"] = "verified"
    with pytest.raises(ValidationError, match="requires real Lean evidence"):
        CheckReport.model_validate(data)


# ----------------------------------------------------- other status invariants


@pytest.mark.parametrize(
    "status",
    [s for s in VerificationStatus if s is not VerificationStatus.VERIFIED],
)
def test_non_verified_status_requires_detail(status):
    with pytest.raises(ValidationError, match="requires a status_detail"):
        CheckReport(submission=submission(), status=status, lean_run=lean_run())


def test_verification_failed_requires_a_lean_run():
    with pytest.raises(ValidationError, match="requires the Lean run"):
        CheckReport(
            submission=submission(),
            status=VerificationStatus.VERIFICATION_FAILED,
            status_detail="failed",
        )


def test_needs_clarification_requires_an_ambiguous_analysis():
    with pytest.raises(ValidationError, match="ambiguities"):
        CheckReport(
            submission=submission(),
            status=VerificationStatus.NEEDS_CLARIFICATION,
            status_detail="please clarify",
            analysis=analysis(),
        )
    ambiguous = ProblemAnalysis(
        ambiguities=("Is the sequence indexed from 0 or 1?",), in_scope=True
    )
    report = CheckReport(
        submission=submission(),
        status=VerificationStatus.NEEDS_CLARIFICATION,
        status_detail="please clarify",
        analysis=ambiguous,
    )
    assert report.analysis.needs_clarification


def test_runtime_and_translation_failures_need_no_lean_run():
    for status in (VerificationStatus.RUNTIME_ERROR, VerificationStatus.TRANSLATION_FAILED):
        report = CheckReport(submission=submission(), status=status, status_detail="x")
        assert report.lean_run is None


# --------------------------------------------------------------- field-level rules


def test_submission_keeps_text_verbatim_and_rejects_blank():
    original = "  Prove  that a_n → L.\n"
    assert Submission(problem_text=original, proof_text="p").problem_text == original
    with pytest.raises(ValidationError, match="must not be blank"):
        Submission(problem_text="   ", proof_text="p")


@pytest.mark.parametrize("bad_id", ["S0", "s1", "A1", "S", "S1a", "X2"])
def test_proof_step_ids_must_be_student_ids(bad_id):
    with pytest.raises(ValidationError):
        ProofStep(id=bad_id, text="step")


def test_duplicate_step_ids_are_rejected():
    with pytest.raises(ValidationError, match="duplicate proof step ids: S1"):
        ProblemAnalysis(
            goal="g",
            in_scope=True,
            proof_steps=(ProofStep(id="S1", text="a"), ProofStep(id="S1", text="b")),
        )
    with pytest.raises(ValidationError, match="duplicate step ids in step_map: S2"):
        ProofTranslation(
            tactic_block="rfl",
            step_map=(
                StepMapping(step_id="S2", status=StepStatus.TRANSLATED),
                StepMapping(step_id="S2", status=StepStatus.OMITTED),
            ),
        )


def test_clear_problem_must_state_goal():
    with pytest.raises(ValidationError, match="must state its goal"):
        ProblemAnalysis(goal=" ", in_scope=True)
    # an out-of-scope or ambiguous problem may lack a goal
    assert ProblemAnalysis(in_scope=False).needs_clarification


@pytest.mark.parametrize(
    "step_id, status",
    [("A1", StepStatus.TRANSLATED), ("S1", StepStatus.ADDED)],
)
def test_added_status_and_a_ids_go_together(step_id, status):
    with pytest.raises(ValidationError, match="translator-added steps"):
        StepMapping(step_id=step_id, status=status)


def test_finished_lean_run_needs_exit_code():
    with pytest.raises(ValidationError, match="must have an exit code"):
        LeanRun(source="x", exit_code=None, duration_s=1.0)
    assert not LeanRun(source="x", exit_code=None, timed_out=True, duration_s=120).completed


def test_fidelity_summary_from_translation():
    fidelity = FidelitySummary.from_translation(statement(), translation())
    assert fidelity.translated_steps == ("S1",)
    assert fidelity.changed_steps == ("S2",)
    assert fidelity.omitted_steps == ("S3",)
    assert fidelity.added_steps == ("A1",)
    assert not fidelity.is_faithful
    faithful = FidelitySummary(statement_confirmed=True, translated_steps=("S1", "S2"))
    assert faithful.is_faithful
    assert not FidelitySummary(statement_confirmed=False).is_faithful


def test_models_are_frozen_and_reject_unknown_fields():
    report = verified_report()
    with pytest.raises(ValidationError):
        report.status = VerificationStatus.RUNTIME_ERROR  # type: ignore[misc]
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Submission(problem_text="p", proof_text="q", verdict="verified")
