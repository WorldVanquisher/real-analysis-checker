# Specification — Advanced Version

Project: **Real Analysis Homework Checker — Advanced Version**.
This is the original requirements document supplied by the project owner. It
extends [SPEC_BASIC.md](SPEC_BASIC.md); the plan is in
[ARCHITECTURE.md](ARCHITECTURE.md) and [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md).

## 1. Project Overview

Extend the Basic Version into an AI-powered mathematical proof checking and
learning assistant. The application should not only check whether a student's
proof can be formally verified using Lean 4, but also help students understand:

* How their mathematical proof is translated into Lean.
* What each part of the generated Lean code means.
* Why a particular proof step is necessary.
* What a Lean error message means.
* How to correct common mistakes.
* How Lean formalization relates to mathematical reasoning.

The target users are undergraduate mathematics students with little or no prior
Lean experience. The goal is to combine automated proof checking with
introductory Lean education.

## 2. All Basic Version Features Must Be Preserved

The advanced version must retain:

1. Mathematical problem input.
2. Student proof input.
3. LLM-based translation into Lean 4.
4. Actual Lean 4 and Mathlib verification.
5. Error localization.
6. Error explanation.
7. Verification result display.

Do not remove or weaken any verification functionality from the Basic Version.

## 3. Advanced Feature A: Lean Code Explanation

After generating Lean code, provide an explanation of the code, divided into
manageable sections. For each important line or block, explain:

1. The meaning of the Lean syntax.
2. Its mathematical meaning.
3. Its role in the proof.
4. Why this step is necessary.

For example, explain concepts such as `theorem`, `intro`, `apply`, `exact`,
`have`, `rw`, `simp`, `constructor`, `rcases`, `by`.

Do not merely translate the code word by word. Explain how the Lean code
corresponds to the student's original mathematical reasoning.

## 4. Advanced Feature B: Mathematical Proof Mapping

Show the relationship between the student's original proof and the generated
Lean proof. For example:

| Original mathematical reasoning | Corresponding Lean code |
| --- | --- |
| Let epsilon be positive. | `intro ε hε` |
| Since the sequence converges, use the definition of convergence. | Apply the relevant convergence definition or theorem. |
| Establish the required inequality. | Use the corresponding Lean inequality proof. |

The correspondence must be based on the actual generated proof. Do not invent a
correspondence if the student's proof has been substantially transformed by the
LLM. Clearly indicate any proof steps that have been added, omitted, or changed
during formalization.

## 5. Advanced Feature C: Interactive Lean Learning

Add a beginner-friendly Lean learning section. It should provide:

* A short explanation of important Lean concepts used in the current proof.
* Simple examples of relevant syntax.
* The mathematical ideas behind the syntax.
* A short practice question where appropriate.

The learning content should be contextual. For example, if the current proof
uses `intro`, explain how `intro` introduces assumptions or variables into the
proof context. If it uses `rw`, explain rewriting and how it relates to
mathematical equality. Do not overwhelm beginners with advanced Lean theory.

## 6. Advanced Feature D: Enhanced Error Explanation

When verification fails, provide a structured explanation:

1. Error location.
2. Original Lean error message.
3. Simplified explanation.
4. Mathematical interpretation, if applicable.
5. Relevant Lean concept.
6. Suggested correction.
7. A corrected code example, if possible.

Distinguish clearly between:

* Mathematical errors.
* Missing assumptions.
* Incomplete proofs.
* Incorrect theorem application.
* Syntax errors.
* Type errors.
* Unresolved goals.

If the problem is caused by incorrect formalization rather than the student's
original mathematics, state that explicitly. Never present a guessed correction
as a verified solution. Any corrected code must be run through Lean before being
labelled verified.

## 7. Advanced Feature E: Learning Mode

Add an optional learning mode that students can enable or disable.

When enabled:

* Show Lean code explanations.
* Explain unfamiliar syntax.
* Highlight important proof steps.
* Provide short contextual tutorials.
* Offer hints before revealing a complete correction.

When disabled:

* Show only the verification result and concise feedback.

The interface should allow students to choose between:

1. Quick Check Mode.
2. Learning Mode.

## 8. Technical Requirements

Retain the Basic Version technologies: Python, Streamlit, Lean 4 + Mathlib, an
LLM API, Git.

Use a modular design. Consider separate modules for:

1. Mathematical input processing.
2. Lean translation.
3. Lean verification.
4. Error analysis.
5. Lean code explanation.
6. Interactive learning content.
7. User interface.

Use structured LLM outputs wherever possible. Avoid asking the LLM to generate
all explanations in a single unstructured response. The explanation module must
use the actual Lean code and verification results as context.

## 9. Reliability and Evaluation

Build a test set containing:

* Correct mathematical proofs.
* Incorrect proofs.
* Incomplete proofs.
* Proofs with missing assumptions.
* Proofs that are mathematically correct but difficult to formalize.
* Cases where the LLM incorrectly translates the original problem.

Evaluate:

1. Lean compilation success rate.
2. Accuracy of the formalized proposition.
3. Accuracy of error localization.
4. Quality of error explanations.
5. Correctness of Lean code explanations.
6. Usefulness of the learning content.

A successful Lean compilation alone must not be treated as proof that the
original student solution was correctly understood.

## 10. Expected Deliverable

A functional AI-powered real analysis learning assistant that allows students
to:

1. Submit a mathematical problem and their solution.
2. Receive a formalized Lean 4 representation.
3. Check the proof using Lean.
4. Locate and understand possible errors.
5. Read an explanation of the generated Lean code.
6. Learn the basic Lean concepts used in the proof.
7. Choose whether to use Quick Check Mode or Learning Mode.

The advanced version should remain focused on undergraduate real analysis rather
than becoming a general-purpose mathematical theorem prover. Develop it
incrementally on top of the Basic Version, preserving existing functionality and
tests.
