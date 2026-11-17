"""Tests for ra_checker.lean.assemble."""

import pytest

from ra_checker.lean.assemble import (
    PROBE_TACTICS,
    PROBE_THEOREM_NAME,
    THEOREM_NAME,
    AssemblyError,
    assemble_hypotheses_probe,
    assemble_proof,
    assemble_statement_check,
    normalize_tactic_block,
)
from ra_checker.lean.safety import check_tactic_block

STATEMENT = "(a : ℕ → ℝ) (h : ∀ n, a n = 1) : a 3 = 1"


def test_proof_file_layout_and_line_numbers():
    f = assemble_proof(STATEMENT, "-- [S1]\nexact h 3")
    lines = f.source.split("\n")
    assert lines[:2] == ["import Mathlib", "import RaChecker"]
    header = lines[: f.statement_line - 1]
    assert "open RaChecker" in header
    assert "set_option autoImplicit false" in header
    assert lines[f.statement_line - 1] == f"theorem {THEOREM_NAME} {STATEMENT} := by"
    assert lines[f.proof_first_line - 1] == "  -- [S1]"
    assert lines[f.proof_first_line] == "  exact h 3"
    assert f.proof_line_count == 2
    assert lines[f.axioms_line - 1] == f"#print axioms {THEOREM_NAME}"
    assert f.source.endswith("\n")


def test_statement_is_inserted_verbatim():
    odd = "  (x : ℝ)   (hx : 0 < x) :\n    0 < x ^ 2  "
    f = assemble_proof(odd, "positivity")
    assert f.statement == odd
    assert f"theorem {THEOREM_NAME} {odd} := by" in f.source


def test_multiline_statement_shifts_proof_lines():
    f = assemble_proof("(x : ℝ) :\n  x = x", "rfl")
    assert f.proof_first_line == f.statement_line + 2
    assert f.source.split("\n")[f.proof_first_line - 1] == "  rfl"


def test_tactic_block_is_dedented_and_reindented():
    block = "\n\n    intro ε hε\n      linarith\n\n    exact h\n\n"
    assert normalize_tactic_block(block) == ["  intro ε hε", "    linarith", "", "  exact h"]


def test_tabs_and_crlf_are_normalized():
    assert normalize_tactic_block("\tintro x\r\n\t\tsimp\r\n") == ["  intro x", "    simp"]


def test_proof_line_mapping():
    f = assemble_proof(STATEMENT, "a\nb\nc")
    assert f.proof_line(f.proof_first_line) == 1
    assert f.proof_line(f.proof_first_line + 2) == 3
    assert f.proof_line(f.proof_first_line + 3) is None
    assert f.proof_line(f.statement_line) is None


def test_statement_check_uses_sorry_and_no_axiom_check():
    f = assemble_statement_check(STATEMENT)
    assert "  sorry" in f.source
    assert "#print axioms" not in f.source
    assert f.axioms_line is None


@pytest.mark.parametrize("statement, block", [("  ", "rfl"), (STATEMENT, " \n\t\n")])
def test_empty_parts_are_rejected(statement, block):
    with pytest.raises(AssemblyError):
        assemble_proof(statement, block)


def test_hypotheses_probe_proves_false_from_the_same_statement():
    f = assemble_hypotheses_probe(STATEMENT)
    lines = f.source.split("\n")
    assert f.theorem_name == PROBE_THEOREM_NAME != THEOREM_NAME
    assert lines[f.statement_line - 1] == f"theorem {PROBE_THEOREM_NAME} {STATEMENT} := by"
    assert lines[f.proof_first_line - 1 : f.proof_first_line - 1 + f.proof_line_count] == [
        "  " + t for t in PROBE_TACTICS
    ]
    assert lines[f.axioms_line - 1] == f"#print axioms {PROBE_THEOREM_NAME}"
    assert PROBE_TACTICS[0] == "exfalso" and "sorry" not in "\n".join(PROBE_TACTICS)
    # The fixed tactics would pass the same screen as translator-written ones.
    assert check_tactic_block("\n".join(PROBE_TACTICS)).ok
