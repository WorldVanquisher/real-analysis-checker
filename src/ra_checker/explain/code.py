"""Advanced Feature A: explain the generated Lean code, block by block.

One structured LLM call receives the actual tagged code, the student's step for
each block, the statement and Lean's verdict. Its answer is then checked
deterministically:

* only blocks that exist in the code are kept (one per tag, in code order);
* every Lean name the explanation writes in backticks must occur in that
  block, the statement or the RaChecker definitions — otherwise the block's
  explanation is withheld and replaced by an automatic summary built from the
  concept cards, so an explanation can never describe a lemma or tactic the
  proof does not use;
* if the LLM is unavailable, every block gets the automatic summary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ra_checker.input_validation import normalize_for_llm
from ra_checker.learning.cards import ALWAYS_SHOWN
from ra_checker.learning.detect import concepts_in
from ra_checker.llm.client import LLMClient, LLMError
from ra_checker.llm.prompts import (
    DEFINITIONS_SUMMARY,
    EXPLAIN_CODE_SYSTEM,
    EXPLAIN_CODE_VERSION,
    explain_code_user_message,
)
from ra_checker.models import CheckReport, VerificationStatus
from ra_checker.report.mapping import MappingRow, build_mapping

EXPLAIN_CODE_TASK = "explain_code"

_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
_IDENT_RE = re.compile(r"[^\W\d_][\w'.!?]*")
# Words a beginner explanation may put in backticks without them being in the block.
_GENERIC = frozenset({"theorem", "by", "sorry", "Prop", "True", "False"})


class _BlockOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    lean_syntax: str
    math_meaning: str
    role: str
    why_needed: str


class CodeExplanationOutput(BaseModel):
    """The LLM's answer (structured output schema)."""

    model_config = ConfigDict(extra="forbid")

    overview: str
    blocks: list[_BlockOut]


@dataclass(frozen=True)
class BlockExplanation:
    step_id: str
    student_text: str | None
    lean_code: str
    lean_syntax: str
    math_meaning: str
    role: str
    why_needed: str
    source: Literal["llm", "automatic"]
    withheld_mentions: tuple[str, ...] = ()  # names that caused the LLM text to be withheld


@dataclass(frozen=True)
class CodeExplanation:
    overview: str
    blocks: tuple[BlockExplanation, ...]
    llm_model: str | None
    prompt_version: str = EXPLAIN_CODE_VERSION


def explain_code(report: CheckReport, llm: LLMClient) -> CodeExplanation | None:
    mapping = build_mapping(report)
    if mapping is None or report.statement is None:
        return None
    rows = [r for r in mapping.rows if r.lean_code]
    statement = report.statement.lean_statement
    try:
        result = llm.complete_structured(
            task=EXPLAIN_CODE_TASK,
            system=EXPLAIN_CODE_SYSTEM,
            user=explain_code_user_message(
                problem=normalize_for_llm(report.submission.problem_text),
                statement=statement,
                back_translation=report.statement.back_translation,
                verdict=_verdict_text(report),
                blocks=[(r.step_id, r.status.value, r.student_text, r.lean_code) for r in rows],
            ),
            schema=CodeExplanationOutput,
            effort="medium",
        )
    except LLMError:
        return CodeExplanation(
            overview="An AI explanation is not available right now; below is an automatic "
            "summary of the Lean used in each block.",
            blocks=tuple(_automatic(r) for r in rows),
            llm_model=None,
        )

    answers = {b.step_id: b for b in result.value.blocks}
    blocks = []
    for row in rows:
        answer = answers.get(row.step_id)
        if answer is None:
            blocks.append(_automatic(row))
            continue
        texts = (answer.lean_syntax, answer.math_meaning, answer.role, answer.why_needed)
        stray = ungrounded_mentions(" ".join(texts), row.lean_code, statement)
        if stray:
            blocks.append(_automatic(row, stray))
            continue
        blocks.append(
            BlockExplanation(
                step_id=row.step_id,
                student_text=row.student_text,
                lean_code=row.lean_code,
                lean_syntax=answer.lean_syntax.strip(),
                math_meaning=answer.math_meaning.strip(),
                role=answer.role.strip(),
                why_needed=answer.why_needed.strip(),
                source="llm",
            )
        )

    overview = result.value.overview.strip()
    all_code = "\n".join(r.lean_code for r in rows)
    if not overview or ungrounded_mentions(overview, all_code, statement):
        overview = "The Lean proof follows the blocks below, one per step."
    return CodeExplanation(overview, tuple(blocks), result.model)


def ungrounded_mentions(text: str, code: str, statement: str) -> tuple[str, ...]:
    """Backticked Lean names in ``text`` that occur in neither the code, the
    statement nor the RaChecker definitions."""
    allowed = f"{code}\n{statement}\n{DEFINITIONS_SUMMARY}"
    stray: list[str] = []
    for snippet in _BACKTICK_RE.findall(text):
        for name in _IDENT_RE.findall(snippet):
            if name not in _GENERIC and name not in allowed and name not in stray:
                stray.append(name)
    return tuple(stray)


def _automatic(row: MappingRow, withheld: tuple[str, ...] = ()) -> BlockExplanation:
    cards = [c for c in concepts_in(row.lean_code) if c.key not in ALWAYS_SHOWN]
    used = ", ".join(f"`{c.key}`" for c in cards) or "basic Lean steps"
    meaning = (
        f"It formalizes your step: {row.student_text}"
        if row.student_text
        else "It is bookkeeping the translator added; it is not part of your proof."
    )
    return BlockExplanation(
        step_id=row.step_id,
        student_text=row.student_text,
        lean_code=row.lean_code,
        lean_syntax=f"This block uses {used}; see the Lean lessons below for what each does.",
        math_meaning=meaning,
        role="",
        why_needed="",
        source="automatic",
        withheld_mentions=withheld,
    )


def _verdict_text(report: CheckReport) -> str:
    if report.status is VerificationStatus.VERIFIED:
        return "Lean accepted this formal proof."
    if report.status is VerificationStatus.VERIFICATION_FAILED:
        steps = [e.step_id for e in report.error_analyses if e.step_id]
        where = f" (first problem in block {steps[0]})" if steps else ""
        return f"Lean rejected this formal proof{where}."
    return f"Lean did not decide ({report.status.value}): {report.status_detail}"
