"""Stage 1: the LLM reads the problem and the student's proof.

The LLM answers with :class:`ProblemParseOutput`; this module turns it into the
domain model :class:`ProblemAnalysis`, numbering the steps ``S1, S2, …`` and
applying deterministic checks the LLM cannot override:

* every step is compared with the student's text; a step that is not a
  verbatim excerpt is kept but marked ``verbatim=False``;
* an in-scope problem without a goal, or a proof that produced no steps,
  becomes a clarification question rather than a guess.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from ra_checker.input_validation import normalize_for_llm
from ra_checker.llm.client import LLMClient
from ra_checker.llm.prompts import (
    PARSE_PROBLEM_SYSTEM,
    PARSE_PROBLEM_VERSION,
    parse_problem_user_message,
)
from ra_checker.logging_setup import text_fingerprint
from ra_checker.models import ProblemAnalysis, ProofStep, Submission

logger = logging.getLogger(__name__)

PARSE_TASK = "parse_problem"
NO_GOAL_QUESTION = (
    "I could not identify what exactly has to be proved. "
    "Could you state the claim to prove explicitly?"
)
NO_STEPS_QUESTION = (
    "I could not find any proof steps in your solution. "
    "Could you write out your argument step by step?"
)


class ProblemParseOutput(BaseModel):
    """The LLM's answer (structured output schema)."""

    model_config = ConfigDict(extra="forbid")

    in_scope: bool
    out_of_scope_reason: str
    topic: str
    hypotheses: list[str]
    goal: str
    proof_steps: list[str]
    ambiguities: list[str]


@dataclass(frozen=True)
class ParseOutcome:
    analysis: ProblemAnalysis
    llm_model: str
    prompt_version: str


def parse_problem(submission: Submission, llm: LLMClient) -> ParseOutcome:
    """Run stage 1. LLM errors propagate (see ``ra_checker.llm.client``)."""
    problem = normalize_for_llm(submission.problem_text)
    proof = normalize_for_llm(submission.proof_text)
    logger.info(
        "parsing problem (%s) proof (%s)", text_fingerprint(problem), text_fingerprint(proof)
    )
    result = llm.complete_structured(
        task=PARSE_TASK,
        system=PARSE_PROBLEM_SYSTEM,
        user=parse_problem_user_message(problem, proof),
        schema=ProblemParseOutput,
        effort="medium",
    )
    return ParseOutcome(
        analysis=to_analysis(result.value, proof),
        llm_model=result.model,
        prompt_version=PARSE_PROBLEM_VERSION,
    )


def to_analysis(output: ProblemParseOutput, proof_text: str) -> ProblemAnalysis:
    """Deterministic post-processing of the LLM's answer."""
    haystack = _squash(proof_text)
    steps = tuple(
        ProofStep(id=f"S{i}", text=text.strip(), verbatim=_squash(text) in haystack)
        for i, text in enumerate((t for t in output.proof_steps if t.strip()), start=1)
    )
    ambiguities = [a.strip() for a in output.ambiguities if a.strip()]
    if output.in_scope and not ambiguities:
        if not output.goal.strip():
            ambiguities.append(NO_GOAL_QUESTION)
        if not steps:
            ambiguities.append(NO_STEPS_QUESTION)

    reworded = [s.id for s in steps if not s.verbatim]
    if reworded:
        logger.warning("parser reworded steps %s", ", ".join(reworded))

    return ProblemAnalysis(
        hypotheses=tuple(h.strip() for h in output.hypotheses if h.strip()),
        goal=output.goal.strip(),
        proof_steps=steps,
        ambiguities=tuple(ambiguities),
        in_scope=output.in_scope,
        out_of_scope_reason="" if output.in_scope else output.out_of_scope_reason.strip(),
        topic=output.topic.strip() or None,
    )


def _squash(text: str) -> str:
    """Whitespace-insensitive form used for the verbatim comparison."""
    return " ".join(normalize_for_llm(text).split())
