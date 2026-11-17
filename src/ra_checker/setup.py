"""Builds the real Checker (Claude + local Lean), or explains what is missing.
Shared by the Streamlit app and the evaluation command line."""

from __future__ import annotations

from ra_checker.config import ConfigError, Settings, load_settings
from ra_checker.lean.runner import LeanUnavailableError, SubprocessLeanRunner
from ra_checker.llm.client import AnthropicClient, LLMUnavailableError
from ra_checker.logging_setup import configure_logging
from ra_checker.pipeline import Checker


def build_checker(settings: Settings | None = None) -> tuple[Checker | None, list[str]]:
    try:
        settings = settings or load_settings()
    except ConfigError as exc:
        return None, [f"Configuration problem: {exc}"]
    secrets = [settings.require_api_key()] if settings.has_api_key else []
    configure_logging(settings.log_level, secrets=secrets)

    problems: list[str] = []
    llm = lean = None
    try:
        llm = AnthropicClient(settings)
    except LLMUnavailableError as exc:
        problems.append(f"The LLM is not available: {exc}")
    try:
        lean = SubprocessLeanRunner(settings.lean_project_dir, settings.lean_timeout_s)
    except LeanUnavailableError as exc:
        problems.append(str(exc))
    if not (settings.lean_project_dir / ".lake" / "packages" / "mathlib").is_dir():
        problems.append(
            "Mathlib is not set up in the Lean project: run `lake exe cache get` and "
            "`lake build` in the lean/ folder (see the README)."
        )
    if problems or llm is None or lean is None:
        return None, problems
    return Checker(llm, lean), []
