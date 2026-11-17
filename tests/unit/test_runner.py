"""Tests for ra_checker.lean.runner using small Python scripts in place of Lean.

These exercise process handling (arguments, environment, timeout and
process-tree kill, output caps) without needing a Lean installation.
"""

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from ra_checker.lean.runner import (
    CHECK_FILE_NAME,
    TRUNCATION_MARKER,
    FakeLeanRunner,
    LeanUnavailableError,
    SubprocessLeanRunner,
)

FAKE_LEAN = textwrap.dedent(
    """
    import json, os, sys
    if sys.argv[1] == "--version":
        print("Lean (version 9.9.9, fake)")
        sys.exit(0)
    path = sys.argv[1]
    print(json.dumps({
        "file_name": os.path.basename(path),
        "content": open(path, encoding="utf-8").read(),
        "cwd": os.getcwd(),
        "has_api_key": "ANTHROPIC_API_KEY" in os.environ,
        "has_github_token": "GITHUB_TOKEN" in os.environ,
    }))
    sys.exit(int(os.environ.get("FAKE_LEAN_EXIT", "0")))
    """
)

SLOW_LEAN = textwrap.dedent(
    """
    import os, subprocess, sys, time
    if sys.argv[1] == "--version":
        print("Lean (slow fake)")
        sys.exit(0)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    with open(os.environ["RA_TEST_PID_FILE"], "w") as f:
        f.write(f"{os.getpid()} {child.pid}")
    time.sleep(120)
    """
)

NOISY_LEAN = "import sys\nprint('x' * 5000)\n"


def script_runner(tmp_path: Path, code: str, **kwargs) -> SubprocessLeanRunner:
    script = tmp_path / "fake_lean.py"
    script.write_text(code, encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    return SubprocessLeanRunner(project, kwargs.pop("timeout_s", 30), command=(sys.executable, str(script)), **kwargs)


def pid_alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True
        ).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_runs_file_from_temp_dir_with_project_as_cwd(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-leak")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_should_not_leak")
    runner = script_runner(tmp_path, FAKE_LEAN)
    source = "theorem t : True := trivial  -- ε ∀ ℝ\n"
    run = runner.run(source)

    seen = json.loads(run.stdout)
    assert run.exit_code == 0 and not run.timed_out
    assert run.source == source
    assert seen["file_name"] == CHECK_FILE_NAME
    assert seen["content"] == source  # UTF-8 round trip
    assert Path(seen["cwd"]) == runner.project_dir
    assert seen["has_api_key"] is False
    assert seen["has_github_token"] is False
    assert run.lean_version == "Lean (version 9.9.9, fake)"


def test_nonzero_exit_code_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_LEAN_EXIT", "1")
    run = script_runner(tmp_path, FAKE_LEAN).run("x")
    assert run.exit_code == 1
    assert run.completed


def test_timeout_kills_the_whole_process_tree(tmp_path, monkeypatch):
    pid_file = tmp_path / "pids.txt"
    monkeypatch.setenv("RA_TEST_PID_FILE", str(pid_file))
    runner = script_runner(tmp_path, SLOW_LEAN, timeout_s=3)

    start = time.monotonic()
    run = runner.run("x")
    elapsed = time.monotonic() - start

    assert run.timed_out
    assert run.exit_code is None
    assert not run.completed
    assert elapsed < 60
    parent_pid, child_pid = map(int, pid_file.read_text().split())
    deadline = time.monotonic() + 10
    while (pid_alive(parent_pid) or pid_alive(child_pid)) and time.monotonic() < deadline:
        time.sleep(0.2)
    assert not pid_alive(parent_pid), "lean (parent) process survived the timeout"
    assert not pid_alive(child_pid), "child process survived the timeout"


def test_output_is_capped(tmp_path):
    run = script_runner(tmp_path, NOISY_LEAN, max_output_chars=100).run("x")
    assert run.stdout.endswith(TRUNCATION_MARKER)
    assert len(run.stdout) == 100 + len(TRUNCATION_MARKER)


def test_missing_executable_raises_unavailable(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    runner = SubprocessLeanRunner(project, 10, command=(str(tmp_path / "no-such-lake.exe"),))
    with pytest.raises(LeanUnavailableError):
        runner.run("x")
    assert runner.lean_version() is None


def test_missing_project_dir_raises_unavailable(tmp_path):
    runner = SubprocessLeanRunner(tmp_path / "missing", 10, command=(sys.executable,))
    with pytest.raises(LeanUnavailableError, match="project directory not found"):
        runner.run("x")


def test_fake_runner_records_sources():
    fake = FakeLeanRunner("out", exit_code=1)
    run = fake.run("source A")
    assert fake.sources == ["source A"]
    assert (run.stdout, run.exit_code, run.timed_out) == ("out", 1, False)
    timed_out = FakeLeanRunner(timed_out=True).run("B")
    assert timed_out.exit_code is None and timed_out.timed_out
