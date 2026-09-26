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
If `status` is `error`, follow its `hint` (exit code 4 = network: retry once). The JSON contains:
- **`reporting_rules`**: rules for this result. Follow all of them.
- **`draft`**: the interpretation, already written correctly by code. `draft.answer_markdown` is a
  complete answer; `draft.narrative_draft` is the complete PDF text. Other `draft` fields are their parts.
- Raw data (`results`, `missing`, `ranking`, `notes`, `files`) if you need to look something up.

### 3. Handle gaps before answering (re-run once if needed)
- **Ambiguous topic** (`topics[].ambiguous`): if the request hints at a meaning, re-run with that
  `--topic Q<id>`. Otherwise keep the result: the draft already names the analysed meaning first.
- **Missing article**: never estimate it. Only if a `suggestions` title is the same concept (not just
  related), re-run with `--article "pl:<Title>"` and call it a proxy.
- **All results Insufficient**: broaden the topic with a basket (step 1) and re-run once.
- **User's own criteria** ("audience size matters most"): re-run with `--weights`, e.g.
  `--weights volume=0.6,growth=0.2,share=0.1,confidence=0.1`. The draft then states the weights.

### 4. Answer in chat = translate `draft.answer_markdown`
- Translate it into the user's language. Keep every number, date, hedge and caveat exactly as written.
- Do **not** add analysis, reasons, ratios, generalisations or causes that are not in the draft, and do
  not drop lines (spikes, reasons, limits). You may shorten long lists of languages into a table.
- Adapt only the **Recommendation** line to the user's product (same stance, no new facts).
- Replace `PDF_PATH` with the path printed by the report command (step 5).
- If the user asked for a short answer: translate only the first bold sentence, each language's
  first two lines, the limits and the recommendation, and offer the PDF instead of making it.
- Ukrainian terms: share of views = частка переглядів; raw views = абсолютні перегляди;
  confidence = рівень довіри; Ukrainian-language Wikipedia = україномовна Вікіпедія;
  spike = сплеск; survey = опитування. Write natural Ukrainian, no Russian words.

### 5. Build the PDF (always, unless the user asked only for a short answer)
1. Save `draft.narrative_draft` as `narrative.json`, translating `title`, `headline`, `findings[].text`,
   `recommendation` and `next_steps` into the user's language (keep numbers, `about`, `claim`).
2. Run with `--lang` = the language the user wrote in:
```bash
scripts/wpv report --study <study> --narrative narrative.json --lang <uk|en|pl|cs|de|es|fr>
```
3. If `status` is `rejected`, fix exactly the listed fields (hints show the real values) and re-run.

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
