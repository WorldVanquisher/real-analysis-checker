"""Tests for ra_checker.analysis.locate and ra_checker.analysis.explain."""

import pytest

from ra_checker.analysis.explain import (
    EXPLAIN_TASK,
    MAX_ANALYZED_ERRORS,
    ExplanationOutput,
    analyze_failure,
    apply_guardrails,
)
from ra_checker.analysis.locate import locate_error
from ra_checker.lean.assemble import assemble_proof
from ra_checker.lean.diagnostics import LeanOutput
from ra_checker.llm.client import FakeLLMClient, LLMUnavailableError
from ra_checker.models import (
    Confidence as C,
    Diagnostic,
    ErrorCategory as Cat,
    ErrorOrigin as O,
    FormalStatement,
    LeanErrorKind as K,
    ProblemAnalysis,
    ProofStep,
    ProofTranslation,
    Severity,
    StepMapping,
    StepStatus as St,
)

STATEMENT = "(ε : ℝ) (hε : 0 < ε) : 0 < ε / 2 + ε"
BLOCK = "-- [S1]\nintro x\n-- [A1]\nhave h : 0 < ε / 2 := half_pos hε\n-- [S2]\nlinarith"
ASSEMBLED = assemble_proof(STATEMENT, BLOCK)
FIRST = ASSEMBLED.proof_first_line  # file line of "-- [S1]"
ANALYSIS = ProblemAnalysis(
    goal="0 < ε/2 + ε",
    proof_steps=(ProofStep(id="S1", text="Fix x."), ProofStep(id="S2", text="Then the sum is positive.")),
    in_scope=True,
)
STATEMENT_MODEL = FormalStatement(lean_statement=STATEMENT, back_translation="…", confirmed_by_student=True)


def translation(s2_status=St.TRANSLATED):
    return ProofTranslation(
        tactic_block=BLOCK,
        step_map=(
            StepMapping(step_id="S1", status=St.TRANSLATED),
            StepMapping(step_id="S2", status=s2_status, note="adjusted" if s2_status is St.CHANGED else ""),
            StepMapping(step_id="A1", status=St.ADDED, note="side condition"),
        ),
    )


def diag(line, message="linarith failed to find a contradiction", goal=None):
    return Diagnostic(line=line, column=2, severity=Severity.ERROR, message=message, goal_state=goal)


# ------------------------------------------------------------------------ locate


def test_error_inside_a_student_step():
    loc = locate_error(diag(FIRST + 5), ASSEMBLED, ANALYSIS)
    assert (loc.step_id, loc.block_line, loc.at_end_of_proof) == ("S2", 6, False)
    assert loc.step_text == "Then the sum is positive."
    assert loc.lean_snippet == "linarith"


def test_error_inside_a_translator_step():
    loc = locate_error(diag(FIRST + 3), ASSEMBLED, ANALYSIS)
    assert loc.step_id == "A1" and loc.step_text is None
    assert loc.lean_snippet == "have h : 0 < ε / 2 := half_pos hε"


def test_unsolved_goals_on_the_theorem_line_blame_the_last_step():
    loc = locate_error(diag(ASSEMBLED.statement_line, "unsolved goals"), ASSEMBLED, ANALYSIS)
    assert loc.at_end_of_proof and loc.block_line is None
    assert loc.step_id == "S2"


def test_error_after_the_block_goes_to_the_last_step():
    loc = locate_error(diag(ASSEMBLED.axioms_line), ASSEMBLED, ANALYSIS)
    assert loc.step_id == "S2" and not loc.at_end_of_proof


def test_untagged_block():
    assembled = assemble_proof(STATEMENT, "positivity")
    loc = locate_error(diag(assembled.proof_first_line), assembled, ANALYSIS)
    assert loc.step_id is None and loc.lean_snippet == "positivity"


# ----------------------------------------------------------------------- explain


def answer(category="mathematical_reasoning", origin="student_reasoning", confidence="high"):
    return ExplanationOutput(
        category=category, origin=origin, confidence=confidence,
        explanation="Your bound gives 2ε, not ε.", math_interpretation="The two estimates add up to 2ε.", correction_direction="Use ε/2 for each sequence.",
    )


def analyze(*diagnostics, responder=None, s2_status=St.TRANSLATED):
    fake = FakeLLMClient({EXPLAIN_TASK: responder if responder is not None else answer()})
    results = analyze_failure(
        problem_text="Prove 0 < ε/2 + ε.",
        analysis=ANALYSIS,
        statement=STATEMENT_MODEL,
        translation=translation(s2_status),
        assembled=ASSEMBLED,
        output=LeanOutput(tuple(diagnostics), None, False, ""),
        llm=fake,
    )
    return results, fake


@pytest.mark.parametrize(
    "message, kind, category",
    [
        ("Unknown identifier `half_pos_made_up`", K.UNKNOWN_IDENTIFIER, Cat.FORMALIZATION_ERROR),
        ("unexpected token ')'; expected term", K.SYNTAX, Cat.LEAN_SYNTAX),
    ],
)
def test_lean_side_errors_never_blame_the_student_and_skip_the_llm(message, kind, category):
    (result,), fake = analyze(diag(FIRST + 5, message))
    assert (result.lean_error_kind, result.category, result.origin) == (kind, category, O.FORMALIZATION)
    assert "not with your mathematics" in result.explanation
    assert fake.requests == []


def test_llm_explanation_is_used_with_location_and_raw_message():
    (result,), fake = analyze(diag(FIRST + 5, goal="⊢ False"))
    assert (result.category, result.origin, result.confidence) == (
        Cat.MATHEMATICAL_REASONING, O.STUDENT_REASONING, C.HIGH,
    )
    assert result.confident
    assert (result.step_id, result.line) == ("S2", 6)
    assert result.raw_message == "linarith failed to find a contradiction"
    request = fake.requests[0]
    assert request.effort == "high"
    for fragment in ("S2: Then the sum is positive.", "linarith failed", "⊢ False", "<lean_code>\nlinarith"):
        assert fragment in request.user


def test_end_of_proof_is_explained_as_such():
    _, fake = analyze(diag(ASSEMBLED.statement_line, "unsolved goals", goal="⊢ x < x + 1"))
    assert "ENDED with goals still open" in fake.requests[0].user


def test_errors_in_translator_steps_are_formalization_errors():
    (result,), _ = analyze(diag(FIRST + 3))
    assert (result.origin, result.category) == (O.FORMALIZATION, Cat.FORMALIZATION_ERROR)


def test_llm_failure_falls_back_to_an_honest_undetermined():
    (result,), _ = analyze(diag(FIRST + 5, "unsolved goals"), responder=LLMUnavailableError("down"))
    assert (result.origin, result.confidence, result.category) == (O.UNDETERMINED, C.LOW, Cat.UNRESOLVED_GOAL)
    assert not result.confident
    assert "could not determine automatically" in result.explanation


def test_at_most_a_few_errors_are_analyzed():
    results, fake = analyze(*[diag(FIRST + 5)] * (MAX_ANALYZED_ERRORS + 2))
    assert len(results) == MAX_ANALYZED_ERRORS == len(fake.requests)


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        # contradictory: blames the student but calls it a Lean problem
        (dict(category=Cat.FORMALIZATION_ERROR, origin=O.STUDENT_REASONING, confidence=C.HIGH),
         (Cat.FORMALIZATION_ERROR, O.UNDETERMINED, C.LOW)),
        # formalization origin cannot carry a student category
        (dict(category=Cat.MATHEMATICAL_REASONING, origin=O.FORMALIZATION, confidence=C.HIGH),
         (Cat.FORMALIZATION_ERROR, O.FORMALIZATION, C.HIGH)),
        # the translator changed the step: no high-confidence blame on the student
        (dict(category=Cat.ALGEBRAIC_COMPUTATIONAL, origin=O.STUDENT_REASONING, confidence=C.HIGH, step_status=St.CHANGED),
         (Cat.ALGEBRAIC_COMPUTATIONAL, O.STUDENT_REASONING, C.MEDIUM)),
        # a faithful step keeps the LLM's judgement
        (dict(category=Cat.MISSING_ASSUMPTION, origin=O.STUDENT_REASONING, confidence=C.HIGH),
         (Cat.MISSING_ASSUMPTION, O.STUDENT_REASONING, C.HIGH)),
    ],
)
def test_guardrails(kwargs, expected):
    args = dict(kind=K.TACTIC_FAILED, step_id="S2", step_status=St.TRANSLATED)
    args.update(kwargs)
    assert apply_guardrails(**args) == expected


def test_changed_step_caps_confidence_end_to_end():
    (result,), _ = analyze(diag(FIRST + 5), s2_status=St.CHANGED)
    assert result.confidence is C.MEDIUM
