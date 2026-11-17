"""Run the evaluation set against the real Claude API and real Lean.

    python eval/run_eval.py --yes                      # all cases
    python eval/run_eval.py --yes --category incorrect # one category
    python eval/run_eval.py --yes --case correct_squeeze --no-explain

Each case makes several Claude API calls (costs API usage) and one to three
Lean runs (about 20–25 s each). Results go to eval/results/<timestamp>/
(git-ignored): results.json, summary.md and grading.csv for human grading
(see eval/RUBRIC.md).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from ra_checker.evaluation import load_cases, render_summary, run_case, summarize, write_outputs
from ra_checker.setup import build_checker

HERE = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--yes", action="store_true", help="confirm that this uses the paid API")
    parser.add_argument("--case", action="append", default=[], help="run only this case id (repeatable)")
    parser.add_argument("--category", action="append", default=[], help="run only this category (repeatable)")
    parser.add_argument("--no-explain", action="store_true", help="skip the Lean code explanation")
    parser.add_argument("--cases-file", type=Path, default=HERE / "cases.toml")
    parser.add_argument("--out", type=Path, default=None, help="output directory")
    args = parser.parse_args(argv)

    cases = load_cases(args.cases_file)
    if args.case:
        cases = tuple(c for c in cases if c.id in set(args.case))
    if args.category:
        cases = tuple(c for c in cases if c.category in set(args.category))
    if not cases:
        print("No cases selected.")
        return 1
    if not args.yes:
        print(
            f"This would run {len(cases)} case(s) through the real Claude API and Lean, "
            "which costs API usage and takes about a minute per case.\n"
            "Re-run with --yes to start."
        )
        return 2

    checker, problems = build_checker()
    if checker is None:
        print("The checker is not ready:\n" + "\n".join(f"- {p}" for p in problems))
        return 1
    if hasattr(checker.lean, "wait"):
        print("Warming up Lean (after a restart this can take several minutes) …", flush=True)
        status = checker.lean.wait()
        print(f"    Lean {status.state} after {status.seconds:.0f} s {status.message}".rstrip(), flush=True)

    results = []
    for number, case in enumerate(cases, start=1):
        print(f"[{number}/{len(cases)}] {case.id} …", flush=True)
        result = run_case(case, checker, explain=not args.no_explain)
        flag = "FALSE VERIFICATION" if result.false_verified else ("ok" if result.status_ok else "unexpected")
        print(f"    {result.status} ({flag}, {result.duration_s:.0f} s)", flush=True)
        results.append(result)

    summary = summarize(results)
    out = args.out or HERE / "results" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    write_outputs(results, summary, out)
    print("\n" + render_summary(results, summary))
    print(f"Written to {out}")
    return 1 if summary["false_verifications"] else 0


if __name__ == "__main__":
    sys.exit(main())
