"""Live check of the Lean code explanation (Advanced A). Run with `pytest -m llm`."""

import tomllib
from pathlib import Path

import pytest

from ra_checker.explain.code import explain_code
from ra_checker.lean.assemble import assemble_proof
from ra_checker.models import (
    CheckReport,
    FidelitySummary,
    FormalStatement,
    LeanRun,
    ProblemAnalysis,
    ProofStep,
    ProofTranslation,
    StepMapping,
    StepStatus,
    Submission,
    VerificationStatus,
)

pytestmark = pytest.mark.llm

CASES = tomllib.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "reference_cases.toml").read_text(encoding="utf-8")
)["case"]
SUM = next(c for c in CASES if c["id"] == "sum_of_limits")


def verified_reference_report() -> CheckReport:
    statement = FormalStatement(
        lean_statement=SUM["statement"], back_translation="If a → A and b → B then a + b → A + B.",
        confirmed_by_student=True,
    )
    translation = ProofTranslation(
        tactic_block=SUM["tactic_block"],
        step_map=tuple(
            StepMapping(step_id=f"S{i}", status=StepStatus.TRANSLATED) for i in range(1, len(SUM["steps"]) + 1)
        ),
    )
    source = assemble_proof(SUM["statement"], SUM["tactic_block"]).source
    return CheckReport(
        submission=Submission(problem_text=SUM["problem"], proof_text=" ".join(SUM["steps"])),
        status=VerificationStatus.VERIFIED,
        analysis=ProblemAnalysis(
            goal="a_n + b_n → A + B", in_scope=True,
            proof_steps=tuple(ProofStep(id=f"S{i}", text=t) for i, t in enumerate(SUM["steps"], 1)),
        ),
        statement=statement,
        translation=translation,
        # The reference proof is verified by real Lean in tests/lean; here only the
        # explanation is under test, so the run record mirrors that verified run.
        lean_run=LeanRun(source=source, exit_code=0, duration_s=22.0),
        fidelity=FidelitySummary.from_translation(statement, translation),
    )


def test_explanation_is_grounded_and_honest(live_llm):
    explanation = explain_code(verified_reference_report(), live_llm)
    assert len(explanation.blocks) == len(SUM["steps"])
    grounded = [b for b in explanation.blocks if b.source == "llm"]
    assert len(grounded) >= len(explanation.blocks) - 1, [b.withheld_mentions for b in explanation.blocks]
    assert "proof is correct" not in explanation.overview.lower()
