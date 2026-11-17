# Real Analysis Homework Checker

An AI-assisted proof checker and Lean tutor for undergraduate real analysis.
A student types a problem and their proof; the app formalizes both in
**Lean 4 + Mathlib**, runs the real Lean checker, and explains where and why
verification failed — in language a beginner can follow.

> **Status: Milestone B0 — architecture and scaffold.** No checking features
> are implemented yet. Next up is B1 (config, data models, logging); see
> [docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md).

## How it will work

1. **Input** — the student types the problem and their proof (plain text and
   standard math notation).
2. **Understand** — an LLM extracts hypotheses, the goal, and the proof's steps.
   Ambiguous problems trigger a clarification question instead of guesses.
3. **Formalize the statement** — the Lean statement is shown next to the
   original, with a plain-English back-translation, and the student confirms it.
4. **Translate the proof** — the LLM writes the proof steps in Lean; Python
   assembles the file around the confirmed statement.
5. **Verify** — real Lean + Mathlib checks the file (with a timeout, in a
   controlled environment).
6. **Explain** — on failure, the error is located to a step of the student's
   proof, classified, and explained, with a direction for fixing it.

The advanced version adds a Learning Mode: Lean code explanations, a mapping
between the student's proof and the Lean proof, contextual Lean lessons with
practice questions, and Lean-verified corrections.

## Design principles

* **Lean decides, not the LLM.** Only a real Lean run can produce a
  "Verified" result.
* **Compiling is not the same as being right.** The app reports separately
  whether Lean accepted the formal proof and whether the formalization follows
  what the student wrote. It never says "your proof is correct".
* **No silent changes to the problem.** The student confirms the formal
  statement before it is locked.
* **Honest uncertainty.** When the app cannot tell what went wrong
  mathematically, it says so.

## Documents

* [Basic specification](docs/SPEC_BASIC.md)
* [Advanced specification](docs/SPEC_ADVANCED.md)
* [Architecture](docs/ARCHITECTURE.md)
* [Development plan, risks and dependencies](docs/DEVELOPMENT_PLAN.md)

## Development setup (current state)

Requires Python 3.11 or newer.

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -e ".[dev]"
pytest
```

Lean 4, Mathlib and the LLM API key are needed from milestones B2 and B4
onwards; installation instructions will be added here when those milestones
land. API keys are read from environment variables only (see `.env.example`).

## Scope

Undergraduate real analysis, starting with sequences and convergence. Typed
input only — no handwriting recognition, no user accounts, no model training.
