"""Tests for ra_checker.explain.code (Advanced Feature A) with a fake LLM."""

import pytest
from pipeline_helpers import make_checker, parse_answer
from translation_helpers import STATEMENT_OK, UNSOLVED

from ra_checker.explain.code import (
    EXPLAIN_CODE_TASK,
    CodeExplanationOutput,
    explain_code,
    ungrounded_mentions,
)
from ra_checker.llm.client import FakeLLMClient, LLMUnavailableError
from ra_checker.models import Submission

SUBMISSION = Submission(problem_text="Suppose a_n → A. Prove that a_n + 1 → A + 1.", proof_text="…")


def report(*lean):
    checker, *_ = make_checker(*lean)
    return checker.verify(checker.formalize(SUBMISSION).confirmed()).report


def block(step_id, syntax="`intro ε hε` introduces ε and the fact hε : ε > 0."):
    return {
        "step_id": step_id, "lean_syntax": syntax, "math_meaning": "Let ε > 0.",
        "role": "Starts the ε–N argument.", "why_needed": "The definition quantifies over ε.",
    }


def answer(*blocks, overview="The proof unpacks the definition and estimates."):
    return CodeExplanationOutput(overview=overview, blocks=list(blocks))


def run(responder, r=None):
    fake = FakeLLMClient({EXPLAIN_CODE_TASK: responder})
    return explain_code(r or report(), fake), fake


def test_grounded_explanations_are_kept_in_code_order():
    explanation, fake = run(answer(
        block("S3", "`rw [e]` rewrites the difference, then `exact` finishes."),
        block("S1"),
        block("S2", "`obtain ⟨N, hN⟩ := ha ε hε` takes the N for this ε."),
    ))
    assert [b.step_id for b in explanation.blocks] == ["S1", "S2", "S3"]
    assert all(b.source == "llm" for b in explanation.blocks)
    assert explanation.overview.startswith("The proof")
    request = fake.requests[0]
    assert "What Lean concluded: Lean accepted this formal proof." in request.user
    assert "obtain ⟨N, hN⟩ := ha ε hε" in request.user  # the actual code is the context
    assert request.effort == "medium"


def test_explanation_mentioning_names_not_in_the_proof_is_withheld():
    explanation, _ = run(answer(
        block("S1", "`intro ε hε` and then `linarith` with `half_pos`."),
        block("S2", "Uses `nlinarith` to pick N."),
        block("S3", "`rw [e]` then `exact hN n hn`."),
    ))
    s1, s2, s3 = explanation.blocks
    assert s1.source == "automatic" and s1.withheld_mentions == ("linarith", "half_pos")
    assert s2.source == "automatic" and s2.withheld_mentions == ("nlinarith",)
    assert s3.source == "llm"
    assert "`intro`" in s1.lean_syntax  # the automatic summary names what the block uses


def test_references_to_other_blocks_of_the_proof_are_allowed():
    # Found in the first live evaluation: explanations rightly refer back to
    # hypotheses introduced earlier (here `hε` from S1) and to other steps.
    explanation, _ = run(answer(
        block("S1"),
        block("S2", "Applies `ha` to the `ε` and `hε` from `intro`."),
        block("S3", "Finishes the goal opened by `refine` after `obtain` gave `hN`."),
    ))
    assert [b.source for b in explanation.blocks] == ["llm", "llm", "llm"]


def test_missing_and_invented_blocks():
    explanation, _ = run(answer(block("S1"), block("S9")))
    assert [b.step_id for b in explanation.blocks] == ["S1", "S2", "S3"]
    assert [b.source for b in explanation.blocks] == ["llm", "automatic", "automatic"]


def test_ungrounded_overview_is_replaced():
    explanation, _ = run(answer(block("S1"), overview="It uses `nlinarith` throughout."))
    assert "nlinarith" not in explanation.overview


def test_llm_outage_gives_automatic_summaries():
    explanation, _ = run(LLMUnavailableError("down"))
    assert explanation.llm_model is None
    assert all(b.source == "automatic" for b in explanation.blocks)
    assert explanation.blocks[0].math_meaning == "It formalizes your step: Let ε > 0."


def test_failed_check_passes_the_failure_on():
    _, fake = run(answer(block("S1")), r=report(STATEMENT_OK, UNSOLVED))
    assert "Lean rejected this formal proof (first problem in block S3)" in fake.requests[0].user


def test_no_explanation_without_a_translation():
    checker, *_ = make_checker(parse=parse_answer(ambiguities=["Which sequence?"]))
    assert explain_code(checker.formalize(SUBMISSION), FakeLLMClient({})) is None


@pytest.mark.parametrize(
    "text, expected",
    [
        ("`intro ε hε` then `exact h`", ()),
        ("uses `SeqConvergesTo` and `theorem`", ()),
        ("calls `abs_sub_lt_iff`", ("abs_sub_lt_iff",)),
        ("no backticks at all, linarith", ()),
    ],
)
def test_ungrounded_mentions(text, expected):
    assert ungrounded_mentions(text, "intro ε hε\nexact h", "(a : ℕ → ℝ) : True") == expected
