"""Orchestrates a check in two phases, with the student's confirmation between.

Phase 1 — :meth:`Checker.formalize`: parse the problem (stage 1) and formalize
the statement (stage 2a). Returns a :class:`PendingCheck` for the student to
confirm, or a final :class:`CheckReport` (clarification needed, translation
failed, runtime error).

Phase 2 — :meth:`Checker.verify`: requires the confirmed statement; translates
the proof (stage 2b), runs Lean, analyses failures (stage 4) and returns the
final report. The report's status comes only from the Lean verdict (or from a
failure before Lean could decide); ``CheckReport`` re-validates that on
construction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from ra_checker.analysis.correction import Correction, suggest_correction
from ra_checker.analysis.explain import analyze_failure
from ra_checker.explain.code import CodeExplanation, explain_code
from ra_checker.lean.runner import LeanRunner
from ra_checker.llm.client import LLMClient, LLMError
from ra_checker.llm.prompts import EXPLAIN_ERROR_VERSION
from ra_checker.models import (
    CheckReport,
    FidelitySummary,
    FormalStatement,
    ProblemAnalysis,
    Submission,
    VerificationStatus,
)
from ra_checker.parsing.problem_parser import parse_problem
from ra_checker.translation import status_for_llm_error
from ra_checker.translation.proof import ProofAttempt, translate_proof
from ra_checker.translation.statement import StatementAttempt, formalize_statement

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PendingCheck:
    """Phase 1 succeeded: the formal statement awaits the student's confirmation."""

    submission: Submission
    analysis: ProblemAnalysis
    statement: FormalStatement
    statement_attempts: tuple[StatementAttempt, ...]
    llm_models: tuple[str, ...]
    prompt_versions: tuple[str, ...]

    def confirmed(self) -> PendingCheck:
        """The student confirmed that the formal statement matches the problem."""
        return replace(self, statement=self.statement.model_copy(update={"confirmed_by_student": True}))


@dataclass(frozen=True)
class VerifiedCheck:
    """Phase 2 result: the report plus the attempt logs for display."""

    report: CheckReport
    statement_attempts: tuple[StatementAttempt, ...]
    proof_attempts: tuple[ProofAttempt, ...]


class Checker:
    def __init__(self, llm: LLMClient, lean: LeanRunner) -> None:
        self.llm = llm
        self.lean = lean

    # ------------------------------------------------------------------ phase 1

    def formalize(self, submission: Submission) -> PendingCheck | CheckReport:
        try:
            parsed = parse_problem(submission, self.llm)
        except LLMError as exc:
            return _report(submission, status_for_llm_error(exc), str(exc))
        analysis = parsed.analysis
        models, versions = [parsed.llm_model], [parsed.prompt_version]

        if analysis.needs_clarification:
            return _report(
                submission,
                VerificationStatus.NEEDS_CLARIFICATION,
                _clarification_detail(analysis),
                analysis=analysis,
                models=models,
                versions=versions,
            )

        outcome = formalize_statement(submission.problem_text, analysis, self.llm, self.lean)
        if outcome.llm_model:
            models.append(outcome.llm_model)
        versions.append(outcome.prompt_version)
        if not outcome.ok:
            return _report(
                submission,
                outcome.failure or VerificationStatus.TRANSLATION_FAILED,
                outcome.detail,
                analysis=analysis,
                models=models,
                versions=versions,
            )
        return PendingCheck(
            submission=submission,
            analysis=analysis,
            statement=outcome.statement,
            statement_attempts=outcome.attempts,
            llm_models=tuple(models),
            prompt_versions=tuple(versions),
        )

    # ------------------------------------------------------------------ phase 2

    def verify(self, pending: PendingCheck) -> VerifiedCheck:
        if not pending.statement.confirmed_by_student:
            raise ValueError("the student has not confirmed the formal statement")
        outcome = translate_proof(
            pending.submission.problem_text, pending.analysis, pending.statement, self.llm, self.lean
        )
        models = list(pending.llm_models) + ([outcome.llm_model] if outcome.llm_model else [])
        versions = list(pending.prompt_versions) + [outcome.prompt_version]

        error_analyses = ()
        if (
            outcome.status is VerificationStatus.VERIFICATION_FAILED
            and outcome.translation is not None
            and outcome.assembled is not None
            and outcome.output is not None
        ):
            error_analyses = analyze_failure(
                problem_text=pending.submission.problem_text,
                analysis=pending.analysis,
                statement=pending.statement,
                translation=outcome.translation,
                assembled=outcome.assembled,
                output=outcome.output,
                llm=self.llm,
            )
            versions.append(EXPLAIN_ERROR_VERSION)

        fidelity = (
            FidelitySummary.from_translation(pending.statement, outcome.translation)
            if outcome.translation is not None
            else None
        )
        report = CheckReport(
            submission=pending.submission,
            status=outcome.status,
            status_detail="" if outcome.status is VerificationStatus.VERIFIED else outcome.detail,
            analysis=pending.analysis,
            statement=pending.statement,
            translation=outcome.translation,
            lean_run=outcome.run,
            diagnostics=outcome.output.diagnostics if outcome.output else (),
            error_analyses=error_analyses,
            fidelity=fidelity,
            llm_model=_join(models),
            prompt_version=_join(versions),
        )
        logger.info("check %s finished: %s", report.id, report.status)
        return VerifiedCheck(report, pending.statement_attempts, outcome.attempts)

    # ---------------------------------------------------- learning (on demand)

    def explain_code(self, report: CheckReport) -> CodeExplanation | None:
        """Advanced Feature A; called only when the student asks for it."""
        return explain_code(report, self.llm)

    def suggest_correction(self, report: CheckReport, error_index: int) -> Correction:
        """Advanced Feature D; checked by Lean; never changes ``report``.
        Raises CorrectionUnavailable with a student-facing message."""
        return suggest_correction(report, error_index, self.llm, self.lean)


def _report(
    submission: Submission,
    status: VerificationStatus,
    detail: str,
    *,
    analysis: ProblemAnalysis | None = None,
    models: list[str] | None = None,
    versions: list[str] | None = None,
) -> CheckReport:
    return CheckReport(
        submission=submission,
        status=status,
        status_detail=detail or str(status),
        analysis=analysis,
        llm_model=_join(models or []),
        prompt_version=_join(versions or []),
    )


def _clarification_detail(analysis: ProblemAnalysis) -> str:
    if not analysis.in_scope:
        reason = analysis.out_of_scope_reason or "it is outside the supported topics"
        return (
            "This problem is outside what the checker currently supports "
            f"(sequences of real numbers): {reason}"
        )
    return "Please clarify: " + " ".join(analysis.ambiguities)


def _join(items: list[str]) -> str | None:
    unique = list(dict.fromkeys(i for i in items if i))
    return ", ".join(unique) or None
