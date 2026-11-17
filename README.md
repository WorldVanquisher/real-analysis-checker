# Real Analysis Homework Checker

An AI-assisted proof checker and Lean tutor for undergraduate real analysis.
A student types a problem and their proof; the app formalizes both in
**Lean 4 + Mathlib**, runs the real Lean checker, and explains where and why
verification failed — in language a beginner can follow.

> **Status: `v0.1.0` — the basic version and the advanced features work end
> to end with the real Claude API and real Lean.** On the 20-case evaluation
> set: 0 false verifications, every case got its expected outcome, every
> generated proof compiled, and every mistake was located at the right step.
> Results and the fixes the first live run led to are in
> [docs/DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md#first-live-run-2026-11-17-claude-opus-5-5-leanmathlib-v4360).

## How it works

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

A **Quick Check / Learning Mode** switch chooses how much is shown. Learning
Mode adds:

* a side-by-side mapping of each of your steps to its Lean code, built from
  the code itself and flagged when the translation departs from your proof;
* a block-by-block explanation of the Lean code (Lean syntax, mathematical
  meaning, role, why it is needed), withheld if it mentions anything the code
  does not use;
* error cards with a hint, then the mathematical interpretation, then a
  corrected proof — labelled "Verified by Lean" only if Lean accepts it;
* short Lean lessons for exactly the tactics your proof uses, with practice
  questions checked by Lean.

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
* [Demo script](docs/DEMO.md) — five paste-ready inputs covering every result
* [Evaluation rubric](eval/RUBRIC.md) — how to grade an evaluation run

## Project layout

```text
src/ra_checker/
  config.py, models.py, logging_setup.py, input_validation.py
  llm/          Claude client (structured outputs) and versioned prompts
  parsing/      stage 1: read the problem, split the proof into steps
  translation/  stage 2: formal statement, then the tagged Lean proof
  lean/         file assembly, safety screen, runner, output parser
  analysis/     error classification, localization, explanations, corrections
  report/       verdict rules (Lean only), wording, reasoning ↔ Lean mapping
  explain/      block-by-block Lean code explanation
  learning/     concept cards, detection, Lean-checked practice
  pipeline.py   two-phase Checker: formalize → student confirms → verify
  setup.py      builds the real Checker (Claude + local Lean)
  evaluation.py evaluation harness and metrics
  ui/           Streamlit app
lean/           Lean project: RaChecker definitions + bridges to Mathlib
eval/           evaluation cases, runner (python eval/run_eval.py --yes), rubric
tests/
  unit/         no Lean, no network (fakes for the LLM and Lean)
  lean/         real Lean + Mathlib
  llm/          live Claude API (opt-in)
  fixtures/     real Lean output, Lean-verified reference exercises
```

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

2. **Download Mathlib and its prebuilt cache, then build the checker's own
   Lean library** (several GB, about 12 minutes on a home connection; the right
   Lean toolchain is installed automatically):

   ```bash
   cd lean
   lake exe cache get
   lake build
   lake build repl
   ```

   The last command builds the Lean REPL, which lets the app keep Mathlib
   loaded between checks: a check's Lean step then takes well under a second
   instead of about 25 s. Without it the app still works, starting Lean for
   every check.

3. **Check the installation** by running the real-Lean tests from the project
   root (34 tests, about 20 minutes; each check loads Mathlib, about 22–30 s
   on a typical Windows laptop):

   ```bash
   pytest -m lean
   ```

   To refresh the captured Lean output used by the parser's unit tests (for
   example after upgrading Mathlib), set `RA_CAPTURE_FIXTURES=1` while running
   that command.

The app finds `lake` on your PATH or in `~/.elan/bin`, so step 1's new
terminal is only needed for running `lake` by hand.

## Running the app

After installing Lean and Mathlib (above) and setting `ANTHROPIC_API_KEY`
(see Configuration), start the app from the project root:

```bash
streamlit run src/ra_checker/ui/app.py
```

It opens in your browser. Type the problem and your proof, press **Formalize
the statement**, check that the Lean statement says what the problem says, and
press **Yes, it matches — check my proof**. With the Lean REPL built, Lean's
part of a check takes well under a second (most of the time is Claude reading
and translating); without it, each check also waits about 25 s for Lean to load
Mathlib. If something is missing (API key, Lean, Mathlib), the app says what
and disables checking.

Right after a computer restart, Lean's first run has to read all of Mathlib
from disk, which took about 7 minutes on the development machine. The app
starts this in the background as soon as it opens and shows a notice; a check
started meanwhile simply waits until Lean is ready.

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
| `RA_LLM_TIMEOUT_S` | `300` | Time limit for one LLM request, in seconds (max 1800). |
| `RA_LEAN_RUNNER` | `auto` | `auto`: keep Mathlib loaded in the Lean REPL if it is built, otherwise start Lean per check; `repl`: require the REPL; `cli`: always start Lean per check. |
| `RA_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`. |

Logs never contain the API key: it is redacted, as is anything shaped like an
Anthropic key, including inside error tracebacks. They also never contain the
student's text — only its length and a hash.

The LLM is Claude, via the official `anthropic` SDK. For models that support
it, Claude's server-side refusal fallback is switched on: if the chosen model
declines a request, the API answers with a fallback model instead, and the
report records which model actually answered.

## Tests

```bash
pytest            # 383 unit tests: no network, no API key, no Lean (~15 s)
pytest -m lean    # 34 real Lean + Mathlib tests (~20 min; last run 19 min 8 s)
pytest -m llm     # live Claude API calls: needs ANTHROPIC_API_KEY and costs money
```

The real-Lean tests cover the verdict rules on real output (including unsound
tricks such as `native_decide` and an injected axiom), timeouts, the 8
reference exercises, the translation and repair stages, error localization,
the whole pipeline with a stand-in LLM, corrections (verified only when Lean
accepts them), every concept-card example and practice solution, and the
evaluation set's reference statements.

## Evaluation

`eval/cases.toml` holds 20 cases across the spec's categories — correct,
incorrect, incomplete, missing assumptions, hard to formalize, likely to be
mistranslated — plus ambiguous and out-of-scope inputs. With an API key:

```bash
python eval/run_eval.py --yes
```

It runs every case through the real Claude API and Lean (it refuses without
`--yes`, because it costs API usage), prints the automatic metrics — false
verifications (must be zero), status accuracy, Lean compile rate, statement
match, error localization, explanation grounding — and writes
`eval/results/<timestamp>/` with a `grading.csv` for the human-graded metrics
(see [eval/RUBRIC.md](eval/RUBRIC.md)). Use `--category` or `--case` to run a
subset.

## Scope

Undergraduate real analysis, starting with sequences and convergence. Typed
input only — no handwriting recognition, no user accounts, no model training.
