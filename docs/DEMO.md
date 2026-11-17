# Demo script

Five inputs that show every kind of result. Start the app with
`streamlit run src/ra_checker/ui/app.py` (Lean, Mathlib and
`ANTHROPIC_API_KEY` must be set up — see the README), paste the problem and
proof, press **Formalize the statement**, then **Yes, it matches — check my
proof**.

The *expected* column describes what the checker is designed to do. LLM
answers vary between runs, so wording and step splits will differ; the status
is what to look at. Record what actually happened when you run the demo.

## 1. A correct proof → Lean accepts the formal proof

**Problem**

```text
Suppose a_n → A and b_n → B. Prove that a_n + b_n → A + B.
```

**Proof**

```text
Let ε > 0. Since a_n → A, there is N₁ with |a_n − A| < ε/2 for all n ≥ N₁.
Since b_n → B, there is N₂ with |b_n − B| < ε/2 for all n ≥ N₂.
Let N = max(N₁, N₂). For n ≥ N, by the triangle inequality
|a_n + b_n − (A + B)| ≤ |a_n − A| + |b_n − B| < ε/2 + ε/2 = ε.
```

**Expected:** the formal statement uses `SeqConvergesTo`; after confirming,
*"Lean accepted the formalized proof."* with every step "translated as
written". (A hand-written formalization of exactly this exercise is verified
by Lean in the test suite.)

## 2. A wrong proof → Lean rejects it and points at the step

Same problem as 1, with ε instead of ε/2:

```text
Let ε > 0. Since a_n → A, there is N₁ with |a_n − A| < ε for all n ≥ N₁.
Since b_n → B, there is N₂ with |b_n − B| < ε for all n ≥ N₂.
Let N = max(N₁, N₂). For n ≥ N, by the triangle inequality
|a_n + b_n − (A + B)| ≤ |a_n − A| + |b_n − B| < ε.
```

**Expected:** *"Lean did not accept the formalized proof."* The error card
points at the last step (the estimate only gives 2ε), shows Lean's
`linarith failed` message, and gives a direction marked "not checked by
Lean". (With real Lean, the test suite locates this exact mistake at that
step.)

## 3. An incomplete proof → the gap is reported

```text
Problem: Prove that every convergent sequence of real numbers is bounded.
Proof:   Let a_n → L. Then the terms eventually stay close to L, so the
         sequence is bounded.
```

**Expected:** either Lean rejects the formal proof with an unresolved goal,
or the translation is reported as incomplete (a step left as a placeholder).
It must not be accepted: "eventually close" does not bound the first N terms.

## 4. An ambiguous problem → a clarification question

```text
Problem: Prove that the sequence converges.
Proof:   It is decreasing and bounded below, so it converges.
```

**Expected:** *"We need a clarification before checking."* with a question
about which sequence is meant. Nothing is sent to Lean.

## 5. An out-of-scope problem → declined honestly

```text
Problem: Prove that the integral of x² from 0 to 1 equals 1/3.
Proof:   By the fundamental theorem of calculus it equals 1³/3 − 0³/3 = 1/3.
```

**Expected:** the checker says the problem is outside what it currently
supports (sequences of real numbers). Nothing is sent to Lean.

## What to look for in every run

* The formal statement is shown next to the original **before** anything is
  checked, with a plain-English reading.
* "Verified" appears only after Lean ran; the wording always speaks of the
  *formal* proof.
* Steps the translator added, changed or could not translate are listed.
* When the cause of a failure is unclear, the app says so instead of guessing.
