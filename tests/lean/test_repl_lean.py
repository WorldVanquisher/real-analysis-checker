"""The REPL runner must give the same results as the command-line runner (A8).
Run with `pytest -m lean`."""

import dataclasses
import json
import time
import tomllib
from pathlib import Path

import pytest
from lean_cases import CASES as LEAN_CASES

from ra_checker.lean.assemble import assemble_proof, assemble_statement_check
from ra_checker.lean.diagnostics import parse_lean_output
from ra_checker.lean.repl import ReplLeanRunner, find_repl
from ra_checker.lean.runner import SubprocessLeanRunner
from ra_checker.report.verdict import decide_proof_verdict, decide_statement_check

pytestmark = pytest.mark.lean

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
EVAL_RUN1 = json.loads((FIXTURES / "eval_run1_checked.json").read_text(encoding="utf-8"))["cases"]
REFERENCE = tomllib.loads((FIXTURES / "reference_cases.toml").read_text(encoding="utf-8"))["case"]


@pytest.fixture(scope="module")
def repl_runner(lean_project_dir):
    if find_repl(lean_project_dir) is None:
        pytest.skip("the Lean REPL is not built (lake build repl)")
    runner = ReplLeanRunner(lean_project_dir, 300, fallback=SubprocessLeanRunner(lean_project_dir, 300))
    yield runner
    runner.close()


def check(runner, statement, block, source=None):
    assembled = assemble_proof(statement, block)
    if source is not None:
        assembled = dataclasses.replace(assembled, source=source)
    run = runner.run(assembled.source)
    output = parse_lean_output(run.stdout, assembled.theorem_name, run.stderr)
    verdict = decide_proof_verdict(confirmed_statement=statement, assembled=assembled, run=run, output=output)
    return run, output, verdict


def test_same_verdicts_on_the_live_evaluation_files(repl_runner):
    mismatches = []
    for case in EVAL_RUN1:
        _, output, verdict = check(repl_runner, case["statement"], case["tactic_block"])
        got = (verdict.status.value, [d.line for d in output.errors])
        expected = (case["cli_status"], case["cli_error_lines"])
        if got != expected:
            mismatches.append((case["case_id"], expected, got))
    assert not mismatches, mismatches
    assert repl_runner.starts == 1  # Mathlib was loaded once for all of them


@pytest.mark.parametrize("case", LEAN_CASES, ids=lambda c: c.name)
def test_same_outcomes_on_the_hand_written_cases(case, repl_runner):
    _, output, verdict = check(repl_runner, case.statement, case.tactic_block, case.raw_source)
    assert verdict.status is case.expected, (verdict.reasons, output)


@pytest.mark.parametrize("case", REFERENCE, ids=lambda c: c["id"])
def test_reference_exercises_verified(case, repl_runner):
    _, output, verdict = check(repl_runner, case["statement"], case["tactic_block"])
    assert verdict.verified and output.diagnostics == ()


def test_statement_checks(repl_runner):
    for statement, ok in (("(a : ℕ → ℝ) (L : ℝ) (h : SeqConvergesTo a L) : SeqBounded a", True),
                          ("(x : ℝ) : x = undefinedConstantXyz", False)):
        assembled = assemble_statement_check(statement)
        run = repl_runner.run(assembled.source)
        output = parse_lean_output(run.stdout, assembled.theorem_name, run.stderr)
        assert decide_statement_check(assembled=assembled, run=run, output=output).ok is ok


def test_checks_are_fast_once_mathlib_is_loaded(repl_runner, capsys):
    source = assemble_proof("(x : ℝ) (hx : 0 < x) : 0 < x ^ 2", "positivity").source
    repl_runner.run(source)  # make sure the REPL is up
    start = time.monotonic()
    for _ in range(5):
        assert repl_runner.run(source).exit_code == 0
    per_check = (time.monotonic() - start) / 5
    with capsys.disabled():
        print(f"\n[timing] REPL check with Mathlib loaded: {per_check:.2f} s")
    assert per_check < 10
