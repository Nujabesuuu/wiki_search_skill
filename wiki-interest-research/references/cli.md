# CLI reference

All commands: `scripts/wpv <command> [options]`. Output is a single JSON object on stdout; progress goes to
stderr. Exit codes: 0 ok, 2 bad arguments, 3 data/resolution problem or rejected narrative, 4 network.

## run - create or update a study
| option | meaning |
|---|---|
| `--topic T` | repeatable. Free text (`"intermittent fasting"`), a QID (`Q333`), or a basket `"label=Q1,Q2"` / `"label=text one,text two"` |
| `--langs L` | `pl,cs` or `Polish,Czech` (replaces the list) |
| `--months N` | window length, default 24 (statistics use at least 24) |
| `--end YYYY-MM` | last month (default: last complete month) |
| `--article "pl:Title"` | add a specific article to the first topic; `"pl:Title@topic label"` for another topic |
| `--weights growth=..,volume=..,share=..,confidence=..` | ranking weights (normalised to sum 1) |
| `--study DIR` | study folder; default `wiki-interest-studies/<topic>-<langs>` in the current directory |
| `--add-langs`, `--remove-langs`, `--add-topic`, `--remove-topic` | modify an existing study |
| `--no-redirects` | do not add redirect views |

Limit: 40 topic x language combinations per study. Typical run: 2-15 s; follow-ups use the cache.

Output fields: `status` (ok / partial = some languages missing), `study`, `window`
(`start`, `end`, `months`, `analysis_months`), `topics[]` (`label`, `items`, `ambiguous`, `alternatives`),
`results[]` (`topic`, `lang`, `articles`, `metrics`, `direction`, `confidence`, `claim_strength`,
`allowed_claims`, `passed_checks`, `failed_checks`, `flags`, `largest_spike`, `basket_missing`),
`missing[]` (`topic`, `lang`, `suggestions`, `hint`), `ranking[]` (`rank`, `score`, `strongest_factor`,
`weakest_factor`), `ranking_weights`, `notes`, `files` (`summary`, `csv`, `charts.trend|growth|views`), `next`.

Files in the study folder: `study.json` (parameters), `summary.json` (everything, incl. monthly series and
all spikes), `data/monthly.csv`, `charts/*.png` (English), `charts/<lang>/*.png` and `report-<lang>.pdf`
after `report`, `narrative.verified.json`; `report-en.pdf` is built by `run` itself.

## show - print the summary of an existing study (no network)
`scripts/wpv show --study DIR`

## resolve - which articles would be used (no pageviews downloaded)
`scripts/wpv resolve --topic "English as a second language" --langs pl,de`
Returns items, alternatives, articles per language (with redirect counts) and missing languages.

## search - find candidate articles inside one wiki
`scripts/wpv search --lang pl "post przerywany"` -> `titles[]`. Use only genuine equivalents.

## report - verify narrative and render the PDF
`scripts/wpv report --study DIR --narrative narrative.json --lang uk [--check-only]`
- Narrative fields: `headline` (<= 240 chars, required), `findings` (1-5 of `{text <= 300, about[], claim}`),
  `recommendation` (<= 420, required), `next_steps` (<= 4 x 170), optional `title` (<= 90).
- `status: rejected` -> `errors[]` with `field`, `problem`, `hint`. Fix and re-run.
- `--lang` sets labels and the method/limitations text: en, uk, pl, cs, de, es, fr (others fall back to
  English labels; your narrative can still be in any language with Latin, Cyrillic or Greek script).
- Without `--narrative` a data-only report is produced (not recommended).

## check - verify your chat answer before sending
`scripts/wpv check --study DIR --answer answer.md`
Returns `status: ok` or `issues_found` with `issues[]` of type `unknown_number` (not in the data),
`country_name` (a country instead of a language edition), `generalisation` ("all markets" when languages
differ), `overstatement`, `dropped_line` (a language's share change or the ranking weights are missing) and
`missing_report_path`. Works for answers in any language (numbers and paths are language-independent).

Note: `run` also writes `report-en.pdf` from the verified draft (`files.pdf`); build other languages with `report`.
