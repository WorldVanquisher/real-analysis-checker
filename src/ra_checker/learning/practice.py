"""Check a student's answer to a practice question with real Lean.

The answer is a tactic block for the card's fixed statement. It goes through
exactly the path a generated proof takes — safety screen, Python-assembled
file, Lean run, the verdict rules of ``report/verdict.py`` — so "Lean accepted
your answer" means the same thing as everywhere else in the app.
"""

from __future__ import annotations

from dataclasses import dataclass

from ra_checker.lean.assemble import AssemblyError, assemble_proof
from ra_checker.lean.diagnostics import parse_lean_output
from ra_checker.lean.runner import LeanRunner, LeanUnavailableError
from ra_checker.lean.safety import check_tactic_block
from ra_checker.learning.cards import Practice
from ra_checker.report.verdict import decide_proof_verdict


@dataclass(frozen=True)
class PracticeResult:
    verified: bool
    message: str
    lean_errors: tuple[str, ...] = ()


def check_practice(practice: Practice, answer: str, lean: LeanRunner) -> PracticeResult:
    screen = check_tactic_block(answer)
    if not screen.ok:
        details = "; ".join(f"line {v.line}: {v.message}" for v in screen.violations)
        return PracticeResult(False, f"Your answer uses something that is not allowed here ({details}).")
    if screen.placeholder_count:
        return PracticeResult(False, "Your answer still contains `sorry`, so it is not a complete proof.")
    try:
        assembled = assemble_proof(practice.statement, answer)
    except AssemblyError:
        return PracticeResult(False, "Please type at least one tactic.")
    try:
        run = lean.run(assembled.source)
    except LeanUnavailableError as exc:
        return PracticeResult(False, f"Lean is not available: {exc}")
    output = parse_lean_output(run.stdout, assembled.theorem_name, run.stderr)
    verdict = decide_proof_verdict(
        confirmed_statement=practice.statement, assembled=assembled, run=run, output=output
    )
    if verdict.verified:
        return PracticeResult(True, "Lean accepted your answer.")
    errors = tuple(
        f"line {assembled.proof_line(e.line) or '?'}: {e.message}" for e in output.errors
    )
    return PracticeResult(False, "Lean did not accept your answer: " + "; ".join(verdict.reasons), errors)
