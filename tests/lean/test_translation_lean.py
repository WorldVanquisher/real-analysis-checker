"""Translation stages against real Lean (the LLM is a fake that returns
hand-written answers). Run with `pytest -m lean`."""

import tomllib
from pathlib import Path

import pytest

from ra_checker.lean.assemble import assemble_proof
from ra_checker.lean.diagnostics import parse_lean_output
from ra_checker.llm.client import FakeLLMClient
from ra_checker.llm.prompts import EXAMPLE_STATEMENT, EXAMPLE_TACTIC_BLOCK
from ra_checker.models import (
    FormalStatement,
    ProblemAnalysis,
    ProofStep,
    StepStatus,
    VerificationStatus as S,
)
from ra_checker.report.verdict import decide_proof_verdict
from ra_checker.translation.proof import (
    REPAIR_PROOF_TASK,
    TRANSLATE_TASK,
    ProofOutput,
    StepEntry,
    translate_proof,
)
from ra_checker.translation.statement import (
    FORMALIZE_TASK,
    REPAIR_STATEMENT_TASK,
    StatementOutput,
    formalize_statement,
)

pytestmark = pytest.mark.lean

CASES = tomllib.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "reference_cases.toml").read_text(
        encoding="utf-8"
    )
)["case"]
SUM = next(c for c in CASES if c["id"] == "sum_of_limits")


def analysis_for(case) -> ProblemAnalysis:
    return ProblemAnalysis(
        goal="the claim",
        proof_steps=tuple(ProofStep(id=f"S{i}", text=t) for i, t in enumerate(case["steps"], 1)),
        in_scope=True,
    )


def statement_answer(lean_statement: str) -> StatementOutput:
    return StatementOutput(
        cannot_formalize=False, reason="", lean_statement=lean_statement,
        back_translation="…", assumptions_added=[],
    )


def proof_answer(block: str, n_steps: int) -> ProofOutput:
    return ProofOutput(
        tactic_block=block,
        step_map=[StepEntry(step_id=f"S{i}", status="translated", note="") for i in range(1, n_steps + 1)],
        translator_notes="",
    )


def confirmed(lean_statement: str) -> FormalStatement:
    return FormalStatement(lean_statement=lean_statement, back_translation="…", confirmed_by_student=True)


def test_prompt_example_compiles(lean_runner):
    assembled = assemble_proof(EXAMPLE_STATEMENT, EXAMPLE_TACTIC_BLOCK)
    run = lean_runner.run(assembled.source)
    output = parse_lean_output(run.stdout, assembled.theorem_name, run.stderr)
    verdict = decide_proof_verdict(
        confirmed_statement=EXAMPLE_STATEMENT, assembled=assembled, run=run, output=output
    )
    assert verdict.verified, (verdict.reasons, run.stdout)


def test_statement_is_repaired_after_a_real_lean_error(lean_runner):
    broken = SUM["statement"].replace("SeqConvergesTo a A", "SeqConvergesToo a A")
    fake = FakeLLMClient(
        {FORMALIZE_TASK: statement_answer(broken), REPAIR_STATEMENT_TASK: statement_answer(SUM["statement"])}
    )
    outcome = formalize_statement(SUM["problem"], analysis_for(SUM), fake, lean_runner)
    assert outcome.ok, outcome.detail
    assert [a.accepted for a in outcome.attempts] == [False, True]
    assert "SeqConvergesToo" in fake.requests[1].user  # the real Lean error was passed on


def test_reference_proof_translates_to_verified(lean_runner):
    fake = FakeLLMClient({TRANSLATE_TASK: proof_answer(SUM["tactic_block"], len(SUM["steps"]))})
    outcome = translate_proof(SUM["problem"], analysis_for(SUM), confirmed(SUM["statement"]), fake, lean_runner)
    assert outcome.status is S.VERIFIED, outcome.detail
    assert all(m.status is StepStatus.TRANSLATED for m in outcome.translation.step_map)


def test_made_up_lemma_is_repaired(lean_runner):
    broken = SUM["tactic_block"].replace("le_of_max_le_left", "le_of_max_le_left_made_up")
    n = len(SUM["steps"])
    fake = FakeLLMClient(
        {TRANSLATE_TASK: proof_answer(broken, n), REPAIR_PROOF_TASK: proof_answer(SUM["tactic_block"], n)}
    )
    outcome = translate_proof(SUM["problem"], analysis_for(SUM), confirmed(SUM["statement"]), fake, lean_runner)
    assert outcome.status is S.VERIFIED, outcome.detail
    assert [a.kind for a in outcome.attempts] == ["initial", "repair"]
    assert "le_of_max_le_left_made_up" in fake.requests[1].user


def test_mathematical_error_is_reported_not_repaired(lean_runner):
    # The student uses ε instead of ε/2 for both sequences: the final bound is 2ε, not ε.
    wrong = (
        SUM["tactic_block"]
        .replace("ha (ε / 2) (half_pos hε)", "ha ε hε")
        .replace("hb (ε / 2) (half_pos hε)", "hb ε hε")
    )
    fake = FakeLLMClient({TRANSLATE_TASK: proof_answer(wrong, len(SUM["steps"]))})
    outcome = translate_proof(SUM["problem"], analysis_for(SUM), confirmed(SUM["statement"]), fake, lean_runner)
    assert outcome.status is S.VERIFICATION_FAILED
    assert len(fake.requests) == 1  # no repair attempted for a non-Lean-side error
    assert any("linarith failed" in e.message for e in outcome.output.errors)
