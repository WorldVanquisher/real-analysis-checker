"""Hand-written, beginner-level concept cards.

Every ``example_proof`` and every practice ``solution`` is compiled by Lean in
``tests/lean/test_learning_lean.py``, so a card can never teach code that does
not work. Statements use the same ``(binders) : goal`` form as the checker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Practice:
    prompt: str
    statement: str
    hint: str
    solution: str  # Lean-checked in the test suite


@dataclass(frozen=True)
class ConceptCard:
    key: str
    title: str
    lean_meaning: str
    math_meaning: str
    example_statement: str
    example_proof: str
    triggers: tuple[str, ...]  # words whose presence in the code selects the card
    practice: Practice | None = None

    @property
    def pattern(self) -> re.Pattern[str]:
        words = "|".join(re.escape(t) for t in self.triggers)
        return re.compile(rf"(?<![\w'.])(?:{words})(?![\w'!?])")


CARDS: tuple[ConceptCard, ...] = (
    ConceptCard(
        key="theorem",
        title="theorem — the claim and its assumptions",
        lean_meaning=(
            "`theorem name (assumptions) : goal := proof` states a claim. Everything "
            "before the last `:` may be assumed; the part after it must be proved."
        ),
        math_meaning='Like "Theorem. Let x be a real number with x > 0. Then x² > 0."',
        example_statement="(x : ℝ) (hx : 0 < x) : 0 < x ^ 2",
        example_proof="positivity",
        triggers=("theorem",),
    ),
    ConceptCard(
        key="by",
        title="by — a proof as a sequence of steps",
        lean_meaning=(
            "`by` starts a proof written as tactics: instructions that change the goal "
            "step by step until nothing is left to prove."
        ),
        math_meaning='The "Proof." of a written proof; each tactic is one step of the argument.',
        example_statement="(x : ℝ) (hx : 0 < x) : 0 < x ^ 2",
        example_proof="positivity",
        triggers=("by",),
    ),
    ConceptCard(
        key="intro",
        title="intro — let x be arbitrary / assume A",
        lean_meaning=(
            "`intro x` turns a goal `∀ x, P x` into the goal `P x` for a fresh, "
            "arbitrary `x`; for a goal `A → B` it adds the assumption `A` and leaves `B`. "
            "`intro ε hε` on `∀ ε > 0, …` gives both ε and the fact `hε : ε > 0`."
        ),
        math_meaning='"Let ε > 0 be arbitrary." or "Assume A."',
        example_statement=": ∀ x : ℝ, x ≤ x",
        example_proof="intro x\nexact le_refl x",
        triggers=("intro", "intros"),
        practice=Practice(
            prompt="Prove that for every ε > 0, also ε/2 > 0.",
            statement=": ∀ ε : ℝ, ε > 0 → ε / 2 > 0",
            hint="Introduce ε and the assumption with `intro`, then use the lemma `half_pos`.",
            solution="intro ε hε\nexact half_pos hε",
        ),
    ),
    ConceptCard(
        key="exact",
        title="exact — this is exactly what we need",
        lean_meaning=(
            "`exact t` finishes the goal with a term `t` whose statement is exactly the "
            "goal — a hypothesis, or a theorem applied to hypotheses."
        ),
        math_meaning='"…which is exactly hypothesis (h)." or "…by Theorem T applied to (h)."',
        example_statement="(x : ℝ) (h : x < 1) : x < 1",
        example_proof="exact h",
        triggers=("exact",),
        practice=Practice(
            prompt="From a < b and b < 1, conclude a < 1.",
            statement="(a b : ℝ) (hab : a < b) (hb : b < 1) : a < 1",
            hint="`lt_trans` turns `a < b` and `b < c` into `a < c`.",
            solution="exact lt_trans hab hb",
        ),
    ),
    ConceptCard(
        key="apply",
        title="apply — it suffices to show…",
        lean_meaning=(
            "`apply f` works backwards: if `f` proves the goal from some premises, the "
            "goal is replaced by those premises."
        ),
        math_meaning='"By Theorem T, it suffices to show …"',
        example_statement="(a b c : ℝ) (h₁ : a < b) (h₂ : b < c) : a < c",
        example_proof="apply lt_trans h₁\nexact h₂",
        triggers=("apply",),
        practice=Practice(
            prompt="Show 0 < x/2 for x > 0 by reducing it to 0 < x.",
            statement="(x : ℝ) (hx : 0 < x) : 0 < x / 2",
            hint="`half_pos` says: if 0 < a then 0 < a / 2. Apply it, then finish with `exact`.",
            solution="apply half_pos\nexact hx",
        ),
    ),
    ConceptCard(
        key="have",
        title="have — an intermediate claim",
        lean_meaning=(
            "`have h : P := by …` proves a fact `P` on the way and records it as `h` for "
            "the rest of the proof."
        ),
        math_meaning='"First we show P." — a small lemma inside the proof.',
        example_statement="(x : ℝ) (hx : 1 < x) : 0 < x",
        example_proof="have h : (0 : ℝ) < 1 := by norm_num\nlinarith",
        triggers=("have",),
        practice=Practice(
            prompt="If x > 2, show x − 1 > 0 by first proving x − 1 > 1.",
            statement="(x : ℝ) (hx : 2 < x) : 0 < x - 1",
            hint="Start with `have h : 1 < x - 1 := by linarith`, then conclude.",
            solution="have h : 1 < x - 1 := by linarith\nlinarith",
        ),
    ),
    ConceptCard(
        key="rw",
        title="rw — substitute equals for equals",
        lean_meaning=(
            "`rw [h]` uses an equation `h : a = b` to replace `a` by `b` in the goal "
            "(`rw [← h]` replaces `b` by `a`). Lemmas like `abs_lt` can be used the same way."
        ),
        math_meaning='"Substituting a = b, it remains to show …"',
        example_statement="(a b : ℝ) (h : a = b) (hb : 0 < b) : 0 < a",
        example_proof="rw [h]\nexact hb",
        triggers=("rw", "rewrite"),
        practice=Practice(
            prompt="Given y = x + 1 and x > 0, show y > 0.",
            statement="(x y : ℝ) (h : y = x + 1) (hx : 0 < x) : 0 < y",
            hint="Rewrite `y` with `rw [h]`; what is left is linear arithmetic.",
            solution="rw [h]\nlinarith",
        ),
    ),
    ConceptCard(
        key="simp",
        title="simp / simpa — routine simplification",
        lean_meaning=(
            "`simp` simplifies the goal with a large set of rules (`c - c = 0`, "
            "`|0| = 0`, …). `simpa using h` simplifies both the goal and `h`, then closes "
            "the goal with `h`."
        ),
        math_meaning='"Simplifying, we get …" — the routine algebra a textbook skips.',
        example_statement="(c ε : ℝ) (hε : 0 < ε) : |c - c| < ε",
        example_proof="simpa using hε",
        triggers=("simp", "simpa", "simp_all"),
        practice=Practice(
            prompt="Show x + 0 = x.",
            statement="(x : ℝ) : x + 0 = x",
            hint="This is a one-word simplification.",
            solution="simp",
        ),
    ),
    ConceptCard(
        key="constructor",
        title="constructor — prove both parts",
        lean_meaning=(
            "`constructor` splits a goal `A ∧ B` into the goals `A` and `B` (and `A ↔ B` "
            "into both directions). Each goal is then proved under its own `·`."
        ),
        math_meaning='"We prove both claims." / "We prove both directions."',
        example_statement="(x : ℝ) (hx : 0 < x) : 0 < x ∧ 0 < 2 * x",
        example_proof="constructor\n· exact hx\n· linarith",
        triggers=("constructor",),
        practice=Practice(
            prompt="If x > 1, show both x > 0 and x + 1 > 0.",
            statement="(x : ℝ) (hx : 1 < x) : 0 < x ∧ 0 < x + 1",
            hint="Split with `constructor`; each part follows by `linarith`.",
            solution="constructor\n· linarith\n· linarith",
        ),
    ),
    ConceptCard(
        key="rcases",
        title="obtain / rcases — fix such an N",
        lean_meaning=(
            "`obtain ⟨N, hN⟩ := h` unpacks `h : ∃ N, P N` into a witness `N` and the fact "
            "`hN : P N` (`rcases h with ⟨N, hN⟩` does the same). With convergence, "
            "`obtain ⟨N, hN⟩ := ha ε hε` takes the N that the definition promises for ε."
        ),
        math_meaning='"Since a_n → A, there is an N such that …; fix such an N."',
        example_statement="(a : ℕ → ℝ) (h : ∃ N : ℕ, a N = 0) : ∃ n : ℕ, a n ≤ 0",
        example_proof="obtain ⟨N, hN⟩ := h\nexact ⟨N, le_of_eq hN⟩",
        triggers=("obtain", "rcases", "rintro"),
        practice=Practice(
            prompt="If some x is positive, show some y has 2·y > 0.",
            statement="(h : ∃ x : ℝ, 0 < x) : ∃ y : ℝ, 0 < 2 * y",
            hint="Unpack `h` with `obtain ⟨x, hx⟩ := h`, then use the same x.",
            solution="obtain ⟨x, hx⟩ := h\nexact ⟨x, by linarith⟩",
        ),
    ),
    ConceptCard(
        key="use",
        title="use / refine — take N = …",
        lean_meaning=(
            "`use N` proves `∃ N, P N` by choosing the witness `N`, leaving `P N`. "
            "`refine ⟨N, fun n hn => ?_⟩` does the same and also introduces `n` and "
            "`hn : n ≥ N`, leaving the inequality for that `n`."
        ),
        math_meaning='"Take N = … . Then for every n ≥ N, …"',
        example_statement=": ∃ N : ℕ, 3 < N",
        example_proof="use 4\nnorm_num",
        triggers=("use", "refine", "exists"),
        practice=Practice(
            prompt="Show that some real number squares to 4.",
            statement=": ∃ x : ℝ, x ^ 2 = 4",
            hint="Pick the witness with `use`, then let `norm_num` check the arithmetic.",
            solution="use 2\nnorm_num",
        ),
    ),
    ConceptCard(
        key="linarith",
        title="linarith — combine inequalities",
        lean_meaning=(
            "`linarith` proves a linear inequality that follows from the hypotheses by "
            "adding them with positive coefficients; `nlinarith` also tries products. If "
            "it fails, the inequality may simply not follow from what you have — often "
            "exactly where a proof has a gap."
        ),
        math_meaning='"Adding the two inequalities gives …"',
        example_statement="(a b ε : ℝ) (ha : a < ε / 2) (hb : b < ε / 2) : a + b < ε",
        example_proof="linarith",
        triggers=("linarith", "nlinarith"),
        practice=Practice(
            prompt="From x < y and y < 3, conclude x < 3.",
            statement="(x y : ℝ) (h₁ : x < y) (h₂ : y < 3) : x < 3",
            hint="One tactic combines the two hypotheses.",
            solution="linarith",
        ),
    ),
    ConceptCard(
        key="calc",
        title="calc — a chain of (in)equalities",
        lean_meaning=(
            "`calc` writes `a = b`, `_ < c`, `_ = d`, … one link per line, each with its "
            "own justification after `:=`, and concludes `a < d`."
        ),
        math_meaning="A displayed chain like |x| ≤ … < … = ε, justified link by link.",
        example_statement="(x : ℝ) (hx : 0 < x) : x < x + x + 1",
        example_proof="calc x = x + 0 := by ring\n  _ < x + x + 1 := by linarith",
        triggers=("calc",),
    ),
    ConceptCard(
        key="by_contra",
        title="by_contra — suppose not",
        lean_meaning=(
            "`by_contra h` assumes the negation of the goal as `h` and asks for a "
            "contradiction. `push_neg at h` rewrites `¬ (x ≤ 0)` into `0 < x`."
        ),
        math_meaning='"Suppose, for a contradiction, that …"',
        example_statement="(x : ℝ) (h : ∀ ε > 0, x < ε) : x ≤ 0",
        example_proof="by_contra hx\npush_neg at hx\nhave h' := h x hx\nlinarith",
        triggers=("by_contra", "by_contra!"),
    ),
    ConceptCard(
        key="by_cases",
        title="by_cases — split into cases",
        lean_meaning=(
            "`by_cases h : P` splits the proof into the case where `P` holds (`h : P`) and "
            "the case where it does not (`h : ¬P`)."
        ),
        math_meaning='"Case 1: n < N. … Case 2: n ≥ N. …"',
        example_statement="(n : ℕ) : n = 0 ∨ 0 < n",
        example_proof="by_cases h : n = 0\n· left\n  exact h\n· right\n  exact Nat.pos_of_ne_zero h",
        triggers=("by_cases",),
    ),
    ConceptCard(
        key="positivity",
        title="positivity — obviously positive",
        lean_meaning=(
            "`positivity` proves goals `0 < e`, `0 ≤ e` or `e ≠ 0` from the shape of `e`: "
            "squares, absolute values, positive constants, sums and products of those."
        ),
        math_meaning='"…which is positive, being a square plus 1."',
        example_statement="(x : ℝ) : 0 ≤ x ^ 2 + |x|",
        example_proof="positivity",
        triggers=("positivity",),
        practice=Practice(
            prompt="Show x² + 1 > 0.",
            statement="(x : ℝ) : 0 < x ^ 2 + 1",
            hint="The shape of the expression makes this automatic.",
            solution="positivity",
        ),
    ),
    ConceptCard(
        key="unfold",
        title="unfold — use the definition",
        lean_meaning=(
            "`unfold D` replaces a defined notion by its definition, e.g. "
            "`SeqConvergesTo a L` by `∀ ε > 0, ∃ N, ∀ n ≥ N, |a n - L| < ε`."
        ),
        math_meaning='"By definition of convergence, we must show: for every ε > 0 …"',
        example_statement="(c : ℝ) : SeqConvergesTo (fun _ => c) c",
        example_proof="unfold SeqConvergesTo\nintro ε hε\nexact ⟨0, fun n _ => by simpa using hε⟩",
        triggers=("unfold",),
    ),
)

ALWAYS_SHOWN = ("theorem", "by")
