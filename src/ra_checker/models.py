"""Shared data models for every pipeline stage (see docs/ARCHITECTURE.md §5).

All models are immutable (frozen, tuple collections) and reject unknown fields.
Student text is stored exactly as typed; nothing here strips or rewrites it.

Step ids: ``S1, S2, ...`` are steps of the student's proof (tagged ``-- [Sk]``
in Lean); ``A1, A2, ...`` are steps the translator added (``-- [Ak]``).

:class:`CheckReport` enforces status invariants on construction *and* on
deserialization. In particular a ``VERIFIED`` report cannot exist without a
completed, error-free Lean run of the student-confirmed statement. This is a
last line of defence; the full verdict rules (``sorry``, axioms, exact
statement match) are computed from Lean output in ``report/verdict.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


NonBlankStr = Annotated[str, AfterValidator(_not_blank)]
StudentStepId = Annotated[str, Field(pattern=r"^S[1-9][0-9]*$")]
StepId = Annotated[str, Field(pattern=r"^[SA][1-9][0-9]*$")]


def _require_unique(ids: list[str], what: str) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for item in ids:
        if item in seen:
            duplicates.add(item)
        seen.add(item)
    if duplicates:
        raise ValueError(f"duplicate {what}: {', '.join(sorted(duplicates))}")


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------- enums


class CheckMode(StrEnum):
    QUICK = "quick"
    LEARNING = "learning"


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    VERIFICATION_FAILED = "verification_failed"
    TRANSLATION_FAILED = "translation_failed"
    NEEDS_CLARIFICATION = "needs_clarification"
    RUNTIME_ERROR = "runtime_error"


class StepStatus(StrEnum):
    TRANSLATED = "translated"
    ADDED = "added"
    OMITTED = "omitted"
    CHANGED = "changed"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class LeanErrorKind(StrEnum):
    """What Lean complained about, from the message text (rule-based)."""

    SYNTAX = "syntax"
    UNKNOWN_IDENTIFIER = "unknown_identifier"
    TYPE_MISMATCH = "type_mismatch"
    UNSOLVED_GOALS = "unsolved_goals"
    TACTIC_FAILED = "tactic_failed"
    OTHER = "other"


class ErrorCategory(StrEnum):
    """The categories from both specs, plus formalization and unknown."""

    MATHEMATICAL_REASONING = "mathematical_reasoning"
    MISSING_ASSUMPTION = "missing_assumption"
    INCOMPLETE_PROOF = "incomplete_proof"
    INCORRECT_THEOREM_APPLICATION = "incorrect_theorem_application"
    ALGEBRAIC_COMPUTATIONAL = "algebraic_computational"
    LEAN_SYNTAX = "lean_syntax"
    TYPE_MISMATCH = "type_mismatch"
    UNRESOLVED_GOAL = "unresolved_goal"
    FORMALIZATION_ERROR = "formalization_error"
    UNKNOWN = "unknown"


class ErrorOrigin(StrEnum):
    STUDENT_REASONING = "student_reasoning"
    FORMALIZATION = "formalization"
    UNDETERMINED = "undetermined"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# -------------------------------------------------------------------- input stage


class Submission(_Model):
    """What the student typed, kept verbatim."""

    problem_text: NonBlankStr
    proof_text: NonBlankStr
    mode: CheckMode = CheckMode.QUICK


# ------------------------------------------------------------------ parsing stage


class ProofStep(_Model):
    id: StudentStepId
    text: NonBlankStr
    verbatim: bool = True  # False if the parser reworded the student's text


class ProblemAnalysis(_Model):
    """The parser's reading of the problem and the proof's structure."""

    hypotheses: tuple[NonBlankStr, ...] = ()
    goal: str = ""
    proof_steps: tuple[ProofStep, ...] = ()
    ambiguities: tuple[NonBlankStr, ...] = ()
    in_scope: bool
    out_of_scope_reason: str = ""
    topic: str | None = None

    @property
    def needs_clarification(self) -> bool:
        return bool(self.ambiguities) or not self.in_scope

    @model_validator(mode="after")
    def _check(self) -> ProblemAnalysis:
        _require_unique([s.id for s in self.proof_steps], "proof step ids")
        if not self.needs_clarification and not self.goal.strip():
            raise ValueError("an unambiguous, in-scope problem must state its goal")
        return self


# -------------------------------------------------------------- translation stage


class FormalStatement(_Model):
    """The Lean statement shown to the student next to the original."""

    lean_statement: NonBlankStr
    back_translation: NonBlankStr
    assumptions_added: tuple[NonBlankStr, ...] = ()
    confirmed_by_student: bool = False


class StepMapping(_Model):
    step_id: StepId
    status: StepStatus
    note: str = ""

    @model_validator(mode="after")
    def _check(self) -> StepMapping:
        if self.step_id.startswith("A") != (self.status is StepStatus.ADDED):
            raise ValueError(
                "translator-added steps use ids A1, A2, ... with status 'added'; "
                "student steps use ids S1, S2, ..."
            )
        return self


class ProofTranslation(_Model):
    """The LLM-written tactic block and how it maps to the student's steps."""

    tactic_block: NonBlankStr
    step_map: tuple[StepMapping, ...] = ()
    translator_notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> ProofTranslation:
        _require_unique([m.step_id for m in self.step_map], "step ids in step_map")
        return self


class FidelitySummary(_Model):
    """How closely the formalization follows the student. Never part of the status."""

    statement_confirmed: bool
    translated_steps: tuple[StepId, ...] = ()
    added_steps: tuple[StepId, ...] = ()
    omitted_steps: tuple[StepId, ...] = ()
    changed_steps: tuple[StepId, ...] = ()

    @property
    def is_faithful(self) -> bool:
        return self.statement_confirmed and not (
            self.added_steps or self.omitted_steps or self.changed_steps
        )

    @classmethod
    def from_translation(
        cls, statement: FormalStatement, translation: ProofTranslation
    ) -> FidelitySummary:
        def ids(status: StepStatus) -> tuple[str, ...]:
            return tuple(m.step_id for m in translation.step_map if m.status is status)

        return cls(
            statement_confirmed=statement.confirmed_by_student,
            translated_steps=ids(StepStatus.TRANSLATED),
            added_steps=ids(StepStatus.ADDED),
            omitted_steps=ids(StepStatus.OMITTED),
            changed_steps=ids(StepStatus.CHANGED),
        )


# --------------------------------------------------------------------- Lean stage


class LeanRun(_Model):
    """One execution of Lean on one assembled file."""

    source: NonBlankStr  # the exact file content Lean checked
    exit_code: int | None
    timed_out: bool = False
    duration_s: float = Field(ge=0)
    stdout: str = ""
    stderr: str = ""
    lean_version: str | None = None

    @property
    def completed(self) -> bool:
        return not self.timed_out and self.exit_code is not None

    @model_validator(mode="after")
    def _check(self) -> LeanRun:
        if not self.timed_out and self.exit_code is None:
            raise ValueError("a run that did not time out must have an exit code")
        return self


class Diagnostic(_Model):
    """One message reported by Lean."""

    line: int = Field(ge=1)
    column: int = Field(ge=0)
    severity: Severity
    message: NonBlankStr
    goal_state: str | None = None
    step_id: StepId | None = None


# ----------------------------------------------------------------- analysis stage


class ErrorAnalysis(_Model):
    """Explanation of one Lean failure. The raw message is always kept."""

    lean_error_kind: LeanErrorKind
    category: ErrorCategory
    origin: ErrorOrigin
    confidence: Confidence
    raw_message: NonBlankStr
    explanation: NonBlankStr
    step_id: StepId | None = None
    line: int | None = Field(default=None, ge=1)  # line within the tactic block
    correction_direction: str | None = None

    @property
    def confident(self) -> bool:
        """False → the UI must say the cause could not be confidently identified."""
        return self.confidence is not Confidence.LOW and self.origin is not ErrorOrigin.UNDETERMINED


# ------------------------------------------------------------------------- report


class CheckReport(_Model):
    """Everything about one check. Immutable once built."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    submission: Submission
    status: VerificationStatus
    status_detail: str = ""
    analysis: ProblemAnalysis | None = None
    statement: FormalStatement | None = None
    translation: ProofTranslation | None = None
    lean_run: LeanRun | None = None
    diagnostics: tuple[Diagnostic, ...] = ()
    error_analyses: tuple[ErrorAnalysis, ...] = ()
    fidelity: FidelitySummary | None = None
    llm_model: str | None = None
    prompt_version: str | None = None

    @model_validator(mode="after")
    def _check_status_invariants(self) -> CheckReport:
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")

        if self.status is VerificationStatus.VERIFIED:
            self._require_verification_evidence()
            return self

        if not self.status_detail.strip():
            raise ValueError(f"status '{self.status}' requires a status_detail")
        if self.status is VerificationStatus.VERIFICATION_FAILED:
            if self.lean_run is None:
                raise ValueError(
                    "status 'verification_failed' requires the Lean run that failed"
                )
        if self.status is VerificationStatus.NEEDS_CLARIFICATION:
            if self.analysis is None or not self.analysis.needs_clarification:
                raise ValueError(
                    "status 'needs_clarification' requires an analysis with "
                    "ambiguities or an out-of-scope problem"
                )
        return self

    def _require_verification_evidence(self) -> None:
        problems: list[str] = []
        run = self.lean_run
        if run is None:
            problems.append("no Lean run is attached")
        elif run.timed_out:
            problems.append("the Lean run timed out")
        elif run.exit_code != 0:
            problems.append(f"Lean exited with code {run.exit_code}")
        if any(d.severity is Severity.ERROR for d in self.diagnostics):
            problems.append("Lean reported errors")
        if self.error_analyses:
            problems.append("error analyses are present")
        statement = self.statement
        if statement is None or not statement.confirmed_by_student:
            problems.append("the formal statement was not confirmed by the student")
        elif run is not None and statement.lean_statement not in run.source:
            problems.append("the Lean run did not check the confirmed statement")
        if self.translation is None:
            problems.append("no proof translation is attached")
        if self.fidelity is None:
            problems.append("no fidelity summary is attached")
        if problems:
            raise ValueError(
                "status 'verified' requires real Lean evidence: " + "; ".join(problems)
            )
