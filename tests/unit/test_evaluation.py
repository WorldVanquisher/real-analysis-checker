"""Tests for ra_checker.evaluation and eval/run_eval.py (fakes only; no API)."""

import csv
import importlib.util
import re
from collections import Counter
from pathlib import Path

import pytest
from pipeline_helpers import LEAN_STATEMENT, PROBLEM, PROOF, make_checker, parse_answer
from translation_helpers import STATEMENT_OK, UNSOLVED

from ra_checker import evaluation
from ra_checker.evaluation import EvalCase, load_cases, run_case, summarize, write_outputs
from ra_checker.lean.safety import check_statement
from ra_checker.models import VerificationStatus as S

ROOT = Path(__file__).resolve().parents[2]
CASES = load_cases(ROOT / "eval" / "cases.toml")


def case(**overrides) -> EvalCase:
    fields = dict(id="c", category="correct", problem=PROBLEM, proof=PROOF, expected_status=(S.VERIFIED,))
    fields.update(overrides)
    return EvalCase(**fields)


# ------------------------------------------------------------------ the case file


def test_case_file_covers_every_category_in_the_spec():
    counts = Counter(c.category for c in CASES)
    for category in ("correct", "incorrect", "incomplete", "missing_assumption",
                     "hard_to_formalize", "mistranslation"):
        assert counts[category] >= 3, category
    assert counts["ambiguous"] >= 1 and counts["out_of_scope"] >= 1


def test_cases_are_well_formed():
    for c in CASES:
        assert c.problem.strip() and c.proof.strip() and c.notes.strip(), c.id
        if c.expected_error_step:
            assert re.fullmatch(r"S[1-9][0-9]*", c.expected_error_step), c.id
        if c.reference_statement:
            assert check_statement(c.reference_statement).ok, c.id
    for c in CASES:
        if c.category in ("incorrect", "incomplete", "missing_assumption", "ambiguous", "out_of_scope"):
            assert c.must_not_verify, c.id


# ---------------------------------------------------------------------- harness


def test_verified_case():
    checker, *_ = make_checker()
    result = run_case(case(reference_statement=LEAN_STATEMENT), checker)
    assert result.status == "verified" and result.status_ok and not result.false_verified
    assert result.compiled is True and result.statement_exact_match is True
    assert result.explained_blocks == 3 and result.grounded_blocks == 0  # no explanation answer: automatic
    assert result.report["status"] == "verified"


def test_false_verification_is_detected():
    checker, *_ = make_checker()
    result = run_case(case(category="incorrect", expected_status=(S.VERIFICATION_FAILED,)), checker)
    assert result.false_verified and not result.status_ok


def test_failed_case_with_localization():
    checker, *_ = make_checker(STATEMENT_OK, UNSOLVED)
    result = run_case(
        case(category="incorrect", expected_status=(S.VERIFICATION_FAILED,), expected_error_step="S3"),
        checker,
        explain=False,
    )
    assert result.status_ok and result.localization_ok and result.error_step == "S3"
    assert result.compiled is True  # Lean ran; the error is not a Lean-side one


def test_clarification_case_never_runs_lean():
    checker, _, lean = make_checker(parse=parse_answer(ambiguities=["Which sequence?"]))
    result = run_case(case(category="ambiguous", expected_status=(S.NEEDS_CLARIFICATION,)), checker)
    assert result.status_ok and result.compiled is None and lean.sources == []


def test_harness_survives_a_crash():
    class Broken:
        def formalize(self, submission):
            raise RuntimeError("boom")

    result = run_case(case(), Broken())
    assert result.status == "harness_error" and "boom" in result.detail and not result.status_ok


def test_summary_and_outputs(tmp_path):
    ok_checker, *_ = make_checker()
    bad_checker, *_ = make_checker(STATEMENT_OK, UNSOLVED)
    results = [
        run_case(case(id="a", reference_statement=LEAN_STATEMENT), ok_checker),
        run_case(case(id="b", category="incorrect", expected_status=(S.VERIFICATION_FAILED,),
                      expected_error_step="S2"), bad_checker, explain=False),
    ]
    summary = summarize(results)
    assert summary["cases"] == 2 and summary["false_verifications"] == []
    assert summary["status_accuracy"] == 1.0
    assert summary["lean_compile_rate"] == 1.0
    assert summary["localization_accuracy"] == 0.0  # expected S2, located at S3
    assert summary["status_accuracy_by_category"] == {"correct": 1.0, "incorrect": 1.0}

    write_outputs(results, summary, tmp_path)
    assert "**False verifications: 0**" in (tmp_path / "summary.md").read_text(encoding="utf-8")
    with (tmp_path / "grading.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    assert rows[0] == list(evaluation.GRADING_COLUMNS)
    assert [r[0] for r in rows[1:]] == ["a", "b"]
    assert (tmp_path / "results.json").stat().st_size > 0


# -------------------------------------------------------------------------- CLI


def _load_cli():
    spec = importlib.util.spec_from_file_location("run_eval", ROOT / "eval" / "run_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_refuses_to_spend_without_yes(monkeypatch, capsys):
    cli = _load_cli()
    monkeypatch.setattr(cli, "build_checker", lambda: pytest.fail("must not build the real checker"))
    assert cli.main(["--category", "correct"]) == 2
    out = capsys.readouterr().out
    assert "costs API usage" in out and "--yes" in out


def test_cli_runs_selected_cases_with_an_injected_checker(monkeypatch, tmp_path, capsys):
    cli = _load_cli()
    checker, *_ = make_checker(parse=parse_answer(ambiguities=["Which sequence?"]))
    monkeypatch.setattr(cli, "build_checker", lambda: (checker, []))
    code = cli.main(["--yes", "--case", "ambiguous_which_sequence", "--out", str(tmp_path)])
    assert code == 0
    assert (tmp_path / "summary.md").exists()
    assert "ambiguous_which_sequence" in capsys.readouterr().out
