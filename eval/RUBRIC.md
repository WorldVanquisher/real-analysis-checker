# Grading rubric

`python eval/run_eval.py --yes` writes `grading.csv` next to `summary.md`.
Fill in one row per case; leave a cell `n/a` when it does not apply. Grade
from `results.json`, which holds each full report (statement, Lean code,
explanations), or by re-running the case in the app.

The automatic metrics in `summary.md` — false verifications, status accuracy,
Lean compile rate, statement exact match, localization accuracy and
code-explanation grounding — need no grading.

## statement_faithful (y/n)

Does the formal statement say exactly what the problem says?

* **y** — same hypotheses, same conclusion, same quantifier order; any
  convention the translator had to choose (such as indexing from 0) is listed
  in `assumptions_added`.
* **n** — anything weaker, stronger or different: a missing or extra
  hypothesis, `∀ n, ∃ M` instead of `∃ M, ∀ n`, `<` instead of `≤`, an index
  shift that is not declared.

`statement_exact_match` in the summary is only a lower bound: an equivalent
statement written differently is graded **y** here.

## error_explanation_quality (1–5)

For cases where Lean rejected the proof, grade the first error card.

| Score | Meaning |
| --- | --- |
| 5 | Points at the right step, says correctly whether it is the student's reasoning or the translation, explains the actual mistake in the student's terms, and the hint leads to a fix without giving it away. |
| 4 | Correct and helpful, with a small inaccuracy or vague wording. |
| 3 | Partly right: correct location or origin, but the explanation misses the real mistake. |
| 2 | Mostly unhelpful, but honest (for example "cannot confidently identify" when the mistake was clear). |
| 1 | Wrong or misleading: blames the student for a translation problem or the reverse, or describes a mistake that is not there. |

## code_explanation_correct (1–5)

For cases with a translated proof, open "What the Lean code does".

| Score | Meaning |
| --- | --- |
| 5 | Every block's Lean syntax, mathematical meaning, role and necessity are accurate and tied to the student's own sentence. |
| 4 | Accurate, with one block thin or slightly generic. |
| 3 | Mostly accurate, but at least one block misdescribes what the code does. |
| 2 | Several blocks wrong, or mostly word-by-word paraphrase. |
| 1 | Misleading about what the proof does. |

Blocks replaced by an automatic summary were withheld by the grounding check;
grade them as you find them.

## learning_content_useful (1–5)

Open "Learn the Lean in this proof".

| Score | Meaning |
| --- | --- |
| 5 | The cards shown are exactly the concepts this proof uses, the "in your proof" lines are right, and the practice questions fit. |
| 4 | Useful, with one irrelevant or missing card. |
| 3 | Somewhat useful. |
| 2 | Mostly irrelevant to this proof. |
| 1 | Confusing or wrong. |

## Reading the results

* Any **false verification** is a release blocker: investigate the report in
  `results.json` before anything else.
* Categories `hard_to_formalize` and `mistranslation` are expected to fail
  sometimes; what matters there is that failures are reported honestly and
  statements are faithful.
