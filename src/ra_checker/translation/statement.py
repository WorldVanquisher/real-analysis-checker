"""Stage 2a: formalize the problem statement and make Lean type-check it.

The LLM drafts ``(binders) : goal`` plus a plain-English back-translation. The
draft must pass the safety screen and elaborate in Lean (with ``sorry`` as the
proof). If Lean rejects it, the LLM gets the errors and may fix the statement
— at most :data:`MAX_STATEMENT_REPAIRS` times, keeping its meaning. The result
is *not* confirmed: the student must confirm it before the proof stage.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from ra_checker.input_validation import normalize_for_llm
from ra_checker.lean.assemble import assemble_statement_check
from ra_checker.lean.diagnostics import parse_lean_output
from ra_checker.lean.runner import LeanRunner, LeanUnavailableError
from ra_checker.lean.safety import check_statement
from ra_checker.llm.client import LLMClient, LLMError
from ra_checker.llm.prompts import (
    FORMALIZE_STATEMENT_SYSTEM,
    FORMALIZE_STATEMENT_VERSION,
    formalize_statement_user_message,
    repair_statement_user_message,
)
from ra_checker.models import FormalStatement, ProblemAnalysis, VerificationStatus
from ra_checker.report.verdict import decide_statement_check
from ra_checker.translation import status_for_llm_error

logger = logging.getLogger(__name__)

FORMALIZE_TASK = "formalize_statement"
REPAIR_STATEMENT_TASK = "repair_statement"
MAX_STATEMENT_REPAIRS = 2


class StatementOutput(BaseModel):
    """The LLM's answer (structured output schema)."""

    model_config = ConfigDict(extra="forbid")

    cannot_formalize: bool
    reason: str
    lean_statement: str
    back_translation: str
    assumptions_added: list[str]


@dataclass(frozen=True)
class StatementAttempt:
    lean_statement: str
    accepted: bool
    problems: tuple[str, ...]


@dataclass(frozen=True)
class StatementOutcome:
    statement: FormalStatement | None  # set only on success; never pre-confirmed
    failure: VerificationStatus | None
    detail: str
    attempts: tuple[StatementAttempt, ...]
    llm_model: str | None
    prompt_version: str = FORMALIZE_STATEMENT_VERSION

    @property
    def ok(self) -> bool:
        return self.statement is not None


def formalize_statement(
    problem_text: str, analysis: ProblemAnalysis, llm: LLMClient, lean: LeanRunner
) -> StatementOutcome:
    if analysis.needs_clarification:
        raise ValueError("the problem needs clarification before it can be formalized")
    problem = normalize_for_llm(problem_text)
    attempts: list[StatementAttempt] = []
    model: str | None = None

    def fail(status: VerificationStatus, detail: str) -> StatementOutcome:
        return StatementOutcome(None, status, detail, tuple(attempts), model)

    user = formalize_statement_user_message(problem, list(analysis.hypotheses), analysis.goal)
    task = FORMALIZE_TASK
    for round_number in range(MAX_STATEMENT_REPAIRS + 1):
        try:
            result = llm.complete_structured(
                task=task,
                system=FORMALIZE_STATEMENT_SYSTEM,
                user=user,
                schema=StatementOutput,
                effort="high",
            )
        except LLMError as exc:
            return fail(status_for_llm_error(exc), str(exc))
        model, out = result.model, result.value
        if out.cannot_formalize or not out.lean_statement.strip():
            reason = out.reason.strip() or "no reason was given"
            return fail(
                VerificationStatus.TRANSLATION_FAILED,
                f"The problem could not be stated faithfully in Lean: {reason}",
            )

        statement = out.lean_statement.strip()
        try:
            problems, runtime_problem = _check_statement(statement, lean)
        except LeanUnavailableError as exc:
            return fail(VerificationStatus.RUNTIME_ERROR, str(exc))
        attempts.append(StatementAttempt(statement, not problems, tuple(problems)))
        if runtime_problem:
            return fail(VerificationStatus.RUNTIME_ERROR, "; ".join(problems))
        if not problems:
            logger.info("statement accepted after %d attempt(s)", len(attempts))
            return StatementOutcome(
                statement=FormalStatement(
                    lean_statement=statement,
                    back_translation=out.back_translation.strip() or "(no back-translation given)",
                    assumptions_added=tuple(a.strip() for a in out.assumptions_added if a.strip()),
                    confirmed_by_student=False,
                ),
                failure=None,
                detail="Lean accepted the formal statement; the student must confirm it.",
                attempts=tuple(attempts),
                llm_model=model,
            )
        logger.info("statement attempt %d rejected (%d problem(s))", round_number + 1, len(problems))
        task = REPAIR_STATEMENT_TASK
        user = repair_statement_user_message(problem, statement, problems)

    return fail(
        VerificationStatus.TRANSLATION_FAILED,
        f"Lean did not accept the formal statement after {len(attempts)} attempts: "
        + "; ".join(attempts[-1].problems),
    )


def _check_statement(statement: str, lean: LeanRunner) -> tuple[list[str], bool]:
    """Return (problems, runtime_problem). Raises LeanUnavailableError."""
    screen = check_statement(statement)
    if not screen.ok:
        return [f"line {v.line}: {v.message}" for v in screen.violations], False
    assembled = assemble_statement_check(statement)
    run = lean.run(assembled.source)
    output = parse_lean_output(run.stdout, assembled.theorem_name, run.stderr)
    check = decide_statement_check(assembled=assembled, run=run, output=output)
    if check.ok:
        return [], False
    return list(check.reasons), check.runtime_problem
