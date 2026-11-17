"""Error localization on real Lean output (explanations from a fake LLM).
Run with `pytest -m lean`."""

import tomllib
from pathlib import Path

import pytest

from ra_checker.analysis.explain import EXPLAIN_TASK, ExplanationOutput, analyze_failure
from ra_checker.lean.assemble import assemble_proof
from ra_checker.lean.diagnostics import parse_lean_output
from ra_checker.llm.client import FakeLLMClient
from ra_checker.models import (
    FormalStatement,
    LeanErrorKind,
    ProblemAnalysis,
    ProofStep,
    ProofTranslation,
    StepMapping,
    StepStatus,
)

pytestmark = pytest.mark.lean

CASES = tomllib.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "reference_cases.toml").read_text(encoding="utf-8")
)["case"]
SUM = next(c for c in CASES if c["id"] == "sum_of_limits")
EXPLANATION = ExplanationOutput(
    category="algebraic_computational", origin="student_reasoning", confidence="high",
    explanation="…", correction_direction="…",
)


def analyze(statement: str, block: str, steps: list[str], lean_runner):
    analysis = ProblemAnalysis(
        goal="g", in_scope=True,
        proof_steps=tuple(ProofStep(id=f"S{i}", text=t) for i, t in enumerate(steps, 1)),
    )
    translation = ProofTranslation(
        tactic_block=block,
        step_map=tuple(StepMapping(step_id=f"S{i}", status=StepStatus.TRANSLATED) for i in range(1, len(steps) + 1)),
    )
    assembled = assemble_proof(statement, block)
    run = lean_runner.run(assembled.source)
    output = parse_lean_output(run.stdout, assembled.theorem_name, run.stderr)
    fake = FakeLLMClient({EXPLAIN_TASK: EXPLANATION})
    results = analyze_failure(
        problem_text="…", analysis=analysis,
        statement=FormalStatement(lean_statement=statement, back_translation="…", confirmed_by_student=True),
        translation=translation, assembled=assembled, output=output, llm=fake,
    )
    return results, fake


def test_wrong_epsilon_is_located_at_the_final_estimate(lean_runner):
    wrong = (
        SUM["tactic_block"]
        .replace("ha (ε / 2) (half_pos hε)", "ha ε hε")
        .replace("hb (ε / 2) (half_pos hε)", "hb ε hε")
    )
    results, fake = analyze(SUM["statement"], wrong, SUM["steps"], lean_runner)
    assert results, "Lean should have reported an error"
    first = results[0]
    assert first.step_id == "S5"  # the triangle-inequality step, where 2ε ≮ ε
    assert first.lean_error_kind is LeanErrorKind.TACTIC_FAILED
    assert SUM["steps"][4] in fake.requests[0].user


def test_unsolved_goal_is_attributed_to_the_end_of_the_proof(lean_runner):
    block = "-- [S1]\nconstructor\n-- [S2]\n· positivity"
    results, fake = analyze("(x : ℝ) : 0 ≤ x ^ 2 ∧ x < x + 1", block, ["Split.", "x² ≥ 0."], lean_runner)
    (first,) = results
    assert first.lean_error_kind is LeanErrorKind.UNSOLVED_GOALS
    assert first.step_id == "S2" and first.line is None
    assert "ENDED with goals still open" in fake.requests[0].user
    assert "x < x + 1" in fake.requests[0].user  # the open goal is shown to the explainer
