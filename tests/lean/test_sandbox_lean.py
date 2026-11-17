"""The Docker sandbox must give the same verdicts as local Lean, and really be
isolated. Needs Docker and the image (see docker/lean-sandbox.Dockerfile).
Run with `pytest -m lean`; skipped when Docker or the image is missing."""

import dataclasses
import json
import subprocess
import tomllib
from pathlib import Path

import pytest
from lean_cases import CASES as LEAN_CASES

from ra_checker.config import DEFAULT_LEAN_DOCKER_IMAGE
from ra_checker.lean import sandbox
from ra_checker.lean.assemble import assemble_proof
from ra_checker.lean.diagnostics import parse_lean_output
from ra_checker.report.verdict import decide_proof_verdict

pytestmark = pytest.mark.lean

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
EVAL_RUN1 = json.loads((FIXTURES / "eval_run1_checked.json").read_text(encoding="utf-8"))["cases"]
REFERENCE = tomllib.loads((FIXTURES / "reference_cases.toml").read_text(encoding="utf-8"))["case"]
IMAGE = DEFAULT_LEAN_DOCKER_IMAGE


@pytest.fixture(scope="module")
def docker():
    docker = sandbox.find_docker()
    if docker is None or not sandbox.image_available(docker, IMAGE):
        pytest.skip(f"Docker or the image {IMAGE} is not available")
    return docker


@pytest.fixture(scope="module")
def sandbox_runner(docker, tmp_path_factory):
    runner = sandbox.make_sandbox_runner(IMAGE, 300, tmp_path_factory.mktemp("sandbox"))
    yield runner
    runner.close()


def verdict(runner, statement, block, raw_source=None):
    assembled = assemble_proof(statement, block)
    if raw_source is not None:
        assembled = dataclasses.replace(assembled, source=raw_source)
    run = runner.run(assembled.source)
    output = parse_lean_output(run.stdout, assembled.theorem_name, run.stderr)
    return output, decide_proof_verdict(confirmed_statement=statement, assembled=assembled, run=run, output=output)


def test_same_verdicts_as_local_lean_on_the_live_evaluation_files(sandbox_runner):
    mismatches = []
    for case in EVAL_RUN1:
        output, v = verdict(sandbox_runner, case["statement"], case["tactic_block"])
        got = (v.status.value, [d.line for d in output.errors])
        if got != (case["cli_status"], case["cli_error_lines"]):
            mismatches.append((case["case_id"], got))
    assert not mismatches, mismatches


def test_same_outcomes_on_hand_written_cases_and_reference_exercises(sandbox_runner):
    for case in LEAN_CASES:
        _, v = verdict(sandbox_runner, case.statement, case.tactic_block, case.raw_source)
        assert v.status is case.expected, case.name
    for case in REFERENCE:
        output, v = verdict(sandbox_runner, case["statement"], case["tactic_block"])
        assert v.verified and output.diagnostics == (), case["id"]
    assert "4.36.0" in (sandbox_runner.lean_version() or "")


def test_the_container_has_no_network_and_a_read_only_filesystem(docker):
    def in_sandbox(*command):
        return subprocess.run([docker, "run", "--rm", *sandbox.SANDBOX_FLAGS, IMAGE, *command],
                              capture_output=True, text=True, timeout=120)

    assert in_sandbox("true").returncode == 0  # the flags themselves are accepted
    assert in_sandbox("curl", "-sS", "--max-time", "5", "https://github.com").returncode != 0
    assert in_sandbox("touch", "/home/lean/project/written").returncode != 0
    assert in_sandbox("touch", "/tmp/scratch").returncode == 0  # only the small tmpfs is writable


def test_closing_removes_the_container(docker, tmp_path):
    runner = sandbox.make_sandbox_runner(IMAGE, 300, tmp_path)
    name = runner.command[runner.command.index("--name") + 1]
    runner.run(assemble_proof("(x : ℝ) : x = x", "rfl").source)
    runner.close()
    left = subprocess.run([docker, "ps", "-a", "--filter", f"name={name}", "--format", "{{.Names}}"],
                          capture_output=True, text=True, timeout=60).stdout.strip()
    assert left == ""
