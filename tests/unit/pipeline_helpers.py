"""Fakes for the whole pipeline: canned LLM answers for every stage."""

from __future__ import annotations

from translation_helpers import OK, STATEMENT_OK, ScriptedLean

from ra_checker.analysis.explain import EXPLAIN_TASK, ExplanationOutput
from ra_checker.llm.client import FakeLLMClient
from ra_checker.parsing.problem_parser import PARSE_TASK, ProblemParseOutput
from ra_checker.pipeline import Checker
from ra_checker.translation.proof import TRANSLATE_TASK, ProofOutput, StepEntry
from ra_checker.translation.statement import FORMALIZE_TASK, StatementOutput

PROBLEM = "Suppose a_n → A. Prove that a_n + 1 → A + 1."
STEPS = [
    "Let ε > 0.",
    "Since a_n → A, choose N with |a_n − A| < ε for all n ≥ N.",
    "Then for n ≥ N, |(a_n + 1) − (A + 1)| = |a_n − A| < ε.",
]
PROOF = " ".join(STEPS)
LEAN_STATEMENT = "(a : ℕ → ℝ) (A : ℝ) (ha : SeqConvergesTo a A) : SeqConvergesTo (fun n => a n + 1) (A + 1)"
TACTICS = (
    "-- [S1]\nintro ε hε\n-- [S2]\nobtain ⟨N, hN⟩ := ha ε hε\n-- [S3]\n"
    "refine ⟨N, fun n hn => ?_⟩\nshow |a n + 1 - (A + 1)| < ε\n"
    "have e : a n + 1 - (A + 1) = a n - A := by ring\nrw [e]\nexact hN n hn"
)


def parse_answer(**overrides) -> ProblemParseOutput:
    fields = dict(
        in_scope=True, out_of_scope_reason="", topic="sequences", hypotheses=["a_n → A"],
        goal="a_n + 1 → A + 1", proof_steps=STEPS, ambiguities=[],
    )
    fields.update(overrides)
    return ProblemParseOutput(**fields)


def statement_answer(**overrides) -> StatementOutput:
    fields = dict(
        cannot_formalize=False, reason="", lean_statement=LEAN_STATEMENT,
        back_translation="If a converges to A, then a_n + 1 converges to A + 1.",
        assumptions_added=[],
    )
    fields.update(overrides)
    return StatementOutput(**fields)


def proof_answer(block: str = TACTICS, statuses=("translated",) * 3) -> ProofOutput:
    return ProofOutput(
        tactic_block=block,
        step_map=[StepEntry(step_id=f"S{i}", status=s, note="") for i, s in enumerate(statuses, 1)],
        translator_notes="",
    )


EXPLANATION = ExplanationOutput(
    category="incomplete_proof", origin="student_reasoning", confidence="medium",
    explanation="The last step does not show the inequality.",
    correction_direction="Show why |a_n − A| < ε gives the claim.",
)


def make_checker(*lean_results, **answers) -> tuple[Checker, FakeLLMClient, ScriptedLean]:
    responses = {
        PARSE_TASK: answers.get("parse", parse_answer()),
        FORMALIZE_TASK: answers.get("statement", statement_answer()),
        TRANSLATE_TASK: answers.get("proof", proof_answer()),
        EXPLAIN_TASK: answers.get("explain", EXPLANATION),
    }
    llm = FakeLLMClient(responses)
    lean = ScriptedLean(*(lean_results or (STATEMENT_OK, OK)))
    return Checker(llm, lean), llm, lean
