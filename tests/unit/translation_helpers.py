"""Shared test doubles for the translation stages: a scripted Lean runner that
replays output in the real Lean 4.36 format, and canned Lean outputs."""

from __future__ import annotations

from ra_checker.lean.runner import LeanUnavailableError
from ra_checker.models import LeanRun, ProblemAnalysis, ProofStep

STANDARD_AXIOMS_LINE = "'student_claim' depends on axioms: [propext, Classical.choice, Quot.sound]\n"
ERROR_AXIOMS_LINE = "'student_claim' depends on axioms: [propext, sorryAx, Classical.choice, Quot.sound]\n"

OK = (STANDARD_AXIOMS_LINE, 0)
STATEMENT_OK = ("/tmp/x/Check.lean:7:8: warning: declaration uses `sorry`\n", 0)
UNKNOWN_ID = (
    "/tmp/x/Check.lean:9:8: error(lean.unknownIdentifier): Unknown identifier `made_up`\n"
    + ERROR_AXIOMS_LINE,
    1,
)
UNSOLVED = ("/tmp/x/Check.lean:7:57: error: unsolved goals\nx : ℝ\n⊢ x < x + 1\n" + ERROR_AXIOMS_LINE, 1)
SORRY = ("/tmp/x/Check.lean:7:8: warning: declaration uses `sorry`\n"
         "'student_claim' depends on axioms: [propext, sorryAx, Classical.choice, Quot.sound]\n", 0)
STATEMENT_ERROR = ("/tmp/x/Check.lean:7:40: error(lean.unknownIdentifier): Unknown identifier `Foo`\n", 1)
TIMEOUT = "timeout"
UNAVAILABLE = "unavailable"

# The hypotheses probe (a separate file, theorem `hypotheses_contradict`).
NO_CONTRADICTION = (
    "/tmp/x/Check.lean:9:2: error: linarith failed to find a contradiction\n"
    "'hypotheses_contradict' depends on axioms: [sorryAx]\n",
    1,
)
CONTRADICTION = ("'hypotheses_contradict' depends on axioms: [propext, Classical.choice, Quot.sound]\n", 0)


class ScriptedLean:
    """Returns the scripted results in order and records every source.

    Hypotheses-probe files are answered from ``probe_results`` (default: no
    contradiction found) and recorded in ``probe_sources`` instead, so tests
    that count proof and statement runs are unaffected by the probe."""

    def __init__(self, *results, probe_results=()):
        self.results = list(results)
        self.sources: list[str] = []
        self.probe_results = list(probe_results)
        self.probe_sources: list[str] = []

    def run(self, source: str) -> LeanRun:
        if "theorem hypotheses_contradict " in source:
            self.probe_sources.append(source)
            result = self.probe_results.pop(0) if self.probe_results else NO_CONTRADICTION
        else:
            self.sources.append(source)
            result = self.results.pop(0)
        if result == UNAVAILABLE:
            raise LeanUnavailableError("Lean is not installed")
        if result == TIMEOUT:
            return LeanRun(source=source, exit_code=None, timed_out=True, duration_s=120)
        stdout, code = result
        return LeanRun(source=source, exit_code=code, duration_s=1.0, stdout=stdout)


def analysis(n_steps: int = 3) -> ProblemAnalysis:
    return ProblemAnalysis(
        hypotheses=("a_n → A",),
        goal="a_n + 1 → A + 1",
        proof_steps=tuple(ProofStep(id=f"S{i}", text=f"step {i}") for i in range(1, n_steps + 1)),
        in_scope=True,
        topic="sequences",
    )
