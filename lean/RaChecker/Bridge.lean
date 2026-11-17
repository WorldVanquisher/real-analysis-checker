import RaChecker.Defs

/-!
# Bridges to Mathlib

Each student-friendly definition from `RaChecker.Defs` is equivalent to the
corresponding Mathlib notion. These lemmas both certify the definitions and let
a proof switch to Mathlib's library when convenient.
-/

namespace RaChecker

open Filter Topology

theorem seqConvergesTo_iff_tendsto (a : ℕ → ℝ) (L : ℝ) :
    SeqConvergesTo a L ↔ Tendsto a atTop (𝓝 L) := by
  rw [Metric.tendsto_atTop]
  simp only [SeqConvergesTo, Real.dist_eq]

theorem seqCauchy_iff_cauchySeq (a : ℕ → ℝ) : SeqCauchy a ↔ CauchySeq a := by
  rw [Metric.cauchySeq_iff]
  simp only [SeqCauchy, Real.dist_eq]

theorem seqBounded_iff_isBounded_range (a : ℕ → ℝ) :
    SeqBounded a ↔ Bornology.IsBounded (Set.range a) := by
  rw [isBounded_iff_forall_norm_le]
  simp [SeqBounded, Real.norm_eq_abs]

theorem seqTendsToInfinity_iff_tendsto (a : ℕ → ℝ) :
    SeqTendsToInfinity a ↔ Tendsto a atTop atTop := by
  unfold SeqTendsToInfinity
  rw [tendsto_atTop_atTop]
  constructor
  · intro h M
    obtain ⟨N, hN⟩ := h M
    exact ⟨N, fun n hn => (hN n hn).le⟩
  · intro h M
    obtain ⟨N, hN⟩ := h (M + 1)
    exact ⟨N, fun n hn => by linarith [hN n hn]⟩

theorem seqConverges_iff (a : ℕ → ℝ) :
    SeqConverges a ↔ ∃ L, Tendsto a atTop (𝓝 L) := by
  simp only [SeqConverges, seqConvergesTo_iff_tendsto]

end RaChecker
