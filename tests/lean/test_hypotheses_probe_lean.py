"""The contradictory-hypotheses probe on real Lean: statements whose hypotheses
contradict each other are flagged, and none of the real statements in the
project are. Run with `pytest -m lean` (uses the Lean REPL when it is built)."""

import json
import time
import tomllib
from pathlib import Path

import pytest
from lean_cases import CASES as LEAN_CASES

from ra_checker.evaluation import load_cases
from ra_checker.lean.repl import ReplLeanRunner, find_repl
from ra_checker.lean.runner import SubprocessLeanRunner
from ra_checker.learning.cards import CARDS
from ra_checker.translation.statement import probe_hypotheses

pytestmark = pytest.mark.lean

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
EVAL_RUN1 = json.loads((FIXTURES / "eval_run1_checked.json").read_text(encoding="utf-8"))["cases"]
REFERENCE = tomllib.loads((FIXTURES / "reference_cases.toml").read_text(encoding="utf-8"))["case"]
EVAL_CASES = load_cases(ROOT / "eval" / "cases.toml")

CONTRADICTORY = {
    "opposite signs": "(x : ℝ) (h₁ : 0 < x) (h₂ : x < 0) : x = 5",
    "impossible natural number": "(n : ℕ) (h₁ : 3 < n) (h₂ : n < 2) : n = 7",
    "x ≠ x": "(L : ℝ) (h : L ≠ L) : L = 0",
    "strict self-comparison": "(a : ℕ → ℝ) (h : ∀ n, a n < a n) : SeqConverges a",
    "ε that is positive and not": "(ε : ℝ) (hε : 0 < ε) (hε' : ε ≤ 0) : SeqConvergesTo (fun _ => ε) 0",
}


def real_statements() -> dict[str, str]:
    found = {f"reference {c['id']}": c["statement"] for c in REFERENCE}
    found |= {f"live eval {c['case_id']}": c["statement"] for c in EVAL_RUN1}
    found |= {f"eval reference {c.id}": c.reference_statement for c in EVAL_CASES if c.reference_statement}
    found |= {f"lean case {c.name}": c.statement for c in LEAN_CASES if c.raw_source is None}
    found |= {f"card {c.key}": c.example_statement for c in CARDS}
    found |= {f"practice {c.key}": c.practice.statement for c in CARDS if c.practice}
    return found


@pytest.fixture(scope="module")
def runner(lean_project_dir):
    cli = SubprocessLeanRunner(lean_project_dir, 300)
    if find_repl(lean_project_dir) is None:
        yield cli
        return
    repl = ReplLeanRunner(lean_project_dir, 300, fallback=cli)
    yield repl
    repl.close()


@pytest.mark.parametrize("statement", CONTRADICTORY.values(), ids=CONTRADICTORY.keys())
def test_contradictory_hypotheses_are_found(runner, statement):
    assert probe_hypotheses(statement, runner) is True


def test_no_real_statement_is_flagged(runner):
    statements = real_statements()
    assert len(statements) >= 40
    flagged, undecided, slow = [], [], []
    for name, statement in statements.items():
        start = time.monotonic()
        found = probe_hypotheses(statement, runner)
        if found is True:
            flagged.append(name)
        elif found is None:
            undecided.append(name)
        if isinstance(runner, ReplLeanRunner) and time.monotonic() - start > 5:
            slow.append(name)
    assert flagged == [] and undecided == [] and slow == [], (flagged, undecided, slow)
