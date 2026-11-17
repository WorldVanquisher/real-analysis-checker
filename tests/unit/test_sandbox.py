"""Tests for ra_checker.lean.sandbox (no Docker needed)."""

import sys

import pytest

from ra_checker import setup
from ra_checker.config import DEFAULT_LEAN_DOCKER_IMAGE, ENV_LEAN_DOCKER_IMAGE, ENV_LEAN_RUNNER, load_settings
from ra_checker.lean import sandbox
from ra_checker.lean.repl import ReplLeanRunner
from ra_checker.lean.runner import LeanUnavailableError


def test_sandbox_command_isolates_the_container():
    command = sandbox.sandbox_command("docker", "img:tag", "box")
    joined = " ".join(command)
    for flag in ("--network none", "--read-only", "--cap-drop ALL", "--security-opt no-new-privileges",
                 "--pids-limit 512", "--memory 8g", "--rm", "-i", "--name box"):
        assert flag in joined, flag
    assert command[-4:] == ("img:tag", "lake", "env", sandbox.REPL_IN_IMAGE)
    assert "-v" not in command and "--volume" not in joined  # nothing from the host is mounted


def test_missing_docker_or_image_explains_what_to_do(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox, "find_docker", lambda: None)
    with pytest.raises(LeanUnavailableError, match="Docker is not installed"):
        sandbox.make_sandbox_runner("img:tag", 120, tmp_path)
    monkeypatch.setattr(sandbox, "find_docker", lambda: "docker")
    monkeypatch.setattr(sandbox, "image_available", lambda docker, image: False)
    with pytest.raises(LeanUnavailableError, match=r"docker build -f docker/lean-sandbox\.Dockerfile -t img:tag \."):
        sandbox.make_sandbox_runner("img:tag", 120, tmp_path)


def test_runner_removes_its_container_and_never_falls_back(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(sandbox, "find_docker", lambda: "docker")
    monkeypatch.setattr(sandbox, "image_available", lambda docker, image: True)
    monkeypatch.setattr(sandbox.subprocess, "run", lambda args, **kw: calls.append(args))
    runner = sandbox.make_sandbox_runner("img:tag", 120, tmp_path)
    assert isinstance(runner, ReplLeanRunner) and runner.fallback is None
    name = runner.command[runner.command.index("--name") + 1]
    assert name.startswith("ra-checker-lean-")
    runner._on_stop()
    assert calls == [["docker", "rm", "-f", name]]
    with pytest.raises(LeanUnavailableError, match="not available in the Lean REPL"):
        runner.run("import Mathlib.Topology.Basic\n\ntheorem t : True := trivial\n")


def test_version_comes_from_the_image_when_there_is_no_fallback(tmp_path):
    script = tmp_path / "version.py"
    script.write_text("print('Lean (version 4.36.0, in the image)')", encoding="utf-8")
    runner = ReplLeanRunner(tmp_path, 10, command=("unused",), version_command=(sys.executable, str(script)))
    assert runner.lean_version() == "Lean (version 4.36.0, in the image)"


def test_docker_setting_and_runner_choice(monkeypatch, tmp_path):
    env = {"RA_LEAN_PROJECT_DIR": str(tmp_path), ENV_LEAN_RUNNER: "docker"}
    settings = load_settings(environ=env, dotenv_path=None)
    assert settings.lean_runner == "docker" and settings.lean_docker_image == DEFAULT_LEAN_DOCKER_IMAGE
    custom = load_settings(environ={**env, ENV_LEAN_DOCKER_IMAGE: "mine:1"}, dotenv_path=None)
    assert custom.lean_docker_image == "mine:1"
    chosen = []
    monkeypatch.setattr(setup, "make_sandbox_runner", lambda image, timeout, workdir: chosen.append(image) or "sandbox")
    assert setup.choose_lean_runner(custom) == "sandbox" and chosen == ["mine:1"]
