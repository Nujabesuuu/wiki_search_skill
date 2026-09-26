# Methodology and confidence rules

Read this when you must explain *why* a result has its confidence, or when a user challenges the method.

## Data
- Source: Wikimedia Pageviews REST API, `per-article` daily views, `agent=user` (spiders and traffic
  Wikimedia classifies as automated are excluded), `all-access` (desktop + mobile web + app).
- Views of redirects (e.g. "OMAD" -> "Intermittent fasting") are added to the article, up to 50 redirects.
- Wiki-wide totals: `aggregate` endpoint, monthly, `agent=user`.
- Topic -> articles: Wikidata item sitelinks. Missing language = no sitelink; never imputed.
- Data starts 2015-07-01. The current month and the last 3 days are never treated as final.

## Metrics (per topic x language)
| field | definition |
|---|---|
| `views_avg_month` | mean monthly views over the last 12 months (incl. redirects) |
| `median_daily_views` | median daily views, last 365 days |
| `views_per_million` | last-12-month views / wiki total views x 1,000,000 |
| `growth_yoy_pct` | change of monthly *share* (views per million), last 12 months vs previous 12 |
| `growth_yoy_raw_pct` | same on raw views |
| `growth_yoy_no_spikes_pct` | `growth_yoy_pct` after replacing spike days by their 29-day median baseline |
| `growth_recent_3m_pct` | last 3 months vs same 3 months a year earlier (momentum, noisier) |
| `trend_per_year_pct` | Theil-Sen slope on log monthly share, annualised (robust to outliers) |
| `trend_p_value` | seasonal Mann-Kendall test on monthly share (each calendar month compared with itself) |
| `top5_days_share_pct` | share of last-12-month views on the 5 busiest days |
| `wiki_traffic_yoy_pct` | change of the whole wiki's traffic (context) |

Why share instead of raw views: total Wikipedia traffic moves for reasons unrelated to a topic (search
engine changes, AI answers, bot filtering). If the whole Turkish Wikipedia lost 16% of views, a topic
with -16% raw views has *stable* relative interest. Share also makes wikis of different sizes comparable.

A spike day = at least 3x its 29-day rolling median and at least +20 views. Consecutive spike days are one
event. A spike served >= 90% to desktop while the article's normal desktop share is <= 70% is flagged
`possible_bot_traffic`.

Statistics always use at least 24 months (needed for year-over-year and seasonality). Shorter requested
windows only affect the charts.

## Checks -> confidence
| check | passes when |
|---|---|
| `history` | >= 24 months of data and the article existed for the whole window |
| `volume` | median >= 30 views/day (below, small absolute changes swing percentages) |
| `significance` | up/down: seasonal Mann-Kendall p < 0.05 in the same direction; flat: no clear trend |
| `robust_to_spikes` | direction (up / flat / down, +-5% band) unchanged after removing spike days |
| `concentration` | top-5 days <= 15% of last-12-month views |
| `normalization_agrees` | raw and share growth point the same way, or differ by < 10 pp |
| `no_bot_signal` | no desktop-only spikes |

- **Insufficient**: no year-over-year value, or median < 5 views/day.
- **High**: all checks pass.
- **Medium**: at most 2 failed checks, and neither is `history` nor `robust_to_spikes`.
- **Low**: everything else.

`claim_strength`: High + |growth| >= 10% (or flat) -> `strong`; other High and Medium -> `moderate`;
Low -> `weak`; Insufficient -> `none`. `allowed_claims` follows from direction x strength.
Direction: `growth_yoy_pct` >= +5% up, <= -5% down, otherwise flat.

## Ranking
Each option gets z-scores (across the compared options) for: growth (spike-free share growth),
volume (log views/month), share (log views per million), confidence (High 1, Medium 0.6, Low 0.2).
Score = weighted sum; default weights growth 0.40, volume 0.25, share 0.20, confidence 0.15.
Insufficient options are listed but not ranked. Scores are relative to the compared set only.

## Limitations to state in answers
- Pageviews measure attention (curiosity, homework, news), not purchase intent or willingness to pay.
- A language edition is not a country. Many readers use English Wikipedia instead of their own language,
  and big languages (en, es, pt, fr, ar) span many countries.
- Coverage differs by wiki: a missing or stub article lowers views regardless of real interest.
- Seasonality (school terms, New Year resolutions) is handled by YoY and seasonal tests, but a single
  year can still be unusual (news, a viral video). Check `largest_spike`.
- Bot filtering by Wikimedia is imperfect; the desktop-share check catches only the obvious cases.
