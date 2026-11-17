"""Builds the ``.lean`` file that Lean checks.

The LLM never writes this file. It supplies only the formal statement (locked
after the student confirms it) and a tactic block; everything else — imports,
the theorem line, indentation, the axiom check — is written here, so the
translator cannot weaken the theorem or add commands around it.

Layout of a proof file::

    import Mathlib
    import RaChecker
    <blank>
    open RaChecker
    set_option autoImplicit false
    <blank>
    theorem student_claim <statement> := by
      <tactic block, re-indented by two spaces>
    <blank>
    #print axioms student_claim

``RaChecker`` provides the student-friendly ε–N definitions (``SeqConvergesTo``
and friends, each proved equivalent to Mathlib); it must be built with
``lake build`` first.

``autoImplicit`` is switched off because Lean would otherwise turn any unknown
lower-case name in the statement into a new universally quantified variable —
silently changing what is being proved (found by the B2 integration tests).

The statement is inserted byte-for-byte; it is never reformatted.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass

THEOREM_NAME = "student_claim"
HEADER_IMPORTS: tuple[str, ...] = ("Mathlib", "RaChecker")
HEADER_COMMANDS: tuple[str, ...] = ("open RaChecker", "set_option autoImplicit false")
INDENT = "  "


class AssemblyError(ValueError):
    """The statement or tactic block cannot be assembled into a file."""


@dataclass(frozen=True)
class AssembledFile:
    source: str
    statement: str
    theorem_name: str
    statement_line: int  # 1-based line of "theorem <name> ..."
    proof_first_line: int  # 1-based first line of the tactic block
    proof_line_count: int
    axioms_line: int | None  # 1-based line of "#print axioms", if present

    def proof_line(self, file_line: int) -> int | None:
        """Map a file line to a 1-based line of the tactic block, if inside it."""
        offset = file_line - self.proof_first_line
        return offset + 1 if 0 <= offset < self.proof_line_count else None


def normalize_tactic_block(block: str) -> list[str]:
    """Dedent, expand tabs, trim blank edges, and indent by two spaces."""
    text = block.replace("\r\n", "\n").replace("\r", "\n").expandtabs(2)
    lines = [line.rstrip() for line in textwrap.dedent(text).split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    if not lines:
        raise AssemblyError("the tactic block is empty")
    return [INDENT + line if line else "" for line in lines]


def assemble_proof(statement: str, tactic_block: str) -> AssembledFile:
    """File that proves the locked statement with the translated tactic block."""
    return _assemble(statement, normalize_tactic_block(tactic_block), axioms=True)


def assemble_statement_check(statement: str) -> AssembledFile:
    """File that only elaborates the statement (proof left as ``sorry``)."""
    return _assemble(statement, [INDENT + "sorry"], axioms=False)


def _assemble(statement: str, proof_lines: list[str], *, axioms: bool) -> AssembledFile:
    if not statement.strip():
        raise AssemblyError("the statement is empty")
    header = [f"import {module}" for module in HEADER_IMPORTS] + [""]
    header += [*HEADER_COMMANDS, ""]
    theorem = f"theorem {THEOREM_NAME} {statement} := by".split("\n")

    lines = header + theorem
    statement_line = len(header) + 1
    proof_first_line = len(lines) + 1
    lines += proof_lines

    axioms_line = None
    if axioms:
        lines += ["", f"#print axioms {THEOREM_NAME}"]
        axioms_line = len(lines)

    return AssembledFile(
        source="\n".join(lines) + "\n",
        statement=statement,
        theorem_name=THEOREM_NAME,
        statement_line=statement_line,
        proof_first_line=proof_first_line,
        proof_line_count=len(proof_lines),
        axioms_line=axioms_line,
    )
