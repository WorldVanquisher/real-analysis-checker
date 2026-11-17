"""Every reference statement in the evaluation set must type-check in Lean
(with the checker's header). Run with `pytest -m lean`."""

from pathlib import Path

import pytest

from ra_checker.evaluation import load_cases
from ra_checker.lean.assemble import HEADER_COMMANDS, HEADER_IMPORTS
from ra_checker.lean.diagnostics import parse_lean_output

pytestmark = pytest.mark.lean

CASES = load_cases(Path(__file__).resolve().parents[2] / "eval" / "cases.toml")


def test_reference_statements_type_check(lean_runner):
    lines = [f"import {m}" for m in HEADER_IMPORTS] + [""] + list(HEADER_COMMANDS) + [""]
    statements = [(c.id, c.reference_statement) for c in CASES if c.reference_statement]
    assert statements
    for case_id, statement in statements:
        lines += [f"theorem ref_{case_id} {statement} := by", "  sorry", ""]
    run = lean_runner.run("\n".join(lines) + "\n")
    output = parse_lean_output(run.stdout, "unused", run.stderr)
    assert output.errors == (), run.stdout
