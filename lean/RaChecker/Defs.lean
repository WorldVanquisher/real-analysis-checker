import Mathlib

/-!
# Student-friendly definitions

Undergraduate real analysis is taught with ε–N definitions, while Mathlib states
limits with filters (`Filter.Tendsto a atTop (𝓝 L)`). Translating a student's
ε–N proof into filter language would hide the student's own steps, so the
checker formalizes statements with the textbook definitions below.

Each definition is proved equivalent to its Mathlib counterpart in
`RaChecker.Bridge`, so these are not new mathematics — only a familiar shape.
-/

namespace RaChecker

/-- The sequence `a` converges to `L`: for every `ε > 0` there is an `N` such
that `|a n - L| < ε` for all `n ≥ N`. -/
def SeqConvergesTo (a : ℕ → ℝ) (L : ℝ) : Prop :=
  ∀ ε > 0, ∃ N : ℕ, ∀ n ≥ N, |a n - L| < ε

/-- The sequence `a` converges (to some real limit). -/
def SeqConverges (a : ℕ → ℝ) : Prop :=
  ∃ L : ℝ, SeqConvergesTo a L

/-- The sequence `a` is bounded: some `M` bounds every `|a n|`. -/
def SeqBounded (a : ℕ → ℝ) : Prop :=
  ∃ M : ℝ, ∀ n : ℕ, |a n| ≤ M

/-- The sequence `a` is Cauchy: for every `ε > 0` there is an `N` such that
`|a m - a n| < ε` for all `m, n ≥ N`. -/
def SeqCauchy (a : ℕ → ℝ) : Prop :=
  ∀ ε > 0, ∃ N : ℕ, ∀ m ≥ N, ∀ n ≥ N, |a m - a n| < ε

/-- The sequence `a` tends to `+∞`: for every `M` there is an `N` such that
`a n > M` for all `n ≥ N`. -/
def SeqTendsToInfinity (a : ℕ → ℝ) : Prop :=
  ∀ M : ℝ, ∃ N : ℕ, ∀ n ≥ N, M < a n

end RaChecker
