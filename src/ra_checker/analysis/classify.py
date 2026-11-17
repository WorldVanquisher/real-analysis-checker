"""Rule-based classification of Lean error messages (no LLM).

Patterns come from real Lean 4.36 output (``tests/fixtures/lean_output/``).
Matching is case-insensitive because Lean's wording has changed between
versions (``type mismatch`` became ``Type mismatch``).
"""

from __future__ import annotations

import re

from ra_checker.models import LeanErrorKind

_RULES: tuple[tuple[LeanErrorKind, re.Pattern[str]], ...] = (
    (LeanErrorKind.SYNTAX, re.compile(r"^unexpected (token|end of input|identifier)|^expected ", re.I)),
    (LeanErrorKind.UNKNOWN_IDENTIFIER, re.compile(r"^unknown (identifier|constant|namespace)", re.I)),
    (LeanErrorKind.UNSOLVED_GOALS, re.compile(r"^unsolved goals", re.I)),
    (LeanErrorKind.TYPE_MISMATCH, re.compile(r"^(application )?type mismatch", re.I)),
    (
        LeanErrorKind.TACTIC_FAILED,
        re.compile(
            r"(n?linarith|positivity|polyrith|norm_num|omega|decide) failed"
            r"|failed to prove|simp made no progress|rewrite failed|motive is not type correct"
            r"|did not find instance of the pattern|tactic '[^']+' failed|failed to synthesize",
            re.I,
        ),
    ),
)

# Errors that are about Lean itself, never about the student's mathematics.
LEAN_SIDE_KINDS: frozenset[LeanErrorKind] = frozenset(
    {LeanErrorKind.SYNTAX, LeanErrorKind.UNKNOWN_IDENTIFIER}
)


def classify_lean_error(message: str) -> LeanErrorKind:
    first_line = message.strip().splitlines()[0] if message.strip() else ""
    for kind, pattern in _RULES:
        if pattern.search(first_line):
            return kind
    return LeanErrorKind.OTHER
