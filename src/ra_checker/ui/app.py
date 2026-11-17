"""Streamlit entry point.

Run from the project root:  streamlit run src/ra_checker/ui/app.py

Flow: problem + proof → "Formalize" (phase 1) → the student reviews the formal
statement → "Check my proof" (phase 2) → report. The proof is never sent to
Lean before the student confirms the statement.
"""

from __future__ import annotations

import streamlit as st

from ra_checker.input_validation import InputError, validate_submission
from ra_checker.models import CheckReport
from ra_checker.pipeline import PendingCheck
from ra_checker.ui import components as ui
from ra_checker.ui.services import get_checker

PENDING, RESULT, EDIT_HINT = "pending_check", "result", "show_edit_hint"

st.set_page_config(page_title="Real Analysis Checker", page_icon="∑", layout="wide")


def _reset() -> None:
    st.session_state[PENDING] = None
    st.session_state[RESULT] = None


def _discard_statement() -> None:
    """Runs before the page is redrawn, so the rejected statement disappears at once."""
    _reset()
    st.session_state[EDIT_HINT] = True


def main() -> None:
    state = st.session_state
    state.setdefault(PENDING, None)
    state.setdefault(RESULT, None)

    ui.page_header()
    checker, problems = get_checker()
    if problems:
        ui.setup_problems(problems)

    st.subheader("Step 1 · Your problem and proof")
    problem_text = st.text_area(
        "Problem statement",
        key="problem_text",
        height=120,
        placeholder="e.g. Suppose a_n → A and b_n → B. Prove that a_n + b_n → A + B.",
        on_change=_reset,
    )
    proof_text = st.text_area(
        "Your proof",
        key="proof_text",
        height=220,
        placeholder="e.g. Let ε > 0. Since a_n → A, there is N₁ such that …",
        on_change=_reset,
    )
    if st.button("Formalize the statement", type="primary", disabled=checker is None, key="formalize"):
        _reset()
        try:
            submission = validate_submission(problem_text, proof_text)
        except InputError as exc:
            for message in exc.problems:
                st.error(message)
            return
        with st.spinner("Reading your problem and formalizing the statement (Lean checks it too)…"):
            outcome = checker.formalize(submission)
        if isinstance(outcome, PendingCheck):
            state[PENDING] = outcome
        else:
            state[RESULT] = (outcome, (), ())

    if state.pop(EDIT_HINT, False):
        st.info("Edit the problem statement above to make it precise, then formalize again.")

    pending: PendingCheck | None = state[PENDING]
    if pending is not None:
        ui.statement_review(pending)
        confirm, edit = st.columns(2)
        if confirm.button("Yes, it matches — check my proof", type="primary", key="confirm"):
            with st.spinner("Translating your proof and running Lean (this takes about half a minute)…"):
                verified = checker.verify(pending.confirmed())
            state[PENDING] = None
            state[RESULT] = (verified.report, verified.statement_attempts, verified.proof_attempts)
            st.rerun()
        edit.button("No — I'll clarify the problem", key="edit", on_click=_discard_statement)

    result: tuple[CheckReport, tuple, tuple] | None = state[RESULT]
    if result is not None:
        st.divider()
        ui.report_view(*result)


main()
