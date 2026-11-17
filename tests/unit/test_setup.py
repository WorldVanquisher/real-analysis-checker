"""Tests for RA_LEAN_RUNNER and ra_checker.setup.choose_lean_runner (no Lean needed)."""

from pathlib import Path

import pytest

from ra_checker import setup
from ra_checker.config import ENV_LEAN_RUNNER, ConfigError, load_settings
from ra_checker.lean import repl, runner
from ra_checker.lean.repl import ReplLeanRunner
from ra_checker.lean.runner import LeanUnavailableError, SubprocessLeanRunner


def settings(tmp_path, mode=None):
    env = {"RA_LEAN_PROJECT_DIR": str(tmp_path)}
    if mode is not None:
        env[ENV_LEAN_RUNNER] = mode
    return load_settings(environ=env, dotenv_path=None)


@pytest.fixture
def fake_lean(monkeypatch, tmp_path):
    fake_lake = tmp_path / "lake.exe"
    monkeypatch.setattr(runner, "find_lake", lambda: fake_lake)
    monkeypatch.setattr(repl, "find_lake", lambda: fake_lake)
    built = {"repl": True}
    monkeypatch.setattr(repl, "find_repl", lambda d: tmp_path / "repl.exe" if built["repl"] else None)
    monkeypatch.setattr(setup, "find_repl", lambda d: tmp_path / "repl.exe" if built["repl"] else None)
    return built


def test_setting_defaults_and_validation(tmp_path):
    assert settings(tmp_path).lean_runner == "auto"
    assert settings(tmp_path, "CLI").lean_runner == "cli"
    with pytest.raises(ConfigError, match=ENV_LEAN_RUNNER):
        settings(tmp_path, "docker-ish")


def test_auto_uses_the_repl_when_built(fake_lean, tmp_path):
    chosen = setup.choose_lean_runner(settings(tmp_path))
    assert isinstance(chosen, ReplLeanRunner)
    assert isinstance(chosen.fallback, SubprocessLeanRunner)  # for imports beyond Mathlib + RaChecker


def test_auto_falls_back_to_the_command_line_when_not_built(fake_lean, tmp_path):
    fake_lean["repl"] = False
    assert isinstance(setup.choose_lean_runner(settings(tmp_path)), SubprocessLeanRunner)


def test_repl_required_but_missing_says_how_to_build_it(fake_lean, tmp_path):
    fake_lean["repl"] = False
    with pytest.raises(LeanUnavailableError, match="lake build repl"):
        setup.choose_lean_runner(settings(tmp_path, "repl"))


def test_cli_mode_ignores_the_repl(fake_lean, tmp_path):
    assert isinstance(setup.choose_lean_runner(settings(tmp_path, "cli")), SubprocessLeanRunner)


def test_find_repl_points_into_the_lake_build(tmp_path):
    assert repl.find_repl(tmp_path) is None
    exe = "repl.exe" if Path(runner.__file__).drive else "repl"
    path = tmp_path / ".lake" / "packages" / "REPL" / ".lake" / "build" / "bin" / exe
    path.parent.mkdir(parents=True)
    path.write_text("")
    assert repl.find_repl(tmp_path) == path
