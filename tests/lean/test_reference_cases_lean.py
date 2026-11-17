"""Every reference exercise must be VERIFIED by real Lean through the same
assemble → run → parse → verdict path the app uses. Run with `pytest -m lean`."""

import tomllib
from pathlib import Path

import pytest

from ra_checker.lean.assemble import assemble_proof
from ra_checker.lean.diagnostics import parse_lean_output
from ra_checker.models import VerificationStatus
from ra_checker.report.verdict import decide_proof_verdict

pytestmark = pytest.mark.lean

CASES_FILE = Path(__file__).resolve().parents[1] / "fixtures" / "reference_cases.toml"
CASES = tomllib.loads(CASES_FILE.read_text(encoding="utf-8"))["case"]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_reference_case_is_verified(case, lean_runner):
    assembled = assemble_proof(case["statement"], case["tactic_block"])
    run = lean_runner.run(assembled.source)
    output = parse_lean_output(run.stdout, assembled.theorem_name, run.stderr)
    verdict = decide_proof_verdict(
        confirmed_statement=case["statement"], assembled=assembled, run=run, output=output
    )
    assert verdict.status is VerificationStatus.VERIFIED, (verdict.reasons, run.stdout)
    assert output.diagnostics == (), run.stdout  # not even warnings
