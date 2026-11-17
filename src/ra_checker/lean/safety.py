"""Deny-list screen for LLM-generated Lean, applied before Lean ever runs.

Lean can execute code while elaborating (``#eval``, ``run_tac``, custom
``elab``/``macro``, ``IO``) and can be told to skip checks (``set_option``).
A tactic block can also smuggle in new top-level commands, because Lean starts
a new command at any command keyword, whatever its indentation. This screen
rejects all of that. It is deliberately strict: a legitimate undergraduate
real-analysis proof never needs any denied construct, and a false positive only
costs a ``TRANSLATION_FAILED``.

This is not a sandbox. The second line of defence is ``#print axioms`` (see
``report/verdict.py``), plus timeouts and a scrubbed environment in the runner.

Comments are skipped (``--`` to end of line, nested ``/- ... -/``); string
literals are rejected outright, so text inside them can never hide code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

STATEMENT_MAX_CHARS = 2_000
TACTIC_BLOCK_MAX_CHARS = 20_000

# Commands and keywords that must never appear in a statement or tactic block.
DENIED_WORDS: frozenset[str] = frozenset(
    {
        # file / environment control
        "import", "prelude", "set_option", "namespace", "section", "end",
        "universe", "variable", "attribute", "export", "mutual", "deriving",
        # new declarations
        "def", "theorem", "lemma", "abbrev", "instance", "example",
        "structure", "class", "inductive", "axiom", "opaque",
        # code execution and metaprogramming
        "unsafe", "partial", "implemented_by", "extern", "initialize",
        "builtin_initialize", "run_cmd", "run_tac", "run_elab", "run_meta",
        "elab", "elab_rules", "macro", "macro_rules", "syntax",
        "declare_syntax_cat", "notation", "infix", "infixl", "infixr",
        "prefix", "postfix",
        # unsound or unchecked proof terms (explicit `sorry` is handled apart)
        "admit", "native_decide", "ofReduceBool",
        # namespaces that give access to IO and the elaborator
        "IO", "EIO", "BaseIO", "unsafeIO", "unsafeBaseIO", "unsafeEIO",
        "Lean", "System",
    }
)  # fmt: skip

_IDENT_CHAR = r"[\w'!?]"
_DENIED_WORD_RE = re.compile(
    rf"(?<!{_IDENT_CHAR})(?:{'|'.join(sorted(map(re.escape, DENIED_WORDS)))})(?!{_IDENT_CHAR})"
)
_SORRY_RE = re.compile(rf"(?<!{_IDENT_CHAR})sorry(?!{_IDENT_CHAR})")
_DENIED_SYMBOLS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"#[A-Za-z_]"), "'#' commands are not allowed"),
    (re.compile(r"@\["), "attributes are not allowed"),
    (re.compile(r"[«»]"), "«guillemet» identifiers are not allowed"),
    (re.compile(r'"'), "string literals are not allowed"),
)
_STATEMENT_ONLY_SYMBOLS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r":="), "':=' is not allowed in a statement"),
)
# Control characters (except tab/newline/CR) and bidirectional overrides.
_HIDDEN_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f‪-‮⁦-⁩]")


@dataclass(frozen=True)
class Violation:
    rule: str
    token: str
    line: int
    message: str


@dataclass(frozen=True)
class SafetyReport:
    violations: tuple[Violation, ...]
    placeholder_count: int  # number of explicit `sorry` placeholders

    @property
    def ok(self) -> bool:
        return not self.violations


def check_statement(text: str) -> SafetyReport:
    """Screen a formal statement. ``sorry`` and ``:=`` are violations here."""
    report = _check(text, STATEMENT_MAX_CHARS, _STATEMENT_ONLY_SYMBOLS)
    sorry_violations = tuple(
        Violation("placeholder", "sorry", line, "a statement cannot contain 'sorry'")
        for line in _sorry_lines(_strip_comments(text)[0])
    )
    return SafetyReport(report.violations + sorry_violations, placeholder_count=0)


def check_tactic_block(text: str) -> SafetyReport:
    """Screen a tactic block. ``sorry`` is allowed but counted as a placeholder."""
    report = _check(text, TACTIC_BLOCK_MAX_CHARS, ())
    placeholders = len(_sorry_lines(_strip_comments(text)[0]))
    return SafetyReport(report.violations, placeholder_count=placeholders)


def _check(
    text: str,
    max_chars: int,
    extra_symbols: tuple[tuple[re.Pattern[str], str], ...],
) -> SafetyReport:
    violations: list[Violation] = []
    if len(text) > max_chars:
        violations.append(
            Violation("too_long", "", 1, f"longer than {max_chars} characters")
        )
    for match in _HIDDEN_CHARS_RE.finditer(text):
        violations.append(
            Violation(
                "hidden_character",
                f"U+{ord(match.group()):04X}",
                _line_of(text, match.start()),
                "control or bidirectional-override characters are not allowed",
            )
        )

    code, comment_violations = _strip_comments(text)
    violations += comment_violations
    for match in _DENIED_WORD_RE.finditer(code):
        violations.append(
            Violation(
                "denied_word",
                match.group(),
                _line_of(code, match.start()),
                f"'{match.group()}' is not allowed in generated Lean",
            )
        )
    for pattern, message in _DENIED_SYMBOLS + extra_symbols:
        for match in pattern.finditer(code):
            violations.append(
                Violation("denied_symbol", match.group(), _line_of(code, match.start()), message)
            )
    violations.sort(key=lambda v: (v.line, v.rule, v.token))
    return SafetyReport(tuple(violations), placeholder_count=0)


def _strip_comments(text: str) -> tuple[str, list[Violation]]:
    """Replace comments with spaces, keeping newlines so line numbers survive."""
    out: list[str] = []
    violations: list[Violation] = []
    i, n = 0, len(text)
    while i < n:
        if text.startswith("--", i):
            end = text.find("\n", i)
            end = n if end == -1 else end
            out.append(" " * (end - i))
            i = end
        elif text.startswith("/-", i):
            start, depth = i, 1
            i += 2
            while i < n and depth:
                if text.startswith("/-", i):
                    depth, i = depth + 1, i + 2
                elif text.startswith("-/", i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            if depth:
                violations.append(
                    Violation(
                        "unterminated_comment",
                        "/-",
                        _line_of(text, start),
                        "block comment is never closed",
                    )
                )
            out.append(re.sub(r"[^\n]", " ", text[start:i]))
        else:
            out.append(text[i])
            i += 1
    return "".join(out), violations


def strip_comments(text: str) -> str:
    """The text with comments blanked out (newlines kept), as the screen sees it."""
    return _strip_comments(text)[0]


def _sorry_lines(code: str) -> list[int]:
    return [_line_of(code, m.start()) for m in _SORRY_RE.finditer(code)]


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1
