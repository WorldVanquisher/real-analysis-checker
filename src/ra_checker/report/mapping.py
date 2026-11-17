"""Advanced Feature B: the correspondence between the student's proof and the
Lean proof (no LLM).

Each row pairs a student step with the Lean tactics tagged ``-- [Sk]`` in the
code that Lean actually checked, plus the translator's added ``-- [Ak]``
blocks. The pairing comes from the tags, never from an LLM's description, so
it cannot invent a correspondence. When the translation departs from the
student's proof for more than half of the steps, the mapping is flagged as
approximate.
"""

from __future__ import annotations

from dataclasses import dataclass

from ra_checker.models import CheckReport, StepStatus
from ra_checker.translation.proof import split_tags

TRANSFORMED_THRESHOLD = 0.5


@dataclass(frozen=True)
class MappingRow:
    step_id: str
    student_text: str | None  # None for translator-added steps
    lean_code: str  # tactics under the tag; empty if the step has none
    status: StepStatus
    note: str


@dataclass(frozen=True)
class ProofMapping:
    rows: tuple[MappingRow, ...]
    substantially_transformed: bool


def build_mapping(report: CheckReport) -> ProofMapping | None:
    if report.translation is None or report.analysis is None:
        return None
    student_ids = [s.id for s in report.analysis.proof_steps]
    texts = {s.id: s.text for s in report.analysis.proof_steps}
    segments = split_tags(report.translation.tactic_block, student_ids).segments

    rows = tuple(
        MappingRow(
            step_id=m.step_id,
            student_text=texts.get(m.step_id),
            lean_code=_clean(segments.get(m.step_id, "")),
            status=m.status,
            note=m.note,
        )
        for m in report.translation.step_map
    )
    student_rows = [r for r in rows if r.step_id.startswith("S")]
    departed = sum(r.status in (StepStatus.CHANGED, StepStatus.OMITTED) for r in student_rows)
    added = sum(r.status is StepStatus.ADDED for r in rows)
    n = max(len(student_rows), 1)
    transformed = departed / n > TRANSFORMED_THRESHOLD or added > n
    return ProofMapping(rows, transformed)


def _clean(segment: str) -> str:
    lines = [line.rstrip() for line in segment.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    indent = min((len(l) - len(l.lstrip()) for l in lines if l.strip()), default=0)
    return "\n".join(l[indent:] for l in lines)
