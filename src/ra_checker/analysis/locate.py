"""Map a Lean diagnostic back to the student's proof step (no LLM).

The assembled file (not the LLM's text) is the reference: its tactic block is
scanned for ``-- [Sk]`` / ``-- [Ak]`` tags, and an error belongs to the nearest
tag at or above its line.

Lean reports some failures on the theorem line itself — most importantly
"unsolved goals" at ``by`` when the proof ends with something left to prove.
Those are attributed to the last step, with ``at_end_of_proof`` set.
"""

from __future__ import annotations

from dataclasses import dataclass

from ra_checker.lean.assemble import AssembledFile
from ra_checker.models import Diagnostic, ProblemAnalysis
from ra_checker.translation.proof import TAG_LINE_RE


@dataclass(frozen=True)
class ErrorLocation:
    file_line: int
    block_line: int | None  # 1-based line in the tactic block; None if outside it
    step_id: str | None  # enclosing tag (S… student step, A… translator's addition)
    step_text: str | None  # the student's words for an S step
    lean_snippet: str  # the tactics under that tag
    at_end_of_proof: bool  # Lean reported on the theorem line: goals were left open


def locate_error(
    diagnostic: Diagnostic, assembled: AssembledFile, analysis: ProblemAnalysis
) -> ErrorLocation:
    source_lines = assembled.source.split("\n")
    start = assembled.proof_first_line - 1
    block = source_lines[start : start + assembled.proof_line_count]
    tags = [(i, m.group(1)) for i, line in enumerate(block) if (m := TAG_LINE_RE.match(line))]

    block_line = assembled.proof_line(diagnostic.line)
    at_end = diagnostic.line < assembled.proof_first_line
    if block_line is None:
        # On the theorem line (goals left at the end) or after the block (e.g. an
        # unclosed bracket noticed at the next command): blame the last step.
        index = len(block) - 1
    else:
        index = block_line - 1

    enclosing = [(i, tag) for i, tag in tags if i <= index]
    if not enclosing:
        return ErrorLocation(diagnostic.line, block_line, None, None, "\n".join(block).strip(), at_end)
    tag_index, step_id = enclosing[-1]
    following = [i for i, _ in tags if i > tag_index]
    end = following[0] if following else len(block)
    snippet = "\n".join(line.strip() for line in block[tag_index + 1 : end] if line.strip())
    texts = {step.id: step.text for step in analysis.proof_steps}
    return ErrorLocation(
        file_line=diagnostic.line,
        block_line=block_line,
        step_id=step_id,
        step_text=texts.get(step_id),
        lean_snippet=snippet,
        at_end_of_proof=at_end,
    )
