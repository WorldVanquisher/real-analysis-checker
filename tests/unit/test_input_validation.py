"""Tests for ra_checker.input_validation."""

import pytest

from ra_checker.input_validation import (
    MAX_PROBLEM_CHARS,
    MAX_PROOF_CHARS,
    InputError,
    normalize_for_llm,
    validate_submission,
)
from ra_checker.models import CheckMode


def test_valid_submission_is_kept_verbatim():
    problem = "  Prove that 1/(n+1) → 0.\r\n"
    proof = "Let ε > 0.\tChoose N > 1/ε.  "
    s = validate_submission(problem, proof, CheckMode.LEARNING)
    assert (s.problem_text, s.proof_text, s.mode) == (problem, proof, CheckMode.LEARNING)


def test_blank_inputs_give_friendly_messages():
    with pytest.raises(InputError) as excinfo:
        validate_submission("  ", "\n")
    assert excinfo.value.problems == ("Please enter the problem statement.", "Please enter your proof.")


def test_length_limits():
    with pytest.raises(InputError, match="too long"):
        validate_submission("x" * (MAX_PROBLEM_CHARS + 1), "proof")
    with pytest.raises(InputError, match="too long"):
        validate_submission("problem", "x" * (MAX_PROOF_CHARS + 1))
    validate_submission("x" * MAX_PROBLEM_CHARS, "x" * MAX_PROOF_CHARS)


def test_normalize_for_llm():
    decomposed = "é"  # e + combining acute accent
    assert normalize_for_llm(f"  caf{decomposed}\r\nnext\rline \x00‮ ") == "café\nnext\nline"
    assert normalize_for_llm("x² ≤ |a_n − L|") == "x² ≤ |a_n − L|"  # NFC keeps superscripts
    assert normalize_for_llm("a\tb") == "a\tb"
