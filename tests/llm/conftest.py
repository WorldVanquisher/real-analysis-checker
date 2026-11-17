"""Fixtures for live LLM tests (opt-in: `pytest -m llm`; they cost money)."""

import pytest

from ra_checker.config import load_settings
from ra_checker.llm.client import AnthropicClient


@pytest.fixture(scope="session")
def live_llm():
    settings = load_settings()
    if not settings.has_api_key:
        pytest.skip("ANTHROPIC_API_KEY is not set (environment or .env)")
    return AnthropicClient(settings)
