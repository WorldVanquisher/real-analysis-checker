"""Deterministic, student-facing wording for a report (no LLM).

Rules from the specs that this module enforces:

* never say the student's proof is correct — Lean's acceptance is always
  worded as applying to the *formal* proof;
* when the translation departs from the student's steps, say so in the
  headline, naming the steps;
* when the cause of a failure could not be confidently identified, say that
  explicitly instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ra_checker.models import (
    CheckReport,
    ErrorAnalysis,
    ErrorCategory,
    ErrorOrigin,
    FidelitySummary,
    StepStatus,
    VerificationStatus,
)

Level = Literal["success", "warning", "error", "info"]

NOT_CONFIDENT = "We cannot confidently identify the mathematical error."

CATEGORY_LABELS: dict[ErrorCategory, str] = {
    ErrorCategory.MATHEMATICAL_REASONING: "Mathematical reasoning error",
    ErrorCategory.MISSING_ASSUMPTION: "Missing assumption",
    ErrorCategory.INCOMPLETE_PROOF: "Incomplete proof",
    ErrorCategory.INCORRECT_THEOREM_APPLICATION: "Incorrect theorem application",
    ErrorCategory.ALGEBRAIC_COMPUTATIONAL: "Algebraic or computational error",
    ErrorCategory.LEAN_SYNTAX: "Lean syntax error (translation problem)",
    ErrorCategory.TYPE_MISMATCH: "Type mismatch",
    ErrorCategory.UNRESOLVED_GOAL: "Unresolved proof goal",
    ErrorCategory.FORMALIZATION_ERROR: "Formalization error (translation problem)",
    ErrorCategory.UNKNOWN: "Unclassified error",
}
ORIGIN_LABELS: dict[ErrorOrigin, str] = {
    ErrorOrigin.STUDENT_REASONING: "Likely in your reasoning",
    ErrorOrigin.FORMALIZATION: "In the Lean translation, not your mathematics",
    ErrorOrigin.UNDETERMINED: "Could not be determined",
}
STEP_STATUS_LABELS: dict[StepStatus, str] = {
    StepStatus.TRANSLATED: "translated as written",
    StepStatus.CHANGED: "changed by the translator",
    StepStatus.OMITTED: "not translated",
    StepStatus.ADDED: "added by the translator",
}


@dataclass(frozen=True)
class Headline:
    level: Level
    title: str
    body: str


def headline(report: CheckReport) -> Headline:
    status = report.status
    if status is VerificationStatus.VERIFIED:
        return _verified_headline(report.fidelity)
    if status is VerificationStatus.VERIFICATION_FAILED:
        first = report.error_analyses[0] if report.error_analyses else None
        where = f" The first problem is in step {first.step_id}." if first and first.step_id else ""
        return Headline(
            "error",
            "Lean did not accept the formalized proof.",
            f"Lean found a step it could not verify.{where} See the explanation below — it "
            "says whether the problem looks like your reasoning or the Lean translation.",
        )
    if status is VerificationStatus.TRANSLATION_FAILED:
        return Headline(
            "warning",
            "Your proof could not be fully translated into Lean.",
            f"{report.status_detail} This does not mean your proof is wrong — only that it "
            "could not be checked automatically.",
        )
    if status is VerificationStatus.NEEDS_CLARIFICATION:
        return Headline("info", "We need a clarification before checking.", report.status_detail)
    return Headline(
        "error",
        "The check could not be completed.",
        f"{report.status_detail} Nothing was verified; please try again.",
    )


def _verified_headline(fidelity: FidelitySummary | None) -> Headline:
    if fidelity is not None and fidelity.is_faithful:
        return Headline(
            "success",
            "Lean accepted the formalized proof.",
            "The Lean proof follows your steps as written. Lean's acceptance applies to "
            "this formal version; compare the formal statement with the problem to make "
            "sure it says the same thing.",
        )
    differences = describe_differences(fidelity) if fidelity else "it could not be compared"
    return Headline(
        "warning",
        "Lean accepted a formal proof that differs from yours.",
        f"The translation departs from your proof: {differences}. Lean's acceptance "
        "applies to the formal proof, so check those steps of your own argument.",
    )


def describe_differences(fidelity: FidelitySummary) -> str:
    parts = []
    if not fidelity.statement_confirmed:
        parts.append("the formal statement was not confirmed")
    for label, steps in (
        ("added", fidelity.added_steps),
        ("changed", fidelity.changed_steps),
        ("not translated", fidelity.omitted_steps),
    ):
        if steps:
            parts.append(f"{label}: {', '.join(steps)}")
    return "; ".join(parts) or "no differences"


def explanation_lines(error: ErrorAnalysis) -> tuple[str, str]:
    """(classification line, explanation) for one analysed error."""
    classification = f"{CATEGORY_LABELS[error.category]} — {ORIGIN_LABELS[error.origin]}"
    if not error.confident:
        return classification, f"{NOT_CONFIDENT} {error.explanation}"
    return f"{classification} (confidence: {error.confidence.value})", error.explanation
