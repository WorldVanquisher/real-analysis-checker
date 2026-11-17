"""Stage 2b: translate the student's proof into a tagged Lean tactic block,
assemble it around the locked statement and let Lean check it.

Deterministic rules the LLM cannot override:

* the statement must have been confirmed by the student, and is inserted by
  Python (``assemble_proof``) — the LLM writes only tactics;
* step statuses are reconciled with the tags actually present in the code: a
  student step with no tag is ``omitted``, a tagged step whose tactics are only
  a ``sorry`` placeholder is ``omitted`` (placeholder), ``-- [Ak]`` blocks are
  ``added``; untagged code before the first tag is labelled as an added step;
* a translation that fails the safety screen is rejected, never repaired;
* repair is attempted only when every Lean error is Lean-side (syntax or an
  unknown name), at most :data:`MAX_PROOF_REPAIRS` times, and a repair is
  accepted only if it keeps exactly the same tags and the same number of
  placeholders — so it cannot add, drop, or fill in mathematical steps.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ra_checker.analysis.classify import LEAN_SIDE_KINDS, classify_lean_error
from ra_checker.input_validation import normalize_for_llm
from ra_checker.lean.assemble import AssembledFile, AssemblyError, assemble_proof
from ra_checker.lean.diagnostics import LeanOutput, parse_lean_output
from ra_checker.lean.runner import LeanRunner, LeanUnavailableError
from ra_checker.lean.safety import check_tactic_block
from ra_checker.llm.client import LLMClient, LLMError
from ra_checker.llm.prompts import (
    TRANSLATE_PROOF_SYSTEM,
    TRANSLATE_PROOF_VERSION,
    repair_proof_user_message,
    translate_proof_user_message,
)
from ra_checker.models import (
    FormalStatement,
    LeanRun,
    ProblemAnalysis,
    ProofTranslation,
    StepMapping,
    StepStatus,
    VerificationStatus,
)
from ra_checker.report.verdict import LeanVerdict, decide_proof_verdict
from ra_checker.translation import status_for_llm_error

logger = logging.getLogger(__name__)

TRANSLATE_TASK = "translate_proof"
REPAIR_PROOF_TASK = "repair_proof"
MAX_PROOF_REPAIRS = 2
_TAG_LINE_RE = re.compile(r"^\s*--\s*\[([SA][1-9][0-9]*)\]\s*$")


class StepEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    status: Literal["translated", "changed", "omitted", "added"]
    note: str


class ProofOutput(BaseModel):
    """The LLM's answer (structured output schema)."""

    model_config = ConfigDict(extra="forbid")

    tactic_block: str
    step_map: list[StepEntry]
    translator_notes: str


@dataclass(frozen=True)
class ProofAttempt:
    kind: Literal["initial", "repair"]
    tactic_block: str
    status: VerificationStatus | None  # None: rejected before Lean ran
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ProofOutcome:
    status: VerificationStatus
    detail: str
    translation: ProofTranslation | None = None
    assembled: AssembledFile | None = None
    run: LeanRun | None = None
    output: LeanOutput | None = None
    verdict: LeanVerdict | None = None
    attempts: tuple[ProofAttempt, ...] = field(default_factory=tuple)
    llm_model: str | None = None
    prompt_version: str = TRANSLATE_PROOF_VERSION


# ------------------------------------------------------------- tag reconciliation


@dataclass(frozen=True)
class TaggedBlock:
    block: str  # possibly with an inserted tag for leading untagged code
    tags: tuple[str, ...]  # in order of appearance
    segments: dict[str, str]  # tag -> tactics under it
    problems: tuple[str, ...]


def split_tags(block: str, student_ids: list[str]) -> TaggedBlock:
    lines = block.replace("\r\n", "\n").split("\n")
    tags: list[str] = []
    segments: dict[str, list[str]] = {}
    current: str | None = None
    leading: list[str] = []
    for line in lines:
        if match := _TAG_LINE_RE.match(line):
            current = match.group(1)
            tags.append(current)
            segments.setdefault(current, [])
        elif current is None:
            leading.append(line)
        else:
            segments[current].append(line)

    problems: list[str] = []
    duplicates = sorted({t for t in tags if tags.count(t) > 1})
    if duplicates:
        problems.append(f"step tags used more than once: {', '.join(duplicates)}")
    unknown = [t for t in tags if t.startswith("S") and t not in student_ids]
    if unknown:
        problems.append(f"tags for steps the student did not write: {', '.join(unknown)}")

    if any(_is_code(line) for line in leading):
        # Label leading untagged code instead of letting it go unaccounted for.
        added = [int(t[1:]) for t in tags if t.startswith("A")]
        new_tag = f"A{max(added, default=0) + 1}"
        tags.insert(0, new_tag)
        segments = {new_tag: leading, **segments}
        block = f"-- [{new_tag}]\n" + "\n".join(lines)
    return TaggedBlock(
        block=block,
        tags=tuple(tags),
        segments={t: "\n".join(body) for t, body in segments.items()},
        problems=tuple(problems),
    )


def reconcile_step_map(
    tagged: TaggedBlock, entries: list[StepEntry], student_ids: list[str]
) -> tuple[StepMapping, ...]:
    """Statuses follow the code; the LLM only contributes notes and the
    translated-vs-changed judgement for steps that really have code."""
    by_id = {e.step_id: e for e in entries}
    mapping: list[StepMapping] = []
    for step_id in student_ids:
        entry = by_id.get(step_id)
        note = entry.note.strip() if entry else ""
        if step_id not in tagged.segments:
            status, note = StepStatus.OMITTED, note or "no Lean code is tagged with this step"
        elif _only_placeholder(tagged.segments[step_id]):
            status = StepStatus.OMITTED
            note = f"left as a placeholder (sorry): {note}" if note else "left as a placeholder (sorry)"
        elif entry is not None and entry.status == "changed":
            status = StepStatus.CHANGED
        else:
            status = StepStatus.TRANSLATED
        mapping.append(StepMapping(step_id=step_id, status=status, note=note))
    for tag in tagged.tags:
        if tag.startswith("A"):
            entry = by_id.get(tag)
            note = entry.note.strip() if entry else "added by the translator"
            mapping.append(StepMapping(step_id=tag, status=StepStatus.ADDED, note=note))
    return tuple(mapping)


def _is_code(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("--")


def _only_placeholder(segment: str) -> bool:
    code = [line.strip() for line in segment.split("\n") if _is_code(line)]
    return bool(code) and check_tactic_block(segment).placeholder_count > 0 and all(
        line in ("sorry", "· sorry", "exact sorry") for line in code
    )


# ---------------------------------------------------------------------- the stage


def translate_proof(
    problem_text: str,
    analysis: ProblemAnalysis,
    statement: FormalStatement,
    llm: LLMClient,
    lean: LeanRunner,
) -> ProofOutcome:
    if not statement.confirmed_by_student:
        raise ValueError("the formal statement must be confirmed by the student first")
    problem = normalize_for_llm(problem_text)
    student_ids = [s.id for s in analysis.proof_steps]
    base_user = translate_proof_user_message(
        problem, [(s.id, normalize_for_llm(s.text)) for s in analysis.proof_steps], statement.lean_statement
    )
    attempts: list[ProofAttempt] = []
    model: str | None = None

    def fail(status: VerificationStatus, detail: str, **extra) -> ProofOutcome:
        return ProofOutcome(status, detail, attempts=tuple(attempts), llm_model=model, **extra)

    try:
        result = llm.complete_structured(
            task=TRANSLATE_TASK, system=TRANSLATE_PROOF_SYSTEM, user=base_user,
            schema=ProofOutput, effort="high",
        )
    except LLMError as exc:
        return fail(status_for_llm_error(exc), str(exc))
    model, out = result.model, result.value
    kind: Literal["initial", "repair"] = "initial"
    previous: TaggedBlock | None = None
    last: ProofOutcome | None = None

    for round_number in range(MAX_PROOF_REPAIRS + 1):
        tagged = split_tags(out.tactic_block, student_ids)
        if previous is not None and not _same_shape(previous, tagged):
            attempts.append(ProofAttempt(kind, tagged.block, None, (
                "repair rejected: it changed the step tags or placeholders",
            )))
            break  # keep the previous attempt's result
        if tagged.problems:
            attempts.append(ProofAttempt(kind, tagged.block, None, tagged.problems))
            return fail(
                VerificationStatus.TRANSLATION_FAILED,
                "The translation's step tags are inconsistent: " + "; ".join(tagged.problems),
            )
        screen = check_tactic_block(tagged.block)
        if not screen.ok:
            reasons = tuple(f"line {v.line}: {v.message}" for v in screen.violations)
            attempts.append(ProofAttempt(kind, tagged.block, None, reasons))
            return fail(
                VerificationStatus.TRANSLATION_FAILED,
                "The generated Lean was rejected by the safety screen: " + "; ".join(reasons),
            )
        try:
            assembled = assemble_proof(statement.lean_statement, tagged.block)
        except AssemblyError as exc:
            attempts.append(ProofAttempt(kind, tagged.block, None, (str(exc),)))
            return fail(VerificationStatus.TRANSLATION_FAILED, f"The translation is unusable: {exc}")

        translation = ProofTranslation(
            tactic_block=tagged.block,
            step_map=reconcile_step_map(tagged, out.step_map, student_ids),
            translator_notes=out.translator_notes.strip(),
        )
        try:
            run = lean.run(assembled.source)
        except LeanUnavailableError as exc:
            return fail(VerificationStatus.RUNTIME_ERROR, str(exc), translation=translation)
        output = parse_lean_output(run.stdout, assembled.theorem_name, run.stderr)
        verdict = decide_proof_verdict(
            confirmed_statement=statement.lean_statement, assembled=assembled, run=run, output=output
        )
        attempts.append(ProofAttempt(kind, tagged.block, verdict.status, verdict.reasons))
        last = ProofOutcome(
            status=verdict.status,
            detail="; ".join(verdict.reasons),
            translation=translation,
            assembled=assembled,
            run=run,
            output=output,
            verdict=verdict,
            llm_model=model,
        )
        logger.info("proof attempt %d (%s): %s", round_number + 1, kind, verdict.status)

        lean_side = output.errors and all(
            classify_lean_error(e.message) in LEAN_SIDE_KINDS for e in output.errors
        )
        if verdict.status is not VerificationStatus.VERIFICATION_FAILED or not lean_side:
            break
        if round_number == MAX_PROOF_REPAIRS:
            break
        errors = [
            f"line {assembled.proof_line(e.line) or '?'} of your tactic block: {e.message.splitlines()[0]}"
            for e in output.errors
        ]
        try:
            repaired = llm.complete_structured(
                task=REPAIR_PROOF_TASK, system=TRANSLATE_PROOF_SYSTEM,
                user=repair_proof_user_message(base_user, tagged.block, errors),
                schema=ProofOutput, effort="high",
            )
        except LLMError as exc:
            logger.info("repair call failed (%s); keeping the previous attempt", type(exc).__name__)
            break
        model, out, kind, previous = repaired.model, repaired.value, "repair", tagged

    assert last is not None  # the loop always runs Lean at least once or returns
    return ProofOutcome(
        status=last.status,
        detail=last.detail,
        translation=last.translation,
        assembled=last.assembled,
        run=last.run,
        output=last.output,
        verdict=last.verdict,
        attempts=tuple(attempts),
        llm_model=last.llm_model,
    )


def _same_shape(before: TaggedBlock, after: TaggedBlock) -> bool:
    return before.tags == after.tags and (
        check_tactic_block(before.block).placeholder_count
        == check_tactic_block(after.block).placeholder_count
    )
