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
  Several `--topic` flags compare topics.
- **Vague or narrow intents -> a basket** (`label=part1,part2`, parts are names or QIDs). Specific
  articles are often tiny or missing in smaller wikis, so pair the specific concept with the main one:
  "interest in learning English" ->
  `--topic "English learning=English as a second or foreign language,English language"`.
  In the answer, say the main article is a broader proxy for the intent.
- **Languages**: Wikipedia codes (`pl,cs,uk,de`). Language names also work (`Polish,Czech`).
  A language edition is not a country: "in Poland" -> `pl`, and always write "Polish-language
  Wikipedia" / "Polish-speaking readers", never "Poland" / "in Poland" when describing results.
- **Window**: `--months 24` by default; "last two years" = 24, "three years" = 36.
- Unsure what a topic maps to? Check cheaply first: `scripts/wpv resolve --topic "stoicism" --langs uk,pl`.

### 2. Run the analysis
```bash
scripts/wpv run --topic "intermittent fasting" --langs pl,cs --months 24
```
If `status` is `error`, follow its `hint` (exit code 4 = network: retry once). Then read the JSON:
1. **`reporting_rules`**: rules for this specific result. Follow all of them.
2. **`draft`**: the interpretation, already written correctly by the code:
   - `topics`: which concept was analysed (and alternatives if the name is ambiguous);
   - `per_series[].lines`: per language: hedged verdict, share vs raw growth, audience size, confidence
     reasons in plain words, recent months, spikes;
   - `missing`, `ranking` (with weights and sensitivity), `limits`;
   - `narrative_draft`: ready-made PDF text (English) with verified numbers and claims.
3. Raw data if you need it: `results[]` (`metrics`, `confidence`, `allowed_claims`, `failed_checks`),
   `missing[]` (with `suggestions`), `ranking[]`, `notes[]`, `files` (absolute paths to charts, CSV).

### 3. Handle gaps before concluding
- **Missing article** (`missing[]`): do not guess. Look at `suggestions`. Only if one is a genuine
  equivalent (same concept, not just related), add it:
  `scripts/wpv run --study <study> --article "pl:<Title>"` and tell the user it is a proxy.
  Otherwise report "no dedicated article". That is a finding too (low coverage).
- **Ambiguous topic**: if the request hints at a meaning, re-run with that `--topic Q<id>`. Otherwise
  answer for the analysed meaning, name it in your first sentence ("Mercury, the planet") and offer
  to run the alternatives.
- **Mostly tiny articles** (Insufficient, or median < 10 views/day): do not recommend from them.
  Broaden the topic (step 1 basket) and re-run once.
- User's own criteria ("audience size matters most"): re-run with `--weights`, e.g.
  `--weights volume=0.6,growth=0.2,share=0.1,confidence=0.1`, and state the weights in the answer.

### 4. Answer in chat (always, in the user's language)
Build the answer from `draft`, translated naturally; keep every number and hedge exactly. Include:
1. Direct answer first, 1-2 sentences (analysed concept if ambiguous).
2. One line (or table row) per language from `draft.per_series` (verdict, share change, raw change,
   views/month, confidence), plus `draft.missing`.
3. Why the confidence is what it is: the plain reasons from `draft` (no p-values).
4. Spikes / recent months from `draft` if present; ranking and weights from `draft.ranking` if you rank.
5. Both limits from `draft.limits`.
6. **Your recommendation for the product decision**: go / don't go / validate first, and what evidence
   would change it. This is the only part you write yourself, and it may not add numbers.
7. Absolute paths to the PDF and charts, and 1-2 follow-ups you can run (more languages, longer window,
   other weights, alternative meaning).
If the user asked for a short answer, give items 1, 2 (one line), 3 (one clause), 5, 6 briefly and offer
the PDF instead of making it.

### 5. Build the shareable PDF (when asked for a report / something to share, or for a decision)
1. Copy `draft.narrative_draft` into `narrative.json` and translate `title`, `headline`, `findings[].text`
   and `next_steps` into the user's language. Keep numbers, `about` and `claim` unchanged.
2. Fill `recommendation` (the same stance as in chat, max 420 characters).
3. Run, with `--lang` = the language the user wrote in:
```bash
scripts/wpv report --study <study> --narrative narrative.json --lang <uk|en|pl|cs|de|es|fr>
```
If `status` is `rejected`, fix exactly the listed fields (hints show the real values) and run it again.
Claims (`claim` field) must be in that series' `allowed_claims`; `no_article`, `insufficient_data`,
`context` and `comparison` are also accepted.

## Wording by claim (in any language)

| claim | say | never |
|---|---|---|
| `strong_growth` / `strong_decline` | "clearly growing / declining" | - |
| `growth` / `decline` | "growing / declining (moderate evidence)" | "clearly", "sharply", "real trend", "not random" |
| `possible_growth` / `possible_decline` | "possibly growing / declining, evidence is weak" | "is growing / declining" |
| `stable` | "roughly stable" | "growing", "declining", "falling" |
| `insufficient_data` | "too little data to judge" | any direction, "signal" |
| `no_article` | "no dedicated article" | any number or comparison for that language |

Never generalise ("all markets are falling") unless every series allows it.

## Follow-up requests (reuse the study; cached data is not downloaded again)
```bash
scripts/wpv run --study <study> --add-langs de,sk          # compare more languages
scripts/wpv run --study <study> --months 36                # longer window
scripts/wpv run --study <study> --add-topic "yoga"         # compare another topic
scripts/wpv run --study <study> --weights volume=0.6,growth=0.2,share=0.1,confidence=0.1
scripts/wpv show --study <study>                            # re-read results without network
```
After a re-run all numbers can change: rebuild the answer and narrative from the new `draft`.

More detail when needed: [methodology & confidence rules](references/methodology.md),
[all CLI options and output fields](references/cli.md).
