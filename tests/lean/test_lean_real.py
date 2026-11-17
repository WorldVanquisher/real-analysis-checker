"""End-to-end Lean tests: assemble → screen → run real Lean → parse → verdict.

Run with ``pytest -m lean``. Set ``RA_CAPTURE_FIXTURES=1`` to also save each
case's Lean output (with machine-specific paths removed) to
``tests/fixtures/lean_output/`` for the parser's unit tests.
"""

import dataclasses
import os
import re
import subprocess
import time
from pathlib import Path

import pytest
from lean_cases import CASES

from ra_checker.lean.assemble import assemble_proof, assemble_statement_check
from ra_checker.lean.diagnostics import parse_lean_output
from ra_checker.lean.runner import CHECK_FILE_NAME, SubprocessLeanRunner
from ra_checker.lean.safety import check_tactic_block
from ra_checker.models import VerificationStatus
from ra_checker.report.verdict import decide_proof_verdict, decide_statement_check

pytestmark = pytest.mark.lean

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "lean_output"
SCRUBBED_PATH = f"/tmp/ra_checker/{CHECK_FILE_NAME}"
_CHECK_PATH_RE = re.compile(rf"[^\s:]*?(?:[A-Za-z]:)?[^\s:]*{re.escape(CHECK_FILE_NAME)}")


def scrub(text: str) -> str:
    """Replace the machine-specific temp path of the checked file."""
    return _CHECK_PATH_RE.sub(SCRUBBED_PATH, text)


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_case_outcome(case, lean_runner):
    assembled = assemble_proof(case.statement, case.tactic_block)
    if case.raw_source is None:
        assert check_tactic_block(case.tactic_block).ok
    else:
        # Bypass assembly and the safety screen deliberately: the verdict's
        # axiom check must still catch the unsound trick.
        assembled = dataclasses.replace(assembled, source=case.raw_source)

    run = lean_runner.run(assembled.source)
    output = parse_lean_output(run.stdout, assembled.theorem_name, run.stderr)
    verdict = decide_proof_verdict(
        confirmed_statement=case.statement, assembled=assembled, run=run, output=output
    )

    if os.environ.get("RA_CAPTURE_FIXTURES") == "1":
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        (FIXTURE_DIR / f"{case.name}.txt").write_text(
            scrub(run.stdout), encoding="utf-8", newline="\n"
        )

    assert not output.unparsed, output.unparsed
    assert verdict.status is case.expected, (verdict.reasons, run.stdout)


def test_statement_check_accepts_good_and_rejects_bad_statements(lean_runner):
    good = assemble_statement_check("(a : ℕ → ℝ) (L : ℝ) : ∀ ε > 0, ∃ N : ℕ, ∀ n ≥ N, |a n - L| < ε")
    run = lean_runner.run(good.source)
    assert decide_statement_check(run=run, output=parse_lean_output(run.stdout, good.theorem_name)).ok

    bad = assemble_statement_check("(x : ℝ) : x = undefinedConstantXyz")
    run = lean_runner.run(bad.source)
    check = decide_statement_check(run=run, output=parse_lean_output(run.stdout, bad.theorem_name))
    assert not check.ok


def _lean_pids() -> set[int]:
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq lean.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
        ).stdout
        return {int(line.split('","')[1]) for line in out.splitlines() if line.startswith('"lean.exe"')}
    out = subprocess.run(["pgrep", "-x", "lean"], capture_output=True, text=True).stdout
    return {int(p) for p in out.split()}


def test_timeout_leaves_no_lean_process(lean_project_dir):
    before = _lean_pids()
    runner = SubprocessLeanRunner(lean_project_dir, timeout_s=2)  # shorter than importing Mathlib
    run = runner.run(assemble_proof("(x : ℝ) : x = x", "rfl").source)
    assert run.timed_out and run.exit_code is None

    deadline = time.monotonic() + 15
    while _lean_pids() - before and time.monotonic() < deadline:
        time.sleep(0.5)
    assert not (_lean_pids() - before), "a Lean process outlived the timeout"


def test_timing_report(lean_runner, capsys):
    """Not an assertion on speed: records how long a Mathlib check takes here."""
    source = assemble_proof("(x : ℝ) (hx : 0 < x) : 0 < x ^ 2", "positivity").source
    durations = [lean_runner.run(source).duration_s for _ in range(2)]
    with capsys.disabled():
        print(f"\n[timing] Lean+Mathlib check: first {durations[0]:.1f}s, second {durations[1]:.1f}s")
    assert all(d > 0 for d in durations)
