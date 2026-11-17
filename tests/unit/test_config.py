"""Tests for ra_checker.config (no network, no Lean, no real .env)."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from ra_checker.config import (
    DEFAULT_LEAN_TIMEOUT_S,
    DEFAULT_MODEL,
    ENV_API_KEY,
    ENV_LEAN_PROJECT_DIR,
    ENV_LEAN_TIMEOUT_S,
    ENV_LOG_LEVEL,
    ENV_MODEL,
    PROJECT_ROOT,
    ConfigError,
    load_settings,
)

FAKE_KEY = "sk-ant-test-0123456789abcdef"


def load(env: dict[str, str], dotenv_path: Path | None = None):
    return load_settings(environ=env, dotenv_path=dotenv_path)


def test_defaults_without_any_configuration():
    settings = load({})
    assert settings.anthropic_api_key is None
    assert not settings.has_api_key
    assert settings.llm_model == DEFAULT_MODEL
    assert settings.lean_project_dir == PROJECT_ROOT / "lean"
    assert settings.lean_timeout_s == DEFAULT_LEAN_TIMEOUT_S
    assert settings.log_level == "INFO"


def test_environment_overrides():
    settings = load(
        {
            ENV_API_KEY: FAKE_KEY,
            ENV_MODEL: "claude-sonnet-5-5",
            ENV_LEAN_TIMEOUT_S: "45.5",
            ENV_LOG_LEVEL: "debug",
        }
    )
    assert settings.require_api_key() == FAKE_KEY
    assert settings.llm_model == "claude-sonnet-5-5"
    assert settings.lean_timeout_s == 45.5
    assert settings.log_level == "DEBUG"


def test_missing_key_only_fails_when_required():
    settings = load({})  # loading must not fail without a key
    with pytest.raises(ConfigError) as excinfo:
        settings.require_api_key()
    message = str(excinfo.value)
    assert ENV_API_KEY in message
    assert ".env.example" in message


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_values_count_as_unset(blank):
    settings = load({ENV_API_KEY: blank, ENV_MODEL: blank, ENV_LOG_LEVEL: blank})
    assert settings.anthropic_api_key is None
    assert settings.llm_model == DEFAULT_MODEL
    assert settings.log_level == "INFO"


def test_key_never_appears_in_repr_str_or_json():
    settings = load({ENV_API_KEY: FAKE_KEY})
    assert FAKE_KEY not in repr(settings)
    assert FAKE_KEY not in str(settings)
    assert FAKE_KEY not in settings.model_dump_json()


def test_dotenv_file_is_read_and_environment_wins(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        f"{ENV_API_KEY}={FAKE_KEY}\n{ENV_MODEL}=from-dotenv\n{ENV_LEAN_TIMEOUT_S}=30\n",
        encoding="utf-8",
    )
    settings = load({ENV_MODEL: "from-environment"}, dotenv_path=dotenv)
    assert settings.require_api_key() == FAKE_KEY
    assert settings.llm_model == "from-environment"
    assert settings.lean_timeout_s == 30


def test_missing_dotenv_file_is_ignored(tmp_path):
    settings = load({}, dotenv_path=tmp_path / "does-not-exist.env")
    assert settings.anthropic_api_key is None


def test_relative_lean_dir_resolves_against_project_root(tmp_path):
    assert load({ENV_LEAN_PROJECT_DIR: "custom/lean"}).lean_project_dir == (
        PROJECT_ROOT / "custom" / "lean"
    )
    absolute = tmp_path / "lean-project"
    assert load({ENV_LEAN_PROJECT_DIR: str(absolute)}).lean_project_dir == absolute


@pytest.mark.parametrize("bad", ["abc", "0", "-5", "nan", "inf", "3601"])
def test_invalid_timeout_is_rejected_with_variable_name(bad):
    with pytest.raises(ConfigError, match=ENV_LEAN_TIMEOUT_S):
        load({ENV_LEAN_TIMEOUT_S: bad})


def test_invalid_log_level_is_rejected():
    with pytest.raises(ConfigError, match=ENV_LOG_LEVEL):
        load({ENV_LOG_LEVEL: "verbose"})


def test_config_errors_do_not_leak_the_key():
    with pytest.raises(ConfigError) as excinfo:
        load({ENV_API_KEY: FAKE_KEY, ENV_LEAN_TIMEOUT_S: "soon"})
    assert FAKE_KEY not in str(excinfo.value)


def test_settings_are_immutable():
    settings = load({})
    with pytest.raises(ValidationError):
        settings.llm_model = "other"  # type: ignore[misc]
