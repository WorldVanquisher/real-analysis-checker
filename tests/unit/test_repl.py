"""Tests for ra_checker.lean.repl with a fake REPL speaking the same JSON protocol."""

import sys
import textwrap

import pytest

from ra_checker.lean.assemble import assemble_proof
from ra_checker.lean.diagnostics import parse_lean_output
from ra_checker.lean.repl import ReplLeanRunner, _render, _split_imports
from ra_checker.lean.runner import LeanUnavailableError
from ra_checker.models import LeanRun, VerificationStatus as S
from ra_checker.report.verdict import decide_proof_verdict

STATEMENT = "(x : ℝ) (hx : 0 < x) : 0 < x ^ 2"

FAKE_REPL = textwrap.dedent(
    """
    import json, os, sys, time
    sys.stdout.reconfigure(encoding="utf-8"); sys.stdin.reconfigure(encoding="utf-8")
    env, buffer = 0, []

    def respond(obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\\n\\n")
        sys.stdout.flush()

    for line in sys.stdin:
        if line.strip():
            buffer.append(line)
            continue
        if not buffer:
            continue
        request, buffer = json.loads("".join(buffer)), []
        cmd = request["cmd"]
        if "env" not in request:  # loading the base environment
            if os.environ.get("FAKE_REPL_MODE") == "broken":
                respond({"messages": [{"severity": "error", "pos": {"line": 2, "column": 0},
                         "data": "unknown module prefix 'RaChecker'"}], "env": 0})
            else:
                respond({"env": 0})
            continue
        env += 1
        if "SLOW" in cmd:
            time.sleep(60)
        if "CRASH" in cmd:
            sys.exit(5)
        if "REJECT" in cmd:
            respond({"message": "Unknown environment."})
            continue
        lines = cmd.split("\\n")
        messages = []
        if lines[0] != "":
            messages.append({"severity": "error", "pos": {"line": 1, "column": 0}, "data": "imports were not blanked"})
        for number, text in enumerate(lines, start=1):
            if "BAD" in text:
                messages.append({"severity": "error", "pos": {"line": number, "column": 2},
                                 "data": "unsolved goals\\nx : ℝ\\n⊢ False"})
        axioms = "propext, sorryAx, Classical.choice, Quot.sound" if messages else "propext, Classical.choice, Quot.sound"
        messages.append({"severity": "info", "pos": {"line": len(lines) - 1, "column": 0},
                         "data": "'student_claim' depends on axioms: [" + axioms + "]"})
        respond({"messages": messages, "env": env})
    """
)


class RecordingFallback:
    def __init__(self):
        self.sources = []

    def run(self, source, timeout_s=None):
        self.sources.append(source)
        return LeanRun(source=source, exit_code=0, duration_s=1.0)

    def lean_version(self):
        return "Lean (fake fallback)"


@pytest.fixture
def make_runner(tmp_path):
    script = tmp_path / "fake_repl.py"
    script.write_text(FAKE_REPL, encoding="utf-8")
    runners = []

    def make(**kwargs):
        runner = ReplLeanRunner(tmp_path, kwargs.pop("timeout_s", 20),
                                command=(sys.executable, str(script)), **kwargs)
        runners.append(runner)
        return runner

    yield make
    for runner in runners:
        runner.close()


def verdict_for(runner, block):
    assembled = assemble_proof(STATEMENT, block)
    run = runner.run(assembled.source)
    output = parse_lean_output(run.stdout, assembled.theorem_name, run.stderr)
    return assembled, run, output, decide_proof_verdict(
        confirmed_statement=STATEMENT, assembled=assembled, run=run, output=output
    )


def test_verified_check_reuses_one_process(make_runner):
    runner = make_runner()
    _, run, output, verdict = verdict_for(runner, "-- [S1]\npositivity")
    assert verdict.status is S.VERIFIED
    assert run.stdout.startswith("'student_claim' depends on axioms:")  # bare, as on the command line
    assert output.diagnostics == ()
    verdict_for(runner, "-- [S1]\npositivity")
    assert runner.starts == 1


def test_error_positions_are_file_lines(make_runner):
    assembled, run, output, verdict = verdict_for(make_runner(), "-- [S1]\nintro\n-- [S2]\nBAD")
    assert verdict.status is S.VERIFICATION_FAILED and run.exit_code == 1
    (error,) = output.errors
    assert assembled.source.split("\n")[error.line - 1].strip() == "BAD"
    assert error.goal_state == "x : ℝ\n⊢ False"


def test_timeout_kills_the_repl_and_the_next_check_restarts_it(make_runner):
    runner = make_runner(timeout_s=1)
    _, run, _, verdict = verdict_for(runner, "-- [S1]\nSLOW")
    assert run.timed_out and verdict.status is S.RUNTIME_ERROR
    _, _, _, verdict = verdict_for(runner, "-- [S1]\npositivity")
    assert verdict.status is S.VERIFIED and runner.starts == 2


def test_crash_is_a_runtime_error_not_a_verdict(make_runner):
    runner = make_runner()
    _, run, _, verdict = verdict_for(runner, "-- [S1]\nCRASH")
    assert run.exit_code == 5 and verdict.status is S.RUNTIME_ERROR
    assert verdict_for(runner, "-- [S1]\npositivity")[3].status is S.VERIFIED
    assert runner.starts == 2


def test_rejected_command_is_a_runtime_error(make_runner):
    _, run, _, verdict = verdict_for(make_runner(), "-- [S1]\nREJECT")
    assert run.exit_code == 2 and "Unknown environment" in run.stderr
    assert verdict.status is S.RUNTIME_ERROR


def test_broken_base_environment(make_runner, monkeypatch):
    monkeypatch.setenv("FAKE_REPL_MODE", "broken")
    with pytest.raises(LeanUnavailableError, match="lake build"):
        make_runner().run(assemble_proof(STATEMENT, "positivity").source)


def test_periodic_restart_bounds_memory(make_runner):
    runner = make_runner(max_checks_per_process=2)
    for _ in range(3):
        verdict_for(runner, "-- [S1]\npositivity")
    assert runner.starts == 2


def test_other_imports_go_to_the_command_line_runner(make_runner):
    fallback = RecordingFallback()
    runner = make_runner(fallback=fallback)
    source = "import Mathlib.Analysis.SpecificLimits.Basic\n\ntheorem t : True := trivial\n"
    run = runner.run(source)
    assert fallback.sources == [source] and run.exit_code == 0
    assert runner.starts == 0
    assert runner.lean_version() == "Lean (fake fallback)"
    runner.run("import Mathlib\n\ntheorem t : True := trivial\n")  # a subset stays in the REPL
    assert fallback.sources == [source] and runner.starts == 1


def test_split_imports_keeps_line_numbers():
    imports, body = _split_imports("import Mathlib\nimport RaChecker\n\nopen RaChecker\nimport Late\n")
    assert imports == ("Mathlib", "RaChecker")
    assert body.split("\n") == ["", "", "", "open RaChecker", "import Late", ""]


def test_render_matches_the_command_line_format():
    stdout, code, _ = _render({"messages": [
        {"severity": "warning", "pos": {"line": 7, "column": 8}, "data": "declaration uses `sorry`"},
        {"severity": "info", "pos": {"line": 11, "column": 0}, "data": "'student_claim' does not depend on any axioms"},
    ], "env": 3})
    assert code == 0
    assert stdout == "Check.lean:7:8: warning: declaration uses `sorry`\n'student_claim' does not depend on any axioms\n"
    assert _render({"message": "Unknown environment."}) == ("", 2, "Unknown environment.")
