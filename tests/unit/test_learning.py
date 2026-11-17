"""Tests for ra_checker.learning (cards, detection, practice) — no real Lean."""

import pytest
from pipeline_helpers import TACTICS
from translation_helpers import OK, UNAVAILABLE, UNKNOWN_ID, ScriptedLean

from ra_checker.lean.safety import check_statement, check_tactic_block
from ra_checker.learning.cards import CARDS
from ra_checker.learning.detect import concepts_in, occurrences
from ra_checker.learning.practice import check_practice

BY_KEY = {c.key: c for c in CARDS}
PRACTICE = BY_KEY["intro"].practice


def test_cards_cover_the_concepts_named_in_the_spec():
    keys = [c.key for c in CARDS]
    assert len(keys) == len(set(keys))
    for concept in ("theorem", "intro", "apply", "exact", "have", "rw", "simp", "constructor", "rcases", "by"):
        assert concept in keys


@pytest.mark.parametrize("card", CARDS, ids=lambda c: c.key)
def test_examples_and_solutions_pass_the_safety_screen(card):
    snippets = [(card.example_statement, card.example_proof)]
    if card.practice:
        snippets.append((card.practice.statement, card.practice.solution))
        assert card.practice.prompt and card.practice.hint
    for statement, proof in snippets:
        assert check_statement(statement).ok
        block = check_tactic_block(proof)
        assert block.ok and block.placeholder_count == 0


def test_concepts_follow_the_code_in_order_of_appearance():
    keys = [c.key for c in concepts_in(TACTICS)]
    assert keys == ["theorem", "by", "intro", "rcases", "use", "have", "rw", "exact"]


@pytest.mark.parametrize(
    "code, present, absent",
    [
        ("-- intro is only mentioned\nlinarith", ["linarith"], ["intro"]),
        ("simpa using h", ["simp"], []),
        ("nlinarith [sq_nonneg x]", ["linarith"], []),
        ("exact_mod_cast hn", [], ["exact"]),
        ("by_contra! h\nlinarith", ["by_contra", "linarith"], []),
        ("rcases h with ⟨N, hN⟩", ["rcases"], ["by_cases"]),
    ],
)
def test_detection_respects_word_boundaries_and_comments(code, present, absent):
    keys = {c.key for c in concepts_in(code)}
    assert set(present) <= keys and not (set(absent) & keys)


def test_occurrences_name_the_step():
    hits = occurrences(BY_KEY["rcases"], TACTICS)
    assert hits == [("S2", "obtain ⟨N, hN⟩ := ha ε hε")]
    assert occurrences(BY_KEY["calc"], TACTICS) == []


def test_practice_verified_only_by_lean():
    lean = ScriptedLean(OK)
    result = check_practice(PRACTICE, PRACTICE.solution, lean)
    assert result.verified and result.message == "Lean accepted your answer."
    assert f"theorem student_claim {PRACTICE.statement} := by" in lean.sources[0]


def test_practice_failure_shows_lean_errors():
    result = check_practice(PRACTICE, "intro ε hε\nexact made_up hε", ScriptedLean(UNKNOWN_ID))
    assert not result.verified
    assert any("Unknown identifier" in e for e in result.lean_errors)


@pytest.mark.parametrize(
    "answer, message",
    [
        ("#eval 1", "not allowed"),
        ("intro ε hε\nsorry", "still contains `sorry`"),
        ("   ", "at least one tactic"),
    ],
)
def test_practice_rejections_before_lean(answer, message):
    lean = ScriptedLean()
    result = check_practice(PRACTICE, answer, lean)
    assert not result.verified and message in result.message
    assert lean.sources == []


def test_practice_without_lean():
    assert "Lean is not available" in check_practice(PRACTICE, "intro ε hε", ScriptedLean(UNAVAILABLE)).message
