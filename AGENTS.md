# Instructions for coding agents

Project: Real Analysis Homework Checker. Read `docs/ARCHITECTURE.md` and
`docs/DEVELOPMENT_PLAN.md` before changing code; the specs are in
`docs/SPEC_BASIC.md` and `docs/SPEC_ADVANCED.md`.

## Rules that protect correctness

* Only a real Lean run may produce `VERIFIED`. Never let LLM output set or
  upgrade a verification status, and never fabricate a result in code, tests,
  demos or documentation.
* Keep "Lean accepted the formal proof" separate from "the formalization is
  faithful to the student's proof". UI text must never say the student's proof
  is correct.
* The formal statement is locked after student confirmation; the LLM only
  writes the tactic block, Python assembles the file.
* Generated Lean goes through `lean/safety.py` before it runs. Never call a
  shell with generated text; use argument lists and timeouts.
* A corrected proof is labelled verified only after it passes the same Lean
  verdict rules.

## How to work

* One milestone/module at a time, as listed in `docs/DEVELOPMENT_PLAN.md`.
* After each module: explain what was implemented, run the relevant tests,
  report real output, errors and limitations. Never claim a test passed unless
  it was run.
* Unit tests must not need network, an API key, or Lean (use the fakes).
  Lean tests use the `lean` marker; live LLM tests use the `llm` marker and are
  opt-in.
* API keys come only from environment variables or a git-ignored `.env`. Never
  commit secrets, `.env`, `lean/.lake/`, or logs.
* Do not rewrite unrelated files. Update the docs and the plan's status markers
  when behaviour changes.

## Commands

```bash
pip install -e ".[dev]"   # install
pytest                    # unit tests (no Lean, no network)
pytest -m lean            # real Lean + Mathlib tests (~20 min)
pytest -m llm             # live Claude API tests (needs a key; costs money)
streamlit run src/ra_checker/ui/app.py   # the app
cd lean && lake build     # rebuild the RaChecker library after editing lean/
```

Lean output fixtures are regenerated with `RA_CAPTURE_FIXTURES=1 pytest -m lean`;
the capture scrubs machine paths — keep it that way, the repository is public.
