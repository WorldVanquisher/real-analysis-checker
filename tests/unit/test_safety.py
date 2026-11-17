"""Tests for ra_checker.lean.safety: the deny-list screen."""

import pytest

from ra_checker.lean.safety import (
    STATEMENT_MAX_CHARS,
    TACTIC_BLOCK_MAX_CHARS,
    check_statement,
    check_tactic_block,
)

TYPICAL_PROOF = """\
-- [S1] Let ε > 0.
intro ε hε
-- [S2] Choose N with 1/ε < N.
obtain ⟨N, hN⟩ := exists_nat_gt (1 / ε)
refine ⟨N, fun n hn => ?_⟩
/- [S3] the inequality; note /- nested -/ comments work -/
have h' : (0 : ℝ) < n + 1 := by positivity
rw [abs_sub_comm]
calc |(1 : ℝ) / (n + 1) - 0| = 1 / (n + 1) := by simp [abs_of_pos h']
  _ < ε := by
    rw [div_lt_iff₀ h']
    nlinarith [Classical.em (n = 0), inferInstance]
"""


def test_typical_proof_passes():
    report = check_tactic_block(TYPICAL_PROOF)
    assert report.ok, report.violations
    assert report.placeholder_count == 0


def test_typical_statement_passes():
    assert check_statement("(a : ℕ → ℝ) (L : ℝ) (h : ∀ ε > 0, ∃ N, ∀ n ≥ N, |a n - L| < ε) : True").ok


@pytest.mark.parametrize(
    "snippet, token",
    [
        ("#eval IO.println 1", "#e"),
        ("exact h\n#exit", "#e"),
        ("exact h\n  #print axioms foo", "#p"),
        ("run_tac do pure ()", "run_tac"),
        ("exact h\nset_option debug.skipKernelTC true in\nexample : False := sorry", "set_option"),
        ("exact h\naxiom cheat : False", "axiom"),
        ("exact h\ntheorem other : True := trivial", "theorem"),
        ("exact h\nelab \"x\" : tactic => pure ()", "elab"),
        ("exact h\nmacro \"x\" : tactic => `(tactic| rfl)", "macro"),
        ("exact h\nnotation \"⊤\" => False", "notation"),
        ("exact h\n@[simp] lemma l : True := trivial", "@["),
        ("exact h\nimport Mathlib", "import"),
        ("decide\nend", "end"),
        ("native_decide", "native_decide"),
        ("exact Lean.ofReduceBool _ _ rfl", "Lean"),
        ("exact (IO.Process.run {cmd := \"x\"})", "IO"),
        ("exact _root_.IO.FS.readFile", "IO"),
        ("admit", "admit"),
        ("exact «IO».println", "«"),
        ("exact unsafe_thing", None),  # identifier containing a denied word: allowed
    ],
)
def test_denied_constructs(snippet, token):
    report = check_tactic_block(snippet)
    if token is None:
        assert report.ok, report.violations
    else:
        assert not report.ok
        assert token in [v.token for v in report.violations]


def test_denied_words_inside_comments_are_ignored():
    assert check_tactic_block("-- #eval would be bad\n/- set_option -/ rfl").ok


def test_code_hidden_after_quoted_comment_marker_is_caught():
    # If strings were merely skipped, a naive scanner could misread "--" as a comment.
    report = check_tactic_block('exact "--" \n#eval 1')
    rules = {v.message for v in report.violations}
    assert "string literals are not allowed" in rules
    assert any(v.token.startswith("#") for v in report.violations)


def test_unterminated_block_comment_is_rejected():
    report = check_tactic_block("rfl\n/- never closed\n#print axioms student_claim")
    assert [v.rule for v in report.violations] == ["unterminated_comment"]


def test_hidden_characters_are_rejected():
    for char in ("‮", "\x00", "\x1b"):
        report = check_tactic_block(f"rfl{char}")
        assert [v.rule for v in report.violations] == ["hidden_character"]


def test_sorry_is_counted_in_tactic_blocks_but_denied_in_statements():
    block = check_tactic_block("-- [S2] sorry in a comment does not count\nsorry\nexact sorry")
    assert block.ok
    assert block.placeholder_count == 2
    statement = check_statement("(h : sorry) : True")
    assert [v.rule for v in statement.violations] == ["placeholder"]


def test_sorry_inside_identifier_is_not_a_placeholder():
    assert check_tactic_block("exact sorryAx _ false").placeholder_count == 0


def test_statement_cannot_carry_a_proof():
    report = check_statement(": True := trivial")
    assert "':=' is not allowed in a statement" in [v.message for v in report.violations]


def test_length_limits():
    assert not check_statement("x" * (STATEMENT_MAX_CHARS + 1)).ok
    assert not check_tactic_block("x" * (TACTIC_BLOCK_MAX_CHARS + 1)).ok


def test_violation_line_numbers():
    report = check_tactic_block("rfl\n\n  #eval 1\n-- ok\nset_option x 1 in rfl")
    assert [(v.line, v.token) for v in report.violations] == [(3, "#e"), (5, "set_option")]
