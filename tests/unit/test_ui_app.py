"""Drives the real Streamlit app headlessly (streamlit.testing.v1.AppTest),
with a Checker built from fakes injected through session state."""

from pathlib import Path

import pytest
from pipeline_helpers import PROBLEM, PROOF, make_checker, parse_answer
from streamlit.testing.v1 import AppTest
from translation_helpers import OK, STATEMENT_OK, UNSOLVED

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


def test_full_flow_in_learning_mode():
    checker, _, lean = make_checker()
    at = start(checker)
    at.radio(key="mode").set_value("Learning Mode")
    at = fill(at)
    assert not at.exception
    assert "Does the formal statement match your problem?" in texts(at.subheader)
    assert any("SeqConvergesTo" in c.value for c in at.code)
    assert len(lean.sources) == 1  # the proof has not been sent to Lean yet

    at = at.button(key="confirm").click().run()
    assert not at.exception
    assert "Lean accepted the formalized proof." in texts(at.success)
    headings = texts(at.subheader)
    for section in ("Original problem", "Your proof", "Formalized statement", "Generated Lean code",
                    "Verification result", "Your reasoning ↔ Lean code"):
        assert section in headings
    assert any(c.value == "intro ε hε" for c in at.code)  # S1's own Lean code in the mapping
    assert len(lean.sources) == 2


def test_quick_check_is_concise_but_keeps_every_detail_available():
    checker, *_ = make_checker()
    at = fill(start(checker)).button(key="confirm").click().run()
    assert not at.exception
    assert "Lean accepted the formalized proof." in texts(at.success)
    assert "Generated Lean code" not in texts(at.subheader)
    labels = [e.label for e in at.expander]
    for label in ("Your problem and proof", "Formal statement and generated Lean code",
                  "How your steps were translated"):
        assert label in labels
    assert any("theorem student_claim" in c.value for c in at.code)  # inside the expander


def test_learning_mode_shows_contextual_cards_and_lean_checked_practice():
    checker, _, lean = make_checker(STATEMENT_OK, OK, OK)  # statement, proof, practice
    at = start(checker)
    at.radio(key="mode").set_value("Learning Mode")
    at = fill(at).button(key="confirm").click().run()
    assert "Learn the Lean in this proof" in texts(at.subheader)
    titles = [e.label for e in at.expander]
    for key_word in ("intro —", "obtain / rcases —", "use / refine —", "rw —", "exact —"):
        assert any(t.startswith(key_word) for t in titles), titles
    assert not any(t.startswith("calc") for t in titles)  # not used in this proof

    at.text_area(key="practice_answer_intro").input("intro ε hε\nexact half_pos hε")
    at = at.button(key="practice_check_intro").click().run()
    assert not at.exception
    assert "Lean accepted your answer." in texts(at.success)
    assert len(lean.sources) == 3  # the practice answer really went to the Lean runner


def test_code_explanation_on_request():
    from ra_checker.explain.code import EXPLAIN_CODE_TASK, CodeExplanationOutput

    checker, llm, _ = make_checker()
    llm.responses[EXPLAIN_CODE_TASK] = CodeExplanationOutput(
        overview="Overview of the formal proof.",
        blocks=[{"step_id": "S1", "lean_syntax": "`intro ε hε` fixes ε.", "math_meaning": "Let ε > 0.",
                 "role": "Opens the argument.", "why_needed": "ε is universally quantified."}],
    )
    at = start(checker)
    at.radio(key="mode").set_value("Learning Mode")
    at = fill(at).button(key="confirm").click().run()
    assert "What the Lean code does" in texts(at.subheader)
    calls_before = len(llm.requests)
    at = at.button(key="explain_code").click().run()
    assert not at.exception
    page = texts(at.markdown)
    assert "Overview of the formal proof." in page and "**Mathematical meaning:** Let ε > 0." in page
    assert len(llm.requests) == calls_before + 1
    at = at.run()  # re-rendering does not ask the LLM again
    assert len(llm.requests) == calls_before + 1


def test_switching_mode_after_a_check_does_not_recheck():
    checker, _, lean = make_checker()
    at = fill(start(checker)).button(key="confirm").click().run()
    runs = len(lean.sources)
    at.radio(key="mode").set_value("Learning Mode")
    at = at.run()
    assert "Your reasoning ↔ Lean code" in texts(at.subheader)
    assert len(lean.sources) == runs


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
