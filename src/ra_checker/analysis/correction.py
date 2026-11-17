"""Advanced Feature D: a corrected version of the failing step, checked by Lean.

The LLM proposes replacement tactics for one step only. Python splices them
under that step's tag, screens the result, assembles it around the *same*
locked statement and runs Lean with the same verdict rules as the student's
check. The correction is labelled verified only if that verdict is VERIFIED.
A correction never changes the report of the student's own proof.
"""

from __future__ import annotations

import logging
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
from ra_checker.translation.proof import TAG_LINE_RE

logger = logging.getLogger(__name__)

CORRECTION_TASK = "suggest_correction"


class CorrectionOutput(BaseModel):
    """The LLM's answer (structured output schema)."""

    model_config = ConfigDict(extra="forbid")

    corrected_tactics: str
    explanation: str


@dataclass(frozen=True)
class Correction:
    step_id: str | None
    original_code: str
    corrected_code: str
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

    block = report.translation.tactic_block
    start, end = segment_bounds(block, error.step_id)
    lines = block.split("\n")
    original = "\n".join(lines[start:end]).strip()
    step_text = {s.id: s.text for s in report.analysis.proof_steps}.get(error.step_id or "")

    try:
        answer = llm.complete_structured(
            task=CORRECTION_TASK,
            system=SUGGEST_CORRECTION_SYSTEM,
            user=suggest_correction_user_message(
                problem=normalize_for_llm(report.submission.problem_text),
                statement=report.statement.lean_statement,
                full_block=block,
                step_id=error.step_id,
                step_text=step_text,
                step_code=original,
                lean_message=error.raw_message,
                explanation=error.explanation,
            ),
            schema=CorrectionOutput,
            effort="high",
        ).value
    except LLMError as exc:
        raise CorrectionUnavailable(f"No correction could be generated: {exc}") from None

    corrected = "\n".join(
        line for line in answer.corrected_tactics.strip("\n").split("\n") if not TAG_LINE_RE.match(line)
    ).strip()
    full_block = "\n".join(lines[:start] + corrected.split("\n") + lines[end:])

    def result(status, reasons) -> Correction:
        return Correction(
            step_id=error.step_id,
            original_code=original,
            corrected_code=corrected,
            full_block=full_block,
            explanation=answer.explanation.strip(),
            status=status,
            reasons=tuple(reasons),
        )

    if not corrected:
        return result(None, ["the suggestion was empty"])
    screen = check_tactic_block(full_block)
    if not screen.ok:
        return result(None, [f"rejected by the safety screen: {v.message}" for v in screen.violations])
    if screen.placeholder_count:
        return result(None, ["the suggestion still contains a placeholder (sorry)"])
    try:
        assembled = assemble_proof(report.statement.lean_statement, full_block)
        run = lean.run(assembled.source)
    except AssemblyError as exc:
        return result(None, [str(exc)])
    except LeanUnavailableError as exc:
        raise CorrectionUnavailable(f"Lean is not available: {exc}") from None
    output = parse_lean_output(run.stdout, assembled.theorem_name, run.stderr)
    verdict = decide_proof_verdict(
        confirmed_statement=report.statement.lean_statement, assembled=assembled, run=run, output=output
    )
    logger.info("correction for %s: %s", error.step_id, verdict.status)
    return result(verdict.status, verdict.reasons)


def segment_bounds(block: str, step_id: str | None) -> tuple[int, int]:
    """Line range [start, end) of the tactics under ``step_id``'s tag (the whole
    block if there is no such tag)."""
    lines = block.split("\n")
    tags = [(i, m.group(1)) for i, line in enumerate(lines) if (m := TAG_LINE_RE.match(line))]
    for position, (index, tag) in enumerate(tags):
        if tag == step_id:
            end = tags[position + 1][0] if position + 1 < len(tags) else len(lines)
            return index + 1, end
    return 0, len(lines)
