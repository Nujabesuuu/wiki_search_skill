# Evaluation results

Scenarios: `../evals.json` (3 task examples + follow-up, custom criteria, ambiguous topic, casual prompt).
Rubric: `../rubric.md` (strict, 100 points, automatic deductions for invented numbers / overclaims / missing PDF).
Objective checks: `../check_outputs.py` (same code as `wpv check`).

| round | what changed in the skill | model | graded by | scores (7 scenarios) | mean |
|---|---|---|---|---|---|
| 1 | baseline: code computes, model writes everything | Claude Haiku 4.5 | Opus grader | 50 / 64 / 50 / 49 / 38 / 70 / 52 | **53** |
| 2 | code-written per-language sentences, intensifier lint | Claude Haiku 4.5 | Opus grader | 62 / 62 / 4 / 52 / 27 / 81 / 75 | **52** |
| 3 | complete draft answer + recommendation in code | Claude Haiku 4.5 | Opus grader | 82 / 79 / 34 / 85 / 47 / 74 / 29 | **61** |
| 4 | auto English PDF, `wpv check`, year-ago baselines | Claude Haiku 4.5 | self (rubric + checks) | yoga ≈ 88, stoicism ≈ 70 | — |
| 5 | studies never inside the skill, trade-off kept, "send the checked answer" | Claude Haiku 4.5 | self (rubric + checks) | stoicism ≈ 85 (all objective checks pass) | — |
| 5 | same | Nemotron 3 Super 120B (free, OpenRouter) | self (rubric + checks) | stoicism ≈ 88 (all objective checks pass, 6 requests, 41 s) | — |

Order in rows 1-3: fasting-pl-cs, astronomy-uk-trust, english-learning-audiences, astronomy-followup,
custom-criteria-yoga, ambiguous-mercury, casual-stoicism. Per-run details (breakdown, deductions, problems):
`iteration-{1,2,3}-haiku.json`. Example final answers: `examples/`.

Rounds 4-5 were deliberately small (usage limits): the two weakest scenarios only, graded by me with the
same rubric plus `check_outputs.py`, not by an Opus grader, so they are indicative, not comparable one-to-one.
Qwen 3.8 27B and Gemma 4 31B free endpoints returned upstream 429 (rate-limited) during the session.

What the numbers taught (each fix is in the git history):
- Numbers were right from round 1 (0 invented metrics); points were lost in the model's own wording.
- Moving wording into code (rounds 2-3) fixed hedging, language-vs-country and caveats, but the model
  still added hand-made numbers/generalisations and skipped the PDF step.
- Mechanical safety nets (round 4: PDF built by `run`, `wpv check` on the answer) closed those gaps; in
  round 5 both models sent answers that pass every objective check.
- Remaining weakness: occasional speculation outside the data (e.g. about the user's social feed), now
  addressed by an explicit limit line in the draft; not yet re-measured.
