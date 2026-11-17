"""Live checks of stage 1 against the real Claude API. Run with `pytest -m llm`.

They assert only robust properties (scope, verbatim steps, whether a
clarification is requested), not exact wording.
"""

import tomllib
from pathlib import Path

import pytest

from ra_checker.models import Submission
from ra_checker.parsing.problem_parser import parse_problem

pytestmark = pytest.mark.llm

CASES = tomllib.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "reference_cases.toml").read_text(
        encoding="utf-8"
    )
)["case"]
SUM_OF_LIMITS = next(c for c in CASES if c["id"] == "sum_of_limits")


def test_reference_problem_is_parsed_faithfully(live_llm):
    submission = Submission(
        problem_text=SUM_OF_LIMITS["problem"], proof_text=" ".join(SUM_OF_LIMITS["steps"])
    )
    analysis = parse_problem(submission, live_llm).analysis
    assert analysis.in_scope
    assert not analysis.ambiguities, analysis.ambiguities
    assert len(analysis.proof_steps) >= 3
    assert all(step.verbatim for step in analysis.proof_steps), analysis.proof_steps


def test_out_of_scope_problem_is_flagged(live_llm):
    submission = Submission(
        problem_text="Prove that the integral of x^2 from 0 to 1 equals 1/3.",
        proof_text="By the fundamental theorem of calculus, it is 1^3/3 - 0^3/3 = 1/3.",
    )
    analysis = parse_problem(submission, live_llm).analysis
    assert not analysis.in_scope
    assert analysis.out_of_scope_reason


def test_ambiguous_problem_asks_for_clarification(live_llm):
    submission = Submission(
        problem_text="Prove that the sequence converges.",
        proof_text="It is decreasing and bounded below, so it converges.",
    )
    analysis = parse_problem(submission, live_llm).analysis
    assert analysis.needs_clarification
