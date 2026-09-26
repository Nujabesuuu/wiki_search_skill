"""Turn daily views into decision metrics + an explicit, explainable confidence grade.

Headline metric is growth of *normalized* interest (views per million pageviews of the same
Wikipedia), because raw views also move with wiki-wide traffic (e.g. search/AI answer changes)
and are not comparable across wikis of different size. Every grade comes with the checks that
produced it so the agent (and the reader of the report) can see why.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from . import stats
from .fetch import DATA_START

MIN_ANALYSIS_MONTHS = 24         # YoY and seasonal tests need two full years
FLAT_BAND_PCT = 5.0              # |growth| below this is "flat"
STRONG_GROWTH_PCT = 10.0         # a "strong" claim also needs a material change
VOLUME_OK = 30                   # median daily views for a stable percentage estimate
VOLUME_MIN = 5                   # below this: insufficient
CONCENTRATION_MAX_PCT = 15.0     # max share of window views on the top-5 days
P_VALUE_MAX = 0.05
WIKI_SHIFT_PCT = 10.0            # whole-wiki traffic change worth flagging

ALLOWED_CLAIMS = {
    ("up", "strong"): ["strong_growth", "growth", "possible_growth"],
    ("up", "moderate"): ["growth", "possible_growth"],
    ("up", "weak"): ["possible_growth"],
    ("down", "strong"): ["strong_decline", "decline", "possible_decline"],
    ("down", "moderate"): ["decline", "possible_decline"],
    ("down", "weak"): ["possible_decline"],
    ("flat", "strong"): ["stable"],
    ("flat", "moderate"): ["stable"],
    ("flat", "weak"): ["stable"],
}


# ---------------------------------------------------------------- window

@dataclass
class Window:
    requested_months: int
    months: list[str]            # analysis months (>= 24)
    chart_months: list[str]      # what the user asked to see
    note_codes: list[dict] = field(default_factory=list)   # translated by i18n.note_text

    @property
    def notes(self) -> list[str]:
        from .i18n import note_text
        return [note_text("en", n["code"], n["params"]) for n in self.note_codes]

    @property
    def start_day(self) -> date:
        return stats.month_bounds(self.months[0])[0]

    @property
    def end_day(self) -> date:
        return stats.month_bounds(self.months[-1])[1]

    def to_dict(self) -> dict:
        return {"start": self.chart_months[0], "end": self.months[-1], "months": len(self.chart_months),
                "analysis_start": self.months[0], "analysis_months": len(self.months)}


def last_complete_month(today: date) -> str:
    anchor = today - timedelta(days=3)          # Wikimedia needs ~1-2 days to publish a day
    first = anchor.replace(day=1) - timedelta(days=1)
    return f"{first.year:04d}-{first.month:02d}"


def make_window(months: int, end: str | None = None, today: date | None = None) -> Window:
    end = end or last_complete_month(today or date.today())
    notes = []
    months = max(1, int(months))
    n = max(months, MIN_ANALYSIS_MONTHS)
    y, m = map(int, end.split("-"))
    total = y * 12 + (m - 1) - (n - 1)
    start = f"{total // 12:04d}-{total % 12 + 1:02d}"
    first_available = f"{DATA_START.year:04d}-{DATA_START.month:02d}"
    if start < first_available:
        start = first_available
        notes.append({"code": "data_start", "params": {}})
    all_months = stats.month_range(start, end)
    if months < MIN_ANALYSIS_MONTHS:
        notes.append({"code": "window_min", "params": {"analysis": len(all_months), "months": months}})
    return Window(months, all_months, all_months[-months:], notes)


# ---------------------------------------------------------------- analysis

def _pct(x: float | None, nd: int = 1) -> float | None:
    return None if x is None else round(100 * x, nd)


def _direction(g: float | None) -> str:
    if g is None:
        return "unknown"
    if g >= FLAT_BAND_PCT:
        return "up"
    if g <= -FLAT_BAND_PCT:
        return "down"
    return "flat"


def _sig(x: float, digits: int = 3) -> float:
    return float(f"{x:.{digits}g}") if x else 0.0


def analyze_series(topic: str, lang: str, articles: list, bundle: dict[str, dict[date, int]],
                   totals: dict[str, int], window: Window) -> dict:
    months = window.months
    day_list = [window.start_day + timedelta(days=i) for i in range((window.end_day - window.start_day).days + 1)]
    daily = np.array([bundle["total"].get(d, 0) for d in day_list], dtype=float)
    main = np.array([bundle["main"].get(d, 0) for d in day_list], dtype=float)
    desk = np.array([bundle["main_desktop"].get(d, 0) for d in day_list], dtype=float)

    _, monthly = stats.to_monthly(dict(zip(day_list, daily)), months[0], months[-1])
    _, monthly_robust = stats.to_monthly(dict(zip(day_list, stats.winsorize_spikes(daily))), months[0], months[-1])
    tot = np.array([totals.get(m, 0) for m in months], dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        per_million = np.where(tot > 0, monthly / tot * 1e6, np.nan)
        per_million_robust = np.where(tot > 0, monthly_robust / tot * 1e6, np.nan)
    valid = ~np.isnan(per_million)

    last12 = slice(-12, None)
    days_last12 = daily[-365:]
    g_share = stats.yoy(per_million[valid])
    g_raw = stats.yoy(monthly)
    g_robust = stats.yoy(per_million_robust[valid])
    g_3m = stats.yoy(per_million[valid], window=3)
    wiki_yoy = stats.yoy(tot)
    trend = stats.log_trend_pct_per_year(per_million[valid]) if valid.sum() >= 6 else None
    s_mk, p_mk = stats.seasonal_mann_kendall(per_million[valid])
    top5 = stats.top_days_share(days_last12)
    median_daily = float(np.median(days_last12)) if len(days_last12) else 0.0
    spikes = stats.mark_recurring(stats.detect_spikes(day_list, daily, limit=3), day_list, daily)

    nonzero = np.nonzero(daily)[0]
    first_day = day_list[nonzero[0]] if len(nonzero) else None
    new_article = first_day is not None and (first_day - window.start_day).days > 45

    # bot heuristic: a spike served almost only to desktop while normal traffic is mostly mobile
    base_desktop_share = float(desk.sum() / main.sum()) if main.sum() else 0.0
    bot_spikes = []
    for sp in spikes:
        i = day_list.index(date.fromisoformat(sp["peak_date"]))
        share = desk[i] / main[i] if main[i] else 0.0
        sp["desktop_share_pct"] = round(100 * share)
        if share >= 0.9 and base_desktop_share <= 0.7:
            bot_spikes.append(sp["peak_date"])

    g = _pct(g_share)
    direction = _direction(g)
    metrics = {
        "views_avg_month": int(round(monthly[last12].mean())),
        "views_avg_month_prev_12m": int(round(monthly[-24:-12].mean())) if len(monthly) >= 24 else None,
        "views_avg_month_recent_3m": int(round(monthly[-3:].mean())),
        "views_avg_month_recent_3m_year_ago": int(round(monthly[-15:-12].mean())) if len(monthly) >= 15 else None,
        "median_daily_views": round(median_daily, 1),
        "views_per_million": _sig(float(np.nansum(monthly[last12]) / tot[last12].sum() * 1e6)) if tot[last12].sum() else None,
        "growth_yoy_pct": g,
        "growth_yoy_raw_pct": _pct(g_raw),
        "growth_yoy_no_spikes_pct": _pct(g_robust),
        "growth_recent_3m_pct": _pct(g_3m),
        "trend_per_year_pct": _pct(trend),
        "trend_p_value": _sig(p_mk, 2),
        "top5_days_share_pct": _pct(top5),
        "wiki_traffic_yoy_pct": _pct(wiki_yoy),
    }

    # ------------------------------------------------------------ checks
    checks = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    if new_article:
        check("history", False, f"article only has views since {first_day.isoformat()}; growth may reflect "
                                f"the article being created, not rising interest")
    else:
        check("history", len(months) >= MIN_ANALYSIS_MONTHS and g is not None,
              f"{len(months)} months of data" if g is not None else "fewer than 24 months of data")
    check("volume", median_daily >= VOLUME_OK,
          f"median {median_daily:.0f} views/day" + ("" if median_daily >= VOLUME_OK
                                                    else " (low: small changes swing percentages)"))
    if direction in ("up", "down"):
        agrees = (s_mk > 0) == (direction == "up")
        check("significance", p_mk < P_VALUE_MAX and agrees,
              f"seasonal Mann-Kendall p={metrics['trend_p_value']}" +
              ("" if p_mk < P_VALUE_MAX and agrees else " (month-to-month trend not statistically clear)"))
    elif direction == "flat":
        stable = p_mk >= P_VALUE_MAX or (trend is not None and abs(trend) < 0.10)
        check("significance", stable, f"no clear trend (p={metrics['trend_p_value']})" if stable
              else f"year-over-year is flat but the multi-month trend is significant (p={metrics['trend_p_value']})")
    rd = _direction(metrics["growth_yoy_no_spikes_pct"])
    if g is not None and metrics["growth_yoy_no_spikes_pct"] is not None:
        check("robust_to_spikes", rd == direction,
              f"without spike days growth is {metrics['growth_yoy_no_spikes_pct']:+.1f}% vs {g:+.1f}%")
    check("concentration", top5 * 100 <= CONCENTRATION_MAX_PCT,
          f"top-5 days = {metrics['top5_days_share_pct']}% of last-12-month views")
    check("no_bot_signal", not bot_spikes,
          "no desktop-only spikes" if not bot_spikes
          else f"desktop-only spike(s) on {', '.join(bot_spikes)} look automated")

    # ------------------------------------------------------------ grade
    flags = []
    if new_article:
        flags.append("article_created_recently")
    if bot_spikes:
        flags.append("possible_bot_traffic")
    if spikes:
        flags.append("has_spikes")
    # Informational: raw views and share diverge because the whole wiki moved. Normalisation exists
    # exactly for this, so it does not lower confidence, but the agent should mention it.
    if metrics["wiki_traffic_yoy_pct"] is not None and abs(metrics["wiki_traffic_yoy_pct"]) >= WIKI_SHIFT_PCT:
        flags.append("wiki_traffic_shift")
    fails = [c["name"] for c in checks if not c["ok"]]
    if g is None or median_daily < VOLUME_MIN:
        confidence = "Insufficient"
    elif not fails:
        confidence = "High"
    elif len(fails) <= 2 and not {"history", "robust_to_spikes"} & set(fails):
        confidence = "Medium"
    else:
        confidence = "Low"
    if confidence == "Insufficient":
        strength = "none"
    elif confidence == "High":
        strength = "strong" if abs(g) >= STRONG_GROWTH_PCT or direction == "flat" else "moderate"
    elif confidence == "Medium":
        strength = "moderate"
    else:
        strength = "weak"

    return {
        "topic": topic,
        "lang": lang,
        "articles": [a.title for a in articles],
        "redirects_included": sum(len(a.redirects) for a in articles),
        "redirects_total": sum(a.redirects_total for a in articles),
        "metrics": metrics,
        "direction": direction,
        "confidence": confidence,
        "claim_strength": strength,
        "allowed_claims": ALLOWED_CLAIMS.get((direction, strength), ["insufficient_data"]),
        "checks": checks,
        "flags": flags,
        "spikes": spikes,
        # series for charts / CSV (not printed to stdout)
        "_months": months,
        "_monthly_views": monthly.tolist(),
        "_monthly_per_million": [None if np.isnan(x) else float(x) for x in per_million],
    }
