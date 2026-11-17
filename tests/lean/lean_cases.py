"""Hand-written Lean cases with known outcomes (no LLM involved).

``raw_source`` cases bypass the assembler and safety screen on purpose, to show
that the verdict's axiom check still catches unsound tricks if something slips
past the screen.
"""

from __future__ import annotations

from dataclasses import dataclass

from ra_checker.lean.assemble import THEOREM_NAME
from ra_checker.models import VerificationStatus as S


@dataclass(frozen=True)
class LeanCase:
    name: str
    statement: str
    tactic_block: str
    expected: S
    raw_source: str | None = None  # if set, run this instead of the assembled file


CASES: tuple[LeanCase, ...] = (
    LeanCase(
        "verified_positivity",
        "(x : ℝ) (hx : 0 < x) : 0 < x ^ 2",
        "-- [S1] x² is positive because x is\npositivity",
        S.VERIFIED,
    ),
    LeanCase(
        "verified_epsilon_n",
        "(a : ℕ → ℝ) (ha : ∀ n, a n = 3) : ∀ ε > 0, ∃ N : ℕ, ∀ n ≥ N, |a n - 3| < ε",
        "-- [S1] Let ε > 0.\nintro ε hε\n-- [S2] Any N works, e.g. N = 0.\n"
        "refine ⟨0, fun n _ => ?_⟩\n-- [S3] |a n - 3| = 0 < ε.\nsimpa [ha n] using hε",
        S.VERIFIED,
    ),
    LeanCase(
        "unsolved_goals",
        "(x : ℝ) : 0 ≤ x ^ 2 ∧ x < x + 1",
        "-- [S1]\nconstructor\n-- [S2]\n· positivity",
        S.VERIFICATION_FAILED,
    ),
    LeanCase(
        "type_mismatch",
        "(x : ℝ) (hx : 0 < x) : 0 < x ^ 2",
        "-- [S1]\nexact hx",
        S.VERIFICATION_FAILED,
    ),
    LeanCase(
        "unknown_identifier",
        "(x : ℝ) (hx : 0 < x) : 0 < x ^ 2",
        "-- [S1]\nexact pow_pos_of_made_up_lemma hx 2",
        S.VERIFICATION_FAILED,
    ),
    LeanCase(
        "syntax_error",
        "(x : ℝ) : x = x",
        "-- [S1]\nexact (rfl",
        S.VERIFICATION_FAILED,
    ),
    LeanCase(
        "linarith_failed",
        "(x y : ℝ) (h : x < y) : y < x",
        "-- [S1] by linear arithmetic\nlinarith",
        S.VERIFICATION_FAILED,
    ),
    LeanCase(
        "sorry_placeholder",
        "(x : ℝ) (hx : 0 < x) : 0 < x ^ 2",
        "-- [S1] (could not be formalized)\nsorry",
        S.TRANSLATION_FAILED,
    ),
    LeanCase(
        "native_decide_axiom",
        ": (2 : ℕ) + 2 = 4",
        "native_decide",
        S.VERIFICATION_FAILED,
        raw_source=(
            f"import Mathlib\n\ntheorem {THEOREM_NAME} : (2 : ℕ) + 2 = 4 := by\n"
            f"  native_decide\n\n#print axioms {THEOREM_NAME}\n"
        ),
    ),
    LeanCase(
        "injected_axiom",
        ": (0 : ℝ) = 1",
        "exact cheat.elim",
        S.VERIFICATION_FAILED,
        raw_source=(
            f"import Mathlib\n\naxiom cheat : False\n\ntheorem {THEOREM_NAME} : (0 : ℝ) = 1 := by\n"
            f"  exact cheat.elim\n\n#print axioms {THEOREM_NAME}\n"
        ),
    ),
)
