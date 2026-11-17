import RaChecker.Defs
import RaChecker.Bridge

/-!
# RaChecker

Lean library for the Real Analysis Homework Checker.

* `RaChecker.Defs` — student-friendly ε–N definitions (`SeqConvergesTo`, …).
* `RaChecker.Bridge` — proofs that each definition agrees with Mathlib.

Generated proofs are checked from temporary files with `lake env lean`; they
import this library and `open RaChecker`.
-/
