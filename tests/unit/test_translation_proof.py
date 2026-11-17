"""Tests for ra_checker.translation.proof (fake LLM, scripted Lean)."""

import pytest
from translation_helpers import OK, SORRY, UNAVAILABLE, UNKNOWN_ID, UNSOLVED, ScriptedLean, analysis

from ra_checker.llm.client import FakeLLMClient, LLMRefusalError, LLMUnavailableError
from ra_checker.models import FormalStatement, StepStatus as St, VerificationStatus as S
from ra_checker.translation.proof import (
    MAX_PROOF_REPAIRS,
    REPAIR_PROOF_TASK,
    TRANSLATE_TASK,
    ProofOutput,
    StepEntry,
    translate_proof,
)

STATEMENT = FormalStatement(
    lean_statement="(a : ℕ → ℝ) (A : ℝ) (ha : SeqConvergesTo a A) : SeqConvergesTo (fun n => a n + 1) (A + 1)",
    back_translation="…",
    confirmed_by_student=True,
)
BLOCK = "-- [S1]\nintro ε hε\n-- [S2]\nobtain ⟨N, hN⟩ := ha ε hε\n-- [S3]\nexact ⟨N, fun n hn => by simpa using hN n hn⟩"


def entries(*specs):
    return [StepEntry(step_id=i, status=s, note=n) for i, s, n in specs]


DEFAULT_MAP = entries(("S1", "translated", ""), ("S2", "translated", ""), ("S3", "translated", ""))


def proof(block=BLOCK, step_map=None, notes="") -> ProofOutput:
    return ProofOutput(tactic_block=block, step_map=step_map or DEFAULT_MAP, translator_notes=notes)


def sequence(*answers):
    answers = list(answers)
    return lambda request: answers.pop(0)


def run(first, *lean_results, repairs=(), repair_error=None, statement=STATEMENT):
    repair = repair_error if repair_error is not None else sequence(*repairs)
    fake = FakeLLMClient({TRANSLATE_TASK: first, REPAIR_PROOF_TASK: repair})
    lean = ScriptedLean(*lean_results)
    return translate_proof("Suppose a_n → A. …", analysis(), statement, fake, lean), fake, lean


def statuses(outcome):
    return {m.step_id: m.status for m in outcome.translation.step_map}


def test_unconfirmed_statement_is_refused():
    with pytest.raises(ValueError, match="confirmed"):
        run(proof(), statement=STATEMENT.model_copy(update={"confirmed_by_student": False}))


def test_verified_translation():
    outcome, fake, lean = run(proof(notes="direct"), OK)
    assert outcome.status is S.VERIFIED
    assert statuses(outcome) == {"S1": St.TRANSLATED, "S2": St.TRANSLATED, "S3": St.TRANSLATED}
    assert outcome.translation.translator_notes == "direct"
    assert f"theorem student_claim {STATEMENT.lean_statement} := by" in lean.sources[0]
    assert "  -- [S2]\n  obtain" in lean.sources[0]
    assert fake.requests[0].effort == "high"
    assert "S2: step 2" in fake.requests[0].user
    assert len(outcome.attempts) == 1


def test_step_statuses_follow_the_code_not_the_llm():
    block = "-- [S1]\nintro ε hε\n-- [S3]\nsorry\n-- [A1]\nhave h : 0 < ε / 2 := half_pos hε\nexact ⟨0, fun n _ => by sorry⟩"
    claims = entries(
        ("S1", "changed", "used intro"),
        ("S2", "translated", "claims to be translated"),
        ("S3", "translated", "could not do it"),
        ("A1", "added", "positivity side condition"),
    )
    outcome, _, _ = run(proof(block, claims), SORRY)
    m = {x.step_id: x for x in outcome.translation.step_map}
    assert m["S1"].status is St.CHANGED
    assert m["S2"].status is St.OMITTED  # no S2 tag in the code
    assert m["S3"].status is St.OMITTED and "placeholder" in m["S3"].note
    assert m["A1"].status is St.ADDED
    assert outcome.status is S.TRANSLATION_FAILED  # sorry → incomplete, not a student error


def test_leading_untagged_code_becomes_an_added_step():
    outcome, _, lean = run(proof("unfold SeqConvergesTo at ha\n" + BLOCK), OK)
    assert outcome.translation.tactic_block.startswith("-- [A1]\nunfold")
    assert statuses(outcome)["A1"] is St.ADDED
    assert "  -- [A1]" in lean.sources[0]


@pytest.mark.parametrize(
    "block, message",
    [
        ("-- [S1]\nintro ε hε\n-- [S1]\nrfl", "more than once"),
        ("-- [S1]\nintro ε hε\n-- [S9]\nrfl", "did not write: S9"),
    ],
)
def test_inconsistent_tags_fail_before_lean(block, message):
    outcome, _, lean = run(proof(block))
    assert outcome.status is S.TRANSLATION_FAILED and message in outcome.detail
    assert lean.sources == []


def test_safety_violations_are_never_repaired():
    outcome, fake, lean = run(proof(BLOCK + "\nnative_decide"))
    assert outcome.status is S.TRANSLATION_FAILED and "safety screen" in outcome.detail
    assert lean.sources == [] and len(fake.requests) == 1


def test_lean_side_error_is_repaired():
    fixed = proof(BLOCK.replace("by simpa", "by simpa"))  # same tags, same placeholders
    outcome, fake, lean = run(proof(BLOCK.replace("simpa", "made_up")), UNKNOWN_ID, OK, repairs=[fixed])
    assert outcome.status is S.VERIFIED
    assert [a.kind for a in outcome.attempts] == ["initial", "repair"]
    assert [r.task for r in fake.requests] == [TRANSLATE_TASK, REPAIR_PROOF_TASK]
    # The scripted error is on file line 9 = line 2 of the tactic block.
    assert "line 2 of your tactic block: Unknown identifier `made_up`" in fake.requests[1].user


def test_repair_that_changes_the_steps_is_rejected():
    sneaky = proof(BLOCK + "\n-- [A1]\nnlinarith")
    outcome, _, lean = run(proof(), UNKNOWN_ID, repairs=[sneaky])
    assert outcome.status is S.VERIFICATION_FAILED  # result of the first attempt is kept
    assert outcome.attempts[-1].status is None
    assert "changed the step tags" in outcome.attempts[-1].reasons[0]
    assert len(lean.sources) == 1


def test_repair_that_fills_a_placeholder_is_rejected():
    with_sorry = BLOCK.replace("exact ⟨N, fun n hn => by simpa using hN n hn⟩", "sorry")
    outcome, _, _ = run(proof(with_sorry + "\nexact made_up"), UNKNOWN_ID, repairs=[proof()])
    assert outcome.attempts[-1].status is None


def test_mathematical_failures_are_not_repaired():
    outcome, fake, _ = run(proof(), UNSOLVED)
    assert outcome.status is S.VERIFICATION_FAILED
    assert len(fake.requests) == 1


def test_repairs_are_bounded():
    n = MAX_PROOF_REPAIRS + 1
    outcome, fake, lean = run(proof(), *[UNKNOWN_ID] * n, repairs=[proof()] * MAX_PROOF_REPAIRS)
    assert outcome.status is S.VERIFICATION_FAILED
    assert len(lean.sources) == n and len(fake.requests) == n


def test_failed_repair_call_keeps_previous_result():
    outcome, fake, _ = run(proof(), UNKNOWN_ID, repair_error=LLMUnavailableError("down"))
    assert outcome.status is S.VERIFICATION_FAILED  # the first attempt's result stands
    assert [r.task for r in fake.requests] == [TRANSLATE_TASK, REPAIR_PROOF_TASK]
    assert len(outcome.attempts) == 1


def test_lean_unavailable_is_runtime_error():
    outcome, _, _ = run(proof(), UNAVAILABLE)
    assert outcome.status is S.RUNTIME_ERROR


@pytest.mark.parametrize(
    "error, status",
    [(LLMUnavailableError("down"), S.RUNTIME_ERROR), (LLMRefusalError("no"), S.TRANSLATION_FAILED)],
)
def test_llm_errors(error, status):
    outcome, _, lean = run(error)
    assert outcome.status is status and lean.sources == []
