"""Tests for ra_checker.report.verdict: the deterministic VERIFIED rules."""

import pytest

from ra_checker.lean.assemble import assemble_proof, assemble_statement_check
from ra_checker.lean.diagnostics import LeanOutput
from ra_checker.models import Diagnostic, LeanRun, Severity, VerificationStatus
from ra_checker.report.verdict import (
    STANDARD_AXIOMS,
    decide_proof_verdict,
    decide_statement_check,
)

STATEMENT = "(x : ℝ) (hx : 0 < x) : 0 < x ^ 2"
ASSEMBLED = assemble_proof(STATEMENT, "positivity")
STANDARD = ("propext", "Classical.choice", "Quot.sound")


def run(**overrides) -> LeanRun:
    fields = dict(source=ASSEMBLED.source, exit_code=0, duration_s=1.0)
    fields.update(overrides)
    return LeanRun(**fields)


def output(*diagnostics: Diagnostic, axioms=STANDARD, uses_sorry=False) -> LeanOutput:
    return LeanOutput(tuple(diagnostics), axioms, uses_sorry, "")


def error(msg="unsolved goals") -> Diagnostic:
    return Diagnostic(line=4, column=2, severity=Severity.ERROR, message=msg)


def decide(r=None, o=None, statement=STATEMENT):
    return decide_proof_verdict(
        confirmed_statement=statement,
        assembled=ASSEMBLED,
        run=r or run(),
        output=o or output(),
    )


def test_clean_run_with_standard_axioms_is_verified():
    v = decide()
    assert v.status is VerificationStatus.VERIFIED and v.verified
    assert v.axioms == STANDARD


@pytest.mark.parametrize("axioms", [(), ("propext",), tuple(STANDARD_AXIOMS)])
def test_any_subset_of_standard_axioms_is_fine(axioms):
    assert decide(o=output(axioms=axioms)).verified


def test_warnings_alone_do_not_block():
    lint = Diagnostic(line=4, column=2, severity=Severity.WARNING, message="unused variable `h`")
    assert decide(o=output(lint)).verified


@pytest.mark.parametrize(
    "r, o, status, reason",
    [
        (run(exit_code=None, timed_out=True), output(axioms=None), VerificationStatus.RUNTIME_ERROR, "time limit"),
        (run(exit_code=1), output(error()), VerificationStatus.VERIFICATION_FAILED, "1 error(s)"),
        (run(exit_code=1), output(error(), uses_sorry=True), VerificationStatus.VERIFICATION_FAILED, "placeholders"),
        (run(exit_code=3), output(), VerificationStatus.RUNTIME_ERROR, "without reporting an error"),
        (run(), output(uses_sorry=True, axioms=STANDARD + ("sorryAx",)), VerificationStatus.TRANSLATION_FAILED, "incomplete"),
        (run(), output(axioms=None), VerificationStatus.RUNTIME_ERROR, "did not report the axioms"),
        (run(), output(axioms=STANDARD + ("Lean.ofReduceBool",)), VerificationStatus.VERIFICATION_FAILED, "Lean.ofReduceBool"),
        (run(), output(axioms=("cheat",)), VerificationStatus.VERIFICATION_FAILED, "non-standard axioms: cheat"),
    ],
)
def test_failures_are_never_verified(r, o, status, reason):
    v = decide(r, o)
    assert not v.verified
    assert v.status is status
    assert any(reason in text for text in v.reasons), v.reasons


def test_errors_win_even_if_exit_code_is_zero():
    assert decide(o=output(error())).status is VerificationStatus.VERIFICATION_FAILED


def test_statement_must_match_byte_for_byte():
    v = decide(statement=STATEMENT + " ")
    assert v.status is VerificationStatus.TRANSLATION_FAILED
    assert "differs from the statement the student confirmed" in v.reasons[0]


def test_run_of_a_different_file_is_a_programming_error():
    with pytest.raises(ValueError, match="did not check the assembled file"):
        decide(r=run(source=ASSEMBLED.source + "\n-- tampered"))


def test_statement_check():
    check_file = assemble_statement_check(STATEMENT)
    ok = decide_statement_check(
        run=LeanRun(source=check_file.source, exit_code=0, duration_s=1.0),
        output=output(axioms=None, uses_sorry=True),
    )
    assert ok.ok
    bad = decide_statement_check(
        run=LeanRun(source=check_file.source, exit_code=1, duration_s=1.0),
        output=output(error("unknown identifier 'Foo'"), axioms=None),
    )
    assert not bad.ok and "unknown identifier" in bad.reasons[0]
    slow = decide_statement_check(
        run=LeanRun(source=check_file.source, exit_code=None, timed_out=True, duration_s=9.0),
        output=output(axioms=None),
    )
    assert not slow.ok
