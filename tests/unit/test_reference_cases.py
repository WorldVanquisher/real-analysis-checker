"""Structural checks on tests/fixtures/reference_cases.toml (no Lean needed)."""

import re
import tomllib
from pathlib import Path

import pytest

from ra_checker.lean.assemble import assemble_proof
from ra_checker.lean.safety import check_statement, check_tactic_block

CASES_FILE = Path(__file__).resolve().parents[1] / "fixtures" / "reference_cases.toml"
CASES = tomllib.loads(CASES_FILE.read_text(encoding="utf-8"))["case"]
TAG_RE = re.compile(r"^\s*-- \[(S\d+)\]\s*$", re.MULTILINE)


def test_case_ids_are_unique_and_there_are_enough_cases():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids))
    assert len(ids) >= 5


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_case_structure(case):
    assert {"id", "topic", "problem", "steps", "statement", "tactic_block"} <= case.keys()
    assert case["problem"].strip() and all(s.strip() for s in case["steps"])


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_tags_match_steps_in_order(case):
    tags = TAG_RE.findall(case["tactic_block"])
    assert tags == [f"S{i}" for i in range(1, len(case["steps"]) + 1)]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_case_passes_safety_screen_without_placeholders(case):
    statement = check_statement(case["statement"])
    block = check_tactic_block(case["tactic_block"])
    assert statement.ok, statement.violations
    assert block.ok, block.violations
    assert block.placeholder_count == 0


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_case_assembles(case):
    assembled = assemble_proof(case["statement"], case["tactic_block"])
    assert assembled.statement == case["statement"]
