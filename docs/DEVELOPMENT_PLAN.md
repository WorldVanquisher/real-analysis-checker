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

### ⏳ B5 — Lean translation (statement, then proof)

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

1. ~~Approve installing elan + Lean + Mathlib~~ — done at B2.
2. Confirm Anthropic Claude as the LLM provider and provide an API key before
   B4 live tests.
3. First topic set: sequences and convergence (proposed list in B3).
