"""Evaluation harness (milestone A7).

Runs evaluation cases through a Checker and computes the metrics that can be
measured automatically:

* **status accuracy** — the final status is one of the case's expected ones;
* **false verifications** — VERIFIED although the case must not verify (the
  most important number; it must be zero);
* **Lean compile rate** — Lean ran on the proof and no error was a Lean-side
  one (syntax, unknown name);
* **statement exact match** — the formal statement equals the case's reference
  statement up to whitespace (a lower bound: an equivalent statement written
  differently counts as a mismatch, so a human grades faithfulness);
* **localization accuracy** — the first analysed error is in the expected step;
* **code-explanation grounding** — share of explained blocks whose LLM text
  passed the grounding check.

Faithfulness of the statement, explanation quality, code-explanation
correctness and usefulness of the learning content need a human: the harness
writes a grading sheet (``grading.csv``) and ``eval/RUBRIC.md`` says how to
fill it in.

The harness confirms each formal statement automatically, standing in for a
student who reads and confirms it; that is why every statement is recorded for
human grading.
"""

from __future__ import annotations

import csv
import json
import time
import tomllib
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ra_checker.analysis.classify import LEAN_SIDE_KINDS, classify_lean_error
from ra_checker.models import CheckReport, Submission, VerificationStatus
from ra_checker.pipeline import Checker, PendingCheck

CATEGORIES = (
    "correct", "incorrect", "incomplete", "missing_assumption",
    "hard_to_formalize", "mistranslation", "ambiguous", "out_of_scope",
)  # fmt: skip
GRADING_COLUMNS = (
    "case_id", "category", "formal_statement", "back_translation",
    "statement_faithful (y/n)", "error_explanation_quality (1-5 or n/a)",
    "code_explanation_correct (1-5 or n/a)", "learning_content_useful (1-5 or n/a)", "notes",
)  # fmt: skip


@dataclass(frozen=True)
class EvalCase:
    id: str
    category: str
    problem: str
    proof: str
    expected_status: tuple[VerificationStatus, ...]
    expected_error_step: str | None = None
    reference_statement: str | None = None
    notes: str = ""

    @property
    def must_not_verify(self) -> bool:
        return VerificationStatus.VERIFIED not in self.expected_status


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    category: str
    status: str
    status_ok: bool
    false_verified: bool
    compiled: bool | None  # None: Lean never ran on a proof
    statement: str | None
    back_translation: str | None
    assumptions_added: tuple[str, ...]
    statement_exact_match: bool | None
    error_step: str | None
    localization_ok: bool | None
    explained_blocks: int
    grounded_blocks: int
    duration_s: float
    detail: str
    report: dict | None = field(default=None, repr=False)


def load_cases(path: Path) -> tuple[EvalCase, ...]:
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))["case"]
    cases = []
    for item in raw:
        if item["category"] not in CATEGORIES:
            raise ValueError(f"{item['id']}: unknown category {item['category']!r}")
        cases.append(
            EvalCase(
                id=item["id"],
                category=item["category"],
                problem=item["problem"],
                proof=item["proof"],
                expected_status=tuple(VerificationStatus(s) for s in item["expected_status"]),
                expected_error_step=item.get("expected_error_step"),
                reference_statement=item.get("reference_statement"),
                notes=item.get("notes", ""),
            )
        )
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case ids")
    return tuple(cases)


def run_case(case: EvalCase, checker: Checker, *, explain: bool = True) -> CaseResult:
    start = time.monotonic()
    try:
        first = checker.formalize(Submission(problem_text=case.problem, proof_text=case.proof))
        report = checker.verify(first.confirmed()).report if isinstance(first, PendingCheck) else first
        explanation = checker.explain_code(report) if explain and report.translation else None
    except Exception as exc:  # noqa: BLE001 — a harness must survive and record any failure
        return _harness_failure(case, exc, time.monotonic() - start)

    status = report.status
    first_step = report.error_analyses[0].step_id if report.error_analyses else None
    statement = report.statement.lean_statement if report.statement else None
    blocks = explanation.blocks if explanation else ()
    return CaseResult(
        case_id=case.id,
        category=case.category,
        status=status.value,
        status_ok=status in case.expected_status,
        false_verified=status is VerificationStatus.VERIFIED and case.must_not_verify,
        compiled=_compiled(report),
        statement=statement,
        back_translation=report.statement.back_translation if report.statement else None,
        assumptions_added=report.statement.assumptions_added if report.statement else (),
        statement_exact_match=(
            _squash(statement) == _squash(case.reference_statement)
            if statement is not None and case.reference_statement
            else None
        ),
        error_step=first_step,
        localization_ok=(
            first_step == case.expected_error_step
            if case.expected_error_step and status is VerificationStatus.VERIFICATION_FAILED
            else None
        ),
        explained_blocks=len(blocks),
        grounded_blocks=sum(b.source == "llm" for b in blocks),
        duration_s=time.monotonic() - start,
        detail=report.status_detail,
        report=json.loads(report.model_dump_json()),
    )


def summarize(results: list[CaseResult]) -> dict:
    def rate(values: list[bool]) -> float | None:
        return round(sum(values) / len(values), 3) if values else None

    by_category: dict[str, list[CaseResult]] = defaultdict(list)
    for r in results:
        by_category[r.category].append(r)
    explained = sum(r.explained_blocks for r in results)
    return {
        "cases": len(results),
        "false_verifications": [r.case_id for r in results if r.false_verified],
        "status_accuracy": rate([r.status_ok for r in results]),
        "lean_compile_rate": rate([r.compiled for r in results if r.compiled is not None]),
        "statement_exact_match_rate": rate(
            [r.statement_exact_match for r in results if r.statement_exact_match is not None]
        ),
        "localization_accuracy": rate([r.localization_ok for r in results if r.localization_ok is not None]),
        "code_explanation_grounding_rate": (
            round(sum(r.grounded_blocks for r in results) / explained, 3) if explained else None
        ),
        "status_accuracy_by_category": {
            category: rate([r.status_ok for r in rs]) for category, rs in sorted(by_category.items())
        },
        "total_duration_s": round(sum(r.duration_s for r in results), 1),
    }


def write_outputs(results: list[CaseResult], summary: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(
        json.dumps({"summary": summary, "results": [asdict(r) for r in results]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (out_dir / "grading.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(GRADING_COLUMNS)
        for r in results:
            writer.writerow([r.case_id, r.category, r.statement or "", r.back_translation or "", "", "", "", "", ""])
    (out_dir / "summary.md").write_text(render_summary(results, summary), encoding="utf-8")


def render_summary(results: list[CaseResult], summary: dict) -> str:
    def pct(value: float | None) -> str:
        return "n/a" if value is None else f"{value:.0%}"

    false_verified = summary["false_verifications"]
    lines = [
        "# Evaluation summary",
        "",
        f"- Cases: {summary['cases']}",
        f"- **False verifications: {len(false_verified)}**"
        + (f" ({', '.join(false_verified)})" if false_verified else ""),
        f"- Status accuracy: {pct(summary['status_accuracy'])}",
        f"- Lean compile rate: {pct(summary['lean_compile_rate'])}",
        f"- Statement exact match (lower bound): {pct(summary['statement_exact_match_rate'])}",
        f"- Error localization accuracy: {pct(summary['localization_accuracy'])}",
        f"- Code-explanation grounding: {pct(summary['code_explanation_grounding_rate'])}",
        "",
        "| Case | Category | Status | Expected? | Compiled | Error step | Seconds |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        compiled = "—" if r.compiled is None else ("yes" if r.compiled else "no")
        lines.append(
            f"| {r.case_id} | {r.category} | {r.status} | {'yes' if r.status_ok else '**no**'} "
            f"| {compiled} | {r.error_step or '—'} | {r.duration_s:.0f} |"
        )
    lines += ["", "Human-graded metrics: fill in grading.csv (see eval/RUBRIC.md)."]
    return "\n".join(lines) + "\n"


def _compiled(report: CheckReport) -> bool | None:
    if report.lean_run is None:
        return None
    if report.lean_run.timed_out:
        return False
    errors = [d for d in report.diagnostics if d.severity.value == "error"]
    return not any(classify_lean_error(e.message) in LEAN_SIDE_KINDS for e in errors)


def _harness_failure(case: EvalCase, exc: Exception, duration: float) -> CaseResult:
    return CaseResult(
        case_id=case.id, category=case.category, status="harness_error", status_ok=False,
        false_verified=False, compiled=None, statement=None, back_translation=None,
        assumptions_added=(), statement_exact_match=None, error_step=None, localization_ok=None,
        explained_blocks=0, grounded_blocks=0, duration_s=duration,
        detail=f"{type(exc).__name__}: {exc}",
    )


def _squash(text: str) -> str:
    return " ".join(text.split())
