"""Shared fixtures for tests that need a real Lean + Mathlib installation."""

import pytest

from ra_checker.config import load_settings
from ra_checker.lean.runner import SubprocessLeanRunner, find_lake


@pytest.fixture(scope="session")
def lean_project_dir():
    project = load_settings(environ={}, dotenv_path=None).lean_project_dir
    if find_lake() is None:
        pytest.skip("Lean is not installed (lake not found)")
    if not (project / ".lake" / "packages" / "mathlib").is_dir():
        pytest.skip("Mathlib is not set up in the Lean project (run `lake exe cache get`)")
    return project


@pytest.fixture(scope="session")
def lean_runner(lean_project_dir):
    return SubprocessLeanRunner(lean_project_dir, timeout_s=300)
