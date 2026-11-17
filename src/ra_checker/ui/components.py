"""Rendering helpers for the Streamlit app. Display only — no business logic;
all wording decisions come from ``ra_checker.report.presentation``."""

from __future__ import annotations

import streamlit as st

from ra_checker.models import CheckReport, VerificationStatus
from ra_checker.pipeline import PendingCheck
from ra_checker.report.presentation import (
    STEP_STATUS_LABELS,
    explanation_lines,
    headline,
)
from ra_checker.translation.proof import ProofAttempt
from ra_checker.translation.statement import StatementAttempt

_LEVEL_WIDGETS = {"success": st.success, "warning": st.warning, "error": st.error, "info": st.info}


def page_header() -> None:
    st.title("Real Analysis Homework Checker")
    st.caption(
        "Type a real-analysis problem about sequences and your proof. The checker "
        "formalizes them in Lean 4, lets real Lean verify the formal proof, and explains "
        "where it fails. Lean's verdict applies to the formal version of your proof."
    )
    with st.expander("How it works"):
        st.markdown(
            "1. **Read** — an AI reads the problem and splits your proof into steps.\n"
            "2. **Formalize the statement** — you check that the Lean statement says what "
            "the problem says. Nothing is checked until you confirm it.\n"
            "3. **Translate and verify** — your steps are translated into Lean and Lean "
            "checks them. Only Lean can produce a *verified* result.\n"
            "4. **Explain** — if Lean rejects a step, you see where and, when it can be "
            "told, whether the problem is in your reasoning or in the translation."
        )


def setup_problems(problems: list[str]) -> None:
    st.error("The checker is not ready on this computer:")
    for problem in problems:
        st.markdown(f"- {problem}")


def statement_review(pending: PendingCheck) -> None:
    st.subheader("Step 2 · Does the formal statement match your problem?")
    left, right = st.columns(2)
    with left:
        st.markdown("**Original problem**")
        st.markdown(_quote(pending.submission.problem_text))
    with right:
        st.markdown("**Formal statement (Lean)**")
        st.code(pending.statement.lean_statement, language="lean")
        st.markdown(f"**In words:** {pending.statement.back_translation}")
    if pending.statement.assumptions_added:
        st.warning(
            "To formalize the problem, these conventions were assumed:\n"
            + "\n".join(f"- {a}" for a in pending.statement.assumptions_added)
        )
    _how_we_read_it(pending)


def report_view(
    report: CheckReport,
    statement_attempts: tuple[StatementAttempt, ...] = (),
    proof_attempts: tuple[ProofAttempt, ...] = (),
) -> None:
    head = headline(report)
    _LEVEL_WIDGETS[head.level](f"**{head.title}** {head.body}")

    if report.status is VerificationStatus.NEEDS_CLARIFICATION and report.analysis:
        if report.analysis.ambiguities:
            st.markdown("**Questions:**")
            for question in report.analysis.ambiguities:
                st.markdown(f"- {question}")
        st.caption("Edit the problem statement above to answer, then formalize again.")

    st.subheader("Original problem")
    st.markdown(_quote(report.submission.problem_text))
    st.subheader("Your proof")
    st.markdown(_quote(report.submission.proof_text))

    if report.statement is not None:
        st.subheader("Formalized statement")
        st.code(report.statement.lean_statement, language="lean")
        st.markdown(f"**In words:** {report.statement.back_translation}")
        if report.statement.confirmed_by_student:
            st.caption("You confirmed that this matches the problem.")

    if report.lean_run is not None:
        st.subheader("Generated Lean code")
        st.code(report.lean_run.source, language="lean", line_numbers=True)
        st.subheader("Verification result")
        run = report.lean_run
        timing = "timed out" if run.timed_out else f"finished in {run.duration_s:.0f} s"
        st.markdown(f"**{_STATUS_TEXT[report.status]}** — Lean {timing}.")
        if run.lean_version:
            st.caption(run.lean_version)

    if report.error_analyses:
        st.subheader("Where and why it failed")
        steps = {s.id: s.text for s in report.analysis.proof_steps} if report.analysis else {}
        for error in report.error_analyses:
            _error_card(error, steps)

    if report.translation is not None:
        st.subheader("How your steps were translated")
        _step_table(report)

    _technical_details(report, statement_attempts, proof_attempts)


_STATUS_TEXT = {
    VerificationStatus.VERIFIED: "Verified by Lean",
    VerificationStatus.VERIFICATION_FAILED: "Verification failed",
    VerificationStatus.TRANSLATION_FAILED: "Translation failed",
    VerificationStatus.NEEDS_CLARIFICATION: "Clarification needed",
    VerificationStatus.RUNTIME_ERROR: "Runtime error",
}


def _error_card(error, steps: dict[str, str]) -> None:
    classification, explanation = explanation_lines(error)
    with st.container(border=True):
        where = []
        if error.step_id:
            label = "your step" if error.step_id.startswith("S") else "a step added by the translator"
            where.append(f"{label} **{error.step_id}**")
        if error.line:
            where.append(f"line {error.line} of the proof")
        st.markdown("**Location:** " + (", ".join(where) or "not determined"))
        if error.step_id in steps:
            st.markdown(_quote(steps[error.step_id]))
        st.markdown(f"**{classification}**")
        st.markdown(explanation)
        if error.correction_direction:
            st.markdown(f"**Suggested direction (not checked by Lean):** {error.correction_direction}")
        with st.expander("Original Lean error message"):
            st.code(error.raw_message, language="text")


def _step_table(report: CheckReport) -> None:
    steps = {s.id: s.text for s in report.analysis.proof_steps} if report.analysis else {}
    rows = []
    for mapping in report.translation.step_map:
        rows.append(
            {
                "Step": mapping.step_id,
                "Your text": steps.get(mapping.step_id, "— (added by the translator)"),
                "Translation": STEP_STATUS_LABELS[mapping.status],
                "Note": mapping.note,
            }
        )
    st.dataframe(rows, hide_index=True, width="stretch")
    if report.fidelity and not report.fidelity.is_faithful:
        st.caption("Steps that were changed, added or not translated are where Lean's verdict "
                   "may not reflect your own argument.")
    if report.translation.translator_notes:
        st.caption(f"Translator's notes: {report.translation.translator_notes}")


def _how_we_read_it(pending: PendingCheck) -> None:
    analysis = pending.analysis
    with st.expander("How we read your problem and proof"):
        if analysis.hypotheses:
            st.markdown("**Assumptions:** " + "; ".join(analysis.hypotheses))
        st.markdown(f"**To prove:** {analysis.goal}")
        st.markdown("**Your proof, step by step:**")
        for step in analysis.proof_steps:
            flag = "" if step.verbatim else " *(reworded by the reader — please check)*"
            st.markdown(f"- **{step.id}** {step.text}{flag}")


def _technical_details(report, statement_attempts, proof_attempts) -> None:
    with st.expander("Technical details"):
        st.markdown(f"- Check id: `{report.id}`")
        st.markdown(f"- Models: {report.llm_model or '—'}")
        st.markdown(f"- Prompt versions: {report.prompt_version or '—'}")
        if statement_attempts:
            st.markdown(f"- Statement attempts: {len(statement_attempts)}")
        for i, attempt in enumerate(proof_attempts, start=1):
            outcome = attempt.status.value if attempt.status else "rejected before Lean"
            st.markdown(f"- Proof attempt {i} ({attempt.kind}): {outcome}")


def _quote(text: str) -> str:
    return "\n".join(f"> {line}" if line.strip() else ">" for line in text.splitlines())
