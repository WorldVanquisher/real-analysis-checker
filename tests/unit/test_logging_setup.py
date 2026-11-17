"""Tests for ra_checker.logging_setup: redaction, idempotence, levels."""

import io
import logging

import pytest

from ra_checker.logging_setup import (
    PACKAGE_LOGGER,
    REDACTED,
    configure_logging,
    text_fingerprint,
)

REGISTERED_SECRET = "my-registered-secret-value-42"
ANTHROPIC_SHAPED_KEY = "sk-ant-api03-AbC_dEf-123456"


@pytest.fixture
def log_stream():
    stream = io.StringIO()
    yield stream
    # Leave the package logger clean for other tests.
    logger = logging.getLogger(PACKAGE_LOGGER)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    logger.setLevel(logging.NOTSET)
    logger.propagate = True


def test_registered_secret_is_redacted(log_stream):
    configure_logging("INFO", secrets=[REGISTERED_SECRET], stream=log_stream)
    logging.getLogger("ra_checker.llm").info("calling API with key %s", REGISTERED_SECRET)
    output = log_stream.getvalue()
    assert REGISTERED_SECRET not in output
    assert REDACTED in output
    assert "ra_checker.llm" in output


def test_anthropic_shaped_key_is_redacted_without_registration(log_stream):
    configure_logging("INFO", stream=log_stream)
    logging.getLogger("ra_checker").warning("header x-api-key=%s", ANTHROPIC_SHAPED_KEY)
    output = log_stream.getvalue()
    assert ANTHROPIC_SHAPED_KEY not in output
    assert "x-api-key=" + REDACTED in output


def test_secret_inside_traceback_is_redacted(log_stream):
    configure_logging("INFO", secrets=[REGISTERED_SECRET], stream=log_stream)
    try:
        raise RuntimeError(f"auth failed for {REGISTERED_SECRET}")
    except RuntimeError:
        logging.getLogger("ra_checker.pipeline").exception("LLM call failed")
    output = log_stream.getvalue()
    assert "Traceback" in output
    assert REGISTERED_SECRET not in output


def test_repeated_configuration_does_not_duplicate_output(log_stream):
    configure_logging("INFO", stream=log_stream)
    configure_logging("INFO", stream=log_stream)
    logging.getLogger("ra_checker").info("only once")
    assert log_stream.getvalue().count("only once") == 1
    assert len(logging.getLogger(PACKAGE_LOGGER).handlers) == 1


def test_level_is_applied(log_stream):
    configure_logging("warning", stream=log_stream)
    logger = logging.getLogger("ra_checker.lean")
    logger.info("hidden")
    logger.warning("shown")
    output = log_stream.getvalue()
    assert "hidden" not in output
    assert "shown" in output


def test_records_do_not_propagate_to_root(log_stream):
    root_stream = io.StringIO()
    root_handler = logging.StreamHandler(root_stream)
    logging.getLogger().addHandler(root_handler)
    try:
        configure_logging("INFO", secrets=[REGISTERED_SECRET], stream=log_stream)
        logging.getLogger("ra_checker").info("key %s", REGISTERED_SECRET)
    finally:
        logging.getLogger().removeHandler(root_handler)
    assert root_stream.getvalue() == ""


def test_text_fingerprint_hides_content_but_is_stable():
    text = "Let ε > 0. Choose N > 1/ε."
    fingerprint = text_fingerprint(text)
    assert text not in fingerprint
    assert "ε" not in fingerprint
    assert fingerprint.startswith(f"len={len(text)} sha256=")
    assert fingerprint == text_fingerprint(text)
    assert fingerprint != text_fingerprint(text + " ")
