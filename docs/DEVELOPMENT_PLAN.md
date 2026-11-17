# Development Plan

One milestone at a time. Each milestone ends with: what was implemented, which
tests ran and their real output, known errors and limitations. A milestone is
not "done" until its acceptance criteria are met by tests that actually ran.

Status legend: ✅ done · 🟡 built, a live check is still pending · ⏳ next ·
⬜ planned

## Basic version (MVP)

### ✅ B0 — Repository, architecture, scaffold

* Files: `README.md`, `AGENTS.md`, `docs/*`, `pyproject.toml`, `.gitignore`,
  `.env.example`, `src/ra_checker/__init__.py`, `tests/test_package.py`.
* Accept: package installs in a venv; `pytest` passes; repo pushed to GitHub.

### ✅ B1 — Config, data models, logging

* Files: `src/ra_checker/config.py`, `models.py`, `logging_setup.py`,
  `tests/unit/test_config.py`, `tests/unit/test_models.py`,
  `tests/unit/test_logging_setup.py`.
* Adds dependencies: `pydantic`, `python-dotenv`.
* Accept: missing API key produces a clear error only when the LLM is used (not
  at import); models round-trip to JSON; `VERIFIED` cannot be constructed
  without a Lean run attached (enforced by a model validator); logs never contain
  the key.
* Result: 63 unit tests pass (`pytest -W error`). `CheckReport` rejects
  `VERIFIED` without a completed, error-free Lean run of the student-confirmed
  statement, a proof translation and a fidelity summary — also when loaded from
  JSON. Logging redacts registered secrets and `sk-ant-…` keys, including in
  tracebacks.
* Limitations: the statement check in the model is a substring test; the exact
  match, `sorry` and axiom rules arrive with `report/verdict.py` in B2. Logging
  is console-only; a log file can be added if needed.

### ✅ B2 — Lean environment, runner, diagnostics, safety, verdict

* Install: elan (Lean version manager), the pinned Lean toolchain, Mathlib cache
  (`lake exe cache get`, several GB).
* Files: `lean/lean-toolchain`, `lean/lakefile.toml`, `lean/lake-manifest.json`,
  `lean/RaChecker.lean`, `src/ra_checker/lean/{assemble,safety,runner,diagnostics}.py`,
  `src/ra_checker/report/verdict.py`,
  `tests/unit/test_{assemble,safety,runner,diagnostics,verdict}.py`,
  `tests/lean/{conftest,lean_cases,test_lean_real}.py`,
  `tests/fixtures/lean_output/*.txt`.
* Accept: known-good snippet → `VERIFIED`; snippets with an error, an unsolved
  goal, a `sorry`, and `native_decide` → not verified with the right reason;
  deny-listed code never reaches Lean; a deliberately slow snippet hits the
  timeout and leaves no Lean process running; measured cold/warm run time is
  reported.
* Result: elan 4.2.4; Lean and Mathlib pinned to `v4.36.0` (Mathlib commit
  `fc4f59e`). First setup took 11.7 min (9 117 cache files). 144 unit tests
  (`pytest -W error`) and 13 real-Lean tests (`pytest -m lean`) pass: two
  verified proofs; unsolved goals, type mismatch, unknown identifier, syntax
  error and `linarith` failure → `VERIFICATION_FAILED`; `sorry` →
  `TRANSLATION_FAILED`; `native_decide` and an injected `axiom`, run with the
  safety screen deliberately bypassed, → `VERIFICATION_FAILED` via the axiom
  check; a 2 s timeout leaves no `lean.exe` behind.
* Found by the real-Lean tests and fixed: Lean's default `autoImplicit` turned
  an unknown name in a statement into a new variable, so a wrong statement
  type-checked. The assembled header and the lakefile now set
  `autoImplicit false`. Also: `#print axioms` prints a bare line (no
  `file:line:col` header), and `sorryAx` appears after any error, so
  placeholders are detected from the ``declaration uses `sorry` `` warning.
* Timing on the dev machine (Windows, warm cache): one check takes about
  23 s with `import Mathlib`, 15.5 s with `Mathlib.Tactic` +
  `Mathlib.Analysis.SpecificLimits.Basic`, 12 s with only the latter — the cost
  is almost entirely the import. Kept `import Mathlib` for now (a missing
  import would show up as a false "unknown identifier"); revisit with the B3/B5
  reference proofs, and A8's persistent Lean process removes the import cost.
* Limitations: the safety screen is a deny-list, not a sandbox (A8 adds
  Docker). Errors reported on the theorem line itself (e.g. unsolved goals at
  `by`) need special handling in B6's locator.

### ✅ B3 — Student-friendly Lean definitions + reference cases

* Files: `lean/RaChecker/Defs.lean` (sequence convergence, boundedness,
  Cauchy, …), `lean/RaChecker/Bridge.lean` (equivalence proofs to Mathlib),
  `tests/fixtures/reference_cases.toml` (hand-written, tagged formalizations of
  target exercises), `tests/unit/test_reference_cases.py`,
  `tests/lean/test_reference_cases_lean.py`, `.gitattributes`.
* Accept: all bridge lemmas and reference proofs compile with no `sorry` and
  only standard axioms, via the B2 runner.
* Result: five definitions (`SeqConvergesTo`, `SeqConverges`, `SeqBounded`,
  `SeqCauchy`, `SeqTendsToInfinity`), each with a bridge lemma to Mathlib, all
  built by `lake build` with no `sorry`. Eight reference exercises — constant
  sequence, `1/(n+1) → 0`, sum of limits, uniqueness of limits, convergent ⇒
  bounded, squeeze theorem, constant multiple, convergent ⇒ Cauchy — each
  `VERIFIED` through the app's own assemble → run → parse → verdict path with
  no diagnostics at all. Assembled files now `import RaChecker` and
  `open RaChecker`; an error on a header line is classified `RUNTIME_ERROR`
  ("environment not set up, run `lake build`"), never as a proof error.
  178 unit tests and 21 real-Lean tests pass; a check still takes about 23 s.
* Limitations: Lean warns that `Mathlib` "is designed for use with the module
  system"; harmless, adopting Lean's module system is not needed yet. The
  reference proofs prefer `abs_lt` + `linarith` to named triangle-inequality
  lemmas, whose names change between Mathlib versions — a useful hint for the
  B5 prompts. Only sequences are covered so far.

### 🟡 B4 — LLM client + problem parsing

* Adds dependency: `anthropic`.
* Files: `src/ra_checker/llm/{client,prompts}.py`,
  `src/ra_checker/input_validation.py`, `src/ra_checker/parsing/problem_parser.py`,
  `tests/unit/test_{llm_client,problem_parser,input_validation}.py` (fake LLM),
  `tests/llm/{conftest,test_parser_live}.py` (opt-in).
* Accept: structured output validated by Pydantic; an ambiguous problem yields
  `NEEDS_CLARIFICATION` with questions; an out-of-scope problem is flagged;
  API failure → `RUNTIME_ERROR`; refusal → `TRANSLATION_FAILED`.
* Result: 211 unit tests pass. `AnthropicClient` uses the SDK's
  `beta.messages.parse` with a Pydantic `output_format`, an explicit effort
  (parsing runs at `medium`) and Claude's server-side refusal fallback
  (`fallbacks="default"`) for models that support it; the model that actually
  served the answer is recorded. Every SDK error maps to `LLMUnavailableError`
  (→ `RUNTIME_ERROR`) without chaining the SDK error or leaking the key; a
  refusal raises `LLMRefusalError` and a truncated or off-schema answer
  `LLMOutputError` (both → `TRANSLATION_FAILED`; the mapping to report statuses
  is wired in B7). The parser numbers steps itself, marks any step that is not
  a verbatim excerpt of the student's proof (`ProofStep.verbatim`), turns a
  missing goal or an empty step list into clarification questions, keeps
  student text out of the logs, and stops student text from closing the
  prompt's delimiting tags. New setting `RA_LLM_TIMEOUT_S` (default 300 s).
* Pending: the three live tests (`pytest -m llm`) have not run, because no
  Anthropic API key is configured on the development machine. They check a
  reference problem (in scope, verbatim steps, no questions), an
  out-of-scope problem and an ambiguous one.

### 🟡 B5 — Lean translation (statement, then proof)

* Files: `src/ra_checker/translation/{__init__,statement,proof}.py`,
  `src/ra_checker/analysis/classify.py` (pulled forward from B6 for the repair
  loop), prompts in `llm/prompts.py`, `tests/unit/test_{classify,prompts,
  translation_statement,translation_proof}.py`, `tests/unit/translation_helpers.py`,
  `tests/lean/test_translation_lean.py`.
* Accept: statement is elaborated with `sorry` before it is shown; proof
  translation cannot change the locked statement (assembly test); every tactic
  block carries `-- [Sk]` tags; untranslatable steps become explicit
  placeholders, never silent omissions; bounded repair loop for Lean-side errors
  only, recorded in the report.
* Result: 257 unit tests and 5 new real-Lean tests pass. Statement stage: the
  LLM drafts binders and goal plus a back-translation and any conventions it
  had to choose; the draft must pass the safety screen and type-check in Lean,
  with up to 2 repairs fed by the real errors; the result is never
  pre-confirmed. Proof stage: refuses an unconfirmed statement; step statuses
  are reconciled with the tags actually in the code (untagged → `omitted`,
  `sorry`-only → `omitted` as a placeholder, `-- [Ak]` → `added`, leading
  untagged code is labelled as an added step); inconsistent tags and safety
  violations fail before Lean runs and are never repaired; repair runs only when
  every error is a syntax error or unknown name, at most twice, and is rejected
  unless it keeps the same tags and the same number of placeholders. Real-Lean
  checks: the prompt's worked example compiles; a statement with a misspelled
  definition is repaired; the `sum_of_limits` reference proof translates to
  `VERIFIED`; a made-up lemma name is repaired in one round; an ε-instead-of-ε/2
  mistake is reported (`linarith failed`) and not repaired. Every attempt is
  recorded (`StatementAttempt`, `ProofAttempt`).
* Pending: prompt quality against the real model — needs an API key (live
  tests to be added with B7's end-to-end run). Not yet done: a vacuity check
  that the formal hypotheses are not contradictory.

### 🟡 B6 — Error analysis

* Files: `src/ra_checker/analysis/{classify,locate,explain}.py`, explanation
  prompt in `llm/prompts.py`, `tests/unit/test_error_analysis.py`,
  `tests/lean/test_error_analysis_lean.py`.
* Accept: classifier covers the fixture messages; locator maps every fixture
  error to the right step; guardrails force `origin=formalization` for syntax /
  unknown identifier; low confidence renders as "cannot confidently identify".
* Result: 274 unit tests and 2 new real-Lean tests pass. The locator scans the
  assembled file's tags, so it uses exactly the code Lean checked; errors Lean
  reports on the theorem line ("unsolved goals" at `by`) are attributed to the
  last step with `at_end_of_proof`. Syntax errors and unknown names get a fixed
  "problem with the translation, not with your mathematics" explanation and no
  LLM call. Otherwise the LLM proposes category, origin, confidence,
  explanation and a hint, and guardrails correct it: errors in translator-added
  steps are formalization errors; a self-contradictory answer becomes
  `undetermined`/`low`; a `formalization` origin cannot carry a student
  category; a high-confidence blame on a step the translator `changed` or
  `omitted` drops to `medium`. If the LLM is unavailable, an honest rule-based
  `undetermined`/`low` explanation is used. `ErrorAnalysis.confident` tells the
  UI when to say the cause could not be confidently identified (rendering is
  B7). At most 3 errors per check are analysed. Real Lean: the
  ε-instead-of-ε/2 mistake is located at S5 (the final estimate); an open goal
  at the end of a proof is attributed to the last step with the goal passed on.
* Pending: explanation quality against the real model (API key).

### 🟡 B7 — Pipeline + Streamlit UI

* Adds dependency: `streamlit`.
* Files: `src/ra_checker/pipeline.py`, `src/ra_checker/report/presentation.py`,
  `src/ra_checker/ui/{app,components,services}.py`,
  `tests/unit/test_{pipeline,presentation,ui_app}.py`,
  `tests/unit/pipeline_helpers.py`, `tests/lean/test_pipeline_lean.py`,
  `.claude/launch.json` (local, git-ignored).
* Accept: the two-phase flow works end to end with fakes; one real end-to-end
  run (real LLM + real Lean) on a reference case is performed and recorded; all
  eight Feature E fields are displayed.
* Result: 300 unit tests and 2 new real-Lean tests pass. `Checker.formalize`
  (parse → formalize statement) returns a `PendingCheck` or a final report;
  `Checker.verify` refuses an unconfirmed statement, then translates, runs
  Lean, analyses failures and builds a `CheckReport` (re-validated by the
  model). `report/presentation.py` words every headline deterministically:
  Lean's acceptance always applies to "the formal proof", unfaithful
  translations name the departing steps, low confidence says "We cannot
  confidently identify the mathematical error", and no headline calls the
  student's proof correct (tested for every status). The Streamlit app is
  driven headlessly by `AppTest` through the full flow, clarification,
  failure, input-error, edit and not-ready paths; it shows original problem,
  student proof, formal statement with back-translation, generated Lean code,
  verification result, error location, explanation with the raw Lean message,
  and a suggested direction labelled "not checked by Lean", plus the step
  mapping. With real Lean and a stand-in LLM, the `sum_of_limits` exercise goes
  formalize → confirm → `VERIFIED`, and its ε-error variant fails with the
  explanation at S5. The live app was started and checked in a browser: it
  finds Lean and Mathlib and reports the missing API key, with checking
  disabled. Fixed during testing: "No — I'll clarify" left the statement on
  screen until the next interaction.
* Pending: the real end-to-end run with the real LLM (needs an API key).

### 🟡 B8 — Basic release

* README installation guide (Windows first, then macOS/Linux notes), test case
  set, demo script; tag `v0.1.0`.
* Done: README installation guide (Windows and macOS/Linux), running the app,
  configuration, project layout and test summary; `docs/DEMO.md` with five
  paste-ready inputs (correct, wrong, incomplete, ambiguous, out of scope);
  test set — 300 unit tests, 30 real-Lean tests, 8 Lean-verified reference
  exercises, 3 live-LLM tests.
* Held back on purpose: the `v0.1.0` tag. No LLM stage has run against the
  real Claude API yet, so the release waits for: `pytest -m llm`, the five
  demo inputs run in the app with the outcomes recorded in `docs/DEMO.md`, and
  any prompt fixes those runs require.

## Advanced version

Every advanced milestone keeps all B tests green; none may weaken verification.

| Milestone | Scope | Key acceptance |
| --- | --- | --- |
| ✅ A1 | Quick Check / Learning mode toggle and plumbing | Quick mode shows the verdict and concise feedback with every Basic field still available (collapsed); Learning mode shows everything. |
| 🟡 A2 | Lean code explanation, per tagged block, grounded in the actual code and verdict | Explanations reference only identifiers present in the code (checked). |
| ✅ A3 | Proof mapping table | Added/omitted flags computed from tags, not LLM claims; "changed" judgments labelled as LLM-assessed. |
| ⬜ A4 | Enhanced 7-part error explanation + corrected code | A correction is labelled "Verified by Lean" only after passing §3 rules; otherwise "Unverified suggestion". |
| ✅ A5 | Contextual learning cards + practice questions | Cards selected by tactics detected in code; every card example and practice answer is compiled by Lean in tests. |
| ⬜ A6 | Hints-before-correction ladder in learning mode | Correction hidden until hints are requested. |
| ⬜ A7 | Evaluation set and harness | Report covers the six spec metrics; human rubric documented. |
| ⬜ A8 | Optional hardening: Lean in a no-network Docker container; persistent Lean REPL for speed | Same results as local runner on the eval set. |

**A1 + A3 result.** The app has a Quick Check / Learning Mode toggle
(`ui/app.py`); the current toggle decides the view, so switching after a check
re-renders without re-checking. Quick Check shows the verdict, a one-line Lean
result and the error cards, with the problem and proof, the formal statement
with the generated Lean code, and the step table in collapsed sections — the
acceptance criterion was refined from "unchanged from B7" because the Advanced
spec asks Quick Check for "only the verification result and concise
feedback", while the Basic spec requires every field to stay available.
Learning Mode shows everything plus "Your reasoning ↔ Lean code"
(`report/mapping.py`): each student step beside the Lean tactics tagged with
it in the checked code, translator-added blocks labelled as not part of the
student's proof, and an "only approximate" warning when more than half of the
steps were changed or not translated (or more steps were added than the
student wrote). "Changed" is labelled as the translator's own assessment;
"added" and "not translated" come from the code. 306 unit tests pass,
including `AppTest` runs of both modes and a mode switch that does not re-run
Lean; the toggle was checked in the live app.

**A5 result.** `learning/cards.py` holds 17 hand-written cards — `theorem`,
`by`, `intro`, `exact`, `apply`, `have`, `rw`, `simp`, `constructor`,
`obtain`/`rcases`, `use`/`refine`, `linarith`, `calc`, `by_contra`,
`by_cases`, `positivity`, `unfold` — each with its Lean meaning, its
mathematical meaning and an example; 13 have a practice question with a hint
and a model solution. `learning/detect.py` selects cards from the code Lean
actually checked (comments and tags ignored, word boundaries respected, so
`exact_mod_cast` does not select `exact`), in order of first appearance, and
shows where each concept occurs in the student's proof, by step.
`learning/practice.py` checks practice answers through the same safety screen,
Python-assembled file, Lean run and verdict rules as everything else. In
Learning Mode the app shows the cards; a hint is offered before the model
solution. Real Lean compiles all 17 examples and 13 solutions (standard
axioms only) and checks a right and a wrong practice answer; 339 unit tests
pass, including an `AppTest` run where a practice answer goes to the Lean
runner.

**A2 result (live check pending).** `explain/code.py` makes one structured
LLM call per proof, on request ("Explain the Lean code" in Learning Mode, cached
per check), with the tagged code, each block's student step, the statement and
Lean's verdict as context. For each block it returns the Lean syntax, the
mathematical meaning, the role in the proof and why it is needed. Checked in
code: only blocks that exist are kept, in code order; any Lean name written in
backticks must occur in that block, the statement or the RaChecker
definitions, otherwise the block's text is withheld and replaced by an
automatic summary from the concept cards (the app says which names caused it);
the same applies to the overview; an LLM outage gives automatic summaries.
351 unit tests pass; `tests/llm/test_code_explanation_live.py` is ready for a
key.

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

1. ~~Approve installing elan + Lean + Mathlib~~ — done at B2.
2. Confirm Anthropic Claude as the LLM provider and provide an API key before
   B4 live tests.
3. First topic set: sequences and convergence (proposed list in B3).
