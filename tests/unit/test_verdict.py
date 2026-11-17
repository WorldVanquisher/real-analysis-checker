"""Tests for ra_checker.report.verdict: the deterministic VERIFIED rules."""

import pytest

from ra_checker.lean.assemble import assemble_hypotheses_probe, assemble_proof, assemble_statement_check
from ra_checker.lean.diagnostics import LeanOutput
from ra_checker.models import Diagnostic, LeanRun, Severity, VerificationStatus
from ra_checker.report.verdict import (
    STANDARD_AXIOMS,
    decide_hypotheses_probe,
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


def error(msg="unsolved goals", line=ASSEMBLED.proof_first_line) -> Diagnostic:
    return Diagnostic(line=line, column=2, severity=Severity.ERROR, message=msg)


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


def test_header_errors_are_environment_problems_not_proof_errors():
    unbuilt = error("unknown module prefix 'RaChecker'", line=2)
    v = decide(run(exit_code=1), output(unbuilt, axioms=None))
    assert v.status is VerificationStatus.RUNTIME_ERROR
    assert "environment is not set up" in v.reasons[0]
    assert "lake build" in v.reasons[0]


def test_statement_must_match_byte_for_byte():
    v = decide(statement=STATEMENT + " ")
    assert v.status is VerificationStatus.TRANSLATION_FAILED
    assert "differs from the statement the student confirmed" in v.reasons[0]


def test_run_of_a_different_file_is_a_programming_error():
    with pytest.raises(ValueError, match="did not check the assembled file"):
        decide(r=run(source=ASSEMBLED.source + "\n-- tampered"))


def test_statement_check():
    check_file = assemble_statement_check(STATEMENT)

    def check(o, **run_fields):
        fields = dict(source=check_file.source, exit_code=0, duration_s=1.0)
        fields.update(run_fields)
        return decide_statement_check(assembled=check_file, run=LeanRun(**fields), output=o)

    assert check(output(axioms=None, uses_sorry=True)).ok
    bad = check(
        output(error("unknown identifier 'Foo'", line=check_file.statement_line), axioms=None),
        exit_code=1,
    )
    assert not bad.ok and "unknown identifier" in bad.reasons[0]
    assert not check(output(axioms=None), exit_code=None, timed_out=True).ok
    broken = check(output(error("unknown module prefix", line=1), axioms=None), exit_code=1)
    assert not broken.ok and "environment" in broken.reasons[0]


# ------------------------------------------------------- hypotheses probe

PROBE = assemble_hypotheses_probe("(x : ℝ) (h₁ : 0 < x) (h₂ : x < 0) : x = 5")


def probe(r=None, o=None):
    return decide_hypotheses_probe(
        assembled=PROBE,
        run=r or LeanRun(source=PROBE.source, exit_code=0, duration_s=0.1),
        output=o or output(),
    )


def test_probe_reports_a_contradiction_only_on_a_clean_proof():
    assert probe() is True
    assert probe(o=output(axioms=("propext",))) is True


@pytest.mark.parametrize(
    "o, code",
    [
        (output(error("linarith failed", line=PROBE.proof_first_line + 2)), 1),
        (output(uses_sorry=True, axioms=(*STANDARD, "sorryAx")), 0),
    ],
)
def test_probe_failure_means_no_contradiction_found(o, code):
    assert probe(LeanRun(source=PROBE.source, exit_code=code, duration_s=0.1), o) is False


@pytest.mark.parametrize(
    "r, o",
    [
        (LeanRun(source=PROBE.source, exit_code=None, timed_out=True, duration_s=120), None),
        (None, output(error("unknown module", line=1))),  # broken environment
        (None, output(axioms=None)),  # no axiom report: not positive evidence
        (None, output(axioms=(*STANDARD, "Lean.ofReduceBool"))),
        (LeanRun(source=PROBE.source, exit_code=1, duration_s=0.1), None),
    ],
)
def test_probe_that_cannot_decide_returns_none(r, o):
    assert probe(r, o) is None


def test_probe_must_check_the_assembled_file():
    with pytest.raises(ValueError):
        probe(LeanRun(source="something else", exit_code=0, duration_s=0.1))
