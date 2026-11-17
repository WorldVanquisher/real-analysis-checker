"""Tests for ra_checker.translation.statement (fake LLM, scripted Lean)."""

import pytest
from translation_helpers import (
    STATEMENT_ERROR,
    STATEMENT_OK,
    TIMEOUT,
    UNAVAILABLE,
    ScriptedLean,
    analysis,
)

from ra_checker.llm.client import FakeLLMClient, LLMRefusalError, LLMUnavailableError
from ra_checker.models import ProblemAnalysis, VerificationStatus as S
from ra_checker.translation.statement import (
    FORMALIZE_TASK,
    MAX_STATEMENT_REPAIRS,
    REPAIR_STATEMENT_TASK,
    StatementOutput,
    formalize_statement,
)

GOOD = "(a : ℕ → ℝ) (A : ℝ) (ha : SeqConvergesTo a A) : SeqConvergesTo (fun n => a n + 1) (A + 1)"
PROBLEM = "Suppose a_n → A. Prove that a_n + 1 → A + 1."


def out(statement=GOOD, **overrides) -> StatementOutput:
    fields = dict(
        cannot_formalize=False,
        reason="",
        lean_statement=statement,
        back_translation="If a converges to A then a_n + 1 converges to A + 1.",
        assumptions_added=["sequences are indexed from 0"],
    )
    fields.update(overrides)
    return StatementOutput(**fields)


def sequence(*answers):
    answers = list(answers)
    return lambda request: answers.pop(0)


def run(llm_answers, *lean_results, problem=PROBLEM, a=None):
    fake = FakeLLMClient(
        {FORMALIZE_TASK: llm_answers[0], REPAIR_STATEMENT_TASK: sequence(*llm_answers[1:])}
    )
    lean = ScriptedLean(*lean_results)
    outcome = formalize_statement(problem, a or analysis(), fake, lean)
    return outcome, fake, lean


def test_accepted_statement_is_returned_unconfirmed():
    outcome, fake, lean = run([out()], STATEMENT_OK)
    assert outcome.ok and outcome.failure is None
    s = outcome.statement
    assert s.lean_statement == GOOD and not s.confirmed_by_student
    assert s.assumptions_added == ("sequences are indexed from 0",)
    assert f"theorem student_claim {GOOD} := by" in lean.sources[0]
    assert fake.requests[0].effort == "high"
    assert "a_n → A" in fake.requests[0].user  # parsed hypotheses are passed on
    assert len(outcome.attempts) == 1


def test_cannot_formalize_is_a_translation_failure():
    outcome, _, lean = run([out("", cannot_formalize=True, reason="needs complex numbers")])
    assert outcome.failure is S.TRANSLATION_FAILED
    assert "needs complex numbers" in outcome.detail
    assert lean.sources == []


def test_safety_violation_is_sent_back_for_repair():
    outcome, fake, lean = run([out(": True := trivial"), out()], STATEMENT_OK)
    assert outcome.ok
    assert [r.task for r in fake.requests] == [FORMALIZE_TASK, REPAIR_STATEMENT_TASK]
    assert "':=' is not allowed" in fake.requests[1].user
    assert len(lean.sources) == 1  # the unsafe draft never reached Lean
    assert [a.accepted for a in outcome.attempts] == [False, True]


def test_lean_error_is_repaired_with_the_error_message():
    outcome, fake, _ = run([out("(x : ℝ) : x = Foo"), out()], STATEMENT_ERROR, STATEMENT_OK)
    assert outcome.ok
    assert "Unknown identifier `Foo`" in fake.requests[1].user
    assert outcome.statement.lean_statement == GOOD


def test_repairs_are_bounded():
    bad = [out("(x : ℝ) : x = Foo")] * (MAX_STATEMENT_REPAIRS + 1)
    outcome, fake, lean = run(bad, *[STATEMENT_ERROR] * (MAX_STATEMENT_REPAIRS + 1))
    assert outcome.failure is S.TRANSLATION_FAILED
    assert len(lean.sources) == MAX_STATEMENT_REPAIRS + 1
    assert "Unknown identifier" in outcome.detail


@pytest.mark.parametrize("lean_result", [TIMEOUT, UNAVAILABLE])
def test_lean_problems_are_runtime_errors_without_repair(lean_result):
    outcome, fake, _ = run([out()], lean_result)
    assert outcome.failure is S.RUNTIME_ERROR
    assert len(fake.requests) == 1


@pytest.mark.parametrize(
    "error, status",
    [(LLMUnavailableError("down"), S.RUNTIME_ERROR), (LLMRefusalError("no"), S.TRANSLATION_FAILED)],
)
def test_llm_errors(error, status):
    outcome, _, _ = run([error])
    assert outcome.failure is status


def test_problem_needing_clarification_is_refused():
    unclear = ProblemAnalysis(ambiguities=("Which sequence?",), in_scope=True)
    with pytest.raises(ValueError, match="clarification"):
        run([out()], a=unclear)
