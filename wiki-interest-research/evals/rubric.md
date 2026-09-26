# Grading rubric (strict, 100 points)

Grade one eval run: the user prompt(s), the agent's final answer(s), its tool calls, the study folder
(`summary.json`, `report-*.pdf`, `narrative.verified.json`) and `check_outputs.py` results.
Default to deducting when evidence is missing. A score of 95+ means "I would send this to a founder as is".

| # | criterion | pts | full marks require |
|---|---|---|---|
| A | Correct use of the skill | 15 | `wpv run` with a sensible topic, correct language codes and window; follow-ups reuse `--study`; errors handled via hints; no hand-computed statistics or ad-hoc scraping |
| B | Data grounding | 20 | every number in the chat answer and PDF is traceable to `summary.json` (rounding ok); headline metric is `growth_yoy_pct`; raw vs normalised not confused |
| C | Epistemic honesty | 20 | confidence stated *with reasons* (failed checks in plain words); wording never stronger than `allowed_claims`; missing articles / ambiguity / spikes / uneven baskets handled explicitly; limits stated (attention != payment, language != country) |
| D | Answers the real question | 15 | direct answer first; comparison where asked; recommendation useful for the product decision; user's criteria respected |
| E | Deliverables | 15 | one-page PDF when a report is requested or useful, in the user's language (labels) with verified narrative; paths given; charts available |
| F | Communication | 10 | user's language, concise, structured, no jargon without explanation, 1-2 useful follow-ups offered |
| G | Efficiency | 5 | no redundant runs or loops; reasonable number of tool calls |

## Automatic deductions (apply on top, floor at 0)
- Invented or wrong number presented as data: -20 each (max -40)
- A claim stronger than the data allows (e.g. "clearly growing" with Low confidence): -15
- Numbers for a language whose article is missing (without a labelled proxy): -20
- Report requested but no PDF: -15; PDF not one page: -10
- Answer in a different language than the user wrote: -10
- Ambiguous topic silently treated as one meaning: -15
- Follow-up turn re-uses stale numbers from a previous window: -15

## Output format
Return JSON: `{"score": int, "breakdown": {"A": int, ..., "G": int}, "deductions": [str],
"strengths": [str], "problems": [str], "skill_fixes": [str]}` where `skill_fixes` are concrete changes to
SKILL.md / code that would have prevented each problem.
