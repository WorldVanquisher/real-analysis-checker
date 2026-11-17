"""Deterministic verdict rules (docs/ARCHITECTURE.md §3).

The verdict is computed only from the Lean run, Lean's parsed output, and the
statement the student confirmed. No LLM output is consulted. ``VERIFIED``
requires every one of:

* Lean finished within the timeout with exit code 0;
* no error diagnostics;
* no ``sorry`` (warning or ``sorryAx`` axiom);
* an axiom report for the theorem listing only the standard axioms;
* the checked statement is byte-identical to the confirmed statement, and the
  file Lean ran is exactly the assembled file.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ra_checker.lean.assemble import AssembledFile
from ra_checker.lean.diagnostics import LeanOutput
from ra_checker.models import LeanRun, VerificationStatus

STANDARD_AXIOMS: frozenset[str] = frozenset({"propext", "Classical.choice", "Quot.sound"})


class LeanVerdict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: VerificationStatus
    reasons: tuple[str, ...]
    axioms: tuple[str, ...] | None
    error_count: int
    uses_sorry: bool

    @property
    def verified(self) -> bool:
        return self.status is VerificationStatus.VERIFIED


def decide_proof_verdict(
    *,
    confirmed_statement: str,
    assembled: AssembledFile,
    run: LeanRun,
    output: LeanOutput,
) -> LeanVerdict:
    """Classify one Lean run of an assembled proof file."""
    if run.source != assembled.source:
        raise ValueError("the Lean run did not check the assembled file")

    def verdict(status: VerificationStatus, *reasons: str) -> LeanVerdict:
        return LeanVerdict(
            status=status,
            reasons=reasons,
            axioms=output.axioms,
            error_count=len(output.errors),
            uses_sorry=output.uses_sorry,
        )

    if assembled.statement != confirmed_statement:
        return verdict(
            VerificationStatus.TRANSLATION_FAILED,
            "the checked statement differs from the statement the student confirmed",
        )
    if run.timed_out:
        return verdict(VerificationStatus.RUNTIME_ERROR, "Lean did not finish within the time limit")

    if output.errors:
        reasons = [f"Lean reported {len(output.errors)} error(s)"]
        if output.uses_sorry:
            reasons.append("the formalization also contains placeholders (sorry)")
        return verdict(VerificationStatus.VERIFICATION_FAILED, *reasons)
    if run.exit_code != 0:
        return verdict(
            VerificationStatus.RUNTIME_ERROR,
            f"Lean exited with code {run.exit_code} without reporting an error",
        )
    if output.uses_sorry:
        return verdict(
            VerificationStatus.TRANSLATION_FAILED,
            "the formalization is incomplete: some steps are placeholders (sorry); "
            "Lean found no other errors",
        )
    if output.axioms is None:
        return verdict(
            VerificationStatus.RUNTIME_ERROR,
            "Lean finished but did not report the axioms the theorem depends on",
        )
    nonstandard = sorted(set(output.axioms) - STANDARD_AXIOMS)
    if nonstandard:
        return verdict(
            VerificationStatus.VERIFICATION_FAILED,
            f"the proof depends on non-standard axioms: {', '.join(nonstandard)}",
        )
    return verdict(VerificationStatus.VERIFIED, "Lean accepted the formalized proof")


class StatementCheck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ok: bool
    reasons: tuple[str, ...]


def decide_statement_check(*, run: LeanRun, output: LeanOutput) -> StatementCheck:
    """Did the statement elaborate? (The proof is ``sorry`` by construction.)"""
    if run.timed_out:
        return StatementCheck(ok=False, reasons=("Lean did not finish within the time limit",))
    if output.errors:
        return StatementCheck(
            ok=False,
            reasons=tuple(f"line {d.line}: {d.message}" for d in output.errors),
        )
    if run.exit_code != 0:
        return StatementCheck(
            ok=False, reasons=(f"Lean exited with code {run.exit_code}",)
        )
    return StatementCheck(ok=True, reasons=("the statement type-checks",))
