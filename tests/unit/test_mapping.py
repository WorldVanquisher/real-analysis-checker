"""Tests for ra_checker.report.mapping (Advanced Feature B)."""

from pipeline_helpers import TACTICS, make_checker, parse_answer, proof_answer
from translation_helpers import OK, SORRY, STATEMENT_OK

from ra_checker.models import StepStatus as St, Submission
from ra_checker.report.mapping import build_mapping

SUBMISSION = Submission(problem_text="Suppose a_n → A. Prove that a_n + 1 → A + 1.", proof_text="…")


def report_with(block, lean=OK):
    checker, *_ = make_checker(STATEMENT_OK, lean, proof=proof_answer(block))
    return checker.verify(checker.formalize(SUBMISSION).confirmed()).report


def test_faithful_mapping_pairs_each_step_with_its_code():
    mapping = build_mapping(report_with(TACTICS))
    assert [r.step_id for r in mapping.rows] == ["S1", "S2", "S3"]
    assert mapping.rows[0].lean_code == "intro ε hε"
    assert mapping.rows[1].lean_code == "obtain ⟨N, hN⟩ := ha ε hε"
    assert mapping.rows[2].lean_code.startswith("refine ⟨N, fun n hn => ?_⟩")
    assert mapping.rows[0].student_text == "Let ε > 0."
    assert not mapping.substantially_transformed


def test_untagged_step_has_no_code_and_is_marked():
    mapping = build_mapping(report_with(TACTICS.replace("-- [S2]\n", "")))
    s2 = next(r for r in mapping.rows if r.step_id == "S2")
    assert s2.status is St.OMITTED and s2.lean_code == ""
    assert "obtain" in mapping.rows[0].lean_code  # S2's tactics now sit under S1
    assert not mapping.substantially_transformed  # 1 of 3 steps


def test_mostly_rewritten_translation_is_flagged_approximate():
    block = "-- [A1]\nunfold SeqConvergesTo at ha ⊢\n-- [S1]\nsorry"
    mapping = build_mapping(report_with(block, lean=SORRY))
    assert [r.status for r in mapping.rows] == [St.OMITTED, St.OMITTED, St.OMITTED, St.ADDED]
    assert mapping.rows[-1].student_text is None
    assert mapping.substantially_transformed


def test_no_mapping_without_a_translation():
    checker, *_ = make_checker(parse=parse_answer(ambiguities=["Which sequence?"]))
    assert build_mapping(checker.formalize(SUBMISSION)) is None
