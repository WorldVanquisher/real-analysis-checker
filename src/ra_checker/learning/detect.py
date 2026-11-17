"""Which concepts does this proof use, and where? (no LLM)

Cards are selected from the tactic block Lean actually checked: ``theorem`` and
``by`` always (they frame every proof), then every card whose trigger word
appears in the code, in order of first appearance. Comments — including the
step tags — are ignored.
"""

from __future__ import annotations

from ra_checker.lean.safety import strip_comments
from ra_checker.learning.cards import ALWAYS_SHOWN, CARDS, ConceptCard
from ra_checker.translation.proof import TAG_LINE_RE


def concepts_in(tactic_block: str) -> tuple[ConceptCard, ...]:
    code = strip_comments(tactic_block)
    framing = [c for c in CARDS if c.key in ALWAYS_SHOWN]
    found: list[tuple[int, ConceptCard]] = []
    for card in CARDS:
        if card.key in ALWAYS_SHOWN:
            continue
        if match := card.pattern.search(code):
            found.append((match.start(), card))
    return tuple(framing) + tuple(card for _, card in sorted(found, key=lambda pair: pair[0]))


def occurrences(card: ConceptCard, tactic_block: str, limit: int = 3) -> list[tuple[str | None, str]]:
    """Up to ``limit`` (step tag, line) pairs where the concept is used."""
    hits: list[tuple[str | None, str]] = []
    tag: str | None = None
    for raw, code in zip(tactic_block.split("\n"), strip_comments(tactic_block).split("\n")):
        if match := TAG_LINE_RE.match(raw):
            tag = match.group(1)
            continue
        if code.strip() and card.pattern.search(code):
            hits.append((tag, raw.strip()))
            if len(hits) == limit:
                break
    return hits
