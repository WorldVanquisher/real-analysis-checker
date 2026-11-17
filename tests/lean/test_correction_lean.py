"""Corrections are labelled verified only when real Lean accepts them.
Run with `pytest -m lean`."""

import pytest

from ra_checker.analysis.correction import CORRECTION_TASK, CorrectionOutput
from ra_checker.analysis.explain import EXPLAIN_TASK, ExplanationOutput
from ra_checker.llm.client import FakeLLMClient
from ra_checker.models import Submission, VerificationStatus as S
from ra_checker.parsing.problem_parser import PARSE_TASK, ProblemParseOutput
from ra_checker.pipeline import Checker
from ra_checker.translation.proof import TRANSLATE_TASK, ProofOutput, StepEntry
from ra_checker.translation.statement import FORMALIZE_TASK, StatementOutput

pytestmark = pytest.mark.lean

STATEMENT = "(x : ℝ) (hx : 0 < x) : 0 < x ^ 2"


def failed_report(lean_runner):
    llm = FakeLLMClient(
        {
            PARSE_TASK: ProblemParseOutput(
                in_scope=True, out_of_scope_reason="", topic="sequences", hypotheses=["x > 0"],
                goal="x² > 0", proof_steps=["Since x > 0, x² > 0."], ambiguities=[],
            ),
            FORMALIZE_TASK: StatementOutput(
                cannot_formalize=False, reason="", lean_statement=STATEMENT,
                back_translation="For real x > 0, x² > 0.", assumptions_added=[],
            ),
            TRANSLATE_TASK: ProofOutput(
                tactic_block="-- [S1]\nexact hx",
                step_map=[StepEntry(step_id="S1", status="translated", note="")],
                translator_notes="",
            ),
            EXPLAIN_TASK: ExplanationOutput(
                category="incomplete_proof", origin="student_reasoning", confidence="medium",
                explanation="x > 0 is not yet x² > 0.", math_interpretation="A step is missing.",
                correction_direction="Explain why the square of a positive number is positive.",
            ),
        }
    )
    checker = Checker(llm, lean_runner)
    report = checker.verify(
        checker.formalize(Submission(problem_text="Show x² > 0 for x > 0.", proof_text="…")).confirmed()
    ).report
    assert report.status is S.VERIFICATION_FAILED
    return checker, llm, report


def test_correct_fix_is_verified_and_wrong_fix_is_not(lean_runner):
    checker, llm, report = failed_report(lean_runner)

    llm.responses[CORRECTION_TASK] = CorrectionOutput(corrected_proof="-- [S1]\npositivity", explanation="…")
    good = checker.suggest_correction(report, 0)
    assert good.verified, good.reasons
    assert [c.step_id for c in good.changes] == ["S1"]

    llm.responses[CORRECTION_TASK] = CorrectionOutput(corrected_proof="-- [S1]\nexact le_of_lt hx", explanation="…")
    bad = checker.suggest_correction(report, 0)
    assert not bad.verified and bad.status is S.VERIFICATION_FAILED

    assert report.status is S.VERIFICATION_FAILED  # unchanged by either suggestion
