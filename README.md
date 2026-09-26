# wiki-interest-research — an Agent Skill for Wikipedia-based demand research

An [Agent Skills](https://agentskills.io/specification) skill that lets an AI agent (including a cheap one
such as Claude Haiku 4.5 or free OpenRouter models) answer B2C product questions like

- *"Compare the growth of interest in intermittent fasting on Polish vs Czech Wikipedia over two years"*
- *"Is interest in astronomy growing on Ukrainian Wikipedia, and how far can we trust it?"*
- *"Compare interest in learning English across our target language editions — which audiences next?"*

using [Wikimedia pageview data](https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/reference/page-views.html),
producing charts and a **verified one-page PDF** that can be shared with a team.

> **Коротко українською.** Навичка для AI-агента: за даними переглядів Вікіпедії відповідає, чи зростає
> інтерес до теми в різних мовних розділах і наскільки цьому можна довіряти, будує графіки та PDF на одну
> сторінку. Уся робота з даними (пошук статей, кеш, нормалізація, статистичні тести, рівень довіри,
> ранжування, чернетка відповіді, перевірка висновків) виконується кодом, а модель лише обирає тему/мови
> і перекладає готові, перевірені формулювання. Нижче — логіка рішень, як я перевіряв результат AI
> (4 раунди оцінювання на Claude Haiku 4.5 з суворим оцінювачем) і план розвитку.

```
wiki-interest-research/          <- the skill (everything lives here)
├── SKILL.md                     <- 6-step workflow for the agent (~110 lines)
├── references/                  <- methodology & CLI reference, loaded on demand
├── scripts/wpv                  <- launcher: builds a pinned venv on first run, then runs the CLI
├── scripts/wiki_interest/       <- Python package doing all the data work
├── tests/                       <- 104 offline unit tests
└── evals/                       <- scenarios, strict rubric, objective checks, OpenRouter agent runner
```

## Quick start

```bash
SKILL=$PWD/wiki-interest-research
$SKILL/scripts/wpv run --topic "intermittent fasting" --langs pl,cs --months 24   # JSON (+ report-en.pdf)
$SKILL/scripts/wpv report --study wiki-interest-studies/intermittent-fasting-pl-cs --narrative narrative.json --lang uk
$SKILL/scripts/wpv check --study wiki-interest-studies/intermittent-fasting-pl-cs --answer answer.md
```

Requirements: `python3 >= 3.11`, `bash`, internet. The first call creates `.venv` from pinned
`scripts/requirements.txt` (numpy, matplotlib, reportlab). No compiled binaries, no API keys.
Tests: `python3 -m venv .venv && .venv/bin/pip install -r scripts/requirements-dev.txt && .venv/bin/python -m pytest`.

To use it in Claude Code, copy or symlink `wiki-interest-research/` into `~/.claude/skills/`
(or any agent that supports Agent Skills).

---

## How it works (and why)

### Design principle: code computes *and phrases*; the model maps the request and translates
My first design split the work as "code computes, the model explains". Evaluation (below) showed that a
cheap model copies numbers perfectly but loses most points in its *own wording*: "views fell 44%" for a
share change, "in Poland" for Polish Wikipedia, "clearly declining" on moderate evidence, "all markets are
falling" when one is stable, a ratio computed in its head. So the final design moves the wording into code
too, and gives the model mechanical checks:

| step | who | what |
|---|---|---|
| 1. topic & language mapping | agent | "learning English" → basket *English as a second or foreign language + English language*; "Poland" → `pl` |
| 2. `wpv run` | code | resolve articles, fetch & cache views, normalise, test trends, grade confidence, rank, charts, **a complete draft answer + PDF narrative**, the English PDF |
| 3. gaps | agent + code | ambiguous topic / missing article / tiny articles / user's own weights → one re-run with explicit flags |
| 4. answer | agent | translate `draft.answer_markdown`, adapt only the recommendation to the product |
| 5. `wpv report` | agent translates, code **verifies** | PDF in the user's language; numbers and claim strength checked |
| 6. `wpv check` | code | the chat answer itself: unknown numbers, country names, generalisations, dropped lines, missing PDF path |

The agent needs 3-4 commands. Output is always one JSON object with a `hint` on errors, plus
`reporting_rules` tailored to the result, so a small model can recover by itself.

### Data pipeline
1. **Topic → articles**: Wikidata search → item → sitelinks per language. Candidates are ranked by
   *whether they have articles in the requested wikis*, then exact label, then breadth of coverage — this
   fixed a real failure where "English as a second language" resolved to a TV episode of *Community*.
   Equally good matches (Mercury: planet / element) are flagged `ambiguous` with alternatives.
2. **Redirects** (e.g. *OMAD*, *5:2 diet* → *Intermittent fasting*) are summed into the article, because
   pageviews are counted per title.
3. **Views**: daily `per-article` data, `agent=user` (no spiders/automated), all access methods,
   plus desktop views to detect bot-like spikes. One request returns up to 11 years of daily data.
4. **Cache**: SQLite with *coverage intervals*: only missing date ranges are downloaded; the last 3 days are
   never considered final. Follow-up questions ("add German", "three years instead of two") cost ~0 requests.
5. **Normalisation**: views per million pageviews of the same wiki. This matters: the whole Ukrainian
   Wikipedia lost ~25% of traffic year over year and Turkish ~16%, so raw views would report "declining
   interest" for almost everything. Share also makes wikis of different sizes comparable.

### How the skill decides "how much can we trust this?"
Instead of a black-box score, six named checks produce a grade (details in
[`references/methodology.md`](wiki-interest-research/references/methodology.md)):

| check | why it exists |
|---|---|
| history ≥ 24 months, article existed all window | YoY and seasonality need 2 years; a new article fakes "growth" |
| volume ≥ 30 views/day | on tiny articles ±50% is noise |
| seasonal Mann-Kendall p < 0.05 | trend is not just month-to-month noise; seasonality (school year!) is compared month-to-same-month |
| robust to spikes | growth must survive replacing spike days (news, viral posts) with their baseline |
| concentration (top-5 days ≤ 15%) | interest spread over the year vs a few bursts |
| no desktop-only spikes | classic signature of unflagged bots |

Grade → `claim_strength` → `allowed_claims` (e.g. `possible_growth` only, for Low confidence).
A seventh check, "raw and normalised growth agree", was removed after evaluation: it lowered confidence
exactly when normalisation worked (Turkish Wikipedia −16% overall, topic share flat). It is now an
informational `wiki_traffic_shift` flag. Spikes that recur on the same date every year (e.g. the school
year start for *astronomy*) are marked `recurring_yearly`, so they are not reported as news.
The agent must tag each finding with a claim; `wpv report` rejects claims stronger than allowed.

### Verification of the agent's conclusions (`verify.py`)
Before a PDF is rendered, the narrative is checked:
- every number is matched against computed metrics, pairwise ratios/differences, window lengths;
  it understands `8 178`, `8,178`, `47,7 %`, `8.2k`, `8,2 тис.`, `3.2x`, and ignores numbers inside
  article titles (*5:2 diet*), QIDs and dates;
- claims vs confidence (above); trend claims about languages without an article are rejected;
- length limits guarantee one page. Rejections come back with the nearest real values as hints.

The report's method & limitations section is generated by code in 7 languages (en, uk, pl, cs, de, es, fr),
so caveats cannot be "forgotten" by the model.

### Checking the chat answer (`wpv check`)
The PDF is verified, but the chat answer is where small models drifted most. `wpv check` flags numbers not
in the data (e.g. a hand-computed "down from ~6,672"), country names used as the subject ("in Poland"; the
Wikipedia caveat itself is allowed), cross-language generalisations when directions differ, overstating
words, dropped lines (every language's share change and the ranking weights must appear) and a missing PDF
path. Numbers and paths make it language-independent. The same code powers `evals/check_outputs.py`.

### Ranking with the user's own criteria
Options are ranked by weighted z-scores of spike-free growth, audience size, share and confidence.
Defaults are stated in every output; users change them (`--weights volume=0.6,growth=0.2,...`) when their
definition of "promising" differs.

---

## Evaluation: how I checked the skill (and the AI output)

AI tools wrote much of the code with me, so every layer had its own independent check:

1. **Unit tests (104, offline).** Statistics are tested on synthetic series with known answers (known
   slope, pure seasonality must *not* be a trend, one viral day must *not* count as growth, a new article must
   not look like growth, wiki-wide growth must be neutralised, desktop-only bot spikes). The verifier is tested
   on locale formats and on narratives that must be rejected.
2. **Live data vs the raw API.** I cross-checked outputs against direct Wikimedia API calls; e.g. the
   *Астрономія* monthly series matched the API to the view (the 2-view difference = one redirect).
3. **Real failure cases found on live data and fixed:** "English as a second language" resolved to a TV
   episode; "mercury" silently picked a car brand; the Polish *intermittent fasting* article does not exist;
   the uk.wikipedia total fell ~25% YoY (so raw views mislead). Each became a code change + regression test.
4. **Agent evaluations.** The skill was copied *without* `evals/` and `tests/` (so agents could not see
   expected answers) and run by fresh agents on 7 scenarios (`evals/evals.json`): the three task examples,
   a two-turn follow-up, custom criteria, an ambiguous topic and a casual prompt without the word "Wikipedia".
   Answers were graded by a separate strict grader (Claude Opus, `evals/rubric.md`: 100 points, automatic
   −15/−20 for overclaims, invented numbers, missing PDF) plus objective checks (`evals/check_outputs.py`:
   numbers vs data, PDF pages, answer language). Non-Claude models run through `evals/run_openrouter.py`,
   a minimal tool-calling agent that only sees the skill's name and description, like a real client.
5. **Visual review** of every chart/PDF change (label overlaps, truncated legends, untranslated text).

**Results** (details and per-run grader notes in
[`evals/results/`](wiki-interest-research/evals/results/README.md)):

| round | main change | Haiku 4.5 mean (7 scenarios, strict grader) |
|---|---|---|
| 1 | baseline: code computes, model writes the answer | 53 |
| 2 | code writes per-language sentences; intensifier lint | 52 |
| 3 | code writes the whole answer and a data-grounded recommendation | 61 (best runs 82-85) |
| 4-5 | English PDF built by `run`; `wpv check` on the answer; small targeted runs | ≈85-88 on the hardest scenario (Haiku and free Nemotron 3 Super 120B), all objective checks pass |

I set myself a target of 95+ with a deliberately harsh grader and did not reach it across all scenarios;
rounds 4-5 were scaled down to save usage and graded by me, so they are indicative. The trend and the
reasons are the useful part: **the data layer was right from the first run; almost every lost point came from
free-form model text**, and each fix that moved wording or checking into code raised the score. That is the
main design lesson of this skill and the direction for further work (see Roadmap, step 4).


---

## Limitations (stated in every report)
- Pageviews measure attention, not willingness to pay. Use results to choose what to validate next.
- A language edition is not a country; many people read English Wikipedia instead of their own.
- Article coverage differs between wikis; missing articles are reported, not estimated.
- Wikimedia's bot filter is imperfect; only the obvious desktop-only spikes are caught.
- PDF fonts cover Latin, Cyrillic and Greek scripts (CJK/Arabic narratives are not supported yet).

## Roadmap: from basic questions to larger research

The skill is built so that each step below is an additive module behind the same three commands and the
same `draft` contract, so the agent-facing workflow (and the evals) stay stable while the research gets deeper.

**Step 1 — Better topic coverage (more precise answers to the same questions)**
- *Topic expansion*: build baskets automatically from Wikidata (`P279` subclass / `P361` part-of / main
  category) with a size cap, and report per-article contributions so one dominant article is visible.
- *Proxy articles*: when a language lacks the article, score `search` candidates by Wikidata relation
  (same item's redirect, parent concept) instead of leaving the choice to the model.
- *Localised labels*: take the topic label in the report language from Wikidata (`labels` in `--lang`).

**Step 2 — More signals per question (better trust, still one command)**
- *Country view*: Wikimedia's `top-by-country` and the differential-privacy per-country dataset show where
  a language edition is read — turns "Spanish Wikipedia" into "Mexico vs Spain" when it matters.
- *Speaker normalisation*: views per million speakers (e.g. from Ethnologue/CLDR) next to views per million
  pageviews, for audience-size questions across languages.
- *Clickstream* (monthly dumps for large wikis): where readers come from (search vs internal links) and what
  they read next — a proxy for "intent" that pageviews lack.
- *Seasonality model*: STL decomposition to report "peaks in September every year" as a feature (useful for
  launch timing), not only as a spike.
- *Forecast with intervals* (e.g. ETS/Prophet-style) for "where will it be in 6 months", with the interval
  width feeding the confidence grade.

**Step 3 — Larger data (hundreds of topics x dozens of languages)**
- The REST API is fine up to a few hundred series (cache + 40 req/s + thread pool; follow-ups are free).
  Beyond that, switch the fetch layer to the **monthly pageview dumps** (`pageview_complete`, one file per
  month for all articles): stream them once into **DuckDB/Parquet** partitioned by wiki and month, then
  every query is local SQL. `Fetcher` is the only module that changes.
- Screening mode: `wpv screen --langs ... --category ...` ranks thousands of articles by the same
  metrics and returns only the top N with drafts, so the agent never sees raw volume.
- Scheduled refresh (cron/CI) of saved studies with a change log: "what moved since last month".

**Step 4 — Evaluation as a product feature**
- Grow `evals/evals.json` with every real user question that went wrong; keep the rubric and the objective
  checker in CI, and run the matrix (Haiku / free OpenRouter models) on every change to `SKILL.md` or
  `draft.py`, the two places that most affect small-model quality (see results above).
- Add assertion checks for the chat answer (country names, uncited numbers, generalisations) to
  `check_outputs.py`, so fewer judgements depend on an LLM grader.

