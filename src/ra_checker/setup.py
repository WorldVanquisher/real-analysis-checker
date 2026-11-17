"""Builds the real Checker (Claude + Lean), or explains what is missing.
Shared by the Streamlit app and the evaluation command line."""

from __future__ import annotations

from ra_checker.config import ConfigError, Settings, load_settings
from ra_checker.lean.repl import ReplLeanRunner, find_repl
from ra_checker.lean.runner import LeanUnavailableError, SubprocessLeanRunner
from ra_checker.lean.sandbox import make_sandbox_runner
from ra_checker.lean.warmup import WarmingLeanRunner
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
        runner = choose_lean_runner(settings)
    except LeanUnavailableError as exc:
        problems.append(str(exc))
    else:
        # In Docker mode, Lean and Mathlib live in the image, not on this machine.
        lean_ready = settings.lean_runner == "docker" or (
            settings.lean_project_dir / ".lake" / "packages" / "mathlib"
        ).is_dir()
        if not lean_ready:
            problems.append(
                "Mathlib is not set up in the Lean project: run `lake exe cache get` and "
                "`lake build` in the lean/ folder (see the README)."
            )
        # Start loading Mathlib now: the first run after a restart can take minutes.
        lean = WarmingLeanRunner(runner, start=lean_ready and not problems)
    if problems or llm is None or lean is None:
        return None, problems
    return Checker(llm, lean), []


def choose_lean_runner(settings: Settings) -> SubprocessLeanRunner | ReplLeanRunner:
    """RA_LEAN_RUNNER: ``auto`` uses the REPL when it is built, ``repl`` requires
    it, ``cli`` always starts Lean per check, ``docker`` runs the REPL in a
    no-network container. Raises LeanUnavailableError."""
    if settings.lean_runner == "docker":
        return make_sandbox_runner(settings.lean_docker_image, settings.lean_timeout_s, settings.lean_project_dir)
    cli = SubprocessLeanRunner(settings.lean_project_dir, settings.lean_timeout_s)
    if settings.lean_runner == "cli":
        return cli
    if find_repl(settings.lean_project_dir) is None:
        if settings.lean_runner == "repl":
            raise LeanUnavailableError(
                "RA_LEAN_RUNNER=repl, but the Lean REPL is not built: run `lake build repl` "
                "in the lean/ folder."
            )
        return cli
    return ReplLeanRunner(settings.lean_project_dir, settings.lean_timeout_s, fallback=cli)
