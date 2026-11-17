"""Logging configuration for the ``ra_checker`` package.

Policy for every module:

* log ids, statuses, sizes and timings;
* never log API keys — the handler installed here redacts registered secrets
  and anything shaped like an Anthropic key, including inside tracebacks;
* do not log full student text at INFO or above; use :func:`text_fingerprint`.

Modules get their logger with ``logging.getLogger(__name__)``; because they
live under the ``ra_checker`` package, the handler configured here applies.
"""

from __future__ import annotations

import hashlib
import logging
import re
import sys
from collections.abc import Iterable
from typing import TextIO

PACKAGE_LOGGER = "ra_checker"
REDACTED = "[REDACTED]"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

_ANTHROPIC_KEY_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9_\-]+")
_HANDLER_MARKER = "_ra_checker_handler"


class RedactingFormatter(logging.Formatter):
    """Formats records, then removes secrets from the finished text."""

    def __init__(self, fmt: str = LOG_FORMAT, secrets: Iterable[str] = ()) -> None:
        super().__init__(fmt)
        # Longest first, so a secret containing another is fully replaced.
        self._secrets = sorted({s for s in secrets if s}, key=len, reverse=True)

    def redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, REDACTED)
        return _ANTHROPIC_KEY_PATTERN.sub(REDACTED, text)

    def format(self, record: logging.LogRecord) -> str:
        return self.redact(super().format(record))


def configure_logging(
    level: str = "INFO",
    *,
    secrets: Iterable[str] = (),
    stream: TextIO | None = None,
) -> logging.Logger:
    """Install one redacting handler on the package logger and return it.

    Safe to call repeatedly: the previous handler installed by this function is
    replaced, never duplicated. Records do not propagate to the root logger, so
    host frameworks (e.g. Streamlit) do not print them a second time unredacted.
    """
    logger = logging.getLogger(PACKAGE_LOGGER)
    for handler in list(logger.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            logger.removeHandler(handler)
            handler.close()

    handler = logging.StreamHandler(stream if stream is not None else sys.stderr)
    handler.setFormatter(RedactingFormatter(LOG_FORMAT, secrets))
    setattr(handler, _HANDLER_MARKER, True)
    logger.addHandler(handler)
    logger.setLevel(level.upper())
    logger.propagate = False
    return logger


def text_fingerprint(text: str) -> str:
    """Identify a piece of student text in logs without revealing it."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"len={len(text)} sha256={digest}"
