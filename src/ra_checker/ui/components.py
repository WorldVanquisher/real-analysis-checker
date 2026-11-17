"""Rendering helpers for the Streamlit app. Display only — no business logic;
all wording decisions come from ``ra_checker.report.presentation``."""

from __future__ import annotations

import streamlit as st

from ra_checker.analysis.correction import Correction, CorrectionUnavailable
from ra_checker.explain.code import CodeExplanation
from ra_checker.lean.runner import LeanRunner
from ra_checker.learning.cards import ALWAYS_SHOWN, ConceptCard
from ra_checker.learning.detect import concepts_in, occurrences
from ra_checker.learning.practice import PracticeResult, check_practice
from ra_checker.models import CheckReport, VerificationStatus
from ra_checker.pipeline import Checker, PendingCheck
from ra_checker.report.mapping import build_mapping
from ra_checker.report.presentation import (
    CONTRADICTORY_BEFORE_CONFIRMING,
    CONTRADICTORY_IN_REPORT,
    STEP_STATUS_LABELS,
    explanation_lines,
    has_contradictory_hypotheses,
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
    if pending.statement.contradictory_hypotheses is True:
        st.error(CONTRADICTORY_BEFORE_CONFIRMING)
    _how_we_read_it(pending)


def report_view(
    report: CheckReport,
    statement_attempts: tuple[StatementAttempt, ...] = (),
    proof_attempts: tuple[ProofAttempt, ...] = (),
    *,
    learning: bool = False,
    practice_runner: LeanRunner | None = None,
    checker: Checker | None = None,
) -> None:
    """Quick Check: verdict and concise feedback, with every detail one click
    away in collapsed sections. Learning Mode: everything expanded, plus the
    reasoning ↔ Lean mapping."""
    head = headline(report)
    _LEVEL_WIDGETS[head.level](f"**{head.title}** {head.body}")
    if has_contradictory_hypotheses(report) and report.status is not VerificationStatus.VERIFIED:
        st.warning(CONTRADICTORY_IN_REPORT)  # for VERIFIED the headline already says it

    if report.status is VerificationStatus.NEEDS_CLARIFICATION and report.analysis:
        if report.analysis.ambiguities:
            st.markdown("**Questions:**")
            for question in report.analysis.ambiguities:
                st.markdown(f"- {question}")
        st.caption("Edit the problem statement above to answer, then formalize again.")

    if learning:
        _problem_and_proof(report)
        _statement_and_code(report)
        _verification_result(report)
        _error_cards(report, learning=True, checker=checker)
        _mapping_view(report)
        _code_explanation(report, checker)
        _learning_section(report, practice_runner)
    else:
        _verification_result(report, concise=True)
        _error_cards(report)
        with st.expander("Your problem and proof"):
            _problem_and_proof(report, headings=False)
        if report.statement is not None or report.lean_run is not None:
            with st.expander("Formal statement and generated Lean code"):
                _statement_and_code(report, headings=False)
        if report.translation is not None:
            with st.expander("How your steps were translated"):
                _step_table(report)
    _technical_details(report, statement_attempts, proof_attempts)


def _problem_and_proof(report: CheckReport, headings: bool = True) -> None:
    _heading("Original problem", headings)
    st.markdown(_quote(report.submission.problem_text))
    _heading("Your proof", headings)
    st.markdown(_quote(report.submission.proof_text))


def _statement_and_code(report: CheckReport, headings: bool = True) -> None:
    if report.statement is not None:
        _heading("Formalized statement", headings)
        st.code(report.statement.lean_statement, language="lean")
        st.markdown(f"**In words:** {report.statement.back_translation}")
        if report.statement.confirmed_by_student:
            st.caption("You confirmed that this matches the problem.")
    if report.lean_run is not None:
        _heading("Generated Lean code", headings)
        st.code(report.lean_run.source, language="lean", line_numbers=True)


def _verification_result(report: CheckReport, concise: bool = False) -> None:
    run = report.lean_run
    if run is None:
        return
    timing = "timed out" if run.timed_out else f"finished in {run.duration_s:.0f} s"
    if not concise:
        st.subheader("Verification result")
    st.markdown(f"**{_STATUS_TEXT[report.status]}** — Lean {timing}.")
    if run.lean_version and not concise:
        st.caption(run.lean_version)


def _error_cards(report: CheckReport, learning: bool = False, checker: Checker | None = None) -> None:
    if not report.error_analyses:
        return
    st.subheader("Where and why it failed")
    steps = {s.id: s.text for s in report.analysis.proof_steps} if report.analysis else {}
    for index, error in enumerate(report.error_analyses):
        _error_card(error, steps, learning=learning)
        if learning:
            _hint_ladder(report, index, error, checker)


def _hint_ladder(report: CheckReport, index: int, error, checker: Checker | None) -> None:
    """Advanced E: hints first, the corrected proof last, one click at a time."""
    level_key = f"hint_level_{report.id}_{index}"
    level = st.session_state.get(level_key, 0)

    def advance() -> None:
        st.session_state[level_key] = level + 1

    if level >= 1:
        st.markdown(f"**Hint:** {error.correction_direction or 'No hint is available for this error.'}")
    if level >= 2:
        meaning = error.math_interpretation or "No mathematical interpretation is available."
        st.markdown(f"**What it means mathematically:** {meaning}")
    if level >= 3:
        _correction(report, index, checker)
        return
    labels = ("Show a hint", "Show a bigger hint", "Show a corrected proof (checked by Lean)")
    st.button(labels[level], key=f"hint_button_{report.id}_{index}", on_click=advance,
              disabled=level == 2 and checker is None)


def _correction(report: CheckReport, index: int, checker: Checker | None) -> None:
    key = f"correction_{report.id}_{index}"
    if key not in st.session_state and checker is not None:
        with st.spinner("Writing a corrected version and checking it with Lean (about half a minute)…"):
            try:
                st.session_state[key] = checker.suggest_correction(report, index)
            except CorrectionUnavailable as exc:
                st.session_state[key] = str(exc)
    correction: Correction | str | None = st.session_state.get(key)
    if correction is None:
        return
    if isinstance(correction, str):
        st.info(correction)
        return
    if correction.verified:
        st.success("**Verified by Lean** — with these changes, Lean accepts the whole formal proof.")
    else:
        why = "; ".join(correction.reasons) or "Lean did not accept it"
        st.warning(f"**Unverified suggestion** — Lean did not accept it ({why}). Treat it as an idea only.")
    st.markdown(f"**What changes:** {correction.explanation}")
    for change in correction.changes:
        where = " — where Lean reported the error" if change.step_id == correction.focus_step else ""
        st.markdown(f"**Step {change.step_id}**{where}")
        before, after = st.columns(2)
        with before:
            st.caption("Before")
            st.code(change.before or "(no code)", language="lean")
        with after:
            st.caption("After")
            st.code(change.after or "(no code)", language="lean")
    st.caption("Your own result above is unchanged: this is a suggestion to learn from.")


def _mapping_view(report: CheckReport) -> None:
    mapping = build_mapping(report)
    if mapping is None:
        return
    st.subheader("Your reasoning ↔ Lean code")
    if mapping.substantially_transformed:
        st.warning(
            "The translation departs substantially from your proof, so this "
            "correspondence is only approximate: the Lean proof is not a faithful copy "
            "of your argument."
        )
    for row in mapping.rows:
        with st.container(border=True):
            left, right = st.columns([2, 3])
            with left:
                st.markdown(f"**{row.step_id}** · {STEP_STATUS_LABELS[row.status]}")
                if row.student_text:
                    st.markdown(_quote(row.student_text))
                else:
                    st.markdown("*Added by the translator — not part of your proof.*")
                if row.note:
                    st.caption(row.note)
            with right:
                if row.lean_code:
                    st.code(row.lean_code, language="lean")
                else:
                    st.caption("No Lean code corresponds to this step.")
    if report.translation and report.translation.translator_notes:
        st.caption(f"Translator's notes: {report.translation.translator_notes}")


def _code_explanation(report: CheckReport, checker: Checker | None) -> None:
    if report.translation is None:
        return
    st.subheader("What the Lean code does")
    key = f"code_explanation_{report.id}"
    if key not in st.session_state:
        st.caption("A block-by-block explanation of the Lean proof, tied to your own steps.")
        if st.button("Explain the Lean code", key="explain_code", disabled=checker is None):
            with st.spinner("Explaining the Lean code…"):
                st.session_state[key] = checker.explain_code(report)
            st.rerun()
        return
    explanation: CodeExplanation | None = st.session_state[key]
    if explanation is None:
        st.caption("There is no Lean code to explain for this check.")
        return
    st.markdown(explanation.overview)
    for block in explanation.blocks:
        with st.container(border=True):
            origin = "your step" if block.step_id.startswith("S") else "added by the translator"
            st.markdown(f"**{block.step_id}** · {origin}")
            if block.student_text:
                st.markdown(_quote(block.student_text))
            st.code(block.lean_code, language="lean")
            for label, text in (
                ("Lean syntax", block.lean_syntax),
                ("Mathematical meaning", block.math_meaning),
                ("Role in the proof", block.role),
                ("Why it is needed", block.why_needed),
            ):
                if text:
                    st.markdown(f"**{label}:** {text}")
            if block.source == "automatic":
                reason = (
                    " (the AI explanation was withheld because it mentioned "
                    + ", ".join(f"`{m}`" for m in block.withheld_mentions)
                    + ", which the code does not use)"
                    if block.withheld_mentions
                    else ""
                )
                st.caption(f"Automatic summary{reason}.")


def _learning_section(report: CheckReport, runner: LeanRunner | None) -> None:
    if report.translation is None:
        return
    block = report.translation.tactic_block
    st.subheader("Learn the Lean in this proof")
    st.caption(
        "Short explanations of the Lean used in your proof. Every example and model "
        "solution below is checked by Lean in this project's test suite."
    )
    for card in concepts_in(block):
        with st.expander(card.title):
            st.markdown(f"**In Lean:** {card.lean_meaning}")
            st.markdown(f"**In mathematics:** {card.math_meaning}")
            hits = occurrences(card, block)
            if hits:
                st.markdown("**In your proof:**")
                for tag, line in hits:
                    where = f"step {tag}" if tag else "the proof"
                    st.markdown(f"- {where}: `{line}`")
            elif card.key in ALWAYS_SHOWN:
                st.markdown("**In your proof:** the theorem line of the generated Lean code.")
            st.markdown("**Example:**")
            st.code(_as_theorem("demo", card.example_statement, card.example_proof), language="lean")
            if card.practice is not None:
                _practice(card, runner)


def _practice(card: ConceptCard, runner: LeanRunner | None) -> None:
    practice = card.practice
    st.markdown(f"**Practice:** {practice.prompt}")
    st.code(_as_theorem("practice", practice.statement, "-- your tactics here"), language="lean")
    answer = st.text_area("Your tactics", key=f"practice_answer_{card.key}", height=90)
    if st.checkbox("Show a hint", key=f"practice_hint_{card.key}"):
        st.info(practice.hint)
    if st.checkbox("Show a model solution", key=f"practice_solution_{card.key}"):
        st.code(practice.solution, language="lean")
    result_key = f"practice_result_{card.key}"
    if st.button("Check with Lean", key=f"practice_check_{card.key}", disabled=runner is None):
        with st.spinner("Lean is checking your answer (about 20 seconds)…"):
            st.session_state[result_key] = check_practice(practice, answer, runner)
    result: PracticeResult | None = st.session_state.get(result_key)
    if result is not None:
        (st.success if result.verified else st.error)(result.message)
        for error in result.lean_errors:
            st.code(error, language="text")


def _as_theorem(name: str, statement: str, proof: str) -> str:
    body = "\n".join(f"  {line}" if line else "" for line in proof.split("\n"))
    return f"theorem {name} {statement} := by\n{body}"


def _heading(text: str, show: bool) -> None:
    if show:
        st.subheader(text)
    else:
        st.markdown(f"**{text}**")


_STATUS_TEXT = {
    VerificationStatus.VERIFIED: "Verified by Lean",
    VerificationStatus.VERIFICATION_FAILED: "Verification failed",
    VerificationStatus.TRANSLATION_FAILED: "Translation failed",
    VerificationStatus.NEEDS_CLARIFICATION: "Clarification needed",
    VerificationStatus.RUNTIME_ERROR: "Runtime error",
}


def _error_card(error, steps: dict[str, str], learning: bool = False) -> None:
    classification, explanation = explanation_lines(error)
    with st.container(border=True):
        where = []
        if error.step_id:
            label = "your step" if error.step_id.startswith("S") else "a step added by the translator"
            where.append(f"{label} **{error.step_id}**")
        # Same numbering as the "Generated Lean code" listing above.
        if error.file_line:
            where.append(f"line {error.file_line} of the generated Lean code")
        elif error.line:
            where.append(f"line {error.line} of the proof")
        st.markdown("**Location:** " + (", ".join(where) or "not determined"))
        if error.step_id in steps:
            st.markdown(_quote(steps[error.step_id]))
        st.markdown(f"**{classification}**")
        st.markdown(explanation)
        if learning:
            if error.lean_concept:
                st.markdown(f"**Relevant Lean concept:** {error.lean_concept}")
        elif error.correction_direction:
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
