# Development Plan

One milestone at a time. Each milestone ends with: what was implemented, which
tests ran and their real output, known errors and limitations. A milestone is
not "done" until its acceptance criteria are met by tests that actually ran.

Status legend: ✅ done · ⏳ next · ⬜ planned

## Basic version (MVP)

### ✅ B0 — Repository, architecture, scaffold

* Files: `README.md`, `AGENTS.md`, `docs/*`, `pyproject.toml`, `.gitignore`,
  `.env.example`, `src/ra_checker/__init__.py`, `tests/test_package.py`.
* Accept: package installs in a venv; `pytest` passes; repo pushed to GitHub.

### ⏳ B1 — Config, data models, logging

* Files: `src/ra_checker/config.py`, `models.py`, `logging_setup.py`,
  `tests/unit/test_config.py`, `tests/unit/test_models.py`.
* Adds dependencies: `pydantic`, `python-dotenv`.
* Accept: missing API key produces a clear error only when the LLM is used (not
  at import); models round-trip to JSON; `VERIFIED` cannot be constructed
  without a Lean run attached (enforced by a model validator); logs never contain
  the key.

### ⬜ B2 — Lean environment, runner, diagnostics, safety, verdict

* Install: elan (Lean version manager), the pinned Lean toolchain, Mathlib cache
  (`lake exe cache get`, several GB).
* Files: `lean/lean-toolchain`, `lean/lakefile.toml`, `lean/RaChecker.lean`,
  `src/ra_checker/lean/{assemble,safety,runner,diagnostics}.py`,
  `src/ra_checker/report/verdict.py`, `tests/unit/test_{assemble,safety,diagnostics,verdict}.py`,
  `tests/lean/test_runner_real.py`, `tests/fixtures/lean_output/*.txt`.
* Accept: known-good snippet → `VERIFIED`; snippets with an error, an unsolved
  goal, a `sorry`, and `native_decide` → not verified with the right reason;
  deny-listed code never reaches Lean; a deliberately slow snippet hits the
  timeout and leaves no Lean process running; measured cold/warm run time is
  reported.

### ⬜ B3 — Student-friendly Lean definitions + reference cases

* Files: `lean/RaChecker/Defs.lean` (sequence convergence, boundedness,
  Cauchy, …), `lean/RaChecker/Bridge.lean` (equivalence proofs to Mathlib),
  `tests/fixtures/reference_proofs/*.lean` (hand-written proofs of 5–8 target
  exercises, e.g. `1/n → 0`, sum of limits, uniqueness of limits, convergent ⇒
  bounded, squeeze theorem).
* Accept: all bridge lemmas and reference proofs compile with no `sorry` and
  only standard axioms, via the B2 runner.

### ⬜ B4 — LLM client + problem parsing

* Adds dependency: `anthropic`.
* Files: `src/ra_checker/llm/{client,prompts}`, `src/ra_checker/input/`,
  `src/ra_checker/parsing/problem_parser.py`, `tests/unit/test_parser.py`
  (fake LLM), `tests/llm/test_parser_live.py` (opt-in).
* Accept: structured output validated by Pydantic; an ambiguous problem yields
  `NEEDS_CLARIFICATION` with questions; an out-of-scope problem is flagged;
  API failure → `RUNTIME_ERROR`; refusal → `TRANSLATION_FAILED`.

### ⬜ B5 — Lean translation (statement, then proof)

* Files: `src/ra_checker/translation/{statement,proof}.py`, prompts, tests.
* Accept: statement is elaborated with `sorry` before it is shown; proof
  translation cannot change the locked statement (assembly test); every tactic
  block carries `-- [Sk]` tags; untranslatable steps become explicit
  placeholders, never silent omissions; bounded repair loop for Lean-side errors
  only, recorded in the report.

### ⬜ B6 — Error analysis

* Files: `src/ra_checker/analysis/{classify,locate,explain}.py`, tests with
  captured Lean output.
* Accept: classifier covers the fixture messages; locator maps every fixture
  error to the right step; guardrails force `origin=formalization` for syntax /
  unknown identifier; low confidence renders as "cannot confidently identify".

### ⬜ B7 — Pipeline + Streamlit UI

* Adds dependency: `streamlit`.
* Files: `src/ra_checker/pipeline.py`, `src/ra_checker/ui/{app,components}.py`,
  `tests/unit/test_pipeline.py`, `tests/ui/test_app.py` (AppTest with fakes).
* Accept: the two-phase flow works end to end with fakes; one real end-to-end
  run (real LLM + real Lean) on a reference case is performed and recorded; all
  eight Feature E fields are displayed.

### ⬜ B8 — Basic release

* README installation guide (Windows first, then macOS/Linux notes), test case
  set, demo script; tag `v0.1.0`.

## Advanced version

Every advanced milestone keeps all B tests green; none may weaken verification.

| Milestone | Scope | Key acceptance |
| --- | --- | --- |
| ⬜ A1 | Quick Check / Learning mode toggle and plumbing | Quick mode output unchanged from B7. |
| ⬜ A2 | Lean code explanation, per tagged block, grounded in the actual code and verdict | Explanations reference only identifiers present in the code (checked). |
| ⬜ A3 | Proof mapping table | Added/omitted flags computed from tags, not LLM claims; "changed" judgments labelled as LLM-assessed. |
| ⬜ A4 | Enhanced 7-part error explanation + corrected code | A correction is labelled "Verified by Lean" only after passing §3 rules; otherwise "Unverified suggestion". |
| ⬜ A5 | Contextual learning cards + practice questions | Cards selected by tactics detected in code; every card example and practice answer is compiled by Lean in tests. |
| ⬜ A6 | Hints-before-correction ladder in learning mode | Correction hidden until hints are requested. |
| ⬜ A7 | Evaluation set and harness | Report covers the six spec metrics; human rubric documented. |
| ⬜ A8 | Optional hardening: Lean in a no-network Docker container; persistent Lean REPL for speed | Same results as local runner on the eval set. |

## Technical risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Lean + Mathlib install on Windows (several GB, long download, version pinning) | Blocks B2 | Pin toolchain + Mathlib; use `lake exe cache get`; project path is ASCII-only and short. |
| Mathlib import latency and RAM per check | Slow UX | Measure in B2; narrower imports; later a persistent REPL (A8). |
| LLM changes the problem into an easier statement | False "verified" | Student confirmation, back-translation, locked statement assembled by Python, `assumptions_added` shown. |
| LLM "repairs" a wrong student proof while translating | False "verified" | Step tags, fidelity summary, headline never says "your proof is correct", repair loop limited to Lean-side errors. |
| Hallucinated or outdated Mathlib lemma names | Low compile rate | Curated `RaChecker` definitions and lemma hints in prompts; bounded repair loop. |
| Compile-time code execution in Lean | Security | No LLM-written imports/commands, deny-list, axioms check, timeout, temp dir; optional Docker (A8). |
| Distinguishing Lean errors from mathematical errors is inherently uncertain | Misleading feedback | Explicit `origin` + `confidence`, code guardrails, raw message always shown. |
| API cost and latency (several calls per check) | Cost | Small structured calls, prompt caching, live tests opt-in only. |
| Windows subprocess timeouts leave child processes | Resource leak | Kill the whole process tree; tested in B2. |

## Dependencies

* Python ≥ 3.11 (dev machine: 3.13.1).
* Python packages (added when first needed): `pydantic`, `python-dotenv`,
  `anthropic`, `streamlit`, `pytest`.
* Lean 4 via elan, Mathlib (pinned at B2).
* An Anthropic API key in `ANTHROPIC_API_KEY`.

## Open decisions for the owner

1. Approve installing elan + Lean + Mathlib (several GB under the user profile)
   at B2.
2. Confirm Anthropic Claude as the LLM provider and provide an API key before
   B4 live tests.
3. First topic set: sequences and convergence (proposed list in B3).
