"""Structured LLM calls.

Every LLM step in the pipeline is one small call whose answer must validate
against a Pydantic schema. Failures are reported with three exception types
that the pipeline maps to report statuses:

* :class:`LLMUnavailableError` — no key, network, rate limit, server error →
  ``RUNTIME_ERROR``;
* :class:`LLMRefusalError` — the model declined → ``TRANSLATION_FAILED``;
* :class:`LLMOutputError` — the answer was cut off or did not fit the schema →
  ``TRANSLATION_FAILED``.

Error messages never contain the API key or the student's text.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Generic, Literal, Protocol, TypeVar

import anthropic
import pydantic

from ra_checker.config import ConfigError, Settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=pydantic.BaseModel)
Effort = Literal["low", "medium", "high", "xhigh", "max"]

DEFAULT_MAX_TOKENS = 16_000
FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Models that accept the server-side refusal fallback (`fallbacks="default"`).
FALLBACK_MODELS = frozenset(
    {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-2", "claude-fable-5-1", "claude-sonnet-5-5"}
)


class LLMError(Exception):
    """Base class for LLM failures."""


class LLMUnavailableError(LLMError):
    """The LLM could not be reached or used (maps to RUNTIME_ERROR)."""


class LLMRefusalError(LLMError):
    """The model declined the request (maps to TRANSLATION_FAILED)."""


class LLMOutputError(LLMError):
    """The answer was truncated or invalid (maps to TRANSLATION_FAILED)."""


@dataclass(frozen=True)
class LLMRequest:
    task: str
    system: str
    user: str
    schema: type[pydantic.BaseModel]
    effort: Effort
    max_tokens: int


@dataclass(frozen=True)
class StructuredResult(Generic[T]):
    value: T
    model: str  # the model that actually served the answer
    request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    duration_s: float = 0.0


class LLMClient(Protocol):
    def complete_structured(
        self,
        *,
        task: str,
        system: str,
        user: str,
        schema: type[T],
        effort: Effort = "high",
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> StructuredResult[T]: ...


class AnthropicClient:
    """Claude via the official SDK, using structured outputs (``messages.parse``)."""

    def __init__(self, settings: Settings, *, sdk_client: anthropic.Anthropic | None = None):
        self.model = settings.llm_model
        if sdk_client is None:
            try:
                api_key = settings.require_api_key()
            except ConfigError as exc:
                raise LLMUnavailableError(str(exc)) from None
            sdk_client = anthropic.Anthropic(
                api_key=api_key, timeout=settings.llm_timeout_s, max_retries=2
            )
        self._sdk = sdk_client

    def complete_structured(
        self,
        *,
        task: str,
        system: str,
        user: str,
        schema: type[T],
        effort: Effort = "high",
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> StructuredResult[T]:
        kwargs: dict = dict(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema,
            output_config={"effort": effort},
        )
        if self.model in FALLBACK_MODELS:
            kwargs.update(betas=[FALLBACK_BETA], fallbacks="default")

        start = time.monotonic()
        try:
            response = self._sdk.beta.messages.parse(**kwargs)
        except (anthropic.APIError, pydantic.ValidationError) as exc:
            # Diagnostics for the operator: the type and underlying cause, never the
            # response body (the redacting log formatter also strips any key).
            cause = exc.__cause__ or exc.__context__
            logger.warning(
                "llm task=%s failed: %s%s request=%s",
                task,
                type(exc).__name__,
                f" caused by {type(cause).__name__}: {str(cause)[:200]}" if cause else "",
                getattr(getattr(exc, "response", None), "headers", {}).get("request-id"),
            )
            raise self._translate(exc) from None
        duration = time.monotonic() - start

        usage = getattr(response, "usage", None)
        result_meta = dict(
            model=getattr(response, "model", None) or self.model,
            request_id=getattr(response, "_request_id", None),
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            duration_s=duration,
        )
        logger.info(
            "llm task=%s model=%s stop=%s in=%s out=%s %.1fs request=%s",
            task,
            result_meta["model"],
            response.stop_reason,
            result_meta["input_tokens"],
            result_meta["output_tokens"],
            duration,
            result_meta["request_id"],
        )

        if response.stop_reason == "refusal":
            raise LLMRefusalError("The model declined to process this input.")
        if response.stop_reason == "max_tokens":
            raise LLMOutputError("The LLM's answer was cut off before it was complete.")
        value = response.parsed_output
        if not isinstance(value, schema):
            raise LLMOutputError("The LLM did not return a structured answer.")
        return StructuredResult(value=value, **result_meta)


    def _translate(self, exc: Exception) -> LLMError:
        """Map an SDK error to the pipeline's three error types (most specific first)."""
        if isinstance(exc, pydantic.ValidationError):
            return LLMOutputError("The LLM's answer did not match the expected format.")
        if isinstance(exc, anthropic.AuthenticationError):
            return LLMUnavailableError("The Anthropic API rejected the API key.")
        if isinstance(exc, anthropic.PermissionDeniedError):
            return LLMUnavailableError("The API key is not allowed to use this model.")
        if isinstance(exc, anthropic.NotFoundError):
            return LLMUnavailableError(f"The model '{self.model}' is not available.")
        if isinstance(exc, anthropic.RateLimitError):
            return LLMUnavailableError("The LLM API is rate-limiting requests; try again shortly.")
        if isinstance(exc, anthropic.BadRequestError):
            return LLMUnavailableError(f"The LLM API rejected the request (HTTP {exc.status_code}).")
        if isinstance(exc, anthropic.APIStatusError):
            return LLMUnavailableError(f"The LLM API returned an error (HTTP {exc.status_code}).")
        if isinstance(exc, anthropic.APITimeoutError):
            return LLMUnavailableError("The LLM API did not answer in time.")
        if isinstance(exc, anthropic.APIConnectionError):
            return LLMUnavailableError("Could not connect to the LLM API.")
        return LLMUnavailableError(f"The LLM API call failed ({type(exc).__name__}).")


Responder = pydantic.BaseModel | Exception | Callable[[LLMRequest], pydantic.BaseModel]


class FakeLLMClient:
    """Test double. ``responses`` maps a task name to a model instance, an
    exception to raise, or a callable that builds the answer from the request."""

    def __init__(self, responses: Mapping[str, Responder], *, model: str = "fake-model"):
        self.responses = dict(responses)
        self.model = model
        self.requests: list[LLMRequest] = []

    def complete_structured(
        self,
        *,
        task: str,
        system: str,
        user: str,
        schema: type[T],
        effort: Effort = "high",
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> StructuredResult[T]:
        request = LLMRequest(task, system, user, schema, effort, max_tokens)
        self.requests.append(request)
        if task not in self.responses:
            raise LLMUnavailableError(f"FakeLLMClient has no response for task '{task}'")
        responder = self.responses[task]
        if isinstance(responder, Exception):
            raise responder
        value = responder(request) if callable(responder) and not isinstance(
            responder, pydantic.BaseModel
        ) else responder
        if not isinstance(value, schema):
            raise LLMOutputError(f"fake response for '{task}' is not a {schema.__name__}")
        return StructuredResult(value=value, model=self.model, request_id="fake")
