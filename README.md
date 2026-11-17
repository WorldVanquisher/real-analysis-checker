# Real Analysis Homework Checker

An AI-assisted proof checker and Lean tutor for undergraduate real analysis.
A student types a problem and their proof; the app formalizes both in
**Lean 4 + Mathlib**, runs the real Lean checker, and explains where and why
verification failed — in language a beginner can follow.

> **Status: Milestone B2 done — real Lean verification works** (file
> assembly, safety screen, runner, output parsing, verdict rules). There is no
> LLM translation or user interface yet. Next up is B3 (student-friendly Lean
> definitions); see [docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md).

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

`pytest` runs the unit tests only; they need no network, API key or Lean.

## Installing Lean 4 and Mathlib

The checker runs real Lean. The Lean project lives in [`lean/`](lean) and pins
Lean `v4.36.0` with Mathlib `v4.36.0`.

1. **Install elan**, Lean's version manager (it puts `lean` and `lake` in
   `~/.elan/bin` and adds that to your PATH).

   Windows (PowerShell):

   ```powershell
   curl.exe -sSfL -o elan-init.ps1 https://raw.githubusercontent.com/leanprover/elan/master/elan-init.ps1
   powershell -NoProfile -ExecutionPolicy Bypass -Command '& .\elan-init.ps1 -NoPrompt $true -DefaultToolchain none'
   Remove-Item elan-init.ps1
   ```

   macOS / Linux:

   ```bash
   curl -sSfL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh | sh -s -- -y --default-toolchain none
   ```

   Open a new terminal afterwards so `lake` is on your PATH.

2. **Download Mathlib and its prebuilt cache** (several GB; the right Lean
   toolchain is installed automatically):

   ```bash
   cd lean
   lake exe cache get
   lake build
   ```

3. **Check the installation** by running the real-Lean tests from the project
   root (about 6 minutes; each check loads Mathlib, about 23 s on a typical
   Windows laptop):

   ```bash
   pytest -m lean
   ```

   To refresh the captured Lean output used by the parser's unit tests (for
   example after upgrading Mathlib), set `RA_CAPTURE_FIXTURES=1` while running
   that command.

The app finds `lake` on your PATH or in `~/.elan/bin`, so step 1's new
terminal is only needed for running `lake` by hand.

## Configuration

Settings come from environment variables, or from a `.env` file in the project
root (copy `.env.example`; `.env` is git-ignored). Real environment variables
win over `.env`. Empty values count as unset.

| Variable | Default | Meaning |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | — | Needed only when the LLM is called; the app starts without it. |
| `RA_CHECKER_MODEL` | `claude-opus-5-5` | Claude model used for parsing, translation and explanations. |
| `RA_LEAN_PROJECT_DIR` | `lean` | Lean project folder; relative paths are resolved from the project root. |
| `RA_LEAN_TIMEOUT_S` | `120` | Wall-clock limit for one Lean run, in seconds (max 3600). |
| `RA_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`. |

Logs never contain the API key: it is redacted, as is anything shaped like an
Anthropic key, including inside error tracebacks.

## Scope

Undergraduate real analysis, starting with sequences and convergence. Typed
input only — no handwriting recognition, no user accounts, no model training.
