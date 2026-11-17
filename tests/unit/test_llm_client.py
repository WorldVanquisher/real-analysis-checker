"""Tests for ra_checker.llm.client — no network: the SDK is replaced by a stub."""

from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from pydantic import BaseModel

from ra_checker.config import Settings, load_settings
from ra_checker.llm.client import (
    FALLBACK_BETA,
    AnthropicClient,
    FakeLLMClient,
    LLMOutputError,
    LLMRefusalError,
    LLMUnavailableError,
)

SECRET = "sk-ant-api03-very-secret-key"
REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


class Answer(BaseModel):
    text: str


class Other(BaseModel):
    n: int


class StubSDK:
    def __init__(self, response=None, error=None):
        self.response, self.error = response, error
        self.calls: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(parse=self._parse))

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


def response(stop_reason="end_turn", parsed=Answer(text="ok"), model="claude-opus-5-5"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        parsed_output=parsed,
        model=model,
        usage=SimpleNamespace(input_tokens=120, output_tokens=30),
        _request_id="req_123",
    )


def client(sdk, model="claude-opus-5-5") -> AnthropicClient:
    return AnthropicClient(Settings(llm_model=model), sdk_client=sdk)


def call(c, **overrides):
    kwargs = dict(task="t", system="sys", user="hello", schema=Answer, effort="medium")
    kwargs.update(overrides)
    return c.complete_structured(**kwargs)


def status_error(cls, status):
    return cls(f"error mentioning {SECRET}", response=httpx2.Response(status, request=REQUEST), body=None)


def test_missing_key_is_reported_before_any_request():
    settings = load_settings(environ={}, dotenv_path=None)
    with pytest.raises(LLMUnavailableError, match="ANTHROPIC_API_KEY"):
        AnthropicClient(settings)


def test_request_shape_for_opus():
    sdk = StubSDK(response())
    result = call(client(sdk), max_tokens=2000)
    (kwargs,) = sdk.calls
    assert kwargs["model"] == "claude-opus-5-5"
    assert kwargs["system"] == "sys"
    assert kwargs["messages"] == [{"role": "user", "content": "hello"}]
    assert kwargs["output_format"] is Answer
    assert kwargs["output_config"] == {"effort": "medium"}
    assert kwargs["max_tokens"] == 2000
    assert kwargs["betas"] == [FALLBACK_BETA] and kwargs["fallbacks"] == "default"
    assert "thinking" not in kwargs  # Opus 5.5 always thinks adaptively
    assert result.value == Answer(text="ok")
    assert (result.model, result.request_id, result.input_tokens, result.output_tokens) == (
        "claude-opus-5-5", "req_123", 120, 30,
    )


def test_no_fallback_parameters_for_models_without_support():
    sdk = StubSDK(response(model="claude-haiku-5-5"))
    call(client(sdk, model="claude-haiku-5-5"))
    assert "betas" not in sdk.calls[0] and "fallbacks" not in sdk.calls[0]


def test_served_model_is_recorded_after_a_fallback():
    result = call(client(StubSDK(response(model="claude-opus-4-8"))))
    assert result.model == "claude-opus-4-8"


@pytest.mark.parametrize(
    "resp, error, message",
    [
        (response(stop_reason="refusal", parsed=None), LLMRefusalError, "declined"),
        (response(stop_reason="max_tokens", parsed=None), LLMOutputError, "cut off"),
        (response(parsed=None), LLMOutputError, "structured answer"),
        (response(parsed=Other(n=1)), LLMOutputError, "structured answer"),
    ],
)
def test_unusable_answers(resp, error, message):
    with pytest.raises(error, match=message):
        call(client(StubSDK(resp)))


@pytest.mark.parametrize(
    "sdk_error, message",
    [
        (status_error(anthropic.AuthenticationError, 401), "rejected the API key"),
        (status_error(anthropic.PermissionDeniedError, 403), "not allowed"),
        (status_error(anthropic.NotFoundError, 404), "not available"),
        (status_error(anthropic.RateLimitError, 429), "rate-limiting"),
        (status_error(anthropic.BadRequestError, 400), "HTTP 400"),
        (status_error(anthropic.InternalServerError, 500), "HTTP 500"),
        (anthropic.APITimeoutError(request=REQUEST), "did not answer in time"),
        (anthropic.APIConnectionError(request=REQUEST), "Could not connect"),
    ],
)
def test_sdk_errors_map_to_unavailable_without_leaking(sdk_error, message):
    with pytest.raises(LLMUnavailableError, match=message) as excinfo:
        call(client(StubSDK(error=sdk_error)))
    assert SECRET not in str(excinfo.value)
    assert excinfo.value.__cause__ is None  # SDK error (with its body) not chained


def test_failures_are_logged_with_their_cause_but_never_the_key(caplog):
    error = anthropic.APIConnectionError(request=REQUEST)
    error.__cause__ = OSError(f"getaddrinfo failed while sending {SECRET}")
    with caplog.at_level("WARNING", logger="ra_checker"), pytest.raises(LLMUnavailableError):
        call(client(StubSDK(error=error)), task="parse_problem")
    assert "llm task=parse_problem failed: APIConnectionError caused by OSError: getaddrinfo failed" in caplog.text
    # The raw record keeps the cause text; the redacting formatter installed by
    # configure_logging removes keys from what is written — checked in test_logging_setup.


def test_fake_client_variants():
    fake = FakeLLMClient(
        {
            "fixed": Answer(text="a"),
            "built": lambda req: Answer(text=req.user.upper()),
            "broken": LLMRefusalError("no"),
            "wrong": Other(n=1),
        }
    )
    assert call(fake, task="fixed").value.text == "a"
    assert call(fake, task="built", user="hi").value.text == "HI"
    with pytest.raises(LLMRefusalError):
        call(fake, task="broken")
    with pytest.raises(LLMOutputError):
        call(fake, task="wrong")
    with pytest.raises(LLMUnavailableError, match="no response for task 'missing'"):
        call(fake, task="missing")
    assert [r.task for r in fake.requests] == ["fixed", "built", "broken", "wrong", "missing"]
