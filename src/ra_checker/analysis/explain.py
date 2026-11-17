"""Stage 4: explain why Lean rejected the formalized proof.

For each of the first :data:`MAX_ANALYZED_ERRORS` Lean errors:

1. classify the message (rules) and locate it to a step (rules);
2. syntax errors and unknown names are Lean-side by definition: they get a
   fixed explanation with ``origin=formalization`` and no LLM call;
3. otherwise the LLM proposes category, origin, confidence and an explanation,
   and code-level guardrails then correct impossible or over-confident
   answers (see :func:`apply_guardrails`);
4. if the LLM is unavailable or declines, a rule-based explanation with
   ``origin=undetermined, confidence=low`` is used, so the student still sees
   the raw Lean message and an honest "we could not tell".
"""

from __future__ import annotations

import logging
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ra_checker.analysis.classify import LEAN_SIDE_KINDS, classify_lean_error
from ra_checker.analysis.locate import ErrorLocation, locate_error
from ra_checker.input_validation import normalize_for_llm
from ra_checker.lean.assemble import AssembledFile
from ra_checker.lean.diagnostics import LeanOutput
from ra_checker.learning.cards import CARDS
from ra_checker.llm.client import LLMClient, LLMError
from ra_checker.llm.prompts import EXPLAIN_ERROR_SYSTEM, explain_error_user_message
from ra_checker.models import (
    Confidence,
    Diagnostic,
    ErrorAnalysis,
    ErrorCategory,
    ErrorOrigin,
    FormalStatement,
    LeanErrorKind,
    ProblemAnalysis,
    ProofTranslation,
    StepStatus,
)

logger = logging.getLogger(__name__)

EXPLAIN_TASK = "explain_error"
MAX_ANALYZED_ERRORS = 3

STUDENT_CATEGORIES = frozenset(
    {
        ErrorCategory.MATHEMATICAL_REASONING,
        ErrorCategory.MISSING_ASSUMPTION,
        ErrorCategory.INCOMPLETE_PROOF,
        ErrorCategory.INCORRECT_THEOREM_APPLICATION,
        ErrorCategory.ALGEBRAIC_COMPUTATIONAL,
    }
)
FORMALIZATION_CATEGORIES = frozenset({ErrorCategory.LEAN_SYNTAX, ErrorCategory.FORMALIZATION_ERROR})

_LEAN_SIDE_TEXT = {
    LeanErrorKind.SYNTAX: (
        "The Lean translation of this step contains a syntax error, so Lean could not "
        "even read it. This is a problem with the automatic translation, not with your "
        "mathematics."
    ),
    LeanErrorKind.UNKNOWN_IDENTIFIER: (
        "The Lean translation of this step refers to a name Lean does not know — most "
        "likely a theorem the translator misremembered. This is a problem with the "
        "automatic translation, not with your mathematics."
    ),
}
_LEAN_SIDE_HINT = (
    "Run the check again; if the same problem appears, state this step more explicitly "
    "(for example, name the inequality or theorem you use)."
)
_FALLBACK_TEXT = {
    LeanErrorKind.UNSOLVED_GOALS: (
        "Lean reached the end of this part of the proof with something still left to "
        "prove (shown under the Lean message)."
    ),
    LeanErrorKind.TACTIC_FAILED: "Lean could not justify this step from what had been established so far.",
    LeanErrorKind.TYPE_MISMATCH: (
        "Lean expected a statement of one form here, but this step provides a statement "
        "of a different form."
    ),
    LeanErrorKind.OTHER: "Lean reported an error in this step.",
}
_UNDETERMINED_SUFFIX = (
    " We could not determine automatically whether this comes from your reasoning or "
    "from the Lean translation."
)


class ExplanationOutput(BaseModel):
    """The LLM's answer (structured output schema)."""

    model_config = ConfigDict(extra="forbid")

    category: Literal[
        "mathematical_reasoning", "missing_assumption", "incomplete_proof",
        "incorrect_theorem_application", "algebraic_computational", "lean_syntax",
        "type_mismatch", "unresolved_goal", "formalization_error", "unknown",
    ]
    origin: Literal["student_reasoning", "formalization", "undetermined"]
    confidence: Literal["high", "medium", "low"]
    explanation: str
    math_interpretation: str
    correction_direction: str


_KIND_CONCEPTS = {
    LeanErrorKind.SYNTAX: "Lean syntax: Lean could not read this code as Lean at all.",
    LeanErrorKind.UNKNOWN_IDENTIFIER: (
        "Names: every theorem or definition used in Lean must exist under exactly that name."
    ),
    LeanErrorKind.UNSOLVED_GOALS: (
        "Goals: after the last tactic Lean still had something left to prove — the "
        "goal shown after ⊢ in the message."
    ),
    LeanErrorKind.TYPE_MISMATCH: (
        "Types: every Lean statement has an exact form, and a fact of one form cannot be "
        "used where a statement of another form is expected."
    ),
}
_TACTIC_IN_MESSAGE = re.compile(r"\b(n?linarith|positivity|norm_num|simp|rewrite|rw|calc|exact|apply)\b")
_TRANSLATION_ONLY = (
    "This is a problem with the Lean translation; it says nothing about your mathematics."
)


def lean_concept_for(kind: LeanErrorKind, message: str) -> str | None:
    """The Lean idea involved in an error, chosen by rules (never by the LLM)."""
    if kind in _KIND_CONCEPTS:
        return _KIND_CONCEPTS[kind]
    if kind is LeanErrorKind.TACTIC_FAILED and (match := _TACTIC_IN_MESSAGE.search(message)):
        word = "rw" if match.group(1) == "rewrite" else match.group(1)
        for card in CARDS:
            if card.pattern.search(word):
                return f"{card.title}: {card.lean_meaning}"
    return None


def analyze_failure(
    *,
    problem_text: str,
    analysis: ProblemAnalysis,
    statement: FormalStatement,
    translation: ProofTranslation,
    assembled: AssembledFile,
    output: LeanOutput,
    llm: LLMClient,
) -> tuple[ErrorAnalysis, ...]:
    statuses = {m.step_id: m for m in translation.step_map}
    results = []
    for diagnostic in output.errors[:MAX_ANALYZED_ERRORS]:
        kind = classify_lean_error(diagnostic.message)
        location = locate_error(diagnostic, assembled, analysis)
        mapping = statuses.get(location.step_id) if location.step_id else None
        if kind in LEAN_SIDE_KINDS:
            results.append(_lean_side(kind, diagnostic, location))
            continue
        try:
            answer = llm.complete_structured(
                task=EXPLAIN_TASK,
                system=EXPLAIN_ERROR_SYSTEM,
                user=explain_error_user_message(
                    problem=normalize_for_llm(problem_text),
                    statement=statement.lean_statement,
                    back_translation=statement.back_translation,
                    step_id=location.step_id,
                    step_text=location.step_text,
                    step_status=mapping.status.value if mapping else None,
                    step_note=mapping.note if mapping else None,
                    lean_snippet=location.lean_snippet,
                    error_kind=kind.value,
                    lean_message=diagnostic.message,
                    goal_state=diagnostic.goal_state,
                    at_end_of_proof=location.at_end_of_proof,
                ),
                schema=ExplanationOutput,
                effort="high",
            ).value
        except LLMError as exc:
            logger.info("explanation unavailable (%s); using the rule-based fallback", type(exc).__name__)
            results.append(_fallback(kind, diagnostic, location))
            continue
        category, origin, confidence = apply_guardrails(
            kind=kind,
            step_id=location.step_id,
            step_status=mapping.status if mapping else None,
            category=ErrorCategory(answer.category),
            origin=ErrorOrigin(answer.origin),
            confidence=Confidence(answer.confidence),
        )
        explanation = answer.explanation.strip() or _FALLBACK_TEXT.get(kind, _FALLBACK_TEXT[LeanErrorKind.OTHER])
        results.append(
            ErrorAnalysis(
                lean_error_kind=kind,
                category=category,
                origin=origin,
                confidence=confidence,
                raw_message=diagnostic.message,
                explanation=explanation,
                step_id=location.step_id,
                line=location.block_line,
                correction_direction=answer.correction_direction.strip() or None,
                math_interpretation=answer.math_interpretation.strip() or None,
                lean_concept=lean_concept_for(kind, diagnostic.message),
            )
        )
    return tuple(results)


def apply_guardrails(
    *,
    kind: LeanErrorKind,
    step_id: str | None,
    step_status: StepStatus | None,
    category: ErrorCategory,
    origin: ErrorOrigin,
    confidence: Confidence,
) -> tuple[ErrorCategory, ErrorOrigin, Confidence]:
    """Deterministic corrections of the LLM's judgement."""
    if kind in LEAN_SIDE_KINDS:
        cat = ErrorCategory.LEAN_SYNTAX if kind is LeanErrorKind.SYNTAX else ErrorCategory.FORMALIZATION_ERROR
        return cat, ErrorOrigin.FORMALIZATION, confidence
    if step_id is not None and step_id.startswith("A"):
        # The failing code is the translator's addition, not the student's step.
        if category in STUDENT_CATEGORIES:
            category = ErrorCategory.FORMALIZATION_ERROR
        return category, ErrorOrigin.FORMALIZATION, confidence
    if origin is ErrorOrigin.STUDENT_REASONING and category in FORMALIZATION_CATEGORIES:
        return category, ErrorOrigin.UNDETERMINED, Confidence.LOW  # self-contradictory answer
    if origin is ErrorOrigin.FORMALIZATION and category in STUDENT_CATEGORIES:
        category = ErrorCategory.FORMALIZATION_ERROR
    if (
        origin is ErrorOrigin.STUDENT_REASONING
        and step_status in (StepStatus.CHANGED, StepStatus.OMITTED)
        and confidence is Confidence.HIGH
    ):
        confidence = Confidence.MEDIUM  # the code did not follow the student exactly
    return category, origin, confidence


def _lean_side(kind: LeanErrorKind, diagnostic: Diagnostic, location: ErrorLocation) -> ErrorAnalysis:
    category, origin, _ = apply_guardrails(
        kind=kind, step_id=location.step_id, step_status=None,
        category=ErrorCategory.UNKNOWN, origin=ErrorOrigin.FORMALIZATION, confidence=Confidence.HIGH,
    )
    return ErrorAnalysis(
        lean_error_kind=kind,
        category=category,
        origin=origin,
        confidence=Confidence.HIGH,
        raw_message=diagnostic.message,
        explanation=_LEAN_SIDE_TEXT[kind],
        step_id=location.step_id,
        line=location.block_line,
        correction_direction=_LEAN_SIDE_HINT,
        math_interpretation=_TRANSLATION_ONLY,
        lean_concept=lean_concept_for(kind, diagnostic.message),
    )


def _fallback(kind: LeanErrorKind, diagnostic: Diagnostic, location: ErrorLocation) -> ErrorAnalysis:
    category = {
        LeanErrorKind.UNSOLVED_GOALS: ErrorCategory.UNRESOLVED_GOAL,
        LeanErrorKind.TYPE_MISMATCH: ErrorCategory.TYPE_MISMATCH,
    }.get(kind, ErrorCategory.UNKNOWN)
    return ErrorAnalysis(
        lean_error_kind=kind,
        category=category,
        origin=ErrorOrigin.UNDETERMINED,
        confidence=Confidence.LOW,
        raw_message=diagnostic.message,
        explanation=_FALLBACK_TEXT.get(kind, _FALLBACK_TEXT[LeanErrorKind.OTHER]) + _UNDETERMINED_SUFFIX,
        step_id=location.step_id,
        line=location.block_line,
        correction_direction=None,
        lean_concept=lean_concept_for(kind, diagnostic.message),
    )
