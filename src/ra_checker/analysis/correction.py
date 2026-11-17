"""Advanced Feature D: a corrected version of the proof, checked by Lean.

The LLM proposes a corrected version of the *whole* tactic block, changing as
little as possible. It may change earlier steps: the first live run showed
that the step where Lean fails is often not where the mistake is made (choosing
ε instead of ε/2 in S2 and S3 only fails at the final estimate in S5), and a
correction confined to the failing step could never verify. Deterministic
rules:

* the corrected proof must keep exactly the same step tags, in the same order,
  so every change can be shown against the student's own step;
* which steps changed is computed by comparing the code, not taken from the
  LLM;
* the result is screened, assembled around the *same* locked statement and
  checked by Lean with the same verdict rules as the student's check; it is
  labelled verified only if that verdict is VERIFIED.

A correction never changes the report of the student's own proof.
"""

from __future__ import annotations

import logging
import textwrap
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from ra_checker.input_validation import normalize_for_llm
from ra_checker.lean.assemble import AssemblyError, assemble_proof
from ra_checker.lean.diagnostics import parse_lean_output
from ra_checker.lean.runner import LeanRunner, LeanUnavailableError
from ra_checker.lean.safety import check_tactic_block
from ra_checker.llm.client import LLMClient, LLMError
from ra_checker.llm.prompts import (
    SUGGEST_CORRECTION_SYSTEM,
    SUGGEST_CORRECTION_VERSION,
    suggest_correction_user_message,
)
from ra_checker.models import CheckReport, VerificationStatus
from ra_checker.report.verdict import decide_proof_verdict
from ra_checker.translation.proof import split_tags

logger = logging.getLogger(__name__)

CORRECTION_TASK = "suggest_correction"


class CorrectionOutput(BaseModel):
    """The LLM's answer (structured output schema)."""

    model_config = ConfigDict(extra="forbid")

    corrected_proof: str
    explanation: str


@dataclass(frozen=True)
class StepChange:
    step_id: str
    before: str
    after: str


@dataclass(frozen=True)
class Correction:
    focus_step: str | None  # the step where Lean reported the error
    changes: tuple[StepChange, ...]  # computed from the code, in proof order
    full_block: str  # the whole corrected tactic block that Lean checked
    explanation: str
    status: VerificationStatus | None  # None: rejected before Lean ran
    reasons: tuple[str, ...]
    prompt_version: str = SUGGEST_CORRECTION_VERSION

    @property
    def verified(self) -> bool:
        return self.status is VerificationStatus.VERIFIED


class CorrectionUnavailable(Exception):
    """No correction could be produced (user-facing message)."""


def suggest_correction(
    report: CheckReport, error_index: int, llm: LLMClient, lean: LeanRunner
) -> Correction:
    if report.status is not VerificationStatus.VERIFICATION_FAILED:
        raise CorrectionUnavailable("Corrections are offered only when Lean rejected the proof.")
    if report.translation is None or report.statement is None or report.analysis is None:
        raise CorrectionUnavailable("There is no translated proof to correct.")
    try:
        error = report.error_analyses[error_index]
    except IndexError:
        raise CorrectionUnavailable("Unknown error.") from None

    student_ids = [s.id for s in report.analysis.proof_steps]
    original = split_tags(report.translation.tactic_block, student_ids)
    step_text = {s.id: s.text for s in report.analysis.proof_steps}.get(error.step_id or "")
    try:
        answer = llm.complete_structured(
            task=CORRECTION_TASK,
            system=SUGGEST_CORRECTION_SYSTEM,
            user=suggest_correction_user_message(
                problem=normalize_for_llm(report.submission.problem_text),
                statement=report.statement.lean_statement,
                full_block=original.block,
                step_id=error.step_id,
                step_text=step_text,
                lean_message=error.raw_message,
                explanation=error.explanation,
            ),
            schema=CorrectionOutput,
            effort="high",
        ).value
    except LLMError as exc:
        raise CorrectionUnavailable(f"No correction could be generated: {exc}") from None

    corrected = split_tags(answer.corrected_proof.strip("\n"), student_ids)
    changes = tuple(
        StepChange(tag, _tidy(original.segments.get(tag, "")), _tidy(corrected.segments.get(tag, "")))
        for tag in original.tags
        if _tidy(original.segments.get(tag, "")) != _tidy(corrected.segments.get(tag, ""))
    )

    def result(status, reasons) -> Correction:
        return Correction(
            focus_step=error.step_id,
            changes=changes,
            full_block=corrected.block,
            explanation=answer.explanation.strip(),
            status=status,
            reasons=tuple(reasons),
        )

    if corrected.tags != original.tags or corrected.problems:
        return result(None, ["the suggestion changed the proof's step structure"])
    if not changes:
        return result(None, ["the suggestion did not change anything"])
    screen = check_tactic_block(corrected.block)
    if not screen.ok:
        return result(None, [f"rejected by the safety screen: {v.message}" for v in screen.violations])
    if screen.placeholder_count:
        return result(None, ["the suggestion still contains a placeholder (sorry)"])
    try:
        assembled = assemble_proof(report.statement.lean_statement, corrected.block)
        run = lean.run(assembled.source)
    except AssemblyError as exc:
        return result(None, [str(exc)])
    except LeanUnavailableError as exc:
        raise CorrectionUnavailable(f"Lean is not available: {exc}") from None
    output = parse_lean_output(run.stdout, assembled.theorem_name, run.stderr)
    verdict = decide_proof_verdict(
        confirmed_statement=report.statement.lean_statement, assembled=assembled, run=run, output=output
    )
    logger.info("correction changing %s: %s", ", ".join(c.step_id for c in changes), verdict.status)
    return result(verdict.status, verdict.reasons)


def _tidy(segment: str) -> str:
    lines = [line.rstrip() for line in segment.split("\n")]
    return textwrap.dedent("\n".join(lines)).strip()
