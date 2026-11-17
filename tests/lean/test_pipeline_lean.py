"""The whole pipeline with real Lean (the LLM is a fake returning hand-written
answers for a reference exercise). Run with `pytest -m lean`."""

import tomllib
from pathlib import Path

import pytest

from ra_checker.analysis.explain import EXPLAIN_TASK, ExplanationOutput
from ra_checker.llm.client import FakeLLMClient
from ra_checker.models import CheckReport, Submission, VerificationStatus as S
from ra_checker.parsing.problem_parser import PARSE_TASK, ProblemParseOutput
from ra_checker.pipeline import Checker, PendingCheck
from ra_checker.report.presentation import headline
from ra_checker.translation.proof import TRANSLATE_TASK, ProofOutput, StepEntry
from ra_checker.translation.statement import FORMALIZE_TASK, StatementOutput

pytestmark = pytest.mark.lean

CASES = tomllib.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "reference_cases.toml").read_text(encoding="utf-8")
)["case"]
SUM = next(c for c in CASES if c["id"] == "sum_of_limits")
WRONG_EPSILON = (
    SUM["tactic_block"]
    .replace("ha (ε / 2) (half_pos hε)", "ha ε hε")
    .replace("hb (ε / 2) (half_pos hε)", "hb ε hε")
)


def checker_for(tactic_block: str, lean_runner) -> Checker:
    n = len(SUM["steps"])
    llm = FakeLLMClient(
        {
            PARSE_TASK: ProblemParseOutput(
                in_scope=True, out_of_scope_reason="", topic="sequences",
                hypotheses=["a_n → A", "b_n → B"], goal="a_n + b_n → A + B",
                proof_steps=SUM["steps"], ambiguities=[],
            ),
            FORMALIZE_TASK: StatementOutput(
                cannot_formalize=False, reason="", lean_statement=SUM["statement"],
                back_translation="If a → A and b → B then a + b → A + B.", assumptions_added=[],
            ),
            TRANSLATE_TASK: ProofOutput(
                tactic_block=tactic_block,
                step_map=[StepEntry(step_id=f"S{i}", status="translated", note="") for i in range(1, n + 1)],
                translator_notes="",
            ),
            EXPLAIN_TASK: ExplanationOutput(
                category="algebraic_computational", origin="student_reasoning", confidence="high",
                explanation="With ε for each sequence the sum is only below 2ε.",
                math_interpretation="ε + ε = 2ε, which is not below ε.",
                correction_direction="Use ε/2 for each sequence.",
            ),
        }
    )
    return Checker(llm, lean_runner)


def run_check(tactic_block, lean_runner) -> CheckReport:
    checker = checker_for(tactic_block, lean_runner)
    submission = Submission(problem_text=SUM["problem"], proof_text=" ".join(SUM["steps"]))
    pending = checker.formalize(submission)
    assert isinstance(pending, PendingCheck), getattr(pending, "status_detail", pending)
    return checker.verify(pending.confirmed()).report


def test_reference_exercise_end_to_end(lean_runner):
    report = run_check(SUM["tactic_block"], lean_runner)
    assert report.status is S.VERIFIED
    assert report.fidelity.is_faithful
    assert headline(report).title == "Lean accepted the formalized proof."
    assert CheckReport.model_validate_json(report.model_dump_json()) == report


def test_wrong_epsilon_end_to_end(lean_runner):
    report = run_check(WRONG_EPSILON, lean_runner)
    assert report.status is S.VERIFICATION_FAILED
    assert report.error_analyses[0].step_id == "S5"
    assert "step S5" in headline(report).body
