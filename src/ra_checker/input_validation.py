"""Validation of what the student typed, before anything else runs.

The submission is stored exactly as typed. :func:`normalize_for_llm` produces
the copy sent to the LLM: Unicode NFC (canonical composition only — never NFKC,
which would turn ``x²`` into ``x2``), LF line endings, and no control
characters other than tab and newline.
"""

from __future__ import annotations

import re
import unicodedata

from ra_checker.models import CheckMode, Submission

MAX_PROBLEM_CHARS = 5_000
MAX_PROOF_CHARS = 15_000

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f‪-‮⁦-⁩]")


class InputError(ValueError):
    """The submission cannot be checked; ``problems`` are student-facing messages."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = tuple(problems)


def validate_submission(
    problem_text: str, proof_text: str, mode: CheckMode = CheckMode.QUICK
) -> Submission:
    problems: list[str] = []
    if not problem_text.strip():
        problems.append("Please enter the problem statement.")
    elif len(problem_text) > MAX_PROBLEM_CHARS:
        problems.append(
            f"The problem statement is too long ({len(problem_text)} characters; "
            f"the limit is {MAX_PROBLEM_CHARS})."
        )
    if not proof_text.strip():
        problems.append("Please enter your proof.")
    elif len(proof_text) > MAX_PROOF_CHARS:
        problems.append(
            f"The proof is too long ({len(proof_text)} characters; "
            f"the limit is {MAX_PROOF_CHARS})."
        )
    if problems:
        raise InputError(problems)
    return Submission(problem_text=problem_text, proof_text=proof_text, mode=mode)


def normalize_for_llm(text: str) -> str:
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    return _CONTROL_CHARS_RE.sub("", text).strip()
