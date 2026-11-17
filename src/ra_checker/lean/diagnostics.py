"""Parses Lean's command-line output into structured diagnostics.

Format confirmed against Lean 4.36 (fixtures in ``tests/fixtures/lean_output/``):

* errors and warnings start with a header line
  ``<file>:<line>:<col>: <severity>: <text>`` — the severity may carry a code,
  e.g. ``error(lean.unknownIdentifier):`` — followed by continuation lines
  (goal states, expected/actual types);
* ``#print axioms`` prints a *bare* line, with no header:
  ``'<name>' depends on axioms: [a, b, …]`` or
  ``'<name>' does not depend on any axioms``;
* a ``sorry`` placeholder produces the warning ``declaration uses `sorry```.
  ``sorryAx`` also appears in the axiom list whenever Lean recovered from an
  error, so it does not by itself mean "placeholder".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ra_checker.models import Diagnostic, Severity

_HEADER_RE = re.compile(
    r"^(?P<path>.*?\.lean):(?P<line>\d+):(?P<col>\d+): "
    r"(?P<sev>error|warning|info)(?:\([^)]*\))?:\s?(?P<text>.*)$"
)
_AXIOM_REPORT_START_RE = re.compile(
    r"^'[^']+' (?:depends on axioms: \[|does not depend on any axioms)"
)
_DEPENDS_RE = re.compile(r"'(?P<name>[^']+)' depends on axioms: \[(?P<axioms>[^\]]*)\]")
_NO_AXIOMS_RE = re.compile(r"'(?P<name>[^']+)' does not depend on any axioms")
_SORRY_WARNING_RE = re.compile(r"declaration uses ['`]sorry['`]", re.IGNORECASE)


@dataclass(frozen=True)
class LeanOutput:
    diagnostics: tuple[Diagnostic, ...]
    axioms: tuple[str, ...] | None  # None: no axiom report for the theorem
    uses_sorry: bool  # Lean warned that the declaration uses `sorry`
    unparsed: str  # text outside any diagnostic or axiom report (normally empty)

    @property
    def errors(self) -> tuple[Diagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.severity is Severity.ERROR)


def parse_lean_output(stdout: str, theorem_name: str, stderr: str = "") -> LeanOutput:
    lines = f"{stdout}\n{stderr}".replace("\r\n", "\n").split("\n")
    entries: list[tuple[re.Match[str], list[str]]] = []
    axiom_reports: list[str] = []
    unparsed: list[str] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if _AXIOM_REPORT_START_RE.match(line):
            report = [line]
            if "depends on axioms: [" in line:
                while "]" not in report[-1] and i < len(lines):  # wrapped list
                    report.append(lines[i])
                    i += 1
            axiom_reports.append(" ".join(" ".join(report).split()))
        elif header := _HEADER_RE.match(line):
            entries.append((header, []))
        elif entries:
            entries[-1][1].append(line)
        elif line.strip():
            unparsed.append(line)

    diagnostics = tuple(_to_diagnostic(h, rest) for h, rest in entries)
    info_texts = [
        " ".join(f"{d.message} {d.goal_state or ''}".split())
        for d in diagnostics
        if d.severity is Severity.INFO
    ]
    axioms = _axioms_for(theorem_name, axiom_reports + info_texts)
    uses_sorry = any(
        d.severity is Severity.WARNING and _SORRY_WARNING_RE.search(d.message)
        for d in diagnostics
    )
    return LeanOutput(diagnostics, axioms, uses_sorry, "\n".join(unparsed))


def _to_diagnostic(header: re.Match[str], continuation: list[str]) -> Diagnostic:
    while continuation and not continuation[-1].strip():
        continuation.pop()
    headline = header["text"].rstrip()
    details = "\n".join(continuation).rstrip()
    if "⊢" in details:
        message, goal_state = headline or "(no message)", details
    else:
        message = "\n".join(part for part in (headline, details) if part) or "(no message)"
        goal_state = None
    return Diagnostic(
        line=max(int(header["line"]), 1),
        column=int(header["col"]),
        severity=Severity(header["sev"]),
        message=message,
        goal_state=goal_state,
    )


def _axioms_for(theorem_name: str, reports: list[str]) -> tuple[str, ...] | None:
    """Axioms from the last report that names the theorem."""
    found: tuple[str, ...] | None = None
    for text in reports:
        if (m := _DEPENDS_RE.search(text)) and m["name"] == theorem_name:
            found = tuple(a.strip() for a in m["axioms"].split(",") if a.strip())
        elif (m := _NO_AXIOMS_RE.search(text)) and m["name"] == theorem_name:
            found = ()
    return found
