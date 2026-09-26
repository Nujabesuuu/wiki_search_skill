---
name: wiki-interest-research
description: Measure and compare public interest in topics across Wikipedia language editions using Wikimedia pageview data - growth trends, how much to trust them, charts and a one-page shareable PDF report. Use when a user asks whether interest in a topic is growing, which languages or audiences to localise into or research next, which course/topic/content to add, or wants a data-backed report on topic demand, even if Wikipedia is not mentioned (e.g. "is interest in astronomy growing among Ukrainian speakers?").
compatibility: Needs python3 >= 3.11, bash and internet access (wikimedia.org, wikidata.org, *.wikipedia.org). First run installs pinned numpy, matplotlib and reportlab into the skill's own .venv (about 1 minute).
metadata:
  version: "1.0"
---

# Wikipedia interest research

Answers "is interest in X growing, where, and can we trust it?" with Wikipedia pageviews.
The code does all data work: it finds the articles, downloads and caches views, normalises them,
tests trends, grades confidence, draws charts, verifies your text and builds the PDF.
**Your job: pick the right topics and languages, run the commands, read the JSON, and explain it
honestly.** Never compute numbers yourself and never invent them.

`scripts/wpv` below is inside this skill's directory. If your shell is elsewhere, use its absolute
path (e.g. `/path/to/wiki-interest-research/scripts/wpv`). Every command prints one JSON object.

## Workflow

### 1. Turn the request into topics and languages
- **Topic**: a Wikipedia concept, preferably in English: `"intermittent fasting"`, `astronomy`.
  For vague intents choose the concrete concept(s) people read about:
  "learning English" -> `"English as a second or foreign language"` (the learning article), not the
  language itself. A basket of several concepts: `--topic "English learning=Q130192,Q1860"`.
  Several `--topic` flags compare topics.
- **Languages**: Wikipedia codes (`pl,cs,uk,de`). Language names also work (`Polish,Czech`).
  A language edition is not a country: "Ukraine" -> `uk` and say so in the answer.
- **Window**: `--months 24` by default; "last two years" = 24, "three years" = 36.
- Unsure what a topic maps to? Check cheaply first: `scripts/wpv resolve --topic "stoicism" --langs uk,pl`.

### 2. Run the analysis
```bash
scripts/wpv run --topic "intermittent fasting" --langs pl,cs --months 24
```
Then read the JSON:
- `results[]`: one per topic x language. Key fields:
  - `metrics.growth_yoy_pct`: **headline growth.** Last 12 months vs previous 12, measured as the
    share of that wiki's traffic, so wiki-wide traffic changes are removed.
  - `metrics.growth_yoy_raw_pct`: raw views growth (can differ when the whole wiki grows/shrinks).
  - `metrics.views_avg_month`: audience size; `metrics.views_per_million`: salience in that wiki.
  - `confidence` (High/Medium/Low/Insufficient) + `failed_checks`: **why** it is not higher.
  - `allowed_claims`: the strongest wording the data supports (see table below).
  - `flags`: `has_spikes`, `possible_bot_traffic`, `article_created_recently`, `basket_incomplete`.
- `missing[]`: languages with no article for the topic, plus search `suggestions`.
- `topics[].ambiguous`: several concepts match. Check `alternatives`; re-run with the right QID or ask.
- `ranking[]`: options ordered by a weighted score (`ranking_weights`). Explain the weights if you use it.
- `notes[]`: caveats you must pass on. `files`: charts (PNG), CSV, summary.json.

If `status` is `error`, follow its `hint`. Exit code 4 means a network error: retry once.

### 3. Handle gaps before concluding
- **Missing article** (`missing[]`): do not guess. Look at `suggestions`. Only if one is a genuine
  equivalent (same concept, not just related), add it:
  `scripts/wpv run --study <study> --article "pl:<Title>"` and tell the user it is a proxy.
  Otherwise report "no dedicated article in <language>". That is a finding too (low coverage).
- **Ambiguous topic**: if the chosen item is not what the user meant, re-run with `--topic Q<id>`.
- **Low / Insufficient confidence**: say so plainly and name the failed check in simple words.

### 4. Write the narrative and build the report
Write `narrative.json` in the **user's language**, using only numbers from the JSON (rounding is fine):
```json
{
  "headline": "One sentence that answers the question, with the key number.",
  "findings": [
    {"text": "Czech: share of views fell 47.7% year over year; small audience (183 views/month).",
     "about": ["cs"], "claim": "decline"},
    {"text": "Polish Wikipedia has no article on intermittent fasting.", "about": ["pl"], "claim": "no_article"}
  ],
  "recommendation": "What to do next and why, based on the findings.",
  "next_steps": ["Concrete validation step 1", "Concrete step 2"]
}
```
Then:
```bash
scripts/wpv report --study <study from step 2> --narrative narrative.json --lang <uk|en|pl|cs|de|es|fr>
```
- `about`: language codes (or `topic@lang` when the study has several topics).
- `claim`: must be one of that series' `allowed_claims`, or `no_article` (for `missing`),
  `insufficient_data`, `context` / `comparison` (neutral statements, e.g. audience sizes).
- 1-5 findings (3 is best), max 4 next steps, short sentences.
- If `status` is `rejected`, fix exactly the listed fields (the hint shows the real values) and re-run
  the same command. Never remove the caveats to make it pass.

## Claim strength -> wording

| claim | say | never say |
|---|---|---|
| `strong_growth` / `strong_decline` | "clearly growing/declining" | - |
| `growth` / `decline` | "growing/declining (moderate evidence)" | "clearly", "booming" |
| `possible_growth` / `possible_decline` | "may be growing; not reliable yet because <failed check>" | "is growing" |
| `stable` | "roughly stable" | "growing" / "declining" |
| `insufficient_data` | "too little data to judge" | any trend |
| `no_article` | "no dedicated article in <language>" | any number for that language |

## Answer in chat
1. Direct answer (1-2 sentences) with the headline number and confidence.
2. Small table per option: views/month, growth (share), confidence.
3. Why confidence is what it is (failed checks in plain words) + the `notes`.
4. Limits: pageviews = attention, not willingness to pay; language != country.
5. Paths to the PDF and charts; offer 1-2 follow-ups (more languages, longer window, other weights).

## Follow-up requests (reuse the study, cached data is not downloaded again)
```bash
scripts/wpv run --study <study> --add-langs de,sk          # compare more languages
scripts/wpv run --study <study> --months 36                # longer window
scripts/wpv run --study <study> --add-topic "yoga"         # compare another topic
scripts/wpv run --study <study> --weights volume=0.6,growth=0.2,share=0.1,confidence=0.1  # user's criteria
scripts/wpv show --study <study>                            # re-read results without network
```
After any re-run, rewrite the narrative (numbers change) and run `report` again.

## Rules
- Every number you state must come from the tool output. Growth claims use `growth_yoy_pct`.
- Do not compare raw views across languages as "interest": wikis differ in size. Use `views_per_million`
  for salience and `views_avg_month` for audience size.
- Mention spikes (`largest_spike`) if they exist: a news event can inflate a year.
- Keep the user's assumptions visible. If they change criteria, change `--weights`; don't hand-wave.

More detail when needed: [methodology & confidence rules](references/methodology.md),
[all CLI options and output fields](references/cli.md).
