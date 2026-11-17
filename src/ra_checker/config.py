"""Application settings from environment variables and an optional ``.env`` file.

Nothing is read at import time: call :func:`load_settings`. The API key is
optional at load time so that the UI, tests and Lean-only tools work without
it; code that calls the LLM must use :meth:`Settings.require_api_key`, which
raises a clear :class:`ConfigError` when the key is missing.

Error messages never contain the API key.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DOTENV_PATH = PROJECT_ROOT / ".env"

ENV_API_KEY = "ANTHROPIC_API_KEY"
ENV_MODEL = "RA_CHECKER_MODEL"
ENV_LEAN_PROJECT_DIR = "RA_LEAN_PROJECT_DIR"
ENV_LEAN_TIMEOUT_S = "RA_LEAN_TIMEOUT_S"
ENV_LOG_LEVEL = "RA_LOG_LEVEL"

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_LEAN_TIMEOUT_S = 120.0
MAX_LEAN_TIMEOUT_S = 3600.0

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
LOG_LEVELS: tuple[str, ...] = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class ConfigError(Exception):
    """Missing or invalid configuration. Messages never contain secrets."""


class Settings(BaseModel):
    """Validated, immutable application settings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    anthropic_api_key: SecretStr | None = None
    llm_model: str = Field(default=DEFAULT_MODEL, min_length=1)
    lean_project_dir: Path = PROJECT_ROOT / "lean"
    lean_timeout_s: float = Field(
        default=DEFAULT_LEAN_TIMEOUT_S, gt=0, le=MAX_LEAN_TIMEOUT_S
    )
    log_level: LogLevel = "INFO"

    @property
    def has_api_key(self) -> bool:
        return self.anthropic_api_key is not None

    def require_api_key(self) -> str:
        """Return the API key, or raise ConfigError explaining how to set it."""
        if self.anthropic_api_key is None:
            raise ConfigError(
                f"{ENV_API_KEY} is not set. Set it as an environment variable, "
                "or copy .env.example to .env and fill it in."
            )
        return self.anthropic_api_key.get_secret_value()


def load_settings(
    environ: Mapping[str, str] | None = None,
    dotenv_path: Path | None = DEFAULT_DOTENV_PATH,
) -> Settings:
    """Build Settings from ``environ`` (default: ``os.environ``) and a .env file.

    Real environment variables take precedence over the .env file. Empty values
    count as unset. Pass ``dotenv_path=None`` to ignore .env files entirely.
    """
    values: dict[str, str] = {}
    if dotenv_path is not None and dotenv_path.is_file():
        values.update(
            {k: v for k, v in dotenv_values(dotenv_path).items() if v is not None}
        )
    values.update(os.environ if environ is None else environ)

    def get(name: str) -> str | None:
        raw = values.get(name)
        if raw is None:
            return None
        raw = raw.strip()
        return raw or None

    api_key = get(ENV_API_KEY)
    lean_dir = get(ENV_LEAN_PROJECT_DIR)
    return Settings(
        anthropic_api_key=SecretStr(api_key) if api_key else None,
        llm_model=get(ENV_MODEL) or DEFAULT_MODEL,
        lean_project_dir=_resolve_project_path(lean_dir)
        if lean_dir
        else PROJECT_ROOT / "lean",
        lean_timeout_s=_parse_timeout(get(ENV_LEAN_TIMEOUT_S)),
        log_level=_parse_log_level(get(ENV_LOG_LEVEL)),
    )


def _resolve_project_path(raw: str) -> Path:
    """Relative paths are taken relative to the project root, not the cwd."""
    path = Path(raw).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def _parse_timeout(raw: str | None) -> float:
    if raw is None:
        return DEFAULT_LEAN_TIMEOUT_S
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(
            f"{ENV_LEAN_TIMEOUT_S} must be a number of seconds, got {raw!r}."
        ) from None
    if not math.isfinite(value) or not 0 < value <= MAX_LEAN_TIMEOUT_S:
        raise ConfigError(
            f"{ENV_LEAN_TIMEOUT_S} must be greater than 0 and at most "
            f"{MAX_LEAN_TIMEOUT_S:g} seconds, got {raw!r}."
        )
    return value


def _parse_log_level(raw: str | None) -> LogLevel:
    if raw is None:
        return "INFO"
    level = raw.upper()
    if level not in LOG_LEVELS:
        raise ConfigError(
            f"{ENV_LOG_LEVEL} must be one of {', '.join(LOG_LEVELS)}, got {raw!r}."
        )
    return level  # type: ignore[return-value]
