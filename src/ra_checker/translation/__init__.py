"""Lean translation: the statement (stage 2a) and the proof (stage 2b)."""

from __future__ import annotations

from ra_checker.llm.client import (
    LLMError,
    LLMOutputError,
    LLMRefusalError,
    LLMUnavailableError,
)
from ra_checker.models import VerificationStatus


def status_for_llm_error(error: LLMError) -> VerificationStatus:
    """Unavailable → RUNTIME_ERROR; refusal or unusable answer → TRANSLATION_FAILED."""
    if isinstance(error, LLMUnavailableError):
        return VerificationStatus.RUNTIME_ERROR
    if isinstance(error, (LLMRefusalError, LLMOutputError)):
        return VerificationStatus.TRANSLATION_FAILED
    return VerificationStatus.RUNTIME_ERROR
