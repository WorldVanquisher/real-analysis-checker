"""Drives the real Streamlit app headlessly (streamlit.testing.v1.AppTest),
with a Checker built from fakes injected through session state."""

from pathlib import Path

import pytest
from pipeline_helpers import PROBLEM, PROOF, make_checker, parse_answer
from streamlit.testing.v1 import AppTest
from translation_helpers import STATEMENT_OK, UNSOLVED

from ra_checker.ui import services

APP = Path(__file__).resolve().parents[2] / "src" / "ra_checker" / "ui" / "app.py"


def start(checker=None) -> AppTest:
    at = AppTest.from_file(str(APP), default_timeout=60)
    if checker is not None:
        at.session_state[services.INJECTED_CHECKER_KEY] = checker
    return at.run()


def fill(at: AppTest, problem=PROBLEM, proof=PROOF) -> AppTest:
    at.text_area(key="problem_text").input(problem)
    at.text_area(key="proof_text").input(proof)
    return at.button(key="formalize").click().run()


def texts(elements) -> str:
    return "\n".join(str(e.value) for e in elements)


def test_initial_page():
    checker, *_ = make_checker()
    at = start(checker)
    assert not at.exception
    assert at.title[0].value == "Real Analysis Homework Checker"
    assert not at.button(key="formalize").disabled


def test_empty_input_shows_friendly_errors():
    checker, _, lean = make_checker()
    at = start(checker).button(key="formalize").click().run()
    assert "Please enter the problem statement." in texts(at.error)
    assert lean.sources == []


def test_full_flow_confirm_then_verify():
    checker, _, lean = make_checker()
    at = fill(start(checker))
    assert not at.exception
    assert "Does the formal statement match your problem?" in texts(at.subheader)
    assert any("SeqConvergesTo" in c.value for c in at.code)
    assert len(lean.sources) == 1  # the proof has not been sent to Lean yet

    at = at.button(key="confirm").click().run()
    assert not at.exception
    assert "Lean accepted the formalized proof." in texts(at.success)
    headings = texts(at.subheader)
    for section in ("Original problem", "Your proof", "Formalized statement", "Generated Lean code",
                    "Verification result", "How your steps were translated"):
        assert section in headings
    assert len(lean.sources) == 2


def test_failure_shows_location_explanation_and_unverified_hint():
    checker, *_ = make_checker(STATEMENT_OK, UNSOLVED)
    at = fill(start(checker)).button(key="confirm").click().run()
    assert "Lean did not accept the formalized proof." in texts(at.error)
    page = texts(at.markdown)
    assert "your step **S3**" in page
    assert "Suggested direction (not checked by Lean)" in page


def test_clarification_flow():
    checker, *_ = make_checker(parse=parse_answer(ambiguities=["Is the sequence real?"]))
    at = fill(start(checker))
    assert "We need a clarification before checking." in texts(at.info)
    assert "Is the sequence real?" in texts(at.markdown)


def test_edit_button_discards_the_pending_statement():
    checker, *_ = make_checker()
    at = fill(start(checker)).button(key="edit").click().run()
    assert "Does the formal statement match your problem?" not in texts(at.subheader)
    assert "Edit the problem statement above" in texts(at.info)


def test_not_ready_environment_disables_checking(monkeypatch):
    monkeypatch.setattr(services, "get_checker", lambda: (None, ["ANTHROPIC_API_KEY is not set."]))
    at = start()
    assert "The checker is not ready on this computer:" in texts(at.error)
    assert at.button(key="formalize").disabled


@pytest.fixture(autouse=True)
def _no_real_checker(monkeypatch):
    # Never build the real (networked) checker in unit tests.
    monkeypatch.setattr(services, "_build_checker", lambda: (None, ["not used in tests"]))
