"""Every concept-card example and practice solution must compile with real
Lean, with only standard axioms. Run with `pytest -m lean`."""

import pytest

from ra_checker.lean.assemble import HEADER_COMMANDS, HEADER_IMPORTS, INDENT
from ra_checker.lean.diagnostics import parse_lean_output
from ra_checker.learning.cards import CARDS
from ra_checker.learning.practice import check_practice
from ra_checker.report.verdict import STANDARD_AXIOMS

pytestmark = pytest.mark.lean


def snippets():
    for card in CARDS:
        yield f"card_{card.key}_example", card.example_statement, card.example_proof
        if card.practice:
            yield f"card_{card.key}_solution", card.practice.statement, card.practice.solution


def test_every_example_and_solution_compiles(lean_runner):
    # One file for all snippets (one Mathlib import instead of ~30); the header is
    # the same as the checker's.
    lines = [f"import {m}" for m in HEADER_IMPORTS] + [""] + list(HEADER_COMMANDS) + [""]
    names = []
    for name, statement, proof in snippets():
        names.append(name)
        body = "\n".join(INDENT + line if line else "" for line in proof.split("\n"))
        lines += [f"theorem {name} {statement} := by", body, ""]
    lines += [f"#print axioms {name}" for name in names]
    run = lean_runner.run("\n".join(lines) + "\n")

    output = parse_lean_output(run.stdout, names[0], run.stderr)
    assert output.errors == (), run.stdout
    assert not output.uses_sorry
    for name in names:
        axioms = parse_lean_output(run.stdout, name).axioms
        assert axioms is not None and set(axioms) <= STANDARD_AXIOMS, (name, axioms)


def test_practice_answers_are_checked_by_lean(lean_runner):
    practice = next(c for c in CARDS if c.key == "intro").practice
    assert check_practice(practice, practice.solution, lean_runner).verified
    wrong = check_practice(practice, "intro ε hε\nlinarith [hε]\nexact hε", lean_runner)
    assert not wrong.verified and wrong.lean_errors
